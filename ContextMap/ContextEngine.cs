using System;
using System.Collections.Generic;
using System.Linq;
using TradingPlatform.BusinessLayer;

namespace ContextMap
{
    internal sealed class ContextEngine
    {
        private const int InnerLevels = 10;
        private const int BroadLevels = 30;
        private const int MaxRailKeepHours = 20;
        private const int BarMinutes = 5;

        private readonly double _tickSize;
        private readonly LinkedList<BookSample> _samples = new();
        private readonly Dictionary<long, RailBucket> _rails = new();
        private readonly List<ContextEvent> _events = new();
        private readonly List<ContextMessage> _messages = new();
        private readonly List<BarBin> _recentBins = new();
        private TimeZoneInfo _nyZone;
        private DateTime? _sessionDateNy;
        private int _nextMessageId = 1;
        private long? _lastTradeTick;
        private long? _rthOpenTick;
        private long? _rthHighTick;
        private long? _rthLowTick;
        private bool _sawRthOpen;
        private BarState _bar;
        private RailView _activeLowRail;
        private RailView _activeHighRail;
        private LegState _leg;
        private string _frame = "building";
        private bool _bracketReady;
        private bool _addRiskSent;

        public int BookLookbackSec { get; set; } = 30;
        public double EventZThreshold { get; set; } = 2.5;
        public int OnStartHHmm { get; set; } = 1800;
        public int RthStartHHmm { get; set; } = 930;
        public int BracketReadyHHmm { get; set; } = 945;
        public int UpdateCutoffHHmm { get; set; } = 1230;
        public int RailBinTicks { get; set; } = 16;
        public int RailCountEachSide { get; set; } = 4;
        public double RailMinDominantWeight { get; set; } = 10.0;
        public double RailDominanceRatio { get; set; } = 1.25;
        public int BreakBufferTicks { get; set; } = 4;

        public ContextEngine(double tickSize)
        {
            _tickSize = tickSize > 0 ? tickSize : 0.25;
            try { _nyZone = TimeZoneInfo.FindSystemTimeZoneById("Eastern Standard Time"); }
            catch { _nyZone = TimeZoneInfo.Local; }
        }

        public void OnTrade(DateTime timeUtc, double price, double size, int aggressorSign)
        {
            if (!double.IsFinite(price) || price <= 0) return;
            if (!double.IsFinite(size) || size <= 0) return;

            var phase = UpdateSession(timeUtc);
            long tick = PriceToTicks(price);
            _lastTradeTick = tick;

            if (phase == ContextPhase.RthBuild || phase == ContextPhase.RthUpdate || phase == ContextPhase.AfterCutoff)
            {
                if (!_sawRthOpen)
                {
                    _sawRthOpen = true;
                    _rthOpenTick = tick;
                    _rthHighTick = tick;
                    _rthLowTick = tick;
                    AddMessage(timeUtc, MessageKind.Info, $"open {Abbrev(tick)}");
                }
                _rthHighTick = Math.Max(_rthHighTick ?? tick, tick);
                _rthLowTick = Math.Min(_rthLowTick ?? tick, tick);
                UpdateBar(timeUtc, tick, size, aggressorSign);
            }
        }

        public void OnBookSample(DateTime nowUtc, DepthOfMarketAggregatedCollections dom)
        {
            var phase = UpdateSession(nowUtc);
            var sample = ComputeSample(nowUtc, dom);
            _samples.AddLast(sample);
            EvictOlderThan(_samples, nowUtc, Math.Max(10, BookLookbackSec) * 2);

            if (_samples.Count < 5)
                return;

            var (mBi, sBi) = MeanStd(s => s.BidInner, nowUtc);
            var (mAi, sAi) = MeanStd(s => s.AskInner, nowUtc);
            var (mBc, sBc) = MeanStd(s => s.BidCentroid, nowUtc);
            var (mAc, sAc) = MeanStd(s => s.AskCentroid, nowUtc);

            double zBi = (sample.BidInner - mBi) / Math.Max(1.0, sBi);
            double zAi = (sample.AskInner - mAi) / Math.Max(1.0, sAi);
            double zBc = (sample.BidCentroid - mBc) / Math.Max(0.01, sBc);
            double zAc = (sample.AskCentroid - mAc) / Math.Max(0.01, sAc);

            TryFire(nowUtc, sample.MidTick, zBi, +1, "BID_BUILD", "BID_PULL", phase);
            TryFire(nowUtc, sample.MidTick, zAi, -1, "ASK_BUILD", "ASK_PULL", phase);
            TryFire(nowUtc, sample.MidTick, zBc, -1, "BID_OUT", "BID_IN", phase);
            TryFire(nowUtc, sample.MidTick, zAc, +1, "ASK_OUT", "ASK_IN", phase);

            Prune(nowUtc);
        }

