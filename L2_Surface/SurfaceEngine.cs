using System;
using System.Collections.Generic;
using TradingPlatform.BusinessLayer;

namespace L2_Surface
{
    // Single engine that maintains all state for the four toggleable layers:
    //
    //   1. Events       — discrete BUILD/PULL/IN/OUT/VOD events at price ticks
    //   2. Inflections  — cum-joins-ROC confirmation labels at BUILD trigger price
    //   3. Climax lines — VOD + BUILD same-sample fingerprint, persistent line
    //   4. Build bands  — clusters of same-side BUILDs forming supply/demand zones
    //
    // Plus a Flow band overlay (vertical translucent strip during active flow:
    // vacuum-event density + elevated RV + inner-depth thinning all sustained).
    //
    // All layers share:
    //   - One BookState (live L2)
    //   - One sample loop (default 1 Hz)
    //   - One rolling baseline (default 30s) for z-scoring
    //   - One event vocabulary (matches research/liq_events.py + LiquidityMeter)
    //
    // Each layer's "Enabled" toggle gates only the *visible output* — engine
    // computes everything every sample regardless. The cost of computing
    // unwatched layers is minimal (~few µs/sample) and avoids the surprise of
    // toggling on a layer mid-session and seeing it warm up empty.
    //
    // Design law: surface, don't classify. The engine flags structural shapes
    // at multiple time scales; the trader supplies context and decides.
    internal sealed class SurfaceEngine
    {
        // Sampling depth
        private const int InnerLevels = 10;
        private const int BroadLevels = 30;
        private const int CumWindowSec = 300;     // 5-min rolling cum for Inflection layer
        private const int MidReturnsKeepSec = 90; // keep enough for RV + headroom

        // ── Configuration (set from L2_Surface entry point) ─────────────────
        // Common
        public int LookbackSec { get; set; } = 30;
        public double EventZThreshold { get; set; } = 3.0;

        // Inflection
        public bool InflectionEnabled { get; set; } = true;
        public double TriggerBuildZ { get; set; } = 4.0;
        public double CumThreshold { get; set; } = 7.0;
        public double RocThreshold { get; set; } = 5.0;
        public int ConfirmationWindowSec { get; set; } = 60;
        public int RocWindowSec { get; set; } = 60;

        // Flow
        public bool FlowEnabled { get; set; } = true;
        public double ClimaxVodZ { get; set; } = 5.0;
        public double ClimaxBuildZ { get; set; } = 4.0;
        public int BandWindowSec { get; set; } = 30;
        public int BandEventCount { get; set; } = 5;
        public double BandRvThreshold { get; set; } = 1e-7;   // mid-return^2 sum
        public double BandInnerThinZ { get; set; } = 1.0;     // current inner_depth at least 1σ below baseline
        public int BandSustainSec { get; set; } = 10;
        public int BandCooldownSec { get; set; } = 30;

        // Build bands (supply/demand clusters)
        public bool BuildBandsEnabled { get; set; } = true;
        public int BuildClusterN { get; set; } = 3;
        public int BuildClusterTicks { get; set; } = 8;
        public int BuildClusterSec { get; set; } = 90;

        // ── Internal state ──────────────────────────────────────────────────
        private readonly LinkedList<Sample> _samples = new();
        private readonly LinkedList<L2Event> _events = new();      // all event types, retained for cum/ROC
        private readonly LinkedList<TimedDouble> _innerDeltas = new();
        private readonly LinkedList<TimedDouble> _vodValues = new();
        private double? _prevInnerDepth;
        private readonly LinkedList<TimedDouble> _midRets2 = new();   // squared log returns of mid for RV
        private double? _prevMidPrice;

        // Inflection
        private readonly List<PendingTrigger> _pending = new();
        private readonly LinkedList<Inflection> _inflections = new();

        // Flow climax lines
        private readonly LinkedList<ClimaxLine> _climaxLines = new();

        // Flow band state machine
        private readonly LinkedList<FlowBand> _flowBands = new();
        private FlowBand _openBand;        // null when state == NONE
        private FlowDir _state = FlowDir.None;
        private DateTime? _matchStart;     // when current direction first started matching
        private DateTime _lastMatchTime;   // last sample where current direction matched
        private DateTime _lastUnmatchTime; // last sample with no match (for cooldown)

