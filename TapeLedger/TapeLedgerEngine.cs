using System;
using System.Collections.Generic;
using System.Linq;

namespace TapeLedger
{
    internal enum TapeSide
    {
        Neutral,
        Demand,
        Supply,
        Accepted,
        Warning,
    }

    internal enum TapeBandState
    {
        New,
        Active,
        Held,
        Consumed,
    }

    internal sealed class TapeBandView
    {
        public long MinTick;
        public long MaxTick;
        public long CenterTick;
        public DateTime StartUtc;
        public DateTime LastUtc;
        public TapeSide Side;
        public TapeBandState State;
        public double Volume;
        public double Delta;
        public int Seconds;
        public double Score;
        public string Text = "";
    }

    internal sealed class QuickRejectBandView
    {
        public long MinTick;
        public long MaxTick;
        public long RefTick;
        public long ExtremeTick;
        public DateTime StartUtc;
        public DateTime BuiltUtc;
        public int Direction;
        public string Text = "";
    }

    internal sealed class TapeBannerView
    {
        public TapeSide Side;
        public string Text = "";
        public string Detail = "";
        public DateTime TimeUtc;
    }

    internal sealed class TapeMessageView
    {
        public DateTime TimeUtc;
        public TapeSide Side;
        public string Text = "";
    }

    internal sealed class TapeSnapshot
    {
        public DateTime? SessionDateNy;
        public long? LastTradeTick;
        public long? RthOpenTick;
        public long? RthHighTick;
        public long? RthLowTick;
        public long? OrHighTick;
        public long? OrLowTick;
        public long? IbHighTick;
        public long? IbLowTick;
        public TapeBandView[] Bands = Array.Empty<TapeBandView>();
        public QuickRejectBandView[] QuickRejectBands = Array.Empty<QuickRejectBandView>();
        public TapeBannerView[] Banners = Array.Empty<TapeBannerView>();
        public TapeMessageView[] Messages = Array.Empty<TapeMessageView>();
    }

    internal sealed class TapeLedgerEngine
    {
        private readonly double _tickSize;
        private readonly TimeZoneInfo _nyZone;
        private readonly List<BinAggregate> _recentBins = new();
        private readonly List<CompletedBar> _recentBars = new();
        private readonly List<TapeMessageView> _messages = new();
        private readonly List<ExtremeCandidate> _extremes = new();
        private readonly List<QuickRejectState> _quickRejects = new();
        private readonly Dictionary<string, QuickRejectProbe> _quickRejectProbes = new();
        private int _nextQuickRejectId = 1;
        private DateTime? _sessionDateNy;
        private BarState _bar;
        private BreakState _orBreak;
        private BreakState _ibBreak;
        private long? _lastTradeTick;
        private long? _rthOpenTick;
        private long? _rthHighTick;
        private long? _rthLowTick;
        private long? _orHighTick;
        private long? _orLowTick;
        private long? _ibHighTick;
        private long? _ibLowTick;

        public int RthStartHHmm { get; set; } = 930;
        public int RthEndHHmm { get; set; } = 1600;
        public int OrMinutes { get; set; } = 5;
        public int IbMinutes { get; set; } = 60;
        public int IbBreakEndHHmm { get; set; } = 1230;
        public int BarMinutes { get; set; } = 5;
        public int ShelfBinTicks { get; set; } = 16;
        public int ShelfLookbackMinutes { get; set; } = 30;
        public int ShelfCount { get; set; } = 6;
        public double MinShelfVolume { get; set; } = 1200.0;
        public int MinShelfSeconds { get; set; } = 35;
        public int BreakBufferTicks { get; set; } = 16;
        public int ReclaimBufferTicks { get; set; } = 8;
        public int ExtremeTestTicks { get; set; } = 32;
        public int ExtremeCapTicks { get; set; } = 32;
        public int ExtremeRejectTicks { get; set; } = 64;
        public bool QuickRejectEnabled { get; set; } = true;
        public int QuickRejectMinProbeTicks { get; set; } = 48;
        public int QuickRejectReclaimTicks { get; set; } = 8;
        public int QuickRejectMaxSeconds { get; set; } = 180;
        public double QuickRejectCancelVolume { get; set; } = 1200.0;
        public int QuickRejectCancelSeconds { get; set; } = 35;
        public int QuickRejectLocalLookbackBars { get; set; } = 3;
        public int QuickRejectDedupeTicks { get; set; } = 16;
        public int Watch1StartHHmm { get; set; } = 1115;
        public int Watch1EndHHmm { get; set; } = 1215;
        public int Watch2StartHHmm { get; set; } = 1215;
        public int Watch2EndHHmm { get; set; } = 1315;

        public TapeLedgerEngine(double tickSize)
        {
            _tickSize = tickSize > 0 ? tickSize : 0.25;
            try { _nyZone = TimeZoneInfo.FindSystemTimeZoneById("Eastern Standard Time"); }
            catch { _nyZone = TimeZoneInfo.Local; }
        }