        public ContextSnapshot GetSnapshot(DateTime nowUtc)
        {
            var phase = UpdateSession(nowUtc);
            var reference = _lastTradeTick ?? _rthOpenTick ?? 0;
            var rails = BuildRailViews(reference, nowUtc);

            return new ContextSnapshot
            {
                Phase = phase,
                Frame = _frame,
                SessionDateNy = _sessionDateNy,
                RthOpenTick = _rthOpenTick,
                RthHighTick = _rthHighTick,
                RthLowTick = _rthLowTick,
                LastTradeTick = _lastTradeTick,
                ActiveLow = _activeLowRail,
                ActiveHigh = _activeHighRail,
                Leg = _leg?.ToView(),
                Rails = rails,
                Messages = _messages.OrderByDescending(m => m.TimeUtc).Take(6).Reverse().ToArray(),
            };
        }

        private void TryFire(DateTime nowUtc, long priceTick, double z, int posBias, string posKind, string negKind, ContextPhase phase)
        {
            if (!double.IsFinite(z) || Math.Abs(z) <= EventZThreshold) return;
            if (phase == ContextPhase.Waiting || phase == ContextPhase.AfterCutoff) return;

            int bias = z > 0 ? posBias : -posBias;
            string kind = z > 0 ? posKind : negKind;
            double absZ = Math.Abs(z);
            var ev = new ContextEvent
            {
                TimeUtc = nowUtc,
                PriceTick = priceTick,
                BinTick = BinTick(priceTick),
                Bias = bias,
                AbsZ = absZ,
                Kind = kind,
            };
            _events.Add(ev);
            ApplyEventToRail(ev, phase);
            ApplyEventToLeg(ev);
        }

        private void ApplyEventToRail(ContextEvent ev, ContextPhase phase)
        {
            if (!_rails.TryGetValue(ev.BinTick, out var rail))
            {
                rail = new RailBucket
                {
                    BinTick = ev.BinTick,
                    FirstUtc = ev.TimeUtc,
                    LastUtc = ev.TimeUtc,
                    Origin = phase == ContextPhase.ON ? RailOrigin.ON : RailOrigin.RTH,
                };
                _rails[ev.BinTick] = rail;
            }

            rail.LastUtc = ev.TimeUtc;
            if (phase == ContextPhase.RthBuild || phase == ContextPhase.RthUpdate)
                rail.TouchedRth = true;
            if (ev.Bias > 0)
            {
                rail.DemandWeight += ev.AbsZ;
                rail.DemandEvents++;
            }
            else
            {
                rail.SupplyWeight += ev.AbsZ;
                rail.SupplyEvents++;
            }
            UpdateRailQualification(rail);
        }

        private void UpdateRailQualification(RailBucket rail)
        {
            double dom = Math.Max(rail.DemandWeight, rail.SupplyWeight);
            double opp = Math.Min(rail.DemandWeight, rail.SupplyWeight);
            rail.DominantWeight = dom;
            rail.OpposingWeight = opp;
            rail.Ratio = dom / Math.Max(1.0, opp);
            rail.Side = rail.DemandWeight >= rail.SupplyWeight ? RailSide.Demand : RailSide.Supply;
            rail.IsQualified = dom >= Math.Max(1.0, RailMinDominantWeight)
                            && rail.Ratio >= Math.Max(1.0, RailDominanceRatio);
        }

        private void UpdateBar(DateTime timeUtc, long tick, double size, int aggressorSign)
        {
            DateTime barStart = BarStartUtc(timeUtc);
            if (_bar == null)
            {
                _bar = new BarState(barStart, tick);
            }
            else if (_bar.StartUtc != barStart)
            {
                FinalizeBar(_bar);
                _bar = new BarState(barStart, tick);
            }

            _bar.HighTick = Math.Max(_bar.HighTick, tick);
            _bar.LowTick = Math.Min(_bar.LowTick, tick);
            _bar.CloseTick = tick;
            _bar.Volume += size;
            _bar.Delta += size * aggressorSign;
            _bar.Trades++;

            long bin = BinTick(tick);
            if (!_bar.Bins.TryGetValue(bin, out var b))
            {
                b = new BarBin { BinTick = bin };
                _bar.Bins[bin] = b;
            }
            b.Volume += size;
            b.Delta += size * aggressorSign;
            b.Trades++;
        }