        // Build bands
        private readonly LinkedList<BuildBand> _buildBands = new();
        private readonly LinkedList<L2Event> _buildPending = new();   // recent BUILDs not yet in a band

        // Last-sample event capture (used for climax fingerprint detection AND
        // for band-event-density updates without re-walking history).
        private readonly List<L2Event> _thisSampleEvents = new();

        // ── Public state for painter ────────────────────────────────────────
        public IEnumerable<L2Event> Events => _events;
        public IEnumerable<Inflection> Inflections => _inflections;
        public IEnumerable<ClimaxLine> ClimaxLines => _climaxLines;
        public IEnumerable<BuildBand> BuildBands => _buildBands;
        public IEnumerable<FlowBand> FlowBands => _flowBands;
        public FlowBand OpenBand => _openBand;

        public double CurrentCum5m { get; private set; }
        public double CurrentRoc { get; private set; }
        public long CurrentMidTick { get; private set; }
        public double CurrentTickSize { get; private set; }

        // ── Main entry: invoke once per sample ──────────────────────────────
        public void OnSample(DateTime nowUtc, DepthOfMarketAggregatedCollections dom, double tickSize)
        {
            CurrentTickSize = tickSize;

            var sample = ComputeSample(nowUtc, dom, tickSize);
            CurrentMidTick = sample.MidTick;
            _samples.AddLast(sample);
            EvictOlderThan(_samples, nowUtc, LookbackSec * 2);

            // Track mid log-return^2 for RV. Skip first sample (no prior).
            double midPrice = sample.MidTick * tickSize;
            if (_prevMidPrice.HasValue && _prevMidPrice.Value > 0 && midPrice > 0)
            {
                double r = Math.Log(midPrice / _prevMidPrice.Value);
                _midRets2.AddLast(new TimedDouble { Time = nowUtc, Value = r * r });
                EvictOlderThan(_midRets2, nowUtc, MidReturnsKeepSec);
            }
            _prevMidPrice = midPrice;

            // Always evict events past max needed window — cum window + headroom
            // covers all consumers (Inflection cum_5m being the longest).
            EvictEventsOlderThan(_events, nowUtc, CumWindowSec * 2);

            _thisSampleEvents.Clear();

            if (_samples.Count < 5) return;  // need history before z-scoring

            // ── Z-score detection + event firing ────────────────────────────
            (double mBi, double sBi) = MeanStd(s => s.BidInner, nowUtc);
            (double mAi, double sAi) = MeanStd(s => s.AskInner, nowUtc);
            (double mBc, double sBc) = MeanStd(s => s.BidCentroid, nowUtc);
            (double mAc, double sAc) = MeanStd(s => s.AskCentroid, nowUtc);

            double zBi = (sample.BidInner    - mBi) / Math.Max(1.0,    sBi);
            double zAi = (sample.AskInner    - mAi) / Math.Max(1.0,    sAi);
            double zBc = (sample.BidCentroid - mBc) / Math.Max(0.01, sBc);
            double zAc = (sample.AskCentroid - mAc) / Math.Max(0.01, sAc);

            // Bias map (matches research/liq_events.py and LiquidityMeter):
            //   z_bi > 0 → BID_BUILD (+1)   z_bi < 0 → BID_PULL (-1)
            //   z_ai > 0 → ASK_BUILD (-1)   z_ai < 0 → ASK_PULL (+1)
            //   z_bc > 0 → BID_OUT   (-1)   z_bc < 0 → BID_IN   (+1)
            //   z_ac > 0 → ASK_OUT   (+1)   z_ac < 0 → ASK_IN   (-1)
            TryFire(nowUtc, zBi, +1, "BID_BUILD", "BID_PULL", sample.MidTick, tickSize);
            TryFire(nowUtc, zAi, -1, "ASK_BUILD", "ASK_PULL", sample.MidTick, tickSize);
            TryFire(nowUtc, zBc, -1, "BID_OUT",   "BID_IN",   sample.MidTick, tickSize);
            TryFire(nowUtc, zAc, +1, "ASK_OUT",   "ASK_IN",   sample.MidTick, tickSize);

            // VOD detection (same math as MeterEngine).
            double currInner = sample.BidInner + sample.AskInner;
            double zVod = double.NaN;
            if (_prevInnerDepth.HasValue)
            {
                double delta = currInner - _prevInnerDepth.Value;
                _innerDeltas.AddLast(new TimedDouble { Time = nowUtc, Value = delta });
                EvictOlderThan(_innerDeltas, nowUtc, LookbackSec * 2);

                if (_innerDeltas.Count >= 4)
                {
                    double vod = StdOver(_innerDeltas, nowUtc, LookbackSec);
                    _vodValues.AddLast(new TimedDouble { Time = nowUtc, Value = vod });
                    EvictOlderThan(_vodValues, nowUtc, LookbackSec * 8);

                    if (_vodValues.Count >= 8)
                    {
                        var (mVod, sVod) = MeanStdOf(_vodValues, nowUtc, LookbackSec * 4);
                        zVod = (vod - mVod) / Math.Max(0.1, sVod);
                        if (Math.Abs(zVod) > EventZThreshold)
                        {
                            EmitEvent(nowUtc, 0, Math.Abs(zVod), "VOD", sample.MidTick, tickSize);
                        }
                    }
                }
            }
            _prevInnerDepth = currInner;

            // ── Cum / ROC running totals (Inflection layer) ─────────────────
            CurrentCum5m = SumWeightsOver(_events, nowUtc, CumWindowSec);
            CurrentRoc   = SumWeightsOver(_events, nowUtc, RocWindowSec);

            // ── Inflection: register pending triggers from BUILD≥TriggerBuildZ ──
            if (InflectionEnabled)
            {
                foreach (var ev in _thisSampleEvents)
                {
                    if (ev.AbsZ < TriggerBuildZ) continue;
                    if (ev.Type != "BID_BUILD" && ev.Type != "ASK_BUILD") continue;
                    _pending.Add(new PendingTrigger
                    {
                        Time = nowUtc,
                        PriceTicks = sample.MidTick,
                        TickSize = tickSize,
                        Bias = ev.Bias,
                        // Cum baseline excludes this BUILD's own contribution so
                        // the threshold check measures additional commitment.
                        CumBaseline = CurrentCum5m - (ev.Bias * ev.AbsZ),
                    });
                }

                // Walk pending; promote / drop.
                for (int i = _pending.Count - 1; i >= 0; i--)
                {
                    var t = _pending[i];
                    if ((nowUtc - t.Time).TotalSeconds > ConfirmationWindowSec)
                    {
                        _pending.RemoveAt(i);
                        continue;
                    }
                    double deltaCum = CurrentCum5m - t.CumBaseline;
                    bool cumOk = (t.Bias > 0 && deltaCum >=  CumThreshold) ||
                                 (t.Bias < 0 && deltaCum <= -CumThreshold);
                    bool rocOk = (t.Bias > 0 && CurrentRoc >=  RocThreshold) ||
                                 (t.Bias < 0 && CurrentRoc <= -RocThreshold);
                    if (cumOk && rocOk)
                    {
                        _inflections.AddLast(new Inflection
                        {
                            TriggerTime = t.Time,
                            ConfirmedTime = nowUtc,
                            PriceTicks = t.PriceTicks,
                            TickSize = t.TickSize,
                            Bias = t.Bias,
                        });
                        _pending.RemoveAt(i);
                    }
                }
            }

            // ── Flow climax line: VOD≥ClimaxVodZ AND any BUILD≥ClimaxBuildZ
            //    in the same sample, at the same mid tick. Both events fire from
            //    the same sample by construction, so "same tick" ≡ both share
            //    sample.MidTick (which they will, since it's recorded at fire). ──
            if (FlowEnabled)
            {
                bool hasVod = false; double vodAbsZ = 0;
                bool hasBuild = false; double buildAbsZ = 0;
                foreach (var ev in _thisSampleEvents)
                {
                    if (ev.Type == "VOD" && ev.AbsZ >= ClimaxVodZ) { hasVod = true; vodAbsZ = ev.AbsZ; }
                    if ((ev.Type == "BID_BUILD" || ev.Type == "ASK_BUILD") && ev.AbsZ >= ClimaxBuildZ)
                    {
                        if (ev.AbsZ > buildAbsZ) { hasBuild = true; buildAbsZ = ev.AbsZ; }
                    }
                }
                if (hasVod && hasBuild)
                {
                    // Skip duplicate at same tick within a few seconds (would be
                    // a burst of contiguous samples all clearing the threshold).
                    bool duplicate = false;
                    foreach (var c in _climaxLines)
                    {
                        if (c.PriceTicks == sample.MidTick &&
                            (nowUtc - c.Time).TotalSeconds < 30) { duplicate = true; break; }
                    }
                    if (!duplicate)
                    {
                        _climaxLines.AddLast(new ClimaxLine
                        {
                            Time = nowUtc,
                            PriceTicks = sample.MidTick,
                            TickSize = tickSize,
                            VodAbsZ = vodAbsZ,
                            BuildAbsZ = buildAbsZ,
                        });
                    }
                }

                // ── Flow band state machine ─────────────────────────────────
                UpdateFlowBand(nowUtc);
            }

            // ── Build bands (supply/demand clusters) ────────────────────────
            if (BuildBandsEnabled)
            {
                EvictEventsOlderThan(_buildPending, nowUtc, BuildClusterSec);
                foreach (var ev in _thisSampleEvents)
                {
                    if (ev.Type != "BID_BUILD" && ev.Type != "ASK_BUILD") continue;
                    UpdateBuildBands(ev, tickSize);
                }
            }
        }

