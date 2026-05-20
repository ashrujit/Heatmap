using System;
using System.Collections.Generic;
using System.Linq;
using TradingPlatform.BusinessLayer;

namespace ON_ContextMap
{
    internal sealed class ScenarioEngine
    {
        private const int InnerLevels = 10;
        private const int BroadLevels = 30;
        private const int MaxZoneKeepHours = 20;

        private readonly LinkedList<BookSample> _samples = new();
        private readonly List<ScenarioZone> _zones = new();
        private readonly List<ScenarioRow> _rows = new();
        private TimeZoneInfo _nyZone;
        private DateTime? _sessionDateNy;
        private int _nextZoneId = 1;
        private int _nextRowId = 1;
        private long? _lastTradeTick;
        private long? _rthOpenTick;
        private long? _rthHighTick;
        private long? _rthLowTick;
        private bool _sawRthOpen;

        public int BookLookbackSec { get; set; } = 30;
        public double EventZThreshold { get; set; } = 2.5;
        public int OnStartHHmm { get; set; } = 1800;
        public int RthStartHHmm { get; set; } = 930;
        public int NewZoneCutoffHHmm { get; set; } = 1030;
        public int UpdateCutoffHHmm { get; set; } = 1200;
        public int ZoneClusterTicks { get; set; } = 16;
        public int ZoneMinDominantEvents { get; set; } = 3;
        public double ZoneMinDominantWeight { get; set; } = 10.0;
        public double ZoneDominanceRatio { get; set; } = 1.4;
        public int TestBandTicks { get; set; } = 12;
        public int AcceptanceMoveTicks { get; set; } = 24;
        public int RebuildWindowSec { get; set; } = 120;

        public ScenarioEngine()
        {
            try { _nyZone = TimeZoneInfo.FindSystemTimeZoneById("Eastern Standard Time"); }
            catch { _nyZone = TimeZoneInfo.Local; }
        }

        public void OnTrade(DateTime timeUtc, double price, double size, int aggressorSign, double tickSize)
        {
            if (!double.IsFinite(price) || price <= 0) return;
            if (!double.IsFinite(size) || size <= 0) return;

            var phase = UpdateSession(timeUtc);
            long tick = PriceToTicks(price, tickSize);
            _lastTradeTick = tick;

            if (phase == ScenarioPhase.RthBuild || phase == ScenarioPhase.RthUpdate || phase == ScenarioPhase.AfterCutoff)
            {
                if (!_sawRthOpen)
                {
                    _sawRthOpen = true;
                    _rthOpenTick = tick;
                    _rthHighTick = tick;
                    _rthLowTick = tick;
                    AddSystemRow(timeUtc, $"open {Abbrev(tick, tickSize)}");
                }
                _rthHighTick = Math.Max(_rthHighTick ?? tick, tick);
                _rthLowTick = Math.Min(_rthLowTick ?? tick, tick);
            }

            if (phase == ScenarioPhase.RthBuild || phase == ScenarioPhase.RthUpdate)
                UpdateZoneTradeState(timeUtc, tick, tickSize);
        }

        public void OnBookSample(DateTime nowUtc, DepthOfMarketAggregatedCollections dom, double tickSize)
        {
            var phase = UpdateSession(nowUtc);
            var sample = ComputeSample(nowUtc, dom, tickSize);
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

            TryFire(nowUtc, sample.MidTick, zBi, +1, "BID_BUILD", "BID_PULL", phase, tickSize);
            TryFire(nowUtc, sample.MidTick, zAi, -1, "ASK_BUILD", "ASK_PULL", phase, tickSize);
            TryFire(nowUtc, sample.MidTick, zBc, -1, "BID_OUT", "BID_IN", phase, tickSize);
            TryFire(nowUtc, sample.MidTick, zAc, +1, "ASK_OUT", "ASK_IN", phase, tickSize);

            Prune(nowUtc);
        }

