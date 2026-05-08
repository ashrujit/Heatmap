using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using TradingPlatform.BusinessLayer;
using TradingPlatform.BusinessLayer.Chart;
using TradingPlatform.BusinessLayer.Native;

namespace LiquidityMeter
{
    public class LiquidityMeter : Indicator
    {
        private const string IndicatorVersion = "0.2.0";

        // ── Detection (sortIndex 900-905) ───────────────────────────────────
        [InputParameter("Lookback Seconds (rolling baseline)", sortIndex: 900,
            minimum: 10, maximum: 300, increment: 5, decimalPlaces: 0)]
        public int LookbackSeconds = 30;

        [InputParameter("Event Z Threshold", sortIndex: 901,
            minimum: 1.5, maximum: 5.0, increment: 0.1, decimalPlaces: 2)]
        public double EventZThreshold = 2.5;

        [InputParameter("ROC Window Seconds", sortIndex: 902,
            minimum: 15, maximum: 300, increment: 5, decimalPlaces: 0)]
        public int ROCWindowSeconds = 60;

        [InputParameter("Sample Interval (ms)", sortIndex: 903,
            minimum: 250, maximum: 5000, increment: 250, decimalPlaces: 0)]
        public int SampleIntervalMs = 1000;

        // Defense against orphaned book levels (the 2026-05-08 ref_tick bug —
        // see RESEARCH_LOG). 60s is conservative for liquid futures aggregated
        // L2; lower for less liquid symbols only if you see legitimate quiet
        // levels evicted; 0 disables.
        [InputParameter("Book Stale-Level TTL (sec, 0 = off)", sortIndex: 906,
            minimum: 0, maximum: 600, increment: 5, decimalPlaces: 0)]
        public int BookStaleTtlSec = 60;

        // L1 reconciliation: any L2 entry whose tick violates Symbol.Bid /
        // Symbol.Ask by more than this many ticks gets pruned. L1 is its own
        // stream — independent reference vs the L2 book.
        [InputParameter("Book L1 Reconcile Tolerance (ticks)", sortIndex: 907,
            minimum: 0, maximum: 50, increment: 1, decimalPlaces: 0)]
        public int BookL1ToleranceTicks = 4;

        // Feed-paused detector: if no L2 deltas have arrived for this long,
        // pause sampling and paint a STALE badge.
        [InputParameter("Book Freshness (sec, no-L2-update threshold)", sortIndex: 908,
            minimum: 1, maximum: 60, increment: 1, decimalPlaces: 0)]
        public int BookFreshnessSec = 5;

        [InputParameter("Anchor Mode", sortIndex: 904, variants: new object[]
        {
            "Rolling Window",  AnchorModeRolling,
            "Indicator Load",  AnchorModeLoad,
            "Session Start (NY 09:30)", AnchorModeSession,
        })]
        public int AnchorMode = AnchorModeRolling;

        [InputParameter("Rolling Anchor Minutes (when Anchor=Rolling)", sortIndex: 905,
            minimum: 5, maximum: 240, increment: 5, decimalPlaces: 0)]
        public int RollingAnchorMin = 30;

        // ── Render (sortIndex 910-915) ──────────────────────────────────────
        [InputParameter("Meter Left Offset (px)", sortIndex: 910,
            minimum: 4, maximum: 400, increment: 2, decimalPlaces: 0)]
        public int MeterLeftOffsetPx = 70;

        [InputParameter("Cum Bar Width (px)", sortIndex: 911,
            minimum: 8, maximum: 60, increment: 2, decimalPlaces: 0)]
        public int CumBarWidth = 18;

        [InputParameter("ROC Dial Width (px)", sortIndex: 915,
            minimum: 30, maximum: 200, increment: 5, decimalPlaces: 0)]
        public int RocDialWidth = 90;

        [InputParameter("ROC Dial Height (px)", sortIndex: 916,
            minimum: 12, maximum: 50, increment: 2, decimalPlaces: 0)]
        public int RocDialHeight = 22;

        [InputParameter("VOD Strip Width (px)", sortIndex: 917,
            minimum: 6, maximum: 40, increment: 2, decimalPlaces: 0)]
        public int VodStripWidth = 14;

        [InputParameter("VOD Steady-Glow Saturation Count (events/30s)", sortIndex: 918,
            minimum: 1, maximum: 20, increment: 1, decimalPlaces: 0)]
        public int VodCountForFullSteady = 4;