        // Apply price-through clearing across the layers that respect it.
        // Caller invokes per sample (or per paint, cheap either way).
        public void ApplyPriceThrough(int bufferTicks)
        {
            if (bufferTicks < 0) bufferTicks = 0;
            long midTick = CurrentMidTick;
            if (midTick == 0) return;

            // Inflections clear in their own direction:
            //   bear inflection at price P → clears when mid > P + buffer
            //   bull inflection at price P → clears when mid < P - buffer
            var infNode = _inflections.First;
            while (infNode != null)
            {
                var next = infNode.Next;
                var inf = infNode.Value;
                if ((inf.Bias < 0 && midTick > inf.PriceTicks + bufferTicks) ||
                    (inf.Bias > 0 && midTick < inf.PriceTicks - bufferTicks))
                    _inflections.Remove(infNode);
                infNode = next;
            }

            // Climax lines are amber/neutral — clear on either-direction price-
            // through (level was contested, then resolved).
            var clNode = _climaxLines.First;
            while (clNode != null)
            {
                var next = clNode.Next;
                var cl = clNode.Value;
                if (Math.Abs(midTick - cl.PriceTicks) > bufferTicks)
                {
                    // First time we see midTick is on the "wrong" side of the
                    // line by buffer ticks, clear it.
                    _climaxLines.Remove(clNode);
                }
                clNode = next;
            }

            // Build bands: a supply (ask-side) band clears when mid trades
            // ABOVE its top; a demand (bid-side) band clears when mid trades
            // BELOW its bottom. The buffer applies on the threatened side.
            var bbNode = _buildBands.First;
            while (bbNode != null)
            {
                var next = bbNode.Next;
                var bb = bbNode.Value;
                if (bb.Side == BandSide.Supply && midTick > bb.MaxTick + bufferTicks)
                    _buildBands.Remove(bbNode);
                else if (bb.Side == BandSide.Demand && midTick < bb.MinTick - bufferTicks)
                    _buildBands.Remove(bbNode);
                bbNode = next;
            }
        }