        public void OnTrade(DateTime timeUtc, double price, double size, int aggressorSign)
        {
            if (!double.IsFinite(price) || price <= 0) return;
            if (!double.IsFinite(size) || size <= 0) return;

            var local = TimeZoneInfo.ConvertTimeFromUtc(timeUtc, _nyZone);
            int hm = local.Hour * 100 + local.Minute;
            if (hm < RthStartHHmm || hm >= RthEndHHmm)
                return;

            if (!_sessionDateNy.HasValue || _sessionDateNy.Value.Date != local.Date)
                ResetSession(local.Date);

            EnsureExtremeWindows(local, timeUtc);

            long tick = PriceToTicks(price);
            _lastTradeTick = tick;
            if (!_rthOpenTick.HasValue)
            {
                _rthOpenTick = tick;
                _rthHighTick = tick;
                _rthLowTick = tick;
                AddMessage(timeUtc, TapeSide.Neutral, $"RTH open {Abbrev(tick)}");
            }
            else
            {
                _rthHighTick = Math.Max(_rthHighTick.Value, tick);
                _rthLowTick = Math.Min(_rthLowTick.Value, tick);
            }

            var rthStart = SessionTimeUtc(local.Date, RthStartHHmm);
            if (timeUtc < rthStart.AddMinutes(Math.Max(1, OrMinutes)))
            {
                _orHighTick = !_orHighTick.HasValue ? tick : Math.Max(_orHighTick.Value, tick);
                _orLowTick = !_orLowTick.HasValue ? tick : Math.Min(_orLowTick.Value, tick);
            }
            if (timeUtc < rthStart.AddMinutes(Math.Max(1, IbMinutes)))
            {
                _ibHighTick = !_ibHighTick.HasValue ? tick : Math.Max(_ibHighTick.Value, tick);
                _ibLowTick = !_ibLowTick.HasValue ? tick : Math.Min(_ibLowTick.Value, tick);
            }

            UpdateBar(timeUtc, tick, size, aggressorSign);
            UpdateQuickRejects(local, timeUtc, tick, size, aggressorSign);
            TrackExtremeTrade(timeUtc, tick);
        }

        public TapeSnapshot GetSnapshot(DateTime nowUtc)
        {
            var bands = BuildShelfBands(nowUtc);
            var quickRejectBands = BuildQuickRejectBands();
            var banners = BuildBanners(nowUtc);
            return new TapeSnapshot
            {
                SessionDateNy = _sessionDateNy,
                LastTradeTick = _lastTradeTick,
                RthOpenTick = _rthOpenTick,
                RthHighTick = _rthHighTick,
                RthLowTick = _rthLowTick,
                OrHighTick = _orHighTick,
                OrLowTick = _orLowTick,
                IbHighTick = _ibHighTick,
                IbLowTick = _ibLowTick,
                Bands = bands,
                QuickRejectBands = quickRejectBands,
                Banners = banners,
                Messages = _messages.OrderByDescending(m => m.TimeUtc).Take(8).Reverse().ToArray(),
            };
        }

        private void ResetSession(DateTime localDate)
        {
            _sessionDateNy = localDate.Date;
            _recentBins.Clear();
            _recentBars.Clear();
            _messages.Clear();
            _extremes.Clear();
            _quickRejects.Clear();
            _quickRejectProbes.Clear();
            _nextQuickRejectId = 1;
            _bar = null;
            _orBreak = null;
            _ibBreak = null;
            _lastTradeTick = null;
            _rthOpenTick = null;
            _rthHighTick = null;
            _rthLowTick = null;
            _orHighTick = null;
            _orLowTick = null;
            _ibHighTick = null;
            _ibLowTick = null;
        }

        private void UpdateBar(DateTime timeUtc, long tick, double size, int aggressorSign)
        {
            DateTime start = BarStartUtc(timeUtc);
            if (_bar == null)
            {
                _bar = new BarState(start, tick);
            }
            else if (_bar.StartUtc != start)
            {
                FinalizeBar(_bar);
                _bar = new BarState(start, tick);
            }

            _bar.HighTick = Math.Max(_bar.HighTick, tick);
            _bar.LowTick = Math.Min(_bar.LowTick, tick);
            _bar.CloseTick = tick;
            _bar.Volume += size;
            _bar.Delta += size * aggressorSign;
            _bar.Trades++;

            long binTick = BinTick(tick);
            if (!_bar.Bins.TryGetValue(binTick, out var bin))
            {
                bin = new BarBin { BinTick = binTick };
                _bar.Bins[binTick] = bin;
            }
            bin.Add(timeUtc, tick, size, aggressorSign);
        }

        private void FinalizeBar(BarState bar)
        {
            _recentBars.Add(new CompletedBar
            {
                StartUtc = bar.StartUtc,
                EndUtc = bar.StartUtc.AddMinutes(Math.Max(1, BarMinutes)),
                OpenTick = bar.OpenTick,
                HighTick = bar.HighTick,
                LowTick = bar.LowTick,
                CloseTick = bar.CloseTick,
                Volume = bar.Volume,
                Delta = bar.Delta,
                Trades = bar.Trades,
            });
            foreach (var b in bar.Bins.Values)
            {
                _recentBins.Add(new BinAggregate
                {
                    TimeUtc = bar.StartUtc,
                    BinTick = b.BinTick,
                    MinTick = b.MinTick,
                    MaxTick = b.MaxTick,
                    Volume = b.Volume,
                    Delta = b.Delta,
                    Trades = b.Trades,
                    Seconds = b.Seconds.Count,
                });
            }
            _recentBars.RemoveAll(b => (bar.StartUtc - b.StartUtc).TotalMinutes > 240);
            _recentBins.RemoveAll(b => (bar.StartUtc - b.TimeUtc).TotalMinutes > 240);

            EvaluateBreaks(bar);
            EvaluateExtremes(bar);
        }