        [InputParameter("Meter Height (% of chart)", sortIndex: 912,
            minimum: 20, maximum: 90, increment: 5, decimalPlaces: 0)]
        public int MeterHeightPercent = 55;

        [InputParameter("Cum Scale (full bar at this magnitude)", sortIndex: 913,
            minimum: 5, maximum: 200, increment: 5, decimalPlaces: 0)]
        public double CumScale = 30.0;

        [InputParameter("ROC Scale (full needle deflection at this magnitude)", sortIndex: 914,
            minimum: 2, maximum: 50, increment: 1, decimalPlaces: 0)]
        public double ROCScale = 10.0;

        public const int AnchorModeRolling = 0;
        public const int AnchorModeLoad    = 1;
        public const int AnchorModeSession = 2;

        // ── Internal state ──────────────────────────────────────────────────
        private BookState _bookState;
        private MeterEngine _engine;
        private MeterPainter _painter;
        private ConcurrentQueue<Level2Quote> _l2Queue;
        private bool _l2Subscribed;
        private DateTime _lastSampleUtc = DateTime.MinValue;
        private bool _l2Stale;

        // Manual-click anchor override: set by left-click on the meter strip,
        // cleared by right-click. Wins over the configured Anchor Mode while
        // active. Cleared on indicator unload (in-memory only).
        private DateTime? _manualAnchorUtc;
        private IChart _subscribedChart;

        public LiquidityMeter() : base()
        {
            this.Name = "Liquidity Meter";
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
                if (this.Symbol == null) return;
                double tickSize = this.Symbol.TickSize > 0 ? this.Symbol.TickSize : 0.25;

                _bookState = new BookState(tickSize);
                _engine = new MeterEngine(LookbackSeconds, EventZThreshold, ROCWindowSeconds);
                ApplyAnchor(_engine, DateTime.UtcNow);

                _painter = new MeterPainter
                {
                    LeftOffsetPx = MeterLeftOffsetPx,
                    CumBarWidth = CumBarWidth,
                    RocDialWidth = RocDialWidth,
                    RocDialHeight = RocDialHeight,
                    VodStripWidth = VodStripWidth,
                    VodCountForFullSteady = VodCountForFullSteady,
                    MeterHeightFraction = MeterHeightPercent / 100.0,
                    CumScale = CumScale,
                    ROCScale = ROCScale,
                };
                _l2Queue = new ConcurrentQueue<Level2Quote>();

                this.Symbol.NewLevel2 += Symbol_NewLevel2;
                _l2Subscribed = true;
            }
            catch (Exception ex)
            {
                Core.Instance.Loggers.Log(
                    $"[{nameof(LiquidityMeter)}] OnInit failed: {ex.Message}",
                    LoggingLevel.Error);
            }
        }

        private void ApplyAnchor(MeterEngine eng, DateTime nowUtc)
        {
            switch (AnchorMode)
            {
                case AnchorModeRolling:
                    eng.RollingAnchorWindow = TimeSpan.FromMinutes(RollingAnchorMin);
                    eng.SetAnchor(nowUtc - eng.RollingAnchorWindow.Value);
                    break;
                case AnchorModeLoad:
                    eng.RollingAnchorWindow = null;
                    eng.SetAnchor(nowUtc);
                    break;
                case AnchorModeSession:
                    eng.RollingAnchorWindow = null;
                    eng.SetAnchor(NyTodaysSessionStart());
                    break;
            }
        }

        private static DateTime NyTodaysSessionStart()
        {
            // 09:30 New York time, today, in UTC.
            try
            {
                var ny = TimeZoneInfo.FindSystemTimeZoneById("Eastern Standard Time");
                var nowNy = TimeZoneInfo.ConvertTime(DateTime.UtcNow, ny);
                var todayOpen = new DateTime(nowNy.Year, nowNy.Month, nowNy.Day,
                                             9, 30, 0, DateTimeKind.Unspecified);
                return TimeZoneInfo.ConvertTimeToUtc(todayOpen, ny);
            }
            catch
            {
                return DateTime.UtcNow.Date.AddHours(13).AddMinutes(30);  // fallback ~13:30 UTC
            }
        }

        private void Symbol_NewLevel2(Symbol symbol, Level2Quote l2, DOMQuote dom)
        {
            if (l2 == null) return;
            _l2Queue?.Enqueue(l2);
        }

