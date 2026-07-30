using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.Threading;
using TradingPlatform.BusinessLayer;
using TradingPlatform.BusinessLayer.Chart;
using TradingPlatform.BusinessLayer.Native;

namespace LevelLedger
{
    public class LevelLedger : Indicator
    {
        private const string IndicatorVersion = "0.3.0";
        private const int L1ToleranceTicks = 2;
        private const int TradeQueueCap = 50000;

        // Detection
        [InputParameter("Sample Interval (ms)", sortIndex: 900,
            minimum: 250, maximum: 5000, increment: 250, decimalPlaces: 0)]
        public int SampleIntervalMs = 1000;

        [InputParameter("Book Lookback Seconds", sortIndex: 901,
            minimum: 10, maximum: 300, increment: 5, decimalPlaces: 0)]
        public int BookLookbackSeconds = 30;

        [InputParameter("L2 Event Z Threshold", sortIndex: 902,
            minimum: 1.5, maximum: 5.0, increment: 0.1, decimalPlaces: 2)]
        public double EventZThreshold = 2.5;

        [InputParameter("Spatial Dominance Ratio", sortIndex: 903,
            minimum: 1.2, maximum: 8.0, increment: 0.1, decimalPlaces: 1)]
        public double SpatialDominanceRatio = 2.2;

        [InputParameter("Activation Lookback Minutes", sortIndex: 904,
            minimum: 1, maximum: 30, increment: 1, decimalPlaces: 0)]
        public int ActivationLookbackMinutes = 10;

        [InputParameter("Trade Bar Seconds", sortIndex: 905,
            minimum: 1, maximum: 30, increment: 1, decimalPlaces: 0)]
        public int TradeBarSeconds = 5;

        [InputParameter("Trade Volume Z Threshold", sortIndex: 906,
            minimum: 0.5, maximum: 5.0, increment: 0.1, decimalPlaces: 1)]
        public double TradeVolumeZ = 1.5;

        [InputParameter("Trade |Delta|/Volume Min", sortIndex: 907,
            minimum: 0.05, maximum: 0.80, increment: 0.05, decimalPlaces: 2)]
        public double TradeDeltaRatio = 0.25;

        [InputParameter("Book Freshness (sec, no-L2-update threshold)", sortIndex: 908,
            minimum: 1, maximum: 60, increment: 1, decimalPlaces: 0)]
        public int BookFreshnessSec = 5;

        // Render
        [InputParameter("Panel: Enabled", sortIndex: 920)]
        public bool PanelEnabled = true;

        [InputParameter("Panel Left Offset (px)", sortIndex: 921,
            minimum: 0, maximum: 2000, increment: 5, decimalPlaces: 0)]
        public int PanelLeftOffsetPx = 90;

        [InputParameter("Panel Top Offset (px)", sortIndex: 922,
            minimum: 0, maximum: 1500, increment: 5, decimalPlaces: 0)]
        public int PanelTopOffsetPx = 90;

        [InputParameter("Panel Width (px)", sortIndex: 923,
            minimum: 180, maximum: 520, increment: 10, decimalPlaces: 0)]
        public int PanelWidthPx = 300;

        [InputParameter("Visible Rows", sortIndex: 924,
            minimum: 4, maximum: 12, increment: 1, decimalPlaces: 0)]
        public int VisibleRows = 10;

        [InputParameter("Font Size", sortIndex: 925,
            minimum: 7, maximum: 14, increment: 0.5, decimalPlaces: 1)]
        public double FontSize = 9.0;

        [InputParameter("Panel: Ownership Events", sortIndex: 926)]
        public bool PanelOwnershipEvents = true;

        [InputParameter("VOD+BUILD Dots: Enabled", sortIndex: 940)]
        public bool VodBuildDotsEnabled = true;

        [InputParameter("VOD+BUILD Dots: VOD |z|", sortIndex: 941,
            minimum: 3.0, maximum: 12.0, increment: 0.25, decimalPlaces: 2)]
        public double VodBuildDotVodZ = 5.0;

        [InputParameter("VOD+BUILD Dots: BUILD |z|", sortIndex: 942,
            minimum: 2.0, maximum: 8.0, increment: 0.25, decimalPlaces: 2)]
        public double VodBuildDotBuildZ = 4.0;