        private void EvaluateBreaks(BarState bar)
        {
            if (!_sessionDateNy.HasValue) return;
            var local = TimeZoneInfo.ConvertTimeFromUtc(bar.StartUtc, _nyZone);
            var rthStart = SessionTimeUtc(local.Date, RthStartHHmm);
            var orEnd = rthStart.AddMinutes(Math.Max(1, OrMinutes));
            var ibEnd = rthStart.AddMinutes(Math.Max(1, IbMinutes));
            var ibBreakEnd = SessionTimeUtc(local.Date, IbBreakEndHHmm);

            if (bar.StartUtc >= orEnd && bar.StartUtc < ibEnd && _orHighTick.HasValue && _orLowTick.HasValue)
                _orBreak = EvaluateBreakState(_orBreak, "OR5", bar, _orHighTick.Value, _orLowTick.Value, ibEnd);

            if (bar.StartUtc >= ibEnd && bar.StartUtc < ibBreakEnd && _ibHighTick.HasValue && _ibLowTick.HasValue)
                _ibBreak = EvaluateBreakState(_ibBreak, "IB", bar, _ibHighTick.Value, _ibLowTick.Value, ibBreakEnd);
        }

        private BreakState EvaluateBreakState(BreakState state, string scope, BarState bar, long highLevel, long lowLevel, DateTime stopUtc)
        {
            if (state == null)
            {
                if (bar.HighTick > highLevel + BreakBufferTicks && bar.CloseTick >= highLevel)
                {
                    state = new BreakState(scope, +1, highLevel, bar.StartUtc);
                    AddMessage(bar.StartUtc, TapeSide.Demand, $"{scope} UP break started {Abbrev(highLevel)}");
                }
                else if (bar.LowTick < lowLevel - BreakBufferTicks && bar.CloseTick <= lowLevel)
                {
                    state = new BreakState(scope, -1, lowLevel, bar.StartUtc);
                    AddMessage(bar.StartUtc, TapeSide.Supply, $"{scope} DN break started {Abbrev(lowLevel)}");
                }
            }

            if (state == null || state.Finalized || bar.StartUtc >= stopUtc)
                return state;

            state.LastUtc = bar.StartUtc;
            state.ExtremeTick = state.Direction > 0
                ? Math.Max(state.ExtremeTick, bar.HighTick)
                : Math.Min(state.ExtremeTick, bar.LowTick);

            foreach (var b in bar.Bins.Values)
            {
                bool outside = state.Direction > 0
                    ? b.MaxTick > state.LevelTick
                    : b.MinTick < state.LevelTick;
                if (!outside) continue;
                if (!state.Bins.TryGetValue(b.BinTick, out var agg))
                {
                    agg = new BreakBin { BinTick = b.BinTick, MinTick = b.MinTick, MaxTick = b.MaxTick };
                    state.Bins[b.BinTick] = agg;
                }
                agg.MinTick = Math.Min(agg.MinTick, b.MinTick);
                agg.MaxTick = Math.Max(agg.MaxTick, b.MaxTick);
                agg.Volume += b.Volume;
                agg.Delta += b.Delta;
                agg.Trades += b.Trades;
                agg.Seconds += b.Seconds.Count;
            }

            bool reclaimed = state.Direction > 0
                ? bar.CloseTick <= state.LevelTick - ReclaimBufferTicks
                : bar.CloseTick >= state.LevelTick + ReclaimBufferTicks;
            if (reclaimed)
            {
                state.Finalized = true;
                state.Label = "failed";
                AddMessage(bar.StartUtc, TapeSide.Warning, $"{scope} {DirText(state.Direction)} failed/reclaimed");
            }
            else
            {
                string label = BreakLabel(state);
                if (label != state.Label && label != "watch")
                    AddMessage(bar.StartUtc, state.Direction > 0 ? TapeSide.Demand : TapeSide.Supply, $"{scope} {DirText(state.Direction)} {label}");
                state.Label = label;
            }

            return state;
        }

        private string BreakLabel(BreakState state)
        {
            double vol = state.Bins.Values.Sum(b => b.Volume);
            int acceptedBins = state.Bins.Values.Count(b => b.Volume >= MinShelfVolume && b.Seconds >= MinShelfSeconds);
            long excursion = Math.Abs(state.ExtremeTick - state.LevelTick);
            if (acceptedBins >= 3 && vol >= 4500 && excursion >= BreakBufferTicks * 2)
                return "accepted";
            if (acceptedBins >= 2 || vol >= 2500)
                return "building";
            if (excursion >= BreakBufferTicks && vol > 0)
                return "thin/no-build";
            return "watch";
        }

