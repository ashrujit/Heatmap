using System;
using System.Collections.Generic;
using TradingPlatform.BusinessLayer;

namespace SinglePrints
{
    // RTH single-print TPO indicator. Shows price zones the market traded
    // through quickly (one bracket only) and hasn't returned to fill. Zones
    // extend from session-end to the chart right edge until later trade fully
    // crosses them or they age out of the retention window.
    //
    // No labels, no strength coding, no alerts — same posture as the rest of
    // the suite. A single print is just a structural artifact; the trader
    // supplies meaning.
    public class SinglePrints : Indicator
    {
        private const string IndicatorVersion = "0.1.0";

        // ── Detection (sortIndex 900-905) ───────────────────────────────────
        [InputParameter("Bracket Size (minutes)", sortIndex: 900,
            minimum: 5, maximum: 60, increment: 5, decimalPlaces: 0)]
        public int BracketSizeMin = 30;

        [InputParameter("Minimum Zone Size (ticks)", sortIndex: 901,
            minimum: 1, maximum: 20, increment: 1, decimalPlaces: 0)]
        public int MinZoneTicks = 2;

        [InputParameter("Sessions to Keep Visible", sortIndex: 902,
            minimum: 1, maximum: 20, increment: 1, decimalPlaces: 0)]
        public int RetentionSessions = 3;

        // Default OFF: in classic TPO, single-print tails sit AT session high/low
        // by construction (the unretraced edge of an extension). Excluding them
        // hides the most actionable single-print structure. Kept as a toggle for
        // users who want only "interior" singles.
        [InputParameter("Exclude Session Extremes", sortIndex: 903)]
        public bool ExcludeExtremes = false;

        // ── Render (sortIndex 910-915) ──────────────────────────────────────
        [InputParameter("Show Boundary Lines", sortIndex: 910)]
        public bool ShowBoundaries = true;

        [InputParameter("Show Box Fill", sortIndex: 911)]
        public bool ShowFill = false;

        [InputParameter("Boundary Line Alpha (newest)", sortIndex: 912,
            minimum: 40, maximum: 255, increment: 5, decimalPlaces: 0)]
        public int BoundaryAlpha = 180;

        [InputParameter("Box Fill Alpha (newest)", sortIndex: 913,
            minimum: 5, maximum: 120, increment: 5, decimalPlaces: 0)]
        public int FillAlpha = 40;

        // ── Internal state ──────────────────────────────────────────────────
        private Painter _painter;
        private TimeZoneInfo _ny;
        private List<Zone> _zones = new();
        // Stable key identifying which TPO bracket of which session we last
        // rebuilt for. Advances at each NY bracket boundary (09:30, 10:00,
        // ...). Sentinel value triggers first rebuild after OnInit.
        private long _lastRebuildBracketKey = long.MinValue;
        private int _lastSeenCount = 0;

        public SinglePrints() : base()
        {
            this.Name = "Single Prints (RTH TPO)";
            this.SeparateWindow = false;
        }

        public override IList<SettingItem> Settings
        {
            get
            {
                var settings = base.Settings;
                if (settings != null)
                {
                    var grpDetect = new SettingItemSeparatorGroup("Detection", 900);
                    var grpRender = new SettingItemSeparatorGroup("Render", 910);
                    foreach (var item in settings)
                    {
                        if (item == null) continue;
                        if (item.SortIndex >= 900 && item.SortIndex < 910)
                            item.SeparatorGroup = grpDetect;
                        else if (item.SortIndex >= 910 && item.SortIndex < 920)
                            item.SeparatorGroup = grpRender;
                    }
                }
                return settings;
            }
            set => base.Settings = value;
        }

        protected override void OnInit()
        {
            try
            {
                try { _ny = TimeZoneInfo.FindSystemTimeZoneById("Eastern Standard Time"); }
                catch { _ny = TimeZoneInfo.Utc; }

                _painter = new Painter
                {
                    ShowBoundaries = ShowBoundaries,
                    ShowFill = ShowFill,
                    BoundaryAlphaMax = BoundaryAlpha,
                    FillAlphaMax = FillAlpha,
                    RetentionSessions = RetentionSessions,
                };

                RebuildZones();
                _lastRebuildBracketKey = ComputeBracketKey(DateTime.UtcNow);
                _lastSeenCount = this.Count;
            }
            catch (Exception ex)
            {
                Core.Instance.Loggers.Log(
                    $"[{nameof(SinglePrints)}] OnInit failed: {ex.Message}",
                    LoggingLevel.Error);
            }
        }