        public ScenarioSnapshot GetSnapshot(int maxRows, DateTime nowUtc)
        {
            var phase = UpdateSession(nowUtc);
            var zones = _zones
                .Where(z => z.IsQualified)
                .OrderByDescending(z => z.Origin == ZoneOrigin.ON ? 1 : 0)
                .ThenByDescending(z => z.LastStateUtc)
                .ThenBy(z => z.CenterTick)
                .Select(z => z.Clone())
                .ToArray();

            var rows = BuildRows(maxRows, nowUtc, phase);
            return new ScenarioSnapshot
            {
                Phase = phase,
                SessionDateNy = _sessionDateNy,
                RthOpenTick = _rthOpenTick,
                RthHighTick = _rthHighTick,
                RthLowTick = _rthLowTick,
                Zones = zones,
                Rows = rows,
            };
        }

        private ScenarioRow[] BuildRows(int maxRows, DateTime nowUtc, ScenarioPhase phase)
        {
            var result = new List<ScenarioRow>();
            result.Add(new ScenarioRow
            {
                Id = 0,
                TimeUtc = nowUtc,
                Side = ZoneSide.Neutral,
                State = ZoneState.Info,
                Text = SummaryText(phase),
            });

            var important = _zones
                .Where(z => z.IsQualified)
                .OrderByDescending(z => z.LastStateUtc)
                .ThenByDescending(z => z.DominantWeight)
                .Take(Math.Max(1, maxRows - 1));

            foreach (var z in important)
            {
                result.Add(new ScenarioRow
                {
                    Id = z.Id,
                    TimeUtc = z.LastStateUtc,
                    Side = z.Side,
                    State = z.State,
                    Text = ZoneText(z),
                });
            }

            return result.Take(Math.Max(1, maxRows)).ToArray();
        }

        private string SummaryText(ScenarioPhase phase)
        {
            string phaseText = phase switch
            {
                ScenarioPhase.ON => "ON building rails",
                ScenarioPhase.RthBuild => "IB accepting?",
                ScenarioPhase.RthUpdate => "IB state updating",
                ScenarioPhase.AfterCutoff => "state frozen",
                _ => "waiting",
            };

            if (_rthOpenTick.HasValue && _rthHighTick.HasValue && _rthLowTick.HasValue)
                return $"{phaseText}  O {Abbrev(_rthOpenTick.Value, 0.25)}  H {Abbrev(_rthHighTick.Value, 0.25)}  L {Abbrev(_rthLowTick.Value, 0.25)}";
            return phaseText;
        }

        private string ZoneText(ScenarioZone z)
        {
            string side = z.Side == ZoneSide.Demand ? "D" : z.Side == ZoneSide.Supply ? "S" : "N";
            string origin = z.Origin == ZoneOrigin.ON ? "ON" : "RTH";
            string state = z.State switch
            {
                ZoneState.Unresolved => "unresolved",
                ZoneState.Tested => "tested",
                ZoneState.Held => "held",
                ZoneState.Rebuilt => "rebuilt",
                ZoneState.ResolvedUp => "resolved up",
                ZoneState.ResolvedDown => "resolved down",
                ZoneState.Contested => "contested",
                ZoneState.Swept => "swept",
                ZoneState.Accepted => "accepted",
                _ => "info",
            };
            string tests = z.TestCount > 0 ? $" T{z.TestCount}" : "";
            return $"{Abbrev(z.CenterTick, 0.25)} {side} {origin}{tests} {state}";
        }

        private void TryFire(
            DateTime nowUtc,
            long priceTick,
            double z,
            int posBias,
            string posKind,
            string negKind,
            ScenarioPhase phase,
            double tickSize)
        {
            if (!double.IsFinite(z) || Math.Abs(z) <= EventZThreshold) return;

            int bias = z > 0 ? posBias : -posBias;
            string kind = z > 0 ? posKind : negKind;
            var ev = new BookEvent
            {
                TimeUtc = nowUtc,
                PriceTick = priceTick,
                Bias = bias,
                AbsZ = Math.Abs(z),
                Kind = kind,
            };

            bool canCreate = phase == ScenarioPhase.ON || phase == ScenarioPhase.RthBuild;
            ZoneOrigin origin = phase == ScenarioPhase.ON ? ZoneOrigin.ON : ZoneOrigin.RTH;
            ApplyEventToZones(ev, phase, canCreate, origin, tickSize);
        }