        private void EnsureExtremeWindows(DateTime local, DateTime utc)
        {
            if (!_sessionDateNy.HasValue || !_rthHighTick.HasValue || !_rthLowTick.HasValue)
                return;
            int hm = local.Hour * 100 + local.Minute;
            EnsureExtremeWindow("LM", Watch1StartHHmm, Watch1EndHHmm, hm, utc);
            EnsureExtremeWindow("LUNCH", Watch2StartHHmm, Watch2EndHHmm, hm, utc);
        }

        private void EnsureExtremeWindow(string name, int startHHmm, int endHHmm, int hm, DateTime utc)
        {
            if (hm < startHHmm || hm >= endHHmm) return;
            if (_extremes.Any(e => e.WindowName == name)) return;
            _extremes.Add(new ExtremeCandidate
            {
                WindowName = name,
                StartUtc = utc,
                PriorHighTick = _rthHighTick.Value,
                PriorLowTick = _rthLowTick.Value,
            });
        }

        private void TrackExtremeTrade(DateTime utc, long tick)
        {
            foreach (var e in _extremes)
            {
                if (!e.HighSeen && tick >= e.PriorHighTick - ExtremeTestTicks)
                {
                    e.HighSeen = true;
                    e.HighKind = tick > e.PriorHighTick ? "new high" : "high test";
                    e.HighTick = tick;
                    e.HighUtc = utc;
                    AddMessage(utc, TapeSide.Warning, $"{e.WindowName} {e.HighKind} {Abbrev(tick)}");
                }
                else if (e.HighSeen && tick > e.HighTick)
                {
                    e.HighKind = tick > e.PriorHighTick ? "new high" : e.HighKind;
                    e.HighTick = tick;
                    e.HighUtc = utc;
                }

                if (!e.LowSeen && tick <= e.PriorLowTick + ExtremeTestTicks)
                {
                    e.LowSeen = true;
                    e.LowKind = tick < e.PriorLowTick ? "new low" : "low test";
                    e.LowTick = tick;
                    e.LowUtc = utc;
                    AddMessage(utc, TapeSide.Warning, $"{e.WindowName} {e.LowKind} {Abbrev(tick)}");
                }
                else if (e.LowSeen && tick < e.LowTick)
                {
                    e.LowKind = tick < e.PriorLowTick ? "new low" : e.LowKind;
                    e.LowTick = tick;
                    e.LowUtc = utc;
                }
            }
        }

        private void EvaluateExtremes(BarState bar)
        {
            foreach (var e in _extremes)
            {
                if (e.HighSeen)
                    EvaluateExtremeSide(e, +1, e.HighTick, e.HighUtc, bar);
                if (e.LowSeen)
                    EvaluateExtremeSide(e, -1, e.LowTick, e.LowUtc, bar);
            }
        }

        private void EvaluateExtremeSide(ExtremeCandidate e, int direction, long extremeTick, DateTime extremeUtc, BarState bar)
        {
            if (bar.StartUtc <= extremeUtc) return;
            long retrace = direction > 0
                ? Math.Max(0, extremeTick - bar.LowTick)
                : Math.Max(0, bar.HighTick - extremeTick);
            if (retrace < ExtremeRejectTicks) return;

            if (direction > 0 && !e.HighRejected)
            {
                e.HighRejected = true;
                AddMessage(bar.StartUtc, TapeSide.Warning, $"{e.WindowName} high reject -> repair shelves");
            }
            else if (direction < 0 && !e.LowRejected)
            {
                e.LowRejected = true;
                AddMessage(bar.StartUtc, TapeSide.Warning, $"{e.WindowName} low reject -> repair shelves");
            }
        }

        private void UpdateQuickRejects(DateTime local, DateTime utc, long tick, double size, int aggressorSign)
        {
            if (!QuickRejectEnabled)
            {
                _quickRejects.Clear();
                _quickRejectProbes.Clear();
                return;
            }

            UpdateQuickRejectCancels(utc, tick, size);

            var refs = BuildQuickRejectReferences(local, utc);
            var activeKeys = new HashSet<string>();
            foreach (var r in refs)
            {
                activeKeys.Add(r.Key);
                if (!_quickRejectProbes.TryGetValue(r.Key, out var probe))
                {
                    probe = new QuickRejectProbe
                    {
                        Key = r.Key,
                        Source = r.Source,
                        RefName = r.RefName,
                        Direction = r.Direction,
                        RefTick = r.RefTick,
                    };
                    _quickRejectProbes[r.Key] = probe;
                }
                else
                {
                    probe.Source = r.Source;
                    probe.RefName = r.RefName;
                    probe.Direction = r.Direction;
                    probe.RefTick = r.RefTick;
                }

                UpdateQuickRejectProbe(probe, utc, tick, size, aggressorSign);
            }

            var stale = _quickRejectProbes.Keys
                .Where(k => k.StartsWith("LOCAL:", StringComparison.Ordinal) && !activeKeys.Contains(k))
                .ToList();
            foreach (string key in stale)
                _quickRejectProbes.Remove(key);
        }