        // Optional retention TTL on Events list. Default 0 = never (per
        // persistence-as-confirmation design law). Caller passes minutes.
        public void ApplyEventTtl(DateTime nowUtc, int ttlMinutes)
        {
            if (ttlMinutes <= 0) return;
            var cutoff = nowUtc.AddMinutes(-ttlMinutes);
            // Only TTL on events whose sole consumer is the Events dot painter.
            // Cum/ROC/clustering rely on _events too, so we shouldn't blanket-
            // evict; instead track a separate dot-display list. For v0.1 we
            // accept that lowering TTL also shortens cum/ROC depth as a side
            // effect — same scale as the lookback for normal use.
            while (_events.Count > 0 && _events.First.Value.Time < cutoff)
                _events.RemoveFirst();
        }

        // ── Flow band internals ─────────────────────────────────────────────
        private void UpdateFlowBand(DateTime nowUtc)
        {
            // Compute current direction match (NONE / BEAR / BULL).
            int bearCount = 0, bullCount = 0;
            var cutoff = nowUtc.AddSeconds(-BandWindowSec);
            foreach (var ev in _events)
            {
                if (ev.Time < cutoff) continue;
                if (ev.AbsZ < EventZThreshold) continue;
                if (ev.Bias < 0) bearCount++;
                else if (ev.Bias > 0) bullCount++;
            }
            double rv = SumOver(_midRets2, nowUtc, BandWindowSec);

            // Inner-depth thinning: current inner depth vs rolling baseline mean.
            // Use the most recent sample plus previously-computed mean.
            (double mBiPlusAi, double sBiPlusAi) = MeanStd(s => s.BidInner + s.AskInner, nowUtc);
            double currInner = 0;
            if (_samples.Last != null) currInner = _samples.Last.Value.BidInner + _samples.Last.Value.AskInner;
            double thinZ = sBiPlusAi > 0 ? (currInner - mBiPlusAi) / sBiPlusAi : 0;

            bool bearMatch = bearCount >= BandEventCount && rv >= BandRvThreshold && thinZ <= -BandInnerThinZ;
            bool bullMatch = bullCount >= BandEventCount && rv >= BandRvThreshold && thinZ <= -BandInnerThinZ;
            // Mutual exclusion: stronger side wins if both somehow trigger.
            if (bearMatch && bullMatch)
            {
                if (bearCount >= bullCount) bullMatch = false;
                else bearMatch = false;
            }
            FlowDir match = bearMatch ? FlowDir.Bear : (bullMatch ? FlowDir.Bull : FlowDir.None);

            // State machine.
            if (_state == FlowDir.None)
            {
                if (match != FlowDir.None)
                {
                    if (_matchStart == null) _matchStart = nowUtc;
                    _lastMatchTime = nowUtc;
                    if ((nowUtc - _matchStart.Value).TotalSeconds >= BandSustainSec)
                    {
                        // Open band.
                        _state = match;
                        _openBand = new FlowBand
                        {
                            Direction = match,
                            StartTime = _matchStart.Value,
                            EndTime = nowUtc,    // tracked open-ended; updated each sample
                        };
                        _flowBands.AddLast(_openBand);
                    }
                }
                else
                {
                    _matchStart = null;
                }
            }
            else
            {
                // Currently in BEAR or BULL state.
                if (match == _state)
                {
                    _lastMatchTime = nowUtc;
                    if (_openBand != null) _openBand.EndTime = nowUtc;
                    _lastUnmatchTime = default;
                }
                else
                {
                    if (_lastUnmatchTime == default) _lastUnmatchTime = nowUtc;
                    if ((nowUtc - _lastMatchTime).TotalSeconds >= BandCooldownSec)
                    {
                        // Close band, return to NONE.
                        if (_openBand != null) _openBand.EndTime = _lastMatchTime;
                        _openBand = null;
                        _state = FlowDir.None;
                        _matchStart = null;
                        _lastUnmatchTime = default;
                    }
                }
            }
        }

