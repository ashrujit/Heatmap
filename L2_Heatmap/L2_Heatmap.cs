using System;
using System.Collections.Concurrent;
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

        // ── Book Hygiene (sortIndex 724-726) ──────────────────────────────
        // Defense against orphaned levels in BookState (missed Closed events,
        // contract-roll feed gaps). See RESEARCH_LOG 2026-05-08 for the
        // failure mode this guards against. Three layers:
        //   - StaleTtl: levels untouched for longer than TTL get force-pruned.
        //   - L1ReconcileTolerance: any L2 entry that violates Symbol.Bid /
        //     Symbol.Ask (Level1) by more than this many ticks gets pruned;
        //     L1 is an independent stream from L2, so it's a clean reference.
        //   - FreshnessSec: if no L2 deltas have arrived for this long, the
        //     feed is paused — pause the heatmap snapshot writer / capture
        //     writer until updates resume. Paint a STALE badge.
        [InputParameter("Book Stale-Level TTL (sec, 0 = off)", sortIndex: 724,
            minimum: 0, maximum: 600, increment: 5, decimalPlaces: 0)]
        public int BookStaleTtlSec = 60;

        [InputParameter("Book L1 Reconcile Tolerance (ticks)", sortIndex: 725,
            minimum: 0, maximum: 50, increment: 1, decimalPlaces: 0)]
        public int BookL1ToleranceTicks = 4;

        [InputParameter("Book Freshness (sec, no-L2-update threshold)", sortIndex: 726,
            minimum: 1, maximum: 60, increment: 1, decimalPlaces: 0)]
        public int BookFreshnessSec = 5;

        private BookState _bookState;
        private LiquidityHeatmapBuffer _heatmap;
        private ChartPainter _painter;
        private ConcurrentQueue<Level2Quote> _l2Queue;
        private bool _l2Subscribed;
        private L2Capture _capture;
        private bool _lastSubscribed;
        private DateTime _lastCaptureUtc = DateTime.MinValue;

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
                        else if (item.SortIndex >= 720 && item.SortIndex <= 726)
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
                double tickSize = this.Symbol.TickSize > 0 ? this.Symbol.TickSize : 0.25;

                _bookState = new BookState(tickSize);

                if (LiquidityHeatmapEnabled)
                {
                    _heatmap = new LiquidityHeatmapBuffer(
                        tickSize,
                        LiquidityHeatmapRetentionSec,
                        LiquidityHeatmapSnapshotIntervalMs,
                        LiquidityHeatmapAlphaMax,
                        LiquidityHeatmapSizeFloor,
                        LiquidityHeatmapLevelsWindowPoints,
                        LiquidityHeatmapSizeAtSaturation,
                        LiquidityHeatmapAdaptivePercentile);
                }

                _painter = new ChartPainter { Heatmap = _heatmap };
                _l2Queue = new ConcurrentQueue<Level2Quote>();

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

                this.Symbol.NewLevel2 += Symbol_NewLevel2;
                _l2Subscribed = true;
            }
            catch (Exception ex)
            {
                Core.Instance.Loggers.Log(
                    $"[{nameof(L2_Heatmap)}] OnInit failed: {ex.Message}",
                    LoggingLevel.Error);
            }
        }

        private void Symbol_NewLevel2(Symbol symbol, Level2Quote l2, DOMQuote dom)
        {
            if (l2 == null) return;
            _l2Queue?.Enqueue(l2);
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
            DrainLevel2();
        }

        private void DrainLevel2()
        {
            if (_l2Queue == null || _bookState == null) return;

            // 1) Apply all queued L2 deltas.
            while (_l2Queue.TryDequeue(out var q))
            {
                try { _bookState.Apply(q, DateTime.UtcNow); }
                catch { /* single bad quote shouldn't kill the drain */ }
            }

            var now = DateTime.UtcNow;

            // 2) Book hygiene — three layers of defense against the 2026-05-08
            //    ref_tick corruption (orphaned levels pinning best bid/ask):
            //      • PruneStale (TTL): background sweep of deep stranded levels.
            //      • ReconcileWithL1: top-of-book sanity vs Symbol.Bid/Ask.
            //      • IsFresh: feed-paused detector (no L2 deltas in N sec).
            _bookState.PruneStale(now, BookStaleTtlSec);
            bool sane = _bookState.ReconcileWithL1(
                this.Symbol.Bid, this.Symbol.Ask, BookL1ToleranceTicks);
            bool fresh = _bookState.IsFresh(now, BookFreshnessSec);
            bool stale = !sane || !fresh;

            if (_painter != null) _painter.L2Stale = stale;

            // 3) When stale, freeze: don't enqueue new heatmap snapshots and
            //    don't capture parquet rows. Existing on-screen state remains;
            //    the badge tells the user the cloud is frozen.
            if (stale) return;

            _heatmap?.OnPostApply(_bookState, now);
            if (_capture != null
                && (now - _lastCaptureUtc).TotalMilliseconds >= CaptureSnapshotIntervalMs)
            {
                _lastCaptureUtc = now;
                _capture.EnqueueSnapshot(now, _bookState);
            }
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
                    try { this.Symbol.NewLevel2 -= Symbol_NewLevel2; } catch { }
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
                _bookState?.Clear();
                _bookState = null;
                _l2Queue = null;
            }
            catch { }
        }
    }
}