        private List<QuickRejectReference> BuildQuickRejectReferences(DateTime local, DateTime utc)
        {
            var refs = new List<QuickRejectReference>();
            if (!_sessionDateNy.HasValue) return refs;

            var rthStart = SessionTimeUtc(local.Date, RthStartHHmm);
            var orEnd = rthStart.AddMinutes(Math.Max(1, OrMinutes));
            var ibEnd = rthStart.AddMinutes(Math.Max(1, IbMinutes));

            if (utc >= orEnd && _rthOpenTick.HasValue)
            {
                refs.Add(new QuickRejectReference("REF:OPEN:L", "REF", "OPEN", -1, _rthOpenTick.Value));
                refs.Add(new QuickRejectReference("REF:OPEN:H", "REF", "OPEN", +1, _rthOpenTick.Value));
            }
            if (utc >= orEnd && _orLowTick.HasValue && _orHighTick.HasValue)
            {
                refs.Add(new QuickRejectReference("REF:OR5L", "REF", "OR5L", -1, _orLowTick.Value));
                refs.Add(new QuickRejectReference("REF:OR5H", "REF", "OR5H", +1, _orHighTick.Value));
            }
            if (utc >= ibEnd && _ibLowTick.HasValue && _ibHighTick.HasValue)
            {
                refs.Add(new QuickRejectReference("REF:IBL", "REF", "IBL", -1, _ibLowTick.Value));
                refs.Add(new QuickRejectReference("REF:IBH", "REF", "IBH", +1, _ibHighTick.Value));
            }

            int lookbackCount = Math.Max(1, QuickRejectLocalLookbackBars);
            var lookback = _recentBars
                .OrderByDescending(b => b.StartUtc)
                .Take(lookbackCount)
                .ToList();
            if (lookback.Count > 0)
            {
                long low = lookback.Min(b => b.LowTick);
                long high = lookback.Max(b => b.HighTick);
                int dedupeTicks = Math.Max(1, QuickRejectDedupeTicks);
                if (!refs.Any(r => r.Direction < 0 && Math.Abs(r.RefTick - low) <= dedupeTicks))
                    refs.Add(new QuickRejectReference($"LOCAL:L:{low}", "LOCAL", "LOCL", -1, low));
                if (!refs.Any(r => r.Direction > 0 && Math.Abs(r.RefTick - high) <= dedupeTicks))
                    refs.Add(new QuickRejectReference($"LOCAL:H:{high}", "LOCAL", "LOCH", +1, high));
            }

            return refs;
        }

        private void UpdateQuickRejectProbe(QuickRejectProbe probe, DateTime utc, long tick, double size, int aggressorSign)
        {
            bool outside = IsOutside(probe.Direction, tick, probe.RefTick);
            if (outside)
            {
                if (!probe.HasProbe)
                    probe.Start(utc, tick);
                probe.NoteOutside(utc, tick, size, aggressorSign);
                if (probe.ElapsedSeconds(utc) > QuickRejectMaxSeconds || probe.Seconds.Count > QuickRejectMaxSeconds)
                    probe.Expired = true;
                return;
            }

            if (!probe.HasProbe) return;

            if (IsReclaimed(probe.Direction, tick, probe.RefTick, Math.Max(1, QuickRejectReclaimTicks)))
            {
                TryBuildQuickReject(probe, utc);
                probe.Reset();
                return;
            }

            if (probe.ElapsedSeconds(utc) > QuickRejectMaxSeconds)
                probe.Expired = true;
        }

        private void TryBuildQuickReject(QuickRejectProbe probe, DateTime builtUtc)
        {
            long probeTicks = Math.Abs(probe.ExtremeTick - probe.RefTick);
            if (probe.Expired) return;
            if (probeTicks < Math.Max(1, QuickRejectMinProbeTicks)) return;
            if (probe.Seconds.Count > Math.Max(1, QuickRejectMaxSeconds)) return;
            if (HasDuplicateQuickReject(probe.Direction, probe.RefTick)) return;

            long minTick = Math.Min(probe.RefTick, probe.ExtremeTick);
            long maxTick = Math.Max(probe.RefTick, probe.ExtremeTick);
            _quickRejects.Add(new QuickRejectState
            {
                Id = _nextQuickRejectId++,
                Source = probe.Source,
                RefName = probe.RefName,
                Direction = probe.Direction,
                RefTick = probe.RefTick,
                ExtremeTick = probe.ExtremeTick,
                MinTick = minTick,
                MaxTick = maxTick,
                StartUtc = probe.FirstOutsideUtc,
                BuiltUtc = builtUtc,
                OutsideVolume = probe.OutsideVolume,
                OutsideDelta = probe.OutsideDelta,
                OutsideSeconds = probe.Seconds.Count,
            });

            if (_quickRejects.Count > 16)
                _quickRejects.RemoveRange(0, _quickRejects.Count - 16);
        }

        private bool HasDuplicateQuickReject(int direction, long refTick)
        {
            int dedupeTicks = Math.Max(1, QuickRejectDedupeTicks);
            return _quickRejects.Any(q => q.Direction == direction && Math.Abs(q.RefTick - refTick) <= dedupeTicks);
        }