        private void FinalizeBar(BarState bar)
        {
            foreach (var b in bar.Bins.Values)
            {
                b.TimeUtc = bar.StartUtc;
                _recentBins.Add(b);
            }
            _recentBins.RemoveAll(b => (bar.StartUtc - b.TimeUtc).TotalHours > 2);

            TryReadyBracket(bar);
            if (!_bracketReady || _activeLowRail == null || _activeHighRail == null)
                return;

            bool brokeUp = bar.HighTick > _activeHighRail.MaxTick + BreakBufferTicks;
            bool brokeDown = bar.LowTick < _activeLowRail.MinTick - BreakBufferTicks;

            if (brokeUp && brokeDown)
            {
                AddMessage(
                    bar.StartUtc,
                    MessageKind.Sweep,
                    $"both rails swept L {Abbrev(bar.LowTick)} H {Abbrev(bar.HighTick)}");
            }

            if (_leg == null)
            {
                if (brokeUp && bar.CloseTick >= _activeHighRail.MaxTick)
                    StartLeg(Direction.Up, _activeHighRail, bar);
                else if (brokeDown && bar.CloseTick <= _activeLowRail.MinTick)
                    StartLeg(Direction.Down, _activeLowRail, bar);
            }

            if (_leg != null)
            {
                if (_leg.Direction == Direction.Up && bar.HighTick > _leg.ExtremeTick)
                    _leg.ExtremeTick = bar.HighTick;
                else if (_leg.Direction == Direction.Down && bar.LowTick < _leg.ExtremeTick)
                    _leg.ExtremeTick = bar.LowTick;

                foreach (var b in bar.Bins.Values)
                    _leg.AddBin(b);

                var q = EvaluateLeg(_leg, bar);
                _leg.Quality = q;
                MaybeEmitQuality(bar.StartUtc, _leg, q);

                if (_leg.Direction == Direction.Up && bar.CloseTick < _activeHighRail.MinTick)
                {
                    AddMessage(bar.StartUtc, MessageKind.Failed, $"upper failed after {Abbrev(_leg.ExtremeTick)}");
                    _leg = brokeDown ? StartLeg(Direction.Down, _activeLowRail, bar, true) : null;
                }
                else if (_leg.Direction == Direction.Down && bar.CloseTick > _activeLowRail.MaxTick)
                {
                    AddMessage(bar.StartUtc, MessageKind.Failed, $"lower failed after {Abbrev(_leg.ExtremeTick)}");
                    _leg = null;
                }
            }

            MaybeAddRisk(bar);
        }

        private void TryReadyBracket(BarState bar)
        {
            if (_bracketReady) return;
            var local = TimeZoneInfo.ConvertTimeFromUtc(bar.StartUtc, _nyZone);
            int hm = local.Hour * 100 + local.Minute;
            if (IsBefore(hm, BracketReadyHHmm)) return;

            SelectActiveRails(bar);
            if (_activeLowRail != null && _activeHighRail != null)
            {
                _bracketReady = true;
                AddMessage(
                    bar.StartUtc,
                    MessageKind.Info,
                    $"bracket low {_activeLowRail.Text} / high {_activeHighRail.Text}");
            }
        }

        private void SelectActiveRails(BarState bar)
        {
            long reference = _rthOpenTick ?? bar.CloseTick;
            var views = BuildAllQualifiedRails(DateTime.UtcNow);
            var lows = views
                .Where(r => r.Side == RailSide.Demand && r.CenterTick <= Math.Max(reference + RailBinTicks * 3, _rthHighTick ?? reference))
                .OrderByDescending(r => ScoreForActive(r, reference, below: true))
                .ToList();
            var highs = views
                .Where(r => r.Side == RailSide.Supply && r.CenterTick >= Math.Min(reference - RailBinTicks * 3, _rthLowTick ?? reference))
                .OrderByDescending(r => r.CenterTick <= (_rthHighTick ?? reference) + RailBinTicks * 2)
                .ThenByDescending(r => ScoreForActive(r, reference, below: false))
                .ToList();

            _activeLowRail = lows.FirstOrDefault();
            _activeHighRail = highs.FirstOrDefault();
        }