        private void ApplyEventToZones(BookEvent ev, ScenarioPhase phase, bool canCreate, ZoneOrigin origin, double tickSize)
        {
            ZoneSide eventSide = ev.Bias > 0 ? ZoneSide.Demand : ZoneSide.Supply;
            var nearby = _zones
                .Where(z => Math.Abs(z.CenterTick - ev.PriceTick) <= Math.Max(1, ZoneClusterTicks))
                .OrderBy(z => Math.Abs(z.CenterTick - ev.PriceTick))
                .FirstOrDefault();

            if (nearby == null && canCreate)
            {
                nearby = new ScenarioZone
                {
                    Id = _nextZoneId++,
                    Origin = origin,
                    Side = eventSide,
                    State = ZoneState.Unresolved,
                    FirstUtc = ev.TimeUtc,
                    LastEventUtc = ev.TimeUtc,
                    LastStateUtc = ev.TimeUtc,
                    MinTick = ev.PriceTick,
                    MaxTick = ev.PriceTick,
                    CenterTick = ev.PriceTick,
                };
                _zones.Add(nearby);
            }

            if (nearby == null)
                return;

            nearby.LastEventUtc = ev.TimeUtc;
            nearby.MinTick = Math.Min(nearby.MinTick, ev.PriceTick);
            nearby.MaxTick = Math.Max(nearby.MaxTick, ev.PriceTick);
            nearby.CenterTick = (nearby.MinTick + nearby.MaxTick) / 2;
            if (ev.Bias > 0)
            {
                nearby.DemandWeight += ev.AbsZ;
                nearby.DemandEvents++;
            }
            else
            {
                nearby.SupplyWeight += ev.AbsZ;
                nearby.SupplyEvents++;
            }

            UpdateQualificationAndSide(nearby);

            if (phase == ScenarioPhase.RthBuild || phase == ScenarioPhase.RthUpdate)
                UpdateZoneEventState(nearby, ev, eventSide, tickSize);

            foreach (var z in _zones.Where(z => z.IsQualified && z.Id != nearby.Id))
                UpdateThroughStateFromEvent(z, ev, tickSize);
        }

        private void UpdateQualificationAndSide(ScenarioZone z)
        {
            double dom = Math.Max(z.DemandWeight, z.SupplyWeight);
            double opp = Math.Min(z.DemandWeight, z.SupplyWeight);
            int domEvents = z.DemandWeight >= z.SupplyWeight ? z.DemandEvents : z.SupplyEvents;
            z.DominantWeight = dom;
            z.OpposingWeight = opp;
            if (domEvents >= Math.Max(1, ZoneMinDominantEvents)
                && dom >= Math.Max(1.0, ZoneMinDominantWeight)
                && dom / Math.Max(1.0, opp) >= Math.Max(1.0, ZoneDominanceRatio))
            {
                z.IsQualified = true;
                z.Side = z.DemandWeight >= z.SupplyWeight ? ZoneSide.Demand : ZoneSide.Supply;
            }
        }

        private void UpdateZoneTradeState(DateTime nowUtc, long tradeTick, double tickSize)
        {
            foreach (var z in _zones.Where(z => z.IsQualified))
            {
                bool inTestBand = tradeTick >= z.MinTick - TestBandTicks && tradeTick <= z.MaxTick + TestBandTicks;
                if (inTestBand)
                {
                    if (!z.IsTesting)
                    {
                        z.IsTesting = true;
                        z.TestCount++;
                        SetState(z, ZoneState.Tested, nowUtc);
                    }
                }
                else
                {
                    z.IsTesting = false;
                }

                if (z.Side == ZoneSide.Demand)
                {
                    if (tradeTick < z.MinTick - AcceptanceMoveTicks)
                        SetState(z, ZoneState.Swept, nowUtc);
                    else if ((z.State == ZoneState.Swept || z.State == ZoneState.Tested)
                             && tradeTick > z.MaxTick + Math.Max(1, TestBandTicks / 2))
                        SetState(z, ZoneState.Held, nowUtc);
                }
                else if (z.Side == ZoneSide.Supply)
                {
                    if (tradeTick > z.MaxTick + AcceptanceMoveTicks)
                        SetState(z, ZoneState.ResolvedUp, nowUtc);
                    else if ((z.State == ZoneState.ResolvedUp || z.State == ZoneState.Tested)
                             && tradeTick < z.MinTick - Math.Max(1, TestBandTicks / 2))
                        SetState(z, ZoneState.Held, nowUtc);
                }
            }
        }