        private void UpdateQuickRejectCancels(DateTime utc, long tick, double size)
        {
            if (_quickRejects.Count == 0) return;
            long second = utc.Ticks / TimeSpan.TicksPerSecond;
            for (int i = _quickRejects.Count - 1; i >= 0; i--)
            {
                var q = _quickRejects[i];
                if (utc <= q.BuiltUtc) continue;
                if (!IsOutside(q.Direction, tick, q.RefTick)) continue;

                q.CancelVolume += size;
                q.CancelSeconds.Add(second);
                if (q.CancelVolume >= QuickRejectCancelVolume && q.CancelSeconds.Count >= QuickRejectCancelSeconds)
                    _quickRejects.RemoveAt(i);
            }
        }

        private QuickRejectBandView[] BuildQuickRejectBands()
        {
            if (!QuickRejectEnabled || _quickRejects.Count == 0)
                return Array.Empty<QuickRejectBandView>();

            return _quickRejects
                .OrderBy(q => q.MinTick)
                .Select(q => new QuickRejectBandView
                {
                    MinTick = q.MinTick,
                    MaxTick = q.MaxTick,
                    RefTick = q.RefTick,
                    ExtremeTick = q.ExtremeTick,
                    StartUtc = q.StartUtc,
                    BuiltUtc = q.BuiltUtc,
                    Direction = q.Direction,
                    Text = $"QR {q.RefName} {Abbrev(q.RefTick)}",
                })
                .ToArray();
        }

        private static bool IsOutside(int direction, long tick, long refTick)
        {
            return direction > 0 ? tick > refTick : tick < refTick;
        }

        private static bool IsReclaimed(int direction, long tick, long refTick, int reclaimTicks)
        {
            return direction > 0
                ? tick <= refTick - reclaimTicks
                : tick >= refTick + reclaimTicks;
        }

        private TapeBandView[] BuildShelfBands(DateTime nowUtc)
        {
            if (!_lastTradeTick.HasValue) return Array.Empty<TapeBandView>();
            DateTime cutoff = nowUtc.AddMinutes(-Math.Max(5, ShelfLookbackMinutes));
            var rows = _recentBins
                .Where(b => b.TimeUtc >= cutoff)
                .GroupBy(b => b.BinTick)
                .Select(g => new ProfileBin
                {
                    BinTick = g.Key,
                    MinTick = g.Min(x => x.MinTick),
                    MaxTick = g.Max(x => x.MaxTick),
                    Volume = g.Sum(x => x.Volume),
                    Delta = g.Sum(x => x.Delta),
                    Trades = g.Sum(x => x.Trades),
                    Seconds = g.Sum(x => x.Seconds),
                    FirstUtc = g.Min(x => x.TimeUtc),
                    LastUtc = g.Max(x => x.TimeUtc),
                })
                .OrderBy(b => b.BinTick)
                .ToList();
            if (rows.Count == 0) return Array.Empty<TapeBandView>();

            double maxVol = rows.Max(r => r.Volume);
            double medVol = Median(rows.Select(r => r.Volume).ToList());
            double medSec = Median(rows.Select(r => (double)r.Seconds).ToList());
            double volCut = Math.Max(MinShelfVolume, Math.Max(medVol * 1.35, maxVol * 0.28));
            double secCut = Math.Max(MinShelfSeconds, medSec * 1.10);

            var zones = new List<TapeBandView>();
            var current = new List<ProfileBin>();
            foreach (var row in rows)
            {
                bool qualifies = row.Volume >= volCut
                              || (row.Volume >= MinShelfVolume && row.Seconds >= secCut)
                              || (row.Volume >= medVol * 0.75 && row.Seconds >= MinShelfSeconds);
                bool adjacent = current.Count > 0 && row.BinTick - current[current.Count - 1].BinTick <= ShelfBinTicks;
                if (qualifies && (current.Count == 0 || adjacent))
                {
                    current.Add(row);
                }
                else
                {
                    AddZone(zones, current, maxVol, nowUtc);
                    current = qualifies ? new List<ProfileBin> { row } : new List<ProfileBin>();
                }
            }
            AddZone(zones, current, maxVol, nowUtc);

            long last = _lastTradeTick.Value;
            foreach (var z in zones)
            {
                if (z.MaxTick < last - ShelfBinTicks / 2)
                    z.Side = TapeSide.Demand;
                else if (z.MinTick > last + ShelfBinTicks / 2)
                    z.Side = TapeSide.Supply;
                else
                    z.Side = TapeSide.Accepted;

                bool newish = (nowUtc - z.StartUtc).TotalMinutes <= 12 || (nowUtc - z.LastUtc).TotalMinutes <= 6;
                z.State = newish ? TapeBandState.New : TapeBandState.Active;
                z.Text = $"{Abbrev(z.MinTick)}-{Abbrev(z.MaxTick)} vol {z.Volume:0}";
            }

            return zones
                .OrderByDescending(z => z.Score)
                .Take(Math.Max(1, ShelfCount))
                .OrderBy(z => z.CenterTick)
                .ToArray();
        }