        private double ScoreForActive(RailView r, long reference, bool below)
        {
            double dist = Math.Abs(r.CenterTick - reference) / Math.Max(1.0, RailBinTicks);
            double near = 1.0 / (1.0 + dist * 0.2);
            return r.DominantWeight * near * (r.Freshness == RailFreshness.Fresh ? 1.25 : 1.0);
        }

        private LegState StartLeg(Direction direction, RailView rail, BarState bar, bool returnLeg = false)
        {
            var leg = new LegState
            {
                Direction = direction,
                Rail = rail,
                StartUtc = bar.StartUtc,
                ExtremeTick = direction == Direction.Up ? bar.HighTick : bar.LowTick,
                LastCloseTick = bar.CloseTick,
            };
            foreach (var b in bar.Bins.Values)
                leg.AddBin(b);
            AddMessage(
                bar.StartUtc,
                direction == Direction.Up ? MessageKind.UpBreak : MessageKind.DownBreak,
                $"{(direction == Direction.Up ? "up" : "down")} through {Abbrev(rail.CenterTick)}; quality pending");
            if (!returnLeg)
                _leg = leg;
            return leg;
        }

        private void ApplyEventToLeg(ContextEvent ev)
        {
            if (_leg == null) return;
            if (!_leg.EventBins.TryGetValue(ev.BinTick, out var b))
            {
                b = new LegEventBin { BinTick = ev.BinTick };
                _leg.EventBins[ev.BinTick] = b;
            }
            if (ev.Bias > 0)
            {
                b.DemandWeight += ev.AbsZ;
                b.DemandEvents++;
            }
            else
            {
                b.SupplyWeight += ev.AbsZ;
                b.SupplyEvents++;
            }
        }

        private LegQuality EvaluateLeg(LegState leg, BarState bar)
        {
            long lo;
            long hi;
            if (leg.Direction == Direction.Up)
            {
                lo = leg.Rail.MaxTick;
                hi = Math.Max(leg.ExtremeTick, lo + RailBinTicks);
            }
            else
            {
                lo = Math.Min(leg.ExtremeTick, leg.Rail.MinTick - RailBinTicks);
                hi = leg.Rail.MinTick;
            }

            var bins = leg.TradeBins.Values.Where(b => b.BinTick >= BinTick(lo) && b.BinTick <= BinTick(hi)).ToList();
            double totalVol = bins.Sum(b => b.Volume);
            double avgVol = bins.Count > 0 ? totalVol / bins.Count : 0;
            double acceptedThreshold = Math.Max(450.0, avgVol * 0.65);
            double airThreshold = Math.Max(175.0, avgVol * 0.28);
            int acceptedBins = bins.Count(b => b.Volume >= acceptedThreshold);
            int airBins = bins.Count(b => b.Volume <= airThreshold);
            double airRatio = airBins / Math.Max(1.0, bins.Count);

            double demand = 0;
            double supply = 0;
            foreach (var e in leg.EventBins.Values.Where(e => e.BinTick >= BinTick(lo) && e.BinTick <= BinTick(hi)))
            {
                demand += e.DemandWeight;
                supply += e.SupplyWeight;
            }
            double same = leg.Direction == Direction.Up ? demand : supply;
            double opp = leg.Direction == Direction.Up ? supply : demand;

            double moved = Math.Abs((leg.ExtremeTick - leg.Rail.CenterTick) * _tickSize);
            double retrace = 0;
            if (moved > 0.0001)
            {
                retrace = leg.Direction == Direction.Up
                    ? (leg.ExtremeTick - bar.CloseTick) * _tickSize / moved
                    : (bar.CloseTick - leg.ExtremeTick) * _tickSize / moved;
            }
            retrace = Math.Max(0, Math.Min(2.0, retrace));
            double minutes = Math.Max(0.1, (bar.StartUtc - leg.StartUtc).TotalMinutes + BarMinutes);
            double speed = moved / minutes;

            var label = QualityLabel.Probing;
            if (moved >= 24.0 && retrace >= 0.60)
                label = QualityLabel.FastNoBuild;
            else if (moved >= 12.0 && (acceptedBins <= 1 || airRatio >= 0.45) && same / Math.Max(1.0, opp) < 1.35)
                label = QualityLabel.ThinMixed;
            else if (acceptedBins >= 3 && retrace <= 0.60)
                label = QualityLabel.Building;
            if (acceptedBins >= 6 && retrace <= 0.45 && minutes >= 12.0 && moved >= 24.0)
                label = QualityLabel.Accepted;

            return new LegQuality
            {
                Label = label,
                MovedPoints = moved,
                SpeedPointsPerMin = speed,
                Retrace = retrace,
                Bins = bins.Count,
                AcceptedBins = acceptedBins,
                AirBins = airBins,
                SameSideZ = same,
                OppSideZ = opp,
            };
        }