        // ── Build-band internals ────────────────────────────────────────────
        private void UpdateBuildBands(L2Event ev, double tickSize)
        {
            BandSide side = ev.Type == "ASK_BUILD" ? BandSide.Supply : BandSide.Demand;

            // Try to extend an existing band of same side within proximity.
            foreach (var bb in _buildBands)
            {
                if (bb.Side != side) continue;
                if ((ev.Time - bb.LastUpdate).TotalSeconds > BuildClusterSec) continue;
                long lo = bb.MinTick - BuildClusterTicks;
                long hi = bb.MaxTick + BuildClusterTicks;
                if (ev.PriceTicks >= lo && ev.PriceTicks <= hi)
                {
                    if (ev.PriceTicks < bb.MinTick) bb.MinTick = ev.PriceTicks;
                    if (ev.PriceTicks > bb.MaxTick) bb.MaxTick = ev.PriceTicks;
                    bb.LastUpdate = ev.Time;
                    bb.EventCount++;
                    return;
                }
            }

            // No existing band extended. Check pending list for cluster
            // formation: count same-side BUILDs within ±BuildClusterTicks of
            // this event in the last BuildClusterSec.
            var members = new List<L2Event> { ev };
            foreach (var p in _buildPending)
            {
                if ((side == BandSide.Supply && p.Type != "ASK_BUILD") ||
                    (side == BandSide.Demand && p.Type != "BID_BUILD")) continue;
                if (Math.Abs(p.PriceTicks - ev.PriceTicks) > BuildClusterTicks) continue;
                if ((ev.Time - p.Time).TotalSeconds > BuildClusterSec) continue;
                members.Add(p);
            }

            if (members.Count >= BuildClusterN)
            {
                // Form new band.
                long minT = long.MaxValue, maxT = long.MinValue;
                DateTime first = DateTime.MaxValue, last = DateTime.MinValue;
                foreach (var m in members)
                {
                    if (m.PriceTicks < minT) minT = m.PriceTicks;
                    if (m.PriceTicks > maxT) maxT = m.PriceTicks;
                    if (m.Time < first) first = m.Time;
                    if (m.Time > last)  last  = m.Time;
                }
                _buildBands.AddLast(new BuildBand
                {
                    Side = side,
                    MinTick = minT,
                    MaxTick = maxT,
                    StartTime = first,
                    LastUpdate = last,
                    EventCount = members.Count,
                    TickSize = tickSize,
                });
                // Remove the consumed events from pending (they've been
                // promoted into a band; no longer eligible for re-clustering).
                var node = _buildPending.First;
                while (node != null)
                {
                    var next = node.Next;
                    if (members.Contains(node.Value)) _buildPending.Remove(node);
                    node = next;
                }
            }
            else
            {
                _buildPending.AddLast(ev);
            }
        }

