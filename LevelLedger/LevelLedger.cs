using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using TradingPlatform.BusinessLayer;
using TradingPlatform.BusinessLayer.Chart;
using TradingPlatform.BusinessLayer.Native;

namespace LevelLedger
{
    public class LevelLedger : Indicator
    {
        private const string IndicatorVersion = "0.2.0";
        private const int L1ToleranceTicks = 2;

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
        [InputParameter("Panel Left Offset (px)", sortIndex: 920,
            minimum: 0, maximum: 2000, increment: 5, decimalPlaces: 0)]
        public int PanelLeftOffsetPx = 90;

        [InputParameter("Panel Top Offset (px)", sortIndex: 921,
            minimum: 0, maximum: 1500, increment: 5, decimalPlaces: 0)]
        public int PanelTopOffsetPx = 90;

        [InputParameter("Panel Width (px)", sortIndex: 922,
            minimum: 180, maximum: 520, increment: 10, decimalPlaces: 0)]
        public int PanelWidthPx = 300;

        [InputParameter("Visible Rows", sortIndex: 923,
            minimum: 4, maximum: 12, increment: 1, decimalPlaces: 0)]
        public int VisibleRows = 10;

        [InputParameter("Font Size", sortIndex: 924,
            minimum: 7, maximum: 14, increment: 0.5, decimalPlaces: 1)]
        public double FontSize = 9.0;

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
                    var grpRender = new SettingItemSeparatorGroup("Level Ledger - Render", 920);
                    foreach (var item in settings)
                    {
                        if (item == null) continue;
                        if (item.SortIndex >= 900 && item.SortIndex < 920)
                            item.SeparatorGroup = grpDetect;
                        else if (item.SortIndex >= 920 && item.SortIndex < 940)
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

                _tickSize = this.Symbol.TickSize > 0 ? this.Symbol.TickSize : 0.25;
                _tradeQueue = new ConcurrentQueue<Last>();
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
                    LeftOffsetPx = PanelLeftOffsetPx,
                    TopOffsetPx = PanelTopOffsetPx,
                    PanelWidthPx = PanelWidthPx,
                    VisibleRows = VisibleRows,
                    FontSize = (float)FontSize,
                };

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
            _tradeQueue?.Enqueue(last);
        }

        private void Symbol_NewLevel2Heartbeat(Symbol symbol, Level2Quote l2, DOMQuote dom)
        {
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

                var dom = this.Symbol.DepthOfMarket?
                              .GetDepthOfMarketAggregatedCollections(_domParams);
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

                _engine.OnBookSample(now, dom, _tickSize);
            }
            catch (Exception ex)
            {
                Core.Instance.Loggers.Log(
                    $"[{nameof(LevelLedger)}] sample failed: {ex.Message}",
                    LoggingLevel.Error);
            }
        }

        private void DrainTrades()
        {
            if (_tradeQueue == null || _engine == null) return;
            while (_tradeQueue.TryDequeue(out var last))
            {
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
                    _painter.LeftOffsetPx = PanelLeftOffsetPx;
                    _painter.TopOffsetPx = PanelTopOffsetPx;
                    _painter.PanelWidthPx = PanelWidthPx;
                    _painter.VisibleRows = VisibleRows;
                    _painter.FontSize = (float)FontSize;
                    _painter.L2Stale = _l2Stale;
                    _painter.Paint(args, _engine.GetSnapshot(Math.Max(1, VisibleRows), DateTime.UtcNow));
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
                _engine = null;
                _painter = null;
                _domParams = null;
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