        private void MaybeEmitQuality(DateTime utc, LegState leg, LegQuality q)
        {
            if ((q.Label == QualityLabel.ThinMixed || q.Label == QualityLabel.FastNoBuild) && !leg.EmittedWeak)
            {
                AddMessage(utc, MessageKind.Quality, $"{LegName(leg)} {QualityText(q.Label)}; resolved not accepted");
                leg.EmittedWeak = true;
            }
            else if (q.Label == QualityLabel.Building && !leg.EmittedBuilding)
            {
                AddMessage(utc, MessageKind.Quality, $"{LegName(leg)} building beyond rail");
                leg.EmittedBuilding = true;
            }
            else if (q.Label == QualityLabel.Accepted && !leg.EmittedAccepted)
            {
                _frame = leg.Direction == Direction.Up ? "accepting higher" : "accepting lower";
                AddMessage(utc, MessageKind.Accepted, $"{LegName(leg)} accepted beyond rail");
                leg.EmittedAccepted = true;
            }
        }

        private void MaybeAddRisk(BarState bar)
        {
            if (_addRiskSent || _activeHighRail == null || _rthOpenTick == null) return;
            var local = TimeZoneInfo.ConvertTimeFromUtc(bar.StartUtc, _nyZone);
            int hm = local.Hour * 100 + local.Minute;
            if (IsBefore(hm, 1030)) return;
            if (bar.HighTick > _activeHighRail.MaxTick + RailBinTicks * 2 && bar.CloseTick > _rthOpenTick.Value)
            {
                AddMessage(bar.StartUtc, MessageKind.AddRisk, "upper extension: scale needs accepted pullback");
                _addRiskSent = true;
            }
        }

        private string LegName(LegState leg)
        {
            return $"{(leg.Direction == Direction.Up ? "up" : "down")} {Abbrev(leg.Rail.CenterTick)}->{Abbrev(leg.ExtremeTick)}";
        }

        private static string QualityText(QualityLabel label)
        {
            return label switch
            {
                QualityLabel.FastNoBuild => "fast/no-build",
                QualityLabel.ThinMixed => "thin/mixed",
                QualityLabel.Building => "building",
                QualityLabel.Accepted => "accepted",
                _ => "probing",
            };
        }

        private RailView[] BuildRailViews(long referenceTick, DateTime nowUtc)
        {
            var all = BuildAllQualifiedRails(nowUtc);
            var below = all
                .Where(r => r.CenterTick <= referenceTick)
                .OrderByDescending(r => DisplayScore(r, referenceTick))
                .Take(Math.Max(1, RailCountEachSide));
            var above = all
                .Where(r => r.CenterTick > referenceTick)
                .OrderByDescending(r => DisplayScore(r, referenceTick))
                .Take(Math.Max(1, RailCountEachSide));
            return below.Concat(above).OrderBy(r => r.CenterTick).ToArray();
        }

        private RailView[] BuildAllQualifiedRails(DateTime nowUtc)
        {
            double maxDom = _rails.Values.Where(r => r.IsQualified).Select(r => r.DominantWeight).DefaultIfEmpty(1.0).Max();
            return _rails.Values
                .Where(r => r.IsQualified)
                .Select(r => ToView(r, nowUtc, maxDom))
                .ToArray();
        }

