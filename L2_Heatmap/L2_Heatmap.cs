using System;
using System.Collections.Generic;
using TradingPlatform.BusinessLayer;

namespace L2_Heatmap
{
    public class L2_Heatmap : Indicator
    {
        private const string IndicatorVersion = "0.1.0";

        // ── Liquidity Heatmap (sortIndex 700-707) ───────────────────────────
        // Capture below is independent of this flag — set to false on your
        // main chart to turn off the cloud overlay while capture keeps writing.
        [InputParameter("Show Heatmap Painting (capture is independent)", sortIndex: 700)]
        public bool LiquidityHeatmapEnabled = true;

        [InputParameter("Retention (sec)", sortIndex: 701,
            minimum: 60, maximum: 3600, increment: 60, decimalPlaces: 0)]
        public int LiquidityHeatmapRetentionSec = 600;

        [InputParameter("Snapshot Interval (ms)", sortIndex: 702,
            minimum: 100, maximum: 5000, increment: 100, decimalPlaces: 0)]
        public int LiquidityHeatmapSnapshotIntervalMs = 500;

        [InputParameter("Levels Window (price points each side)", sortIndex: 703,
            minimum: 1, maximum: 1000, increment: 1, decimalPlaces: 1)]
        public double LiquidityHeatmapLevelsWindowPoints = 50.0;

        [InputParameter("Size Floor (skip cells below this)", sortIndex: 704,
            minimum: 0, maximum: 100, increment: 1, decimalPlaces: 1)]
        public double LiquidityHeatmapSizeFloor = 1.0;

        [InputParameter("Alpha Max (cell saturation cap, 0-255)", sortIndex: 705,
            minimum: 10, maximum: 255, increment: 5, decimalPlaces: 0)]
        public int LiquidityHeatmapAlphaMax = 70;

        [InputParameter("Saturation Lot Count (0 = adaptive)", sortIndex: 706,
            minimum: 0, maximum: 10000, increment: 5, decimalPlaces: 1)]
        public double LiquidityHeatmapSizeAtSaturation = 0.0;

        [InputParameter("Adaptive Percentile (when saturation = 0)", sortIndex: 707,
            minimum: 0.5, maximum: 0.999, increment: 0.005, decimalPlaces: 3)]
        public double LiquidityHeatmapAdaptivePercentile = 0.99;

        // ── L2 + Tick Capture (sortIndex 720-722) ──────────────────────────
        // Opt-in. When enabled, writes top-50-each-side L2 snapshots at 1Hz
        // and every trade tick to parquet under captures/<SYMBOL>/ next to
        // the indicator DLL. Buffered, batched-flushed every 10s on a
        // background task. Off by default — accumulating sessions has cost.
        [InputParameter("Capture Enabled (write L2 + ticks to parquet)", sortIndex: 720)]
        public bool CaptureEnabled = false;

        [InputParameter("Capture Snapshot Interval (ms)", sortIndex: 721,
            minimum: 250, maximum: 10000, increment: 250, decimalPlaces: 0)]
        public int CaptureSnapshotIntervalMs = 1000;

        [InputParameter("Capture Retention (days)", sortIndex: 722,
            minimum: 1, maximum: 365, increment: 1, decimalPlaces: 0)]
        public int CaptureRetentionDays = 30;

        // Hardcoded default points at the indicator deploy folder. Quantower
        // shadow-copies indicator DLLs so Assembly.Location can't reliably
        // resolve it at runtime — explicit path is more robust.
        [InputParameter("Capture Root Path", sortIndex: 723)]
        public string CaptureRootPath = @"C:\Quantower\Settings\Scripts\Indicators\L2_Heatmap\captures";

        // ── Book Hygiene (sortIndex 724) ──────────────────────────────
        // Feed-paused detector. We read the canonical book each sample from
        // Symbol.DepthOfMarket — orphan-level corruption (the 2026-05-08
        // ref_tick bug) is structurally impossible because every L2 vendor
        // refresh replaces QT's internal book wholesale. The only remaining
        // stale mode is "feed paused": no L2 events arriving. Above this
        // threshold, the heatmap snapshot writer + capture writer pause, and
        // the painter shows a STALE badge.
        [InputParameter("Book Freshness (sec, no-L2-update threshold)", sortIndex: 724,
            minimum: 1, maximum: 60, increment: 1, decimalPlaces: 0)]
        public int BookFreshnessSec = 5;

        // L1 sanity gate. DOM should already agree with Symbol.Bid/Ask, but
        // paranoia: if best-of-side from DOM diverges by more than this many
        // ticks, treat as stale. Catches a class of bug we can't otherwise
        // see. 2 ticks tolerates the natural in-flight skew between QT's L1
        // cache and DOM aggregation.
        private const int L1ToleranceTicks = 2;