        // ── Sample / events plumbing ────────────────────────────────────────
        private void TryFire(DateTime time, double z, int biasPos,
                             string posLabel, string negLabel,
                             long midTick, double tickSize)
        {
            if (Math.Abs(z) <= EventZThreshold) return;
            int bias = z > 0 ? biasPos : -biasPos;
            string label = z > 0 ? posLabel : negLabel;
            EmitEvent(time, bias, Math.Abs(z), label, midTick, tickSize);
        }

        private void EmitEvent(DateTime time, int bias, double absZ, string type,
                               long midTick, double tickSize)
        {
            var ev = new L2Event
            {
                Time = time,
                Bias = bias,
                AbsZ = absZ,
                Type = type,
                PriceTicks = midTick,
                TickSize = tickSize,
            };
            _events.AddLast(ev);
            _thisSampleEvents.Add(ev);
        }

        private (double mean, double std) MeanStd(Func<Sample, double> sel, DateTime nowUtc)
        {
            var cutoff = nowUtc.AddSeconds(-LookbackSec);
            double sum = 0, sumSq = 0;
            int n = 0;
            foreach (var s in _samples)
            {
                if (s.Time < cutoff) continue;
                double v = sel(s);
                sum += v;
                sumSq += v * v;
                n++;
            }
            if (n < 2) return (0, 0);
            double mean = sum / n;
            double var = (sumSq / n) - mean * mean;
            double std = var > 0 ? Math.Sqrt(var) : 0;
            return (mean, std);
        }

        private static double SumWeightsOver(LinkedList<L2Event> events, DateTime nowUtc, int seconds)
        {
            var cutoff = nowUtc.AddSeconds(-seconds);
            double sum = 0;
            foreach (var ev in events)
            {
                if (ev.Time < cutoff) continue;
                sum += ev.Bias * ev.AbsZ;
            }
            return sum;
        }

        private static double SumOver(LinkedList<TimedDouble> values, DateTime nowUtc, int seconds)
        {
            var cutoff = nowUtc.AddSeconds(-seconds);
            double sum = 0;
            foreach (var v in values)
            {
                if (v.Time < cutoff) continue;
                sum += v.Value;
            }
            return sum;
        }