        protected override void OnUpdate(UpdateArgs args)
        {
            // Rebuild on TPO bracket boundary crossings (NY 10:00, 10:30, ...),
            // not on a free-running wall-clock interval. The previous gate
            // (BracketSizeMin minutes since last rebuild) drifted from TPO
            // boundaries depending on indicator load time — a 10:10 load
            // rebuilt at 10:40, missing the 10:30 boundary by 10 minutes.
            // Bar-count delta still triggers rebuilds for historical-data
            // loads (e.g., chart symbol change, deep history fill).
            long currentBracketKey = ComputeBracketKey(DateTime.UtcNow);
            bool dueByBoundary = currentBracketKey != _lastRebuildBracketKey;
            bool dueByCount = Math.Abs(this.Count - _lastSeenCount) >= 30;
            if (dueByBoundary || dueByCount)
            {
                _lastRebuildBracketKey = currentBracketKey;
                _lastSeenCount = this.Count;
                RebuildZones();
            }
        }

        // Stable key that increments at each TPO bracket boundary anchored on
        // each NY session's 09:30 open. Outside RTH (incl. weekends), returns
        // a per-day stable key so we don't trigger rapid rebuilds when the
        // market is closed; the bar-count delta gate handles historical loads.
        private long ComputeBracketKey(DateTime nowUtc)
        {
            var nowNy = TimeZoneInfo.ConvertTimeFromUtc(nowUtc, _ny);
            long dayKey = nowNy.Date.Ticks / TimeSpan.TicksPerDay;
            var t = nowNy.TimeOfDay;
            if (nowNy.DayOfWeek == DayOfWeek.Saturday || nowNy.DayOfWeek == DayOfWeek.Sunday
                || t < TimeSpan.FromHours(9.5) || t >= TimeSpan.FromHours(16))
            {
                return dayKey * 1000; // pre/post-RTH: one stable key per day
            }
            int minutesSinceOpen = (int)(t - TimeSpan.FromHours(9.5)).TotalMinutes;
            int bracketIdx = minutesSinceOpen / Math.Max(1, BracketSizeMin);
            return dayKey * 1000 + bracketIdx;
        }

        public override void OnPaintChart(PaintChartEventArgs args)
        {
            try
            {
                if (_painter == null) return;
                _painter.ShowBoundaries = ShowBoundaries;
                _painter.ShowFill = ShowFill;
                _painter.BoundaryAlphaMax = BoundaryAlpha;
                _painter.FillAlphaMax = FillAlpha;
                _painter.RetentionSessions = RetentionSessions;
                _painter.Paint(args, this.CurrentChart, _zones, DateTime.UtcNow);
            }
            catch (Exception ex)
            {
                try { Core.Instance.Loggers.Log(
                    $"[{nameof(SinglePrints)}] paint failed: {ex.Message}",
                    LoggingLevel.Error); }
                catch { }
            }
        }