        [InputParameter("VOD+BUILD Dots: Size (px)", sortIndex: 943,
            minimum: 3, maximum: 16, increment: 1, decimalPlaces: 0)]
        public int VodBuildDotSizePx = 7;

        [InputParameter("VOD+BUILD Dots: Alpha", sortIndex: 944,
            minimum: 20, maximum: 255, increment: 5, decimalPlaces: 0)]
        public int VodBuildDotAlpha = 175;

        [InputParameter("VOD+BUILD Dots: Retention Minutes (0=session)", sortIndex: 945,
            minimum: 0, maximum: 480, increment: 5, decimalPlaces: 0)]
        public int VodBuildDotRetentionMinutes = 0;

        [InputParameter("Ownership Rails: Enabled", sortIndex: 950)]
        public bool BuildBandsEnabled = true;

        [InputParameter("Ownership Rails: Event |z|", sortIndex: 951,
            minimum: 1.5, maximum: 8.0, increment: 0.1, decimalPlaces: 2)]
        public double BuildBandBuildZ = 2.5;

        [InputParameter("Ownership Rails: Cluster Min Events", sortIndex: 952,
            minimum: 2, maximum: 10, increment: 1, decimalPlaces: 0)]
        public int BuildBandClusterN = 3;

        [InputParameter("Ownership Rails: Cluster Tick Range", sortIndex: 953,
            minimum: 1, maximum: 40, increment: 1, decimalPlaces: 0)]
        public int BuildBandClusterTicks = 10;

        [InputParameter("Ownership Rails: Cluster Window (sec)", sortIndex: 954,
            minimum: 15, maximum: 600, increment: 15, decimalPlaces: 0)]
        public int BuildBandClusterSec = 90;

        [InputParameter("Ownership Rails: Confirm Move (ticks)", sortIndex: 955,
            minimum: 2, maximum: 80, increment: 1, decimalPlaces: 0)]
        public int BuildBandConfirmMoveTicks = 8;

        [InputParameter("Ownership Rails: Confirm Seconds", sortIndex: 956,
            minimum: 0, maximum: 60, increment: 1, decimalPlaces: 0)]
        public int BuildBandConfirmSec = 10;

        [InputParameter("Ownership Rails: Failure Buffer (ticks)", sortIndex: 957,
            minimum: 0, maximum: 40, increment: 1, decimalPlaces: 0)]
        public int BuildBandPriceThroughBufferTicks = 2;

        [InputParameter("Ownership Rails: Failure Confirm (ticks)", sortIndex: 958,
            minimum: 2, maximum: 120, increment: 1, decimalPlaces: 0)]
        public int BuildBandFailureConfirmTicks = 24;

        [InputParameter("Ownership Rails: Failure Seconds", sortIndex: 959,
            minimum: 0, maximum: 120, increment: 1, decimalPlaces: 0)]
        public int BuildBandFailureSec = 20;

        [InputParameter("Ownership Rails: Max Rails", sortIndex: 960,
            minimum: 2, maximum: 30, increment: 1, decimalPlaces: 0)]
        public int BuildBandMaxRails = 12;

        [InputParameter("Ownership Rails: Active Alpha", sortIndex: 961,
            minimum: 8, maximum: 160, increment: 2, decimalPlaces: 0)]
        public int BuildBandActiveAlpha = 46;

        [InputParameter("Ownership Rails: Failed Alpha", sortIndex: 962,
            minimum: 4, maximum: 100, increment: 1, decimalPlaces: 0)]
        public int BuildBandBreachedAlpha = 18;

        [InputParameter("Ownership Rails: Contested Alpha", sortIndex: 963,
            minimum: 4, maximum: 120, increment: 1, decimalPlaces: 0)]
        public int BuildBandContestedAlpha = 24;

        [InputParameter("Ownership Rails: Retention Minutes (0=session)", sortIndex: 964,
            minimum: 0, maximum: 480, increment: 5, decimalPlaces: 0)]
        public int BuildBandRetentionMinutes = 0;

        [InputParameter("Failure Zones: Enabled", sortIndex: 965)]
        public bool FailureZonesEnabled = true;

        [InputParameter("REV-FAIL: Enabled", sortIndex: 967)]
        public bool ReversalFailsEnabled = true;