        private void UpdateZoneEventState(ScenarioZone z, BookEvent ev, ZoneSide eventSide, double tickSize)
        {
            bool near = ev.PriceTick >= z.MinTick - ZoneClusterTicks && ev.PriceTick <= z.MaxTick + ZoneClusterTicks;
            if (!near) return;

            if (eventSide == z.Side)
            {
                if (z.TestCount > 0)
                    SetState(z, ZoneState.Rebuilt, ev.TimeUtc);
                else if (z.Origin == ZoneOrigin.RTH)
                    SetState(z, ZoneState.Accepted, ev.TimeUtc);
            }
            else if (z.State == ZoneState.Unresolved || z.State == ZoneState.Tested)
            {
                SetState(z, ZoneState.Contested, ev.TimeUtc);
            }
        }

        private void UpdateThroughStateFromEvent(ScenarioZone z, BookEvent ev, double tickSize)
        {
            if (!_lastTradeTick.HasValue) return;
            if (z.Side == ZoneSide.Supply
                && _lastTradeTick.Value > z.MaxTick + AcceptanceMoveTicks
                && ev.PriceTick > z.MaxTick + AcceptanceMoveTicks)
            {
                SetState(z, ZoneState.ResolvedUp, ev.TimeUtc);
            }
            else if (z.Side == ZoneSide.Demand
                     && _lastTradeTick.Value < z.MinTick - AcceptanceMoveTicks
                     && ev.PriceTick < z.MinTick - AcceptanceMoveTicks)
            {
                SetState(z, ZoneState.ResolvedDown, ev.TimeUtc);
            }
        }

        private void SetState(ScenarioZone z, ZoneState state, DateTime timeUtc)
        {
            if (z.State == state && (timeUtc - z.LastStateUtc).TotalSeconds < 15)
                return;
            z.State = state;
            z.LastStateUtc = timeUtc;
            _rows.Add(new ScenarioRow
            {
                Id = _nextRowId++,
                TimeUtc = timeUtc,
                Side = z.Side,
                State = state,
                Text = ZoneText(z),
            });
        }

        private void AddSystemRow(DateTime timeUtc, string text)
        {
            _rows.Add(new ScenarioRow
            {
                Id = _nextRowId++,
                TimeUtc = timeUtc,
                Side = ZoneSide.Neutral,
                State = ZoneState.Info,
                Text = text,
            });
        }

        private ScenarioPhase UpdateSession(DateTime utc)
        {
            DateTime local = TimeZoneInfo.ConvertTimeFromUtc(utc, _nyZone);
            var sessionDate = TradingDate(local);
            if (!_sessionDateNy.HasValue || _sessionDateNy.Value.Date != sessionDate.Date)
            {
                ResetForSession(sessionDate);
            }

            int hm = local.Hour * 100 + local.Minute;
            if (IsOnTime(hm))
                return ScenarioPhase.ON;
            if (IsBefore(hm, NewZoneCutoffHHmm))
                return ScenarioPhase.RthBuild;
            if (IsBefore(hm, UpdateCutoffHHmm))
                return ScenarioPhase.RthUpdate;
            return ScenarioPhase.AfterCutoff;
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
            _zones.Clear();
            _rows.Clear();
            _nextZoneId = 1;
            _nextRowId = 1;
            _lastTradeTick = null;
            _rthOpenTick = null;
            _rthHighTick = null;
            _rthLowTick = null;
            _sawRthOpen = false;
        }

        private void Prune(DateTime nowUtc)
        {
            DateTime cutoff = nowUtc.AddHours(-MaxZoneKeepHours);
            _zones.RemoveAll(z => z.LastEventUtc < cutoff && z.LastStateUtc < cutoff);
            _rows.RemoveAll(r => r.TimeUtc < nowUtc.AddHours(-6));
        }