        // Read aggregate metrics from QT's canonical DepthOfMarket. dom.Bids /
        // dom.Asks are best-first ordered Level2Item arrays. We sum top-N sizes
        // for inner_depth and compute size-weighted centroid distances over the
        // broad-N. Mid-tick = (best_bid + best_ask) / 2 in tick units.
        //
        // Why we read from DepthOfMarket instead of maintaining a delta-merged
        // book: every L2 vendor refresh (DOMQuote) replaces QT's internal book
        // wholesale, so orphaned levels (the 2026-05-08 ref_tick bug class)
        // cannot accumulate. See RESEARCH_LOG 2026-05-08 migration narrative.
        private Sample ComputeSample(DateTime time, DepthOfMarketAggregatedCollections dom, double tickSize)
        {
            var s = new Sample { Time = time };
            var bids = dom?.Bids ?? Array.Empty<Level2Item>();
            var asks = dom?.Asks ?? Array.Empty<Level2Item>();

            // Inner depth — top-N valid sizes each side. Skip non-finite / zero
            // entries so a NaN size leak can't poison sums (and the resulting
            // z-scores).
            int taken = 0;
            for (int i = 0; i < bids.Length && taken < InnerLevels; i++)
            {
                double sz = bids[i].Size;
                if (!double.IsFinite(bids[i].Price) || bids[i].Price <= 0) continue;
                if (!double.IsFinite(sz) || sz <= 0) continue;
                s.BidInner += sz;
                taken++;
            }
            taken = 0;
            for (int i = 0; i < asks.Length && taken < InnerLevels; i++)
            {
                double sz = asks[i].Size;
                if (!double.IsFinite(asks[i].Price) || asks[i].Price <= 0) continue;
                if (!double.IsFinite(sz) || sz <= 0) continue;
                s.AskInner += sz;
                taken++;
            }

            // Mid-tick: (best_bid + best_ask) / 2 from first finite-price,
            // size>0 level on each side. Defensive against NaN/zero leaks.
            double bbPrice = FirstValidPrice(bids);
            double baPrice = FirstValidPrice(asks);
            bool haveBid = !double.IsNaN(bbPrice);
            bool haveAsk = !double.IsNaN(baPrice);
            long bestBid = haveBid ? PriceToTicks(bbPrice, tickSize) : 0;
            long bestAsk = haveAsk ? PriceToTicks(baPrice, tickSize) : 0;
            long refTick = (haveBid && haveAsk) ? (bestBid + bestAsk) / 2 :
                           (haveBid ? bestBid : (haveAsk ? bestAsk : 0));
            s.MidTick = refTick;

            // Centroid — size-weighted mean |tick offset from refTick| over broad-N.
            double bWsum = 0, bSize = 0;
            taken = 0;
            for (int i = 0; i < bids.Length && taken < BroadLevels; i++)
            {
                double p = bids[i].Price;
                double sz = bids[i].Size;
                if (!double.IsFinite(p) || p <= 0) continue;
                if (!double.IsFinite(sz) || sz <= 0) continue;
                long t = PriceToTicks(p, tickSize);
                bWsum += Math.Abs(t - refTick) * sz;
                bSize += sz;
                taken++;
            }
            double aWsum = 0, aSize = 0;
            taken = 0;
            for (int i = 0; i < asks.Length && taken < BroadLevels; i++)
            {
                double p = asks[i].Price;
                double sz = asks[i].Size;
                if (!double.IsFinite(p) || p <= 0) continue;
                if (!double.IsFinite(sz) || sz <= 0) continue;
                long t = PriceToTicks(p, tickSize);
                aWsum += Math.Abs(t - refTick) * sz;
                aSize += sz;
                taken++;
            }
            s.BidCentroid = bSize > 0 ? bWsum / bSize : 0;
            s.AskCentroid = aSize > 0 ? aWsum / aSize : 0;
            return s;
        }

        private static long PriceToTicks(double price, double tickSize)
            => (long)Math.Round(price / tickSize);

        private static double FirstValidPrice(Level2Item[] arr)
        {
            if (arr == null) return double.NaN;
            for (int i = 0; i < arr.Length; i++)
            {
                double p = arr[i].Price;
                double s = arr[i].Size;
                if (double.IsFinite(p) && p > 0 && double.IsFinite(s) && s > 0) return p;
            }
            return double.NaN;
        }