        protected override void OnUpdate(UpdateArgs args)
        {
            if (_l2Queue == null || _bookState == null || _engine == null) return;

            // Drain L2 deltas onto the live book.
            while (_l2Queue.TryDequeue(out var q))
            {
                try { _bookState.Apply(q, DateTime.UtcNow); }
                catch { /* skip bad quote */ }
            }

            // Fixed-cadence book sample — independent of L2 burst rate. The
            // research data is at 1 Hz; we match that by default.
            var now = DateTime.UtcNow;
            if ((now - _lastSampleUtc).TotalMilliseconds >= SampleIntervalMs)
            {
                _lastSampleUtc = now;
                // Book hygiene before sampling — three layers against the
                // 2026-05-08 ref_tick bug:
                //   PruneStale (TTL), ReconcileWithL1 (vs Symbol.Bid/Ask),
                //   IsFresh (feed-paused detector). When stale, freeze: skip
                //   the sample so cum/ROC don't update on bad data; the
                //   painter shows a STALE badge.
                _bookState.PruneStale(now, BookStaleTtlSec);
                bool sane = _bookState.ReconcileWithL1(
                    this.Symbol.Bid, this.Symbol.Ask, BookL1ToleranceTicks);
                bool fresh = _bookState.IsFresh(now, BookFreshnessSec);
                _l2Stale = !sane || !fresh;
                if (_l2Stale) return;
                try { _engine.OnSample(now, _bookState); }
                catch (Exception ex)
                {
                    Core.Instance.Loggers.Log(
                        $"[{nameof(LiquidityMeter)}] sample failed: {ex.Message}",
                        LoggingLevel.Error);
                }
            }
        }

        public override void OnPaintChart(PaintChartEventArgs args)
        {
            try
            {
                // Lazy chart subscribe — CurrentChart isn't reliably non-null
                // until first paint.
                if (_subscribedChart == null)
                {
                    var chart = this.CurrentChart;
                    if (chart != null)
                    {
                        chart.MouseClick += Chart_MouseClick;
                        _subscribedChart = chart;
                    }
                }

                if (_painter != null && _engine != null)
                {
                    _painter.ManualAnchorUtc = _manualAnchorUtc;
                    _painter.L2Stale = _l2Stale;
                    _painter.Paint(args, _engine);
                }
            }
            catch (Exception ex)
            {
                try
                {
                    Core.Instance.Loggers.Log(
                        $"[{nameof(LiquidityMeter)}] paint failed: {ex.Message}",
                        LoggingLevel.Error);
                }
                catch { }
            }
        }

        private void Chart_MouseClick(object sender, ChartMouseNativeEventArgs e)
        {
            if (_painter == null || _engine == null) return;
            var hit = _painter.LastHitRect;
            if (hit.Width <= 0 || hit.Height <= 0) return;
            if (e.X < hit.Left || e.X > hit.Right) return;
            if (e.Y < hit.Top  || e.Y > hit.Bottom) return;

            if (e.Button == NativeMouseButtons.Left)
            {
                // Left-click sets anchor at NOW. The semantic is "I just entered /
                // started caring about this moment" — same posture as Codex
                // suggested but with the anchor at click instant rather than at
                // a clicked-bar timestamp (avoids accidental backdating).
                _manualAnchorUtc = DateTime.UtcNow;
                _engine.RollingAnchorWindow = null;     // disable rolling re-anchor
                _engine.SetAnchor(_manualAnchorUtc.Value);
                e.NeedRedraw = true;
                e.Handled = true;
            }
            else if (e.Button == NativeMouseButtons.Right && _manualAnchorUtc.HasValue)
            {
                _manualAnchorUtc = null;
                ApplyAnchor(_engine, DateTime.UtcNow);   // restore configured mode
                e.NeedRedraw = true;
                e.Handled = true;
            }
        }

        protected override void OnClear()
        {
            try
            {
                if (_l2Subscribed && this.Symbol != null)
                {
                    try { this.Symbol.NewLevel2 -= Symbol_NewLevel2; } catch { }
                    _l2Subscribed = false;
                }
                if (_subscribedChart != null)
                {
                    try { _subscribedChart.MouseClick -= Chart_MouseClick; } catch { }
                    _subscribedChart = null;
                }
                _painter = null;
                _engine = null;
                _bookState?.Clear();
                _bookState = null;
                _l2Queue = null;
                _manualAnchorUtc = null;
            }
            catch { }
        }
    }
}