        private BookSample ComputeSample(DateTime nowUtc, DepthOfMarketAggregatedCollections dom, double tickSize)
        {
            var bids = dom.Bids ?? Array.Empty<Level2Item>();
            var asks = dom.Asks ?? Array.Empty<Level2Item>();
            double bidInner = SumSizes(bids, InnerLevels);
            double askInner = SumSizes(asks, InnerLevels);
            double bidBroad = SumSizes(bids, BroadLevels);
            double askBroad = SumSizes(asks, BroadLevels);
            double bidCentroid = Centroid(bids, BroadLevels, tickSize);
            double askCentroid = Centroid(asks, BroadLevels, tickSize);

            long midTick = 0;
            double bid = FirstValidPrice(bids);
            double ask = FirstValidPrice(asks);
            if (double.IsFinite(bid) && double.IsFinite(ask))
                midTick = (long)Math.Round(((bid + ask) * 0.5) / tickSize);
            else if (double.IsFinite(bid))
                midTick = PriceToTicks(bid, tickSize);
            else if (double.IsFinite(ask))
                midTick = PriceToTicks(ask, tickSize);

            return new BookSample
            {
                TimeUtc = nowUtc,
                MidTick = midTick,
                BidInner = bidInner,
                AskInner = askInner,
                BidBroad = bidBroad,
                AskBroad = askBroad,
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

        private static double Centroid(Level2Item[] arr, int n, double tickSize)
        {
            double best = FirstValidPrice(arr);
            if (!double.IsFinite(best)) return 0;
            long bestTick = PriceToTicks(best, tickSize);
            double weighted = 0;
            double sum = 0;
            int limit = Math.Min(n, arr.Length);
            for (int i = 0; i < limit; i++)
            {
                double p = arr[i].Price;
                double s = arr[i].Size;
                if (!double.IsFinite(p) || !double.IsFinite(s) || p <= 0 || s <= 0) continue;
                long t = PriceToTicks(p, tickSize);
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

        internal static long PriceToTicks(double price, double tickSize)
        {
            return (long)Math.Round(price / Math.Max(0.0000001, tickSize));
        }

        internal static string Abbrev(long tick, double tickSize)
        {
            double price = tick * tickSize;
            int whole = (int)Math.Floor(price);
            int last = ((whole % 1000) + 1000) % 1000;
            double frac = price - whole;
            if (Math.Abs(frac) < 0.0001)
                return last.ToString("000");
            return last.ToString("000") + frac.ToString(".00").TrimEnd('0');
        }

        private sealed class BookSample
        {
            public DateTime TimeUtc;
            public long MidTick;
            public double BidInner;
            public double AskInner;
            public double BidBroad;
            public double AskBroad;
            public double BidCentroid;
            public double AskCentroid;
        }

        private sealed class BookEvent
        {
            public DateTime TimeUtc;
            public long PriceTick;
            public int Bias;
            public double AbsZ;
            public string Kind;
        }
    }

    internal enum ScenarioPhase
    {
        Waiting,
        ON,
        RthBuild,
        RthUpdate,
        AfterCutoff,
    }

    internal enum ZoneOrigin
    {
        ON,
        RTH,
    }

    internal enum ZoneSide
    {
        Neutral,
        Demand,
        Supply,
    }

    internal enum ZoneState
    {
        Info,
        Unresolved,
        Tested,
        Held,
        Rebuilt,
        ResolvedUp,
        ResolvedDown,
        Contested,
        Swept,
        Accepted,
    }

    internal sealed class ScenarioZone
    {
        public int Id;
        public ZoneOrigin Origin;
        public ZoneSide Side;
        public ZoneState State;
        public DateTime FirstUtc;
        public DateTime LastEventUtc;
        public DateTime LastStateUtc;
        public long MinTick;
        public long MaxTick;
        public long CenterTick;
        public double DemandWeight;
        public double SupplyWeight;
        public double DominantWeight;
        public double OpposingWeight;
        public int DemandEvents;
        public int SupplyEvents;
        public int TestCount;
        public bool IsTesting;
        public bool IsQualified;

        public ScenarioZone Clone()
        {
            return (ScenarioZone)MemberwiseClone();
        }
    }

    internal sealed class ScenarioRow
    {
        public int Id;
        public DateTime TimeUtc;
        public ZoneSide Side;
        public ZoneState State;
        public string Text;
    }

    internal sealed class ScenarioSnapshot
    {
        public ScenarioPhase Phase;
        public DateTime? SessionDateNy;
        public long? RthOpenTick;
        public long? RthHighTick;
        public long? RthLowTick;
        public IReadOnlyList<ScenarioZone> Zones = Array.Empty<ScenarioZone>();
        public IReadOnlyList<ScenarioRow> Rows = Array.Empty<ScenarioRow>();
    }
}