        [InputParameter("REV-FAIL: Tail Range (ticks)", sortIndex: 968,
            minimum: 20, maximum: 400, increment: 10, decimalPlaces: 0)]
        public int ReversalFailTailTicks = 96;

        [InputParameter("REV-FAIL: Repair Move (ticks)", sortIndex: 969,
            minimum: 4, maximum: 120, increment: 1, decimalPlaces: 0)]
        public int ReversalFailRepairTicks = 24;

        [InputParameter("VOD Stacks: Enabled", sortIndex: 970)]
        public bool VodStacksEnabled = true;

        [InputParameter("VOD Stacks: VOD |z|", sortIndex: 971,
            minimum: 3.0, maximum: 12.0, increment: 0.25, decimalPlaces: 2)]
        public double VodStackVodZ = 4.0;

        [InputParameter("VOD Stacks: Edge |z|", sortIndex: 972,
            minimum: 1.5, maximum: 8.0, increment: 0.1, decimalPlaces: 2)]
        public double VodStackEdgeZ = 2.5;

        [InputParameter("VOD Stacks: Confirm Move (ticks)", sortIndex: 973,
            minimum: 4, maximum: 120, increment: 1, decimalPlaces: 0)]
        public int VodStackConfirmMoveTicks = 24;

        [InputParameter("VOD Stacks: Price-Through Buffer (ticks)", sortIndex: 974,
            minimum: 0, maximum: 40, increment: 1, decimalPlaces: 0)]
        public int VodStackPriceThroughBufferTicks = 2;

        [InputParameter("VOD Stacks: Retention Minutes (0=session)", sortIndex: 975,
            minimum: 0, maximum: 480, increment: 5, decimalPlaces: 0)]
        public int VodStackRetentionMinutes = 120;

        private LevelLedgerEngine _engine;
        private LevelLedgerPainter _painter;
        private GetDepthOfMarketParameters _domParams;
        private ConcurrentQueue<Last> _tradeQueue;
        private double _tickSize = 0.25;
        private bool _l2Subscribed;
        private bool _lastSubscribed;
        private bool _l2Stale;
        private DateTime _lastL2EventUtc = DateTime.MinValue;
        private DateTime _lastSampleUtc = DateTime.MinValue;
        private DateTime _lastTradeDropLogUtc = DateTime.MinValue;
        private int _queuedTradeCount;
        private long _tradeQueueDrops;
        private IChart _subscribedChart;

        public LevelLedger() : base()
        {
            this.Name = "Level Ledger";
            this.SeparateWindow = false;
        }