        private void AddZone(List<TapeBandView> zones, List<ProfileBin> bins, double maxVol, DateTime nowUtc)
        {
            if (bins == null || bins.Count == 0) return;
            double vol = bins.Sum(b => b.Volume);
            if (bins.Count < 2 && vol < MinShelfVolume * 2) return;
            long minTick = bins.Min(b => b.MinTick);
            long maxTick = bins.Max(b => b.MaxTick);
            double spanTicks = Math.Max(1.0, maxTick - minTick + 1.0);
            double density = vol / spanTicks;
            double score = density * Math.Log(1.0 + vol / Math.Max(1.0, maxVol));
            zones.Add(new TapeBandView
            {
                MinTick = minTick,
                MaxTick = maxTick,
                CenterTick = (minTick + maxTick) / 2,
                StartUtc = bins.Min(b => b.FirstUtc),
                LastUtc = bins.Max(b => b.LastUtc),
                Volume = vol,
                Delta = bins.Sum(b => b.Delta),
                Seconds = bins.Sum(b => b.Seconds),
                Score = score,
                Side = TapeSide.Accepted,
                State = TapeBandState.Active,
            });
        }

        private TapeBannerView[] BuildBanners(DateTime nowUtc)
        {
            var banners = new List<TapeBannerView>();
            AddBreakBanner(banners, _orBreak);
            AddBreakBanner(banners, _ibBreak);

            foreach (var e in _extremes.OrderByDescending(x => x.StartUtc).Take(2).Reverse())
            {
                if (e.HighSeen)
                {
                    string tag = e.HighRejected ? "reject" : "testing";
                    banners.Add(new TapeBannerView
                    {
                        Side = e.HighRejected ? TapeSide.Warning : TapeSide.Supply,
                        TimeUtc = e.HighUtc,
                        Text = $"{e.WindowName} HIGH {tag} {Abbrev(e.HighTick)}",
                        Detail = "watch repair shelf below",
                    });
                }
                if (e.LowSeen)
                {
                    string tag = e.LowRejected ? "reject" : "testing";
                    banners.Add(new TapeBannerView
                    {
                        Side = e.LowRejected ? TapeSide.Warning : TapeSide.Demand,
                        TimeUtc = e.LowUtc,
                        Text = $"{e.WindowName} LOW {tag} {Abbrev(e.LowTick)}",
                        Detail = "watch repair shelf above",
                    });
                }
            }

            return banners.OrderByDescending(b => b.TimeUtc).Take(4).Reverse().ToArray();
        }

        private void AddBreakBanner(List<TapeBannerView> banners, BreakState state)
        {
            if (state == null) return;
            double vol = state.Bins.Values.Sum(b => b.Volume);
            int bins = state.Bins.Values.Count(b => b.Volume >= MinShelfVolume && b.Seconds >= MinShelfSeconds);
            string label = string.IsNullOrEmpty(state.Label) ? BreakLabel(state) : state.Label;
            TapeSide side = label.Contains("fail") ? TapeSide.Warning : (state.Direction > 0 ? TapeSide.Demand : TapeSide.Supply);
            banners.Add(new TapeBannerView
            {
                Side = side,
                TimeUtc = state.StartUtc,
                Text = $"{state.Scope} {DirText(state.Direction)} {label}",
                Detail = $"moved {TicksToPoints(Math.Abs(state.ExtremeTick - state.LevelTick)):0.0} / vol {vol:0} / bins {bins}",
            });
        }

        private DateTime BarStartUtc(DateTime utc)
        {
            var local = TimeZoneInfo.ConvertTimeFromUtc(utc, _nyZone);
            int m = (local.Minute / Math.Max(1, BarMinutes)) * Math.Max(1, BarMinutes);
            var localStart = new DateTime(local.Year, local.Month, local.Day, local.Hour, m, 0);
            return TimeZoneInfo.ConvertTimeToUtc(localStart, _nyZone);
        }

        private DateTime SessionTimeUtc(DateTime localDate, int hhmm)
        {
            int h = Math.Max(0, Math.Min(23, hhmm / 100));
            int m = Math.Max(0, Math.Min(59, hhmm % 100));
            var local = new DateTime(localDate.Year, localDate.Month, localDate.Day, h, m, 0);
            return TimeZoneInfo.ConvertTimeToUtc(local, _nyZone);
        }

        private long PriceToTicks(double price) => (long)Math.Round(price / _tickSize);

        private long BinTick(long tick)
        {
            int width = Math.Max(1, ShelfBinTicks);
            return (long)Math.Floor((double)tick / width) * width;
        }

        private string Abbrev(long tick)
        {
            double price = tick * _tickSize;
            int whole = (int)Math.Floor(price);
            int last = ((whole % 1000) + 1000) % 1000;
            double frac = price - whole;
            if (Math.Abs(frac) < 0.0001)
                return last.ToString("000");
            return last.ToString("000") + frac.ToString(".00").TrimEnd('0');
        }

        private double TicksToPoints(long ticks) => ticks * _tickSize;

        private static string DirText(int direction) => direction > 0 ? "UP" : "DN";

        private void AddMessage(DateTime utc, TapeSide side, string text)
        {
            if (_messages.Count > 0 && _messages[_messages.Count - 1].Text == text)
                return;
            _messages.Add(new TapeMessageView { TimeUtc = utc, Side = side, Text = text });
            if (_messages.Count > 40)
                _messages.RemoveRange(0, _messages.Count - 40);
        }