        private RailView ToView(RailBucket rail, DateTime nowUtc, double maxDom)
        {
            int strength = rail.DominantWeight >= maxDom * 0.66 ? 3 : rail.DominantWeight >= maxDom * 0.38 ? 2 : 1;
            var freshness = RailFreshness.Old;
            if (!_sawRthOpen || (_rthOpenTick.HasValue && (nowUtc - rail.LastUtc).TotalMinutes <= 90))
                freshness = RailFreshness.Fresh;
            return new RailView
            {
                Side = rail.Side,
                Origin = rail.Origin,
                Freshness = freshness,
                Strength = strength,
                MinTick = rail.BinTick,
                MaxTick = rail.BinTick + Math.Max(1, RailBinTicks) - 1,
                CenterTick = rail.BinTick + Math.Max(1, RailBinTicks) / 2,
                FirstUtc = rail.FirstUtc,
                LastUtc = rail.LastUtc,
                DominantWeight = rail.DominantWeight,
                OpposingWeight = rail.OpposingWeight,
                Ratio = rail.Ratio,
                TouchedRth = rail.TouchedRth,
            };
        }

        private double DisplayScore(RailView r, long referenceTick)
        {
            double dist = Math.Abs(r.CenterTick - referenceTick) / Math.Max(1.0, RailBinTicks);
            return r.DominantWeight / (1.0 + dist * 0.12);
        }

        private void AddMessage(DateTime utc, MessageKind kind, string text)
        {
            _messages.Add(new ContextMessage
            {
                Id = _nextMessageId++,
                TimeUtc = utc,
                Kind = kind,
                Text = text,
            });
            _messages.RemoveAll(m => (utc - m.TimeUtc).TotalHours > 4);
        }

        private ContextPhase UpdateSession(DateTime utc)
        {
            DateTime local = TimeZoneInfo.ConvertTimeFromUtc(utc, _nyZone);
            var sessionDate = TradingDate(local);
            if (!_sessionDateNy.HasValue || _sessionDateNy.Value.Date != sessionDate.Date)
                ResetForSession(sessionDate);

            int hm = local.Hour * 100 + local.Minute;
            if (IsOnTime(hm))
                return ContextPhase.ON;
            if (IsBefore(hm, BracketReadyHHmm))
                return ContextPhase.RthBuild;
            if (IsBefore(hm, UpdateCutoffHHmm))
                return ContextPhase.RthUpdate;
            return ContextPhase.AfterCutoff;
        }

        private DateTime TradingDate(DateTime local)
        {
            int hm = local.Hour * 100 + local.Minute;
            if (!IsBefore(hm, OnStartHHmm))
                return local.Date.AddDays(1);
            return local.Date;
        }

        private bool IsOnTime(int hm)
        {
            return !IsBefore(hm, OnStartHHmm) || IsBefore(hm, RthStartHHmm);
        }

        private static bool IsBefore(int hm, int cutoff)
        {
            int h = hm / 100;
            int m = hm % 100;
            int ch = cutoff / 100;
            int cm = cutoff % 100;
            return h < ch || (h == ch && m < cm);
        }

        private void ResetForSession(DateTime sessionDate)
        {
            _sessionDateNy = sessionDate.Date;
            _samples.Clear();
            _rails.Clear();
            _events.Clear();
            _messages.Clear();
            _recentBins.Clear();
            _nextMessageId = 1;
            _lastTradeTick = null;
            _rthOpenTick = null;
            _rthHighTick = null;
            _rthLowTick = null;
            _sawRthOpen = false;
            _bar = null;
            _activeLowRail = null;
            _activeHighRail = null;
            _leg = null;
            _frame = "building";
            _bracketReady = false;
            _addRiskSent = false;
        }

        private void Prune(DateTime nowUtc)
        {
            DateTime cutoff = nowUtc.AddHours(-MaxRailKeepHours);
            var remove = _rails.Where(kv => kv.Value.LastUtc < cutoff).Select(kv => kv.Key).ToList();
            foreach (var key in remove)
                _rails.Remove(key);
            _events.RemoveAll(e => e.TimeUtc < nowUtc.AddHours(-4));
        }