        private LiquidityHeatmapBuffer _heatmap;
        private ChartPainter _painter;
        private GetDepthOfMarketParameters _domParams;
        private double _tickSize = 0.25;
        private bool _l2Subscribed;
        private L2Capture _capture;
        private bool _lastSubscribed;
        private DateTime _lastL2EventUtc = DateTime.MinValue;
        private DateTime _lastDisplayUtc = DateTime.MinValue;
        private DateTime _lastCaptureUtc = DateTime.MinValue;
        private bool _l2Stale;

        public L2_Heatmap() : base()
        {
            this.Name = "L2 Heatmap";
            this.SeparateWindow = false;
        }

        // Native settings-dialog grouping. Quantower renders the section header
        // from SettingItemSeparatorGroup; without it the inputs render
        // ungrouped at the top of the dialog.
        public override IList<SettingItem> Settings
        {
            get
            {
                var settings = base.Settings;
                if (settings != null)
                {
                    var heatmapGroup = new SettingItemSeparatorGroup(
                        "Liquidity Heatmap", 700);
                    var captureGroup = new SettingItemSeparatorGroup(
                        "Capture (L2 + Ticks → parquet)", 720);
                    foreach (var item in settings)
                    {
                        if (item == null) continue;
                        if (item.SortIndex >= 700 && item.SortIndex <= 707)
                            item.SeparatorGroup = heatmapGroup;
                        else if (item.SortIndex >= 720 && item.SortIndex <= 724)
                            item.SeparatorGroup = captureGroup;
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
                _tickSize = this.Symbol.TickSize > 0 ? this.Symbol.TickSize : 0.25;

                if (LiquidityHeatmapEnabled)
                {
                    _heatmap = new LiquidityHeatmapBuffer(
                        _tickSize,
                        LiquidityHeatmapRetentionSec,
                        LiquidityHeatmapSnapshotIntervalMs,
                        LiquidityHeatmapAlphaMax,
                        LiquidityHeatmapSizeFloor,
                        LiquidityHeatmapLevelsWindowPoints,
                        LiquidityHeatmapSizeAtSaturation,
                        LiquidityHeatmapAdaptivePercentile);
                }

                _painter = new ChartPainter { Heatmap = _heatmap };

                // 50 levels each side covers the parquet capture schema.
                _domParams = new GetDepthOfMarketParameters
                {
                    GetLevel2ItemsParameters = new GetLevel2ItemsParameters
                    {
                        LevelsCount = L2Capture.LevelsPerSide,
                        CalculateCumulative = false,
                    },
                };

                if (CaptureEnabled)
                {
                    var captureRoot = string.IsNullOrWhiteSpace(CaptureRootPath)
                        ? @"C:\Quantower\Settings\Scripts\Indicators\L2_Heatmap\captures"
                        : CaptureRootPath;
                    string symKey = this.Symbol.Name ?? "UNKNOWN";
                    _capture = new L2Capture(captureRoot, symKey, CaptureRetentionDays);
                    _capture.Start();
                    Core.Instance.Loggers.Log(
                        $"[L2_Heatmap] Capture ENABLED. root={captureRoot} symbol={symKey} retentionDays={CaptureRetentionDays}",
                        LoggingLevel.System);
                    this.Symbol.NewLast += Symbol_NewLast;
                    _lastSubscribed = true;
                }

                // We don't process L2 events ourselves anymore — QT's
                // DepthOfMarket maintains the canonical book; we read it on
                // each sample. Subscription stays as the freshness heartbeat
                // (and to mark this indicator as an L2 consumer so QT keeps
                // delivering the stream). See RESEARCH_LOG 2026-05-08.
                this.Symbol.NewLevel2 += Symbol_NewLevel2Heartbeat;
                _l2Subscribed = true;
            }
            catch (Exception ex)
            {
                Core.Instance.Loggers.Log(
                    $"[{nameof(L2_Heatmap)}] OnInit failed: {ex.Message}",
                    LoggingLevel.Error);
            }
        }

        // Heartbeat-only handler. We don't apply L2 deltas — QT's DepthOfMarket
        // maintains the canonical book and we sample it directly each tick.
        // This subscription stays so QT delivers the L2 stream and we have a
        // freshness heartbeat for the STALE-badge logic.
        private void Symbol_NewLevel2Heartbeat(Symbol symbol, Level2Quote l2, DOMQuote dom)
        {
            _lastL2EventUtc = DateTime.UtcNow;
        }

        private void Symbol_NewLast(Symbol symbol, Last last)
        {
            if (last == null || _capture == null) return;
            if (double.IsNaN(last.Price) || last.Price <= 0) return;
            var t = last.Time == default ? DateTime.UtcNow : last.Time;
            _capture.EnqueueTick(t, last.Price, last.Size, last.AggressorFlag);
        }

        protected override void OnUpdate(UpdateArgs args)
        {
            if (this.Symbol == null) return;

            // Two independent cadence gates. Previously a single master gate
            // tied capture to the display interval — if display=5000ms and
            // capture=1000ms, capture silently fired every 5s. Each consumer
            // runs on its own clock.
            var now = DateTime.UtcNow;
            bool displayDue = _heatmap != null
                && (now - _lastDisplayUtc).TotalMilliseconds >= LiquidityHeatmapSnapshotIntervalMs;
            bool captureDue = _capture != null
                && (now - _lastCaptureUtc).TotalMilliseconds >= CaptureSnapshotIntervalMs;
            if (!displayDue && !captureDue) return;

            // Freshness gate. Orphan-level corruption is structurally
            // impossible now (we read QT's canonical book each sample). Only
            // remaining stale mode is "feed paused": no L2 events arriving.
            bool fresh = _lastL2EventUtc != DateTime.MinValue
                      && (now - _lastL2EventUtc).TotalSeconds <= BookFreshnessSec;
            _l2Stale = !fresh;
            if (_painter != null) _painter.L2Stale = _l2Stale;
            if (_l2Stale) return;

            var dom = this.Symbol.DepthOfMarket?
                          .GetDepthOfMarketAggregatedCollections(_domParams);
            if (dom == null
                || (dom.Bids == null || dom.Bids.Length == 0)
                && (dom.Asks == null || dom.Asks.Length == 0))
            {
                _l2Stale = true;
                if (_painter != null) _painter.L2Stale = true;
                return;
            }

            // L1 sanity gate. Compare DOM-derived best vs Symbol.Bid/Ask
            // within tolerance. DOM is canonical, but a divergence > Tol
            // ticks signals something we can't otherwise see (vendor lag,
            // inconsistent caches) — pause rather than paint suspect data.
            if (!L1Agrees(dom, _tickSize))
            {
                _l2Stale = true;
                if (_painter != null) _painter.L2Stale = true;
                return;
            }

            if (displayDue)
            {
                _lastDisplayUtc = now;
                _heatmap?.OnSample(dom, now);
            }
            if (captureDue)
            {
                _lastCaptureUtc = now;
                _capture?.EnqueueSnapshot(now, dom, _tickSize);
            }
        }

        // First level with finite price > 0 and finite size > 0. QT's DOM
        // should already be clean, but defensive against any vendor leak of
        // NaN/zero levels (e.g. the synthesized L1-as-L2 events).
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

        private bool L1Agrees(DepthOfMarketAggregatedCollections dom, double tickSize)
        {
            double symBid = this.Symbol.Bid;
            double symAsk = this.Symbol.Ask;
            // No L1 yet (e.g. very early after subscribe) → nothing to check.
            if (!double.IsFinite(symBid) || !double.IsFinite(symAsk) || symBid <= 0 || symAsk <= 0)
                return true;
            double domBid = FirstValidPrice(dom.Bids);
            double domAsk = FirstValidPrice(dom.Asks);
            if (double.IsFinite(domBid))
            {
                long d = Math.Abs((long)Math.Round(domBid / tickSize) - (long)Math.Round(symBid / tickSize));
                if (d > L1ToleranceTicks) return false;
            }
            if (double.IsFinite(domAsk))
            {
                long d = Math.Abs((long)Math.Round(domAsk / tickSize) - (long)Math.Round(symAsk / tickSize));
                if (d > L1ToleranceTicks) return false;
            }
            return true;
        }

        public override void OnPaintChart(PaintChartEventArgs args)
        {
            try
            {
                if (_painter != null && this.CurrentChart != null)
                    _painter.Paint(args, this.CurrentChart);
            }
            catch (Exception ex)
            {
                try
                {
                    Core.Instance.Loggers.Log(
                        $"[{nameof(L2_Heatmap)}] paint failed: {ex.Message}",
                        LoggingLevel.Error);
                }
                catch { }
            }
        }

        protected override void OnClear()
        {
            try
            {
                if (_l2Subscribed && this.Symbol != null)
                {
                    try { this.Symbol.NewLevel2 -= Symbol_NewLevel2Heartbeat; } catch { }
                    _l2Subscribed = false;
                }
                if (_lastSubscribed && this.Symbol != null)
                {
                    try { this.Symbol.NewLast -= Symbol_NewLast; } catch { }
                    _lastSubscribed = false;
                }
                // Dispose capture before painter so the writer task gets its
                // final flush done before anything else is torn down.
                try { _capture?.Dispose(); } catch { }
                _capture = null;
                _painter?.Dispose();
                _painter = null;
                _heatmap?.Clear();
                _heatmap = null;
                _domParams = null;
            }
            catch { }
        }
    }
}