        private static double Median(List<double> values)
        {
            if (values == null || values.Count == 0) return 0.0;
            values.Sort();
            int mid = values.Count / 2;
            if (values.Count % 2 == 1) return values[mid];
            return (values[mid - 1] + values[mid]) / 2.0;
        }

        private sealed class BarState
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

        private sealed class BarBin
        {
            public long BinTick;
            public long MinTick = long.MaxValue;
            public long MaxTick = long.MinValue;
            public double Volume;
            public double Delta;
            public int Trades;
            public readonly HashSet<long> Seconds = new();

            public void Add(DateTime timeUtc, long tick, double size, int sign)
            {
                MinTick = Math.Min(MinTick, tick);
                MaxTick = Math.Max(MaxTick, tick);
                Volume += size;
                Delta += size * sign;
                Trades++;
                Seconds.Add(timeUtc.Ticks / TimeSpan.TicksPerSecond);
            }
        }

        private class BinAggregate
        {
            public DateTime TimeUtc;
            public long BinTick;
            public long MinTick;
            public long MaxTick;
            public double Volume;
            public double Delta;
            public int Trades;
            public int Seconds;
        }

        private sealed class ProfileBin : BinAggregate
        {
            public DateTime FirstUtc;
            public DateTime LastUtc;
        }

        private sealed class CompletedBar
        {
            public DateTime StartUtc;
            public DateTime EndUtc;
            public long OpenTick;
            public long HighTick;
            public long LowTick;
            public long CloseTick;
            public double Volume;
            public double Delta;
            public int Trades;
        }

        private sealed class QuickRejectReference
        {
            public readonly string Key;
            public readonly string Source;
            public readonly string RefName;
            public readonly int Direction;
            public readonly long RefTick;

            public QuickRejectReference(string key, string source, string refName, int direction, long refTick)
            {
                Key = key;
                Source = source;
                RefName = refName;
                Direction = direction;
                RefTick = refTick;
            }
        }

        private sealed class QuickRejectProbe
        {
            public string Key = "";
            public string Source = "";
            public string RefName = "";
            public int Direction;
            public long RefTick;
            public bool HasProbe;
            public bool Expired;
            public DateTime FirstOutsideUtc;
            public DateTime LastOutsideUtc;
            public long ExtremeTick;
            public double OutsideVolume;
            public double OutsideDelta;
            public readonly HashSet<long> Seconds = new();

            public void Start(DateTime utc, long tick)
            {
                HasProbe = true;
                Expired = false;
                FirstOutsideUtc = utc;
                LastOutsideUtc = utc;
                ExtremeTick = tick;
                OutsideVolume = 0.0;
                OutsideDelta = 0.0;
                Seconds.Clear();
            }

            public void NoteOutside(DateTime utc, long tick, double size, int sign)
            {
                LastOutsideUtc = utc;
                ExtremeTick = Direction > 0
                    ? Math.Max(ExtremeTick, tick)
                    : Math.Min(ExtremeTick, tick);
                OutsideVolume += size;
                OutsideDelta += size * sign;
                Seconds.Add(utc.Ticks / TimeSpan.TicksPerSecond);
            }

            public double ElapsedSeconds(DateTime utc)
            {
                if (!HasProbe) return 0.0;
                return Math.Max(0.0, (utc - FirstOutsideUtc).TotalSeconds);
            }

            public void Reset()
            {
                HasProbe = false;
                Expired = false;
                OutsideVolume = 0.0;
                OutsideDelta = 0.0;
                Seconds.Clear();
            }
        }

        private sealed class QuickRejectState
        {
            public int Id;
            public string Source = "";
            public string RefName = "";
            public int Direction;
            public long RefTick;
            public long ExtremeTick;
            public long MinTick;
            public long MaxTick;
            public DateTime StartUtc;
            public DateTime BuiltUtc;
            public double OutsideVolume;
            public double OutsideDelta;
            public int OutsideSeconds;
            public double CancelVolume;
            public readonly HashSet<long> CancelSeconds = new();
        }

        private sealed class BreakState
        {
            public readonly string Scope;
            public readonly int Direction;
            public readonly long LevelTick;
            public readonly DateTime StartUtc;
            public DateTime LastUtc;
            public long ExtremeTick;
            public bool Finalized;
            public string Label = "watch";
            public readonly Dictionary<long, BreakBin> Bins = new();

            public BreakState(string scope, int direction, long levelTick, DateTime startUtc)
            {
                Scope = scope;
                Direction = direction;
                LevelTick = levelTick;
                StartUtc = startUtc;
                LastUtc = startUtc;
                ExtremeTick = levelTick;
            }
        }

        private sealed class BreakBin
        {
            public long BinTick;
            public long MinTick;
            public long MaxTick;
            public double Volume;
            public double Delta;
            public int Trades;
            public int Seconds;
        }

        private sealed class ExtremeCandidate
        {
            public string WindowName = "";
            public DateTime StartUtc;
            public long PriorHighTick;
            public long PriorLowTick;
            public bool HighSeen;
            public bool LowSeen;
            public bool HighRejected;
            public bool LowRejected;
            public string HighKind = "";
            public string LowKind = "";
            public long HighTick;
            public long LowTick;
            public DateTime HighUtc;
            public DateTime LowUtc;
        }
    }
}