        private static void EvictOlderThan<T>(LinkedList<T> list, DateTime nowUtc, int seconds)
            where T : ITimestamped
        {
            var cutoff = nowUtc.AddSeconds(-seconds);
            while (list.Count > 0 && list.First.Value.Time < cutoff)
                list.RemoveFirst();
        }

        private static void EvictEventsOlderThan(LinkedList<L2Event> list, DateTime nowUtc, int seconds)
        {
            var cutoff = nowUtc.AddSeconds(-seconds);
            while (list.Count > 0 && list.First.Value.Time < cutoff)
                list.RemoveFirst();
        }

        private static double StdOver(LinkedList<TimedDouble> values, DateTime nowUtc, int seconds)
        {
            var cutoff = nowUtc.AddSeconds(-seconds);
            double sum = 0, sumSq = 0; int n = 0;
            foreach (var v in values)
            {
                if (v.Time < cutoff) continue;
                sum += v.Value; sumSq += v.Value * v.Value; n++;
            }
            if (n < 2) return 0;
            double mean = sum / n;
            double var = (sumSq / n) - mean * mean;
            return var > 0 ? Math.Sqrt(var) : 0;
        }

        private static (double mean, double std) MeanStdOf(LinkedList<TimedDouble> values, DateTime nowUtc, int seconds)
        {
            var cutoff = nowUtc.AddSeconds(-seconds);
            double sum = 0, sumSq = 0; int n = 0;
            foreach (var v in values)
            {
                if (v.Time < cutoff) continue;
                sum += v.Value; sumSq += v.Value * v.Value; n++;
            }
            if (n < 2) return (0, 0);
            double mean = sum / n;
            double var = (sumSq / n) - mean * mean;
            return (mean, var > 0 ? Math.Sqrt(var) : 0);
        }

        // ── Public types ────────────────────────────────────────────────────
        public interface ITimestamped { DateTime Time { get; } }

        public sealed class TimedDouble : ITimestamped
        {
            public DateTime Time { get; set; }
            public double Value;
        }

        private sealed class Sample : ITimestamped
        {
            public DateTime Time { get; set; }
            public double BidInner;
            public double AskInner;
            public double BidCentroid;
            public double AskCentroid;
            public long MidTick;
        }

        public sealed class L2Event : ITimestamped
        {
            public DateTime Time { get; set; }
            public int Bias;          // +1 bull, -1 bear, 0 neutral (VOD)
            public double AbsZ;
            public string Type;       // BID_BUILD/ASK_BUILD/BID_PULL/ASK_PULL/BID_IN/ASK_IN/BID_OUT/ASK_OUT/VOD
            public long PriceTicks;
            public double TickSize;
            public double Price => PriceTicks * TickSize;
        }

        private sealed class PendingTrigger
        {
            public DateTime Time;
            public long PriceTicks;
            public double TickSize;
            public int Bias;
            public double CumBaseline;
        }

        public sealed class Inflection
        {
            public DateTime TriggerTime;
            public DateTime ConfirmedTime;
            public long PriceTicks;
            public double TickSize;
            public int Bias;
            public double Price => PriceTicks * TickSize;
        }

        public sealed class ClimaxLine : ITimestamped
        {
            public DateTime Time { get; set; }
            public long PriceTicks;
            public double TickSize;
            public double VodAbsZ;
            public double BuildAbsZ;
            public double Price => PriceTicks * TickSize;
        }

        public enum BandSide { Supply, Demand }

        public sealed class BuildBand
        {
            public BandSide Side;
            public long MinTick, MaxTick;
            public DateTime StartTime;
            public DateTime LastUpdate;
            public int EventCount;
            public double TickSize;
            public double MinPrice => MinTick * TickSize;
            public double MaxPrice => MaxTick * TickSize;
        }

        public enum FlowDir { None, Bear, Bull }

        public sealed class FlowBand
        {
            public FlowDir Direction;
            public DateTime StartTime;
            public DateTime EndTime;        // updated continuously while open
        }
    }
}