        public override IList<SettingItem> Settings
        {
            get
            {
                var settings = base.Settings;
                if (settings != null)
                {
                    var grpDetect = new SettingItemSeparatorGroup("Level Ledger - Detection", 900);
                    var grpRender = new SettingItemSeparatorGroup("Level Ledger - Panel", 920);
                    var grpOverlays = new SettingItemSeparatorGroup("Level Ledger - Chart Overlays", 940);
                    foreach (var item in settings)
                    {
                        if (item == null) continue;
                        if (item.SortIndex >= 900 && item.SortIndex < 920)
                            item.SeparatorGroup = grpDetect;
                        else if (item.SortIndex >= 920 && item.SortIndex < 940)
                            item.SeparatorGroup = grpRender;
                        else if (item.SortIndex >= 940 && item.SortIndex < 980)
                            item.SeparatorGroup = grpOverlays;
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
                _tradeQueue = new ConcurrentQueue<Last>();
                _queuedTradeCount = 0;
                _tradeQueueDrops = 0;
                _engine = new LevelLedgerEngine(
                    BookLookbackSeconds,
                    EventZThreshold,
                    SpatialDominanceRatio,
                    ActivationLookbackMinutes,
                    TradeBarSeconds,
                    TradeVolumeZ,
                    TradeDeltaRatio);
                _painter = new LevelLedgerPainter(_tickSize)
                {
                    PanelEnabled = PanelEnabled,
                    LeftOffsetPx = PanelLeftOffsetPx,
                    TopOffsetPx = PanelTopOffsetPx,
                    PanelWidthPx = PanelWidthPx,
                    VisibleRows = VisibleRows,
                    FontSize = (float)FontSize,
                    VodBuildDotsEnabled = VodBuildDotsEnabled,
                    VodBuildDotSizePx = VodBuildDotSizePx,
                    VodBuildDotAlpha = VodBuildDotAlpha,
                    BuildBandsEnabled = BuildBandsEnabled,
                    BuildBandActiveAlpha = BuildBandActiveAlpha,
                    BuildBandBreachedAlpha = BuildBandBreachedAlpha,
                    BuildBandContestedAlpha = BuildBandContestedAlpha,
                    VodStacksEnabled = VodStacksEnabled,
                };
                ApplyEngineConfig();
                ApplyPainterConfig();

                _domParams = new GetDepthOfMarketParameters
                {
                    GetLevel2ItemsParameters = new GetLevel2ItemsParameters
                    {
                        LevelsCount = 30,
                        CalculateCumulative = false,
                    },
                };

                this.Symbol.NewLast += Symbol_NewLast;
                _lastSubscribed = true;
                this.Symbol.NewLevel2 += Symbol_NewLevel2Heartbeat;
                _l2Subscribed = true;
            }
            catch (Exception ex)
            {
                Core.Instance.Loggers.Log(
                    $"[{nameof(LevelLedger)}] OnInit failed: {ex.Message}",
                    LoggingLevel.Error);
            }
        }

        private void Symbol_NewLast(Symbol symbol, Last last)
        {
            if (last == null) return;
            if (!double.IsFinite(last.Price) || last.Price <= 0) return;
            var queue = _tradeQueue;
            if (queue == null) return;
            if (Interlocked.Increment(ref _queuedTradeCount) > TradeQueueCap)
            {
                Interlocked.Decrement(ref _queuedTradeCount);
                long dropped = Interlocked.Increment(ref _tradeQueueDrops);
                MaybeLogTradeDrops(dropped);
                return;
            }
            queue.Enqueue(last);
        }

        private void Symbol_NewLevel2Heartbeat(Symbol symbol, Level2Quote l2, DOMQuote dom)
        {
            if (IsSyntheticLevel1Quote(l2)) return;
            _lastL2EventUtc = DateTime.UtcNow;
        }

        protected override void OnUpdate(UpdateArgs args)
        {
            if (_engine == null || this.Symbol == null) return;

            DrainTrades();

            var now = DateTime.UtcNow;
            if ((now - _lastSampleUtc).TotalMilliseconds < SampleIntervalMs)
                return;
            _lastSampleUtc = now;

            try
            {
                bool fresh = _lastL2EventUtc != DateTime.MinValue
                          && (now - _lastL2EventUtc).TotalSeconds <= BookFreshnessSec;
                _l2Stale = !fresh;
                if (_l2Stale) return;

                if (!TryGetDomSnapshot(out var dom, out bool transientDomRace))
                {
                    if (transientDomRace) return;
                    _l2Stale = true;
                    return;
                }

                if (dom == null
                    || (dom.Bids == null || dom.Bids.Length == 0)
                    && (dom.Asks == null || dom.Asks.Length == 0))
                {
                    _l2Stale = true;
                    return;
                }

                if (!L1Agrees(dom, _tickSize))
                {
                    _l2Stale = true;
                    return;
                }

                ApplyEngineConfig();
                _engine.OnBookSample(now, dom, _tickSize);
            }
            catch (Exception ex)
            {
                Core.Instance.Loggers.Log(
                    $"[{nameof(LevelLedger)}] sample failed: {ex.Message}",
                    LoggingLevel.Error);
            }
        }

        private bool TryGetDomSnapshot(out DepthOfMarketAggregatedCollections dom, out bool transientDomRace)
        {
            dom = null;
            transientDomRace = false;
            try
            {
                dom = this.Symbol.DepthOfMarket?
                    .GetDepthOfMarketAggregatedCollections(_domParams);
                return true;
            }
            catch (InvalidOperationException ex) when (IsCollectionModifiedRace(ex))
            {
                transientDomRace = true;
                return false;
            }
        }

        private void DrainTrades()
        {
            if (_tradeQueue == null || _engine == null) return;
            while (_tradeQueue.TryDequeue(out var last))
            {
                Interlocked.Decrement(ref _queuedTradeCount);
                try
                {
                    var t = NormalizeUtc(last.Time);
                    int sign = AggressorSign(last.AggressorFlag);
                    _engine.OnTrade(t, last.Price, last.Size, sign, _tickSize);
                }
                catch
                {
                    // One bad print should not stop the ledger.
                }
            }
        }

        public override void OnPaintChart(PaintChartEventArgs args)
        {
            try
            {
                IChart chart = null;
                if (_subscribedChart == null)
                {
                    chart = this.CurrentChart;
                    if (chart != null)
                    {
                        chart.MouseClick += Chart_MouseClick;
                        _subscribedChart = chart;
                    }
                }
                else
                {
                    chart = _subscribedChart;
                }

                if (_painter != null && _engine != null)
                {
                    ApplyPainterConfig();
                    _painter.L2Stale = _l2Stale;

                    var now = DateTime.UtcNow;
                    _painter.Paint(
                        args,
                        chart,
                        _engine.GetSnapshot(Math.Max(1, VisibleRows), now),
                        _engine.GetVodBuildDots(now),
                        _engine.GetBuildBands(now),
                        _engine.GetVodStacks(now));
                }
            }
            catch (Exception ex)
            {
                try
                {
                    Core.Instance.Loggers.Log(
                        $"[{nameof(LevelLedger)}] paint failed: {ex.Message}",
                        LoggingLevel.Error);
                }
                catch { }
            }
        }

        private void ApplyEngineConfig()
        {
            if (_engine == null) return;
            _engine.UpdateConfig(
                BookLookbackSeconds,
                EventZThreshold,
                SpatialDominanceRatio,
                ActivationLookbackMinutes,
                TradeBarSeconds,
                TradeVolumeZ,
                TradeDeltaRatio);
            _engine.ChartVodBuildVodZ = VodBuildDotVodZ;
            _engine.ChartVodBuildBuildZ = VodBuildDotBuildZ;
            _engine.ChartVodBuildRetentionMinutes = VodBuildDotRetentionMinutes;
            _engine.ChartBuildBandBuildZ = BuildBandBuildZ;
            _engine.ChartBuildBandClusterN = BuildBandClusterN;
            _engine.ChartBuildBandClusterTicks = BuildBandClusterTicks;
            _engine.ChartBuildBandClusterSec = BuildBandClusterSec;
            _engine.ChartBuildBandConfirmMoveTicks = BuildBandConfirmMoveTicks;
            _engine.ChartBuildBandConfirmSec = BuildBandConfirmSec;
            _engine.ChartBuildBandPriceThroughBufferTicks = BuildBandPriceThroughBufferTicks;
            _engine.ChartBuildBandFailureConfirmTicks = BuildBandFailureConfirmTicks;
            _engine.ChartBuildBandFailureSec = BuildBandFailureSec;
            _engine.ChartBuildBandMaxRails = BuildBandMaxRails;
            _engine.ChartBuildBandRetentionMinutes = BuildBandRetentionMinutes;
            _engine.OwnershipRowsEnabled = PanelOwnershipEvents;
            _engine.ChartFailureZonesEnabled = FailureZonesEnabled;
            _engine.ChartReversalFailsEnabled = ReversalFailsEnabled;
            _engine.ChartReversalFailExtremeTicks = ReversalFailTailTicks;
            _engine.ChartReversalFailRepairTicks = ReversalFailRepairTicks;
            _engine.ChartVodStackVodZ = VodStackVodZ;
            _engine.ChartVodStackEdgeZ = VodStackEdgeZ;
            _engine.ChartVodStackConfirmMoveTicks = VodStackConfirmMoveTicks;
            _engine.ChartVodStackPriceThroughBufferTicks = VodStackPriceThroughBufferTicks;
            _engine.ChartVodStackRetentionMinutes = VodStackRetentionMinutes;
        }

        private void ApplyPainterConfig()
        {
            if (_painter == null) return;
            _painter.PanelEnabled = PanelEnabled;
            _painter.LeftOffsetPx = PanelLeftOffsetPx;
            _painter.TopOffsetPx = PanelTopOffsetPx;
            _painter.PanelWidthPx = PanelWidthPx;
            _painter.VisibleRows = VisibleRows;
            _painter.FontSize = (float)FontSize;
            _painter.VodBuildDotsEnabled = VodBuildDotsEnabled;
            _painter.VodBuildDotSizePx = VodBuildDotSizePx;
            _painter.VodBuildDotAlpha = VodBuildDotAlpha;
            _painter.BuildBandsEnabled = BuildBandsEnabled;
            _painter.BuildBandActiveAlpha = BuildBandActiveAlpha;
            _painter.BuildBandBreachedAlpha = BuildBandBreachedAlpha;
            _painter.BuildBandContestedAlpha = BuildBandContestedAlpha;
            _painter.VodStacksEnabled = VodStacksEnabled;
        }

        protected override void OnSettingsUpdated()
        {
            try
            {
                // Base Indicator.OnSettingsUpdated calls Refresh(), which clears forward-only ledger state.
                ApplyEngineConfig();
                ApplyPainterConfig();
                CurrentChart?.RedrawBuffer();
            }
            catch (Exception ex)
            {
                try
                {
                    Core.Instance.Loggers.Log(
                        $"[{nameof(LevelLedger)}] settings update failed: {ex.Message}",
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
            if (e.Y < hit.Top || e.Y > hit.Bottom) return;

            if (e.Button == NativeMouseButtons.Left)
            {
                _engine.Activate(DateTime.UtcNow);
                e.NeedRedraw = true;
                e.Handled = true;
            }
            else if (e.Button == NativeMouseButtons.Right)
            {
                _engine.Deactivate();
                e.NeedRedraw = true;
                e.Handled = true;
            }
        }

        protected override void OnClear()
        {
            try
            {
                if (_lastSubscribed && this.Symbol != null)
                {
                    try { this.Symbol.NewLast -= Symbol_NewLast; } catch { }
                    _lastSubscribed = false;
                }
                if (_l2Subscribed && this.Symbol != null)
                {
                    try { this.Symbol.NewLevel2 -= Symbol_NewLevel2Heartbeat; } catch { }
                    _l2Subscribed = false;
                }
                if (_subscribedChart != null)
                {
                    try { _subscribedChart.MouseClick -= Chart_MouseClick; } catch { }
                    _subscribedChart = null;
                }
                _tradeQueue = null;
                _queuedTradeCount = 0;
                _engine = null;
                _painter = null;
                _domParams = null;
            }
            catch { }
        }

        private void MaybeLogTradeDrops(long dropped)
        {
            DateTime now = DateTime.UtcNow;
            if (_lastTradeDropLogUtc != DateTime.MinValue
                && (now - _lastTradeDropLogUtc).TotalSeconds < 30)
                return;
            _lastTradeDropLogUtc = now;
            try
            {
                Core.Instance.Loggers.Log(
                    $"[{nameof(LevelLedger)}] trade queue overloaded; dropped_total={dropped} cap={TradeQueueCap}",
                    LoggingLevel.Error);
            }
            catch { }
        }

        private static DateTime NormalizeUtc(DateTime t)
        {
            if (t == default) return DateTime.UtcNow;
            if (t.Kind == DateTimeKind.Utc) return t;
            if (t.Kind == DateTimeKind.Local) return t.ToUniversalTime();
            return DateTime.SpecifyKind(t, DateTimeKind.Utc);
        }

        private static int AggressorSign(AggressorFlag flag)
        {
            switch (flag)
            {
                case AggressorFlag.Buy: return 1;
                case AggressorFlag.Sell: return -1;
                default: return 0;
            }
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

        private static bool IsSyntheticLevel1Quote(Level2Quote l2)
        {
            if (l2 == null) return false;
            if (string.Equals(l2.Id, "generated_from_level1", StringComparison.OrdinalIgnoreCase))
                return true;
            return !double.IsFinite(l2.Price) || !double.IsFinite(l2.Size);
        }

        private static bool IsCollectionModifiedRace(Exception ex)
        {
            return ex.Message != null
                && ex.Message.IndexOf("Collection was modified", StringComparison.OrdinalIgnoreCase) >= 0;
        }

        private bool L1Agrees(DepthOfMarketAggregatedCollections dom, double tickSize)
        {
            double symBid = this.Symbol.Bid;
            double symAsk = this.Symbol.Ask;
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
    }
}