        private BookSample ComputeSample(DateTime nowUtc, DepthOfMarketAggregatedCollections dom)
        {
            var bids = dom.Bids ?? Array.Empty<Level2Item>();
            var asks = dom.Asks ?? Array.Empty<Level2Item>();
            double bidInner = SumSizes(bids, InnerLevels);
            double askInner = SumSizes(asks, InnerLevels);
            double bidBroad = SumSizes(bids, BroadLevels);
            double askBroad = SumSizes(asks, BroadLevels);
            double bidCentroid = Centroid(bids, BroadLevels);
            double askCentroid = Centroid(asks, BroadLevels);

            long midTick = 0;
            double bid = FirstValidPrice(bids);
            double ask = FirstValidPrice(asks);
            if (double.IsFinite(bid) && double.IsFinite(ask))
                midTick = PriceToTicks((bid + ask) * 0.5);
            else if (double.IsFinite(bid))
                midTick = PriceToTicks(bid);
            else if (double.IsFinite(ask))
                midTick = PriceToTicks(ask);

            return new BookSample
            {
                TimeUtc = nowUtc,
                MidTick = midTick,
                BidInner = bidInner,
                AskInner = askInner,
                BidCentroid = bidCentroid,
                AskCentroid = askCentroid,
            };
        }

        private (double mean, double std) MeanStd(Func<BookSample, double> selector, DateTime nowUtc)
        {
            DateTime cutoff = nowUtc.AddSeconds(-Math.Max(10, BookLookbackSec));
            var vals = _samples.Where(s => s.TimeUtc >= cutoff).Select(selector).ToArray();
            if (vals.Length < 2) return (0, 0);
            double mean = vals.Average();
            double var = vals.Select(v => v * v).Average() - mean * mean;
            return (mean, var > 0 ? Math.Sqrt(var) : 0);
        }

        private static void EvictOlderThan(LinkedList<BookSample> list, DateTime nowUtc, int seconds)
        {
            DateTime cutoff = nowUtc.AddSeconds(-seconds);
            while (list.First != null && list.First.Value.TimeUtc < cutoff)
                list.RemoveFirst();
        }

        private static double SumSizes(Level2Item[] arr, int n)
        {
            double sum = 0;
            int limit = Math.Min(n, arr.Length);
            for (int i = 0; i < limit; i++)
            {
                double s = arr[i].Size;
                if (double.IsFinite(s) && s > 0) sum += s;
            }
            return sum;
        }

        private long BinTick(long tick)
        {
            int bin = Math.Max(1, RailBinTicks);
            return (tick / bin) * bin;
        }

        private double Centroid(Level2Item[] arr, int n)
        {
            double best = FirstValidPrice(arr);
            if (!double.IsFinite(best)) return 0;
            long bestTick = PriceToTicks(best);
            double weighted = 0;
            double sum = 0;
            int limit = Math.Min(n, arr.Length);
            for (int i = 0; i < limit; i++)
            {
                double p = arr[i].Price;
                double s = arr[i].Size;
                if (!double.IsFinite(p) || !double.IsFinite(s) || p <= 0 || s <= 0) continue;
                long t = PriceToTicks(p);
                weighted += Math.Abs(t - bestTick) * s;
                sum += s;
            }
            return sum > 0 ? weighted / sum : 0;
        }

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

        private DateTime BarStartUtc(DateTime utc)
        {
            DateTime local = TimeZoneInfo.ConvertTimeFromUtc(utc, _nyZone);
            int minute = (local.Minute / BarMinutes) * BarMinutes;
            var localStart = new DateTime(local.Year, local.Month, local.Day, local.Hour, minute, 0, DateTimeKind.Unspecified);
            return TimeZoneInfo.ConvertTimeToUtc(localStart, _nyZone);
        }

        internal long PriceToTicks(double price)
        {
            return (long)Math.Round(price / Math.Max(0.0000001, _tickSize));
        }

        internal string Abbrev(long tick)
        {
            double price = tick * _tickSize;
            int whole = (int)Math.Floor(price);
            int last = ((whole % 1000) + 1000) % 1000;
            double frac = price - whole;
            if (Math.Abs(frac) < 0.0001)
                return last.ToString("000");
            return last.ToString("000") + frac.ToString(".00").TrimEnd('0');
        }
    }

    internal enum ContextPhase { Waiting, ON, RthBuild, RthUpdate, AfterCutoff }
    internal enum RailOrigin { ON, RTH }
    internal enum RailSide { Neutral, Demand, Supply }
    internal enum RailFreshness { Old, Fresh }
    internal enum Direction { Up, Down }
    internal enum QualityLabel { Probing, ThinMixed, FastNoBuild, Building, Accepted }
    internal enum MessageKind { Info, Sweep, UpBreak, DownBreak, Quality, Accepted, Failed, AddRisk }

    internal sealed class BookSample
    {
        public DateTime TimeUtc;
        public long MidTick;
        public double BidInner;
        public double AskInner;
        public double BidCentroid;
        public double AskCentroid;
    }