        // Walks HistoricalData oldest → newest, groups bars into RTH sessions
        // by NY-local date, computes zones per session, then drops zones that
        // later sessions have spanned (price went above the top AND below the
        // bottom on a future day = "filled", unfinished business closed).
        private void RebuildZones()
        {
            var allZones = new List<Zone>();
            if (this.Symbol == null || this.HistoricalData == null) return;
            double tickSize = this.Symbol.TickSize > 0 ? this.Symbol.TickSize : 0.25;
            int n = this.Count;
            if (n < 2) { _zones = allZones; return; }

            // Group bars by NY-local session date. RTH window per day:
            // 09:30 → 16:00 NY local. Bars outside (overnight/Globex) ignored.
            var sessionBars = new SortedDictionary<DateTime, List<SessionBuilder.Bar>>();
            for (int offset = n - 1; offset >= 0; offset--)
            {
                DateTime tUtc;
                double hi, lo;
                try
                {
                    tUtc = this.Time(offset);
                    hi = this.High(offset);
                    lo = this.Low(offset);
                }
                catch { continue; }
                if (double.IsNaN(hi) || double.IsNaN(lo)) continue;

                var nyTime = TimeZoneInfo.ConvertTimeFromUtc(tUtc, _ny);
                if (nyTime.DayOfWeek == DayOfWeek.Saturday || nyTime.DayOfWeek == DayOfWeek.Sunday) continue;
                var t = nyTime.TimeOfDay;
                if (t < TimeSpan.FromHours(9.5) || t >= TimeSpan.FromHours(16)) continue;

                var sessionDate = nyTime.Date;
                if (!sessionBars.TryGetValue(sessionDate, out var list))
                {
                    list = new List<SessionBuilder.Bar>();
                    sessionBars[sessionDate] = list;
                }
                list.Add(new SessionBuilder.Bar(tUtc, hi, lo));
            }

            // Newest session is "active" if its date == today's NY date AND
            // current NY time is still within the RTH window. Active session's
            // current-bracket bars are excluded — TPO output for an in-progress
            // bracket would be provisional.
            DateTime nowNy = TimeZoneInfo.ConvertTimeFromUtc(DateTime.UtcNow, _ny);
            DateTime activeDate = (nowNy.DayOfWeek != DayOfWeek.Saturday
                && nowNy.DayOfWeek != DayOfWeek.Sunday
                && nowNy.TimeOfDay >= TimeSpan.FromHours(9.5)
                && nowNy.TimeOfDay < TimeSpan.FromHours(16))
                ? nowNy.Date : DateTime.MinValue;

            // Track session ranges to compute fills. (sessionDate, low, high).
            var sessionRanges = new List<(DateTime date, double low, double high)>();

            foreach (var kv in sessionBars)
            {
                DateTime sessionDateNy = kv.Key;
                var bars = kv.Value;
                if (bars.Count == 0) continue;

                var sessionStartNyLocal = new DateTime(sessionDateNy.Year, sessionDateNy.Month,
                    sessionDateNy.Day, 9, 30, 0, DateTimeKind.Unspecified);
                var sessionEndNyLocal = new DateTime(sessionDateNy.Year, sessionDateNy.Month,
                    sessionDateNy.Day, 16, 0, 0, DateTimeKind.Unspecified);
                DateTime sessionStartUtc = TimeZoneInfo.ConvertTimeToUtc(sessionStartNyLocal, _ny);
                DateTime sessionEndUtc = TimeZoneInfo.ConvertTimeToUtc(sessionEndNyLocal, _ny);

                IEnumerable<SessionBuilder.Bar> barsForCompute = bars;

                // Active session: only feed bars from CLOSED brackets. The
                // current bracket isn't single-print yet by definition — it's
                // the only bracket that has touched its prices so far. Each
                // resulting zone's FormedAtUtc points to the END of its own
                // latest tick-bracket (computed inside SessionBuilder), so a
                // zone confirmed in bracket A stays anchored to A's close even
                // after B / C / etc. have completed. This matters so the
                // historical chart still shows the line drawn through the
                // bracket where price interacted with the level.
                if (sessionDateNy == activeDate)
                {
                    int currentBracketIdx = (int)((DateTime.UtcNow - sessionStartUtc).TotalMinutes / BracketSizeMin);
                    // Skip active session when fewer than 2 brackets have closed:
                    // with only one bracket of data, every tick has count==1 and
                    // the whole range collapses to one degenerate "zone" that
                    // carries no information. Real single-print structure needs
                    // at least one cross-bracket comparison.
                    if (currentBracketIdx < 2) continue;
                    DateTime currentBracketStart = sessionStartUtc.AddMinutes(currentBracketIdx * BracketSizeMin);
                    var closed = new List<SessionBuilder.Bar>();
                    foreach (var b in bars)
                        if (b.TimeUtc < currentBracketStart) closed.Add(b);
                    barsForCompute = closed;
                }

                var sessionZones = SessionBuilder.ComputeZones(
                    barsForCompute,
                    sessionStartUtc,
                    sessionEndUtc,
                    sessionDateNy,
                    BracketSizeMin,
                    tickSize,
                    MinZoneTicks,
                    ExcludeExtremes,
                    out double sLow, out double sHigh);

                allZones.AddRange(sessionZones);
                sessionRanges.Add((sessionDateNy, sLow, sHigh));
            }

            // Drop zones spanned by any later session. "Filled" = later session's
            // [low, high] fully crosses the zone's [bottom, top].
            foreach (var z in allZones)
            {
                foreach (var s in sessionRanges)
                {
                    if (s.date <= z.SessionDateNy) continue;
                    if (s.low <= z.BottomPrice && s.high >= z.TopPrice)
                    {
                        z.Filled = true;
                        break;
                    }
                }
            }

            // Retention cap: drop zones from sessions older than RetentionSessions.
            DateTime newestSessionDate = sessionRanges.Count > 0
                ? sessionRanges[sessionRanges.Count - 1].date
                : DateTime.MinValue;
            int retainDays = Math.Max(1, RetentionSessions);
            DateTime cutoff = newestSessionDate.AddDays(-(retainDays - 1));
            allZones.RemoveAll(z => z.Filled || z.SessionDateNy < cutoff);

            _zones = allZones;
        }

        protected override void OnClear()
        {
            try
            {
                _painter = null;
                _zones = new List<Zone>();
            }
            catch { }
        }
    }
}