    internal sealed class ContextEvent
    {
        public DateTime TimeUtc;
        public long PriceTick;
        public long BinTick;
        public int Bias;
        public double AbsZ;
        public string Kind;
    }

    internal sealed class RailBucket
    {
        public long BinTick;
        public RailOrigin Origin;
        public RailSide Side;
        public DateTime FirstUtc;
        public DateTime LastUtc;
        public double DemandWeight;
        public double SupplyWeight;
        public double DominantWeight;
        public double OpposingWeight;
        public double Ratio;
        public int DemandEvents;
        public int SupplyEvents;
        public bool TouchedRth;
        public bool IsQualified;
    }

    internal sealed class RailView
    {
        public RailSide Side;
        public RailOrigin Origin;
        public RailFreshness Freshness;
        public int Strength;
        public long MinTick;
        public long MaxTick;
        public long CenterTick;
        public DateTime FirstUtc;
        public DateTime LastUtc;
        public double DominantWeight;
        public double OpposingWeight;
        public double Ratio;
        public bool TouchedRth;

        public string Text => $"{(Side == RailSide.Demand ? "D" : "S")}{Strength}";
    }

    internal sealed class BarState
    {
        public readonly DateTime StartUtc;
        public long OpenTick;
        public long HighTick;
        public long LowTick;
        public long CloseTick;
        public double Volume;
        public double Delta;
        public int Trades;
        public readonly Dictionary<long, BarBin> Bins = new();

        public BarState(DateTime startUtc, long openTick)
        {
            StartUtc = startUtc;
            OpenTick = openTick;
            HighTick = openTick;
            LowTick = openTick;
            CloseTick = openTick;
        }
    }

    internal sealed class BarBin
    {
        public DateTime TimeUtc;
        public long BinTick;
        public double Volume;
        public double Delta;
        public int Trades;
    }

    internal sealed class LegEventBin
    {
        public long BinTick;
        public double DemandWeight;
        public double SupplyWeight;
        public int DemandEvents;
        public int SupplyEvents;
    }

    internal sealed class LegState
    {
        public Direction Direction;
        public RailView Rail;
        public DateTime StartUtc;
        public long ExtremeTick;
        public long LastCloseTick;
        public readonly Dictionary<long, BarBin> TradeBins = new();
        public readonly Dictionary<long, LegEventBin> EventBins = new();
        public LegQuality Quality;
        public bool EmittedWeak;
        public bool EmittedBuilding;
        public bool EmittedAccepted;

        public void AddBin(BarBin source)
        {
            if (!TradeBins.TryGetValue(source.BinTick, out var b))
            {
                b = new BarBin { BinTick = source.BinTick, TimeUtc = source.TimeUtc };
                TradeBins[source.BinTick] = b;
            }
            b.Volume += source.Volume;
            b.Delta += source.Delta;
            b.Trades += source.Trades;
        }

        public LegView ToView()
        {
            return new LegView
            {
                Direction = Direction,
                Rail = Rail,
                StartUtc = StartUtc,
                ExtremeTick = ExtremeTick,
                Quality = Quality,
            };
        }
    }

    internal sealed class LegQuality
    {
        public QualityLabel Label;
        public double MovedPoints;
        public double SpeedPointsPerMin;
        public double Retrace;
        public int Bins;
        public int AcceptedBins;
        public int AirBins;
        public double SameSideZ;
        public double OppSideZ;
    }

    internal sealed class LegView
    {
        public Direction Direction;
        public RailView Rail;
        public DateTime StartUtc;
        public long ExtremeTick;
        public LegQuality Quality;
    }

    internal sealed class ContextMessage
    {
        public int Id;
        public DateTime TimeUtc;
        public MessageKind Kind;
        public string Text;
    }

    internal sealed class ContextSnapshot
    {
        public ContextPhase Phase;
        public string Frame;
        public DateTime? SessionDateNy;
        public long? RthOpenTick;
        public long? RthHighTick;
        public long? RthLowTick;
        public long? LastTradeTick;
        public RailView ActiveLow;
        public RailView ActiveHigh;
        public LegView Leg;
        public IReadOnlyList<RailView> Rails = Array.Empty<RailView>();
        public IReadOnlyList<ContextMessage> Messages = Array.Empty<ContextMessage>();
    }
}
