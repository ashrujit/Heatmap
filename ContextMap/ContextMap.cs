using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using TradingPlatform.BusinessLayer;
using TradingPlatform.BusinessLayer.Chart;

namespace ContextMap
{
    public class ContextMap : Indicator
    {
        private const int L1ToleranceTicks = 2;

        [InputParameter("Sample Interval (ms)", sortIndex: 1000,
            minimum: 250, maximum: 5000, increment: 250, decimalPlaces: 0)]
        public int SampleIntervalMs = 1000;

        [InputParameter("Book Lookback Seconds", sortIndex: 1001,
            minimum: 10, maximum: 300, increment: 5, decimalPlaces: 0)]
        public int BookLookbackSeconds = 30;

        [InputParameter("L2 Event Z Threshold", sortIndex: 1002,
            minimum: 1.5, maximum: 5.0, increment: 0.1, decimalPlaces: 2)]
        public double EventZThreshold = 2.5;

        [InputParameter("Book Freshness (sec)", sortIndex: 1003,
            minimum: 1, maximum: 60, increment: 1, decimalPlaces: 0)]
        public int BookFreshnessSec = 5;

        [InputParameter("ON Start HHmm", sortIndex: 1010,
            minimum: 0, maximum: 2359, increment: 1, decimalPlaces: 0)]
        public int OnStartHHmm = 1800;

        [InputParameter("RTH Start HHmm", sortIndex: 1011,
            minimum: 0, maximum: 2359, increment: 1, decimalPlaces: 0)]
        public int RthStartHHmm = 930;

        [InputParameter("Bracket Ready HHmm", sortIndex: 1012,
            minimum: 0, maximum: 2359, increment: 1, decimalPlaces: 0)]
        public int BracketReadyHHmm = 945;

        [InputParameter("Update Cutoff HHmm", sortIndex: 1013,
            minimum: 0, maximum: 2359, increment: 1, decimalPlaces: 0)]
        public int UpdateCutoffHHmm = 1230;

        [InputParameter("Rail Bin Ticks", sortIndex: 1020,
            minimum: 4, maximum: 80, increment: 1, decimalPlaces: 0)]
        public int RailBinTicks = 16;

        [InputParameter("Rail Count Each Side", sortIndex: 1021,
            minimum: 1, maximum: 8, increment: 1, decimalPlaces: 0)]
        public int RailCountEachSide = 4;

        [InputParameter("Rail Min Dominant Weight", sortIndex: 1022,
            minimum: 4.0, maximum: 120.0, increment: 1.0, decimalPlaces: 1)]
        public double RailMinDominantWeight = 10.0;

        [InputParameter("Rail Dominance Ratio", sortIndex: 1023,
            minimum: 1.0, maximum: 8.0, increment: 0.1, decimalPlaces: 1)]
        public double RailDominanceRatio = 1.25;

        [InputParameter("Break Buffer Ticks", sortIndex: 1024,
            minimum: 0, maximum: 40, increment: 1, decimalPlaces: 0)]
        public int BreakBufferTicks = 4;

        [InputParameter("Bands Enabled", sortIndex: 1040)]
        public bool BandsEnabled = true;

        [InputParameter("Band Active Alpha", sortIndex: 1041,
            minimum: 4, maximum: 160, increment: 2, decimalPlaces: 0)]
        public int BandActiveAlpha = 38;

        [InputParameter("Band Faded Alpha", sortIndex: 1042,
            minimum: 2, maximum: 100, increment: 1, decimalPlaces: 0)]
        public int BandFadedAlpha = 14;

        [InputParameter("Panel Enabled", sortIndex: 1050)]
        public bool PanelEnabled = true;

        [InputParameter("Panel Left Offset (px)", sortIndex: 1051,
            minimum: 0, maximum: 3000, increment: 5, decimalPlaces: 0)]
        public int PanelLeftOffsetPx = 90;

        [InputParameter("Panel Top Offset (px)", sortIndex: 1052,
            minimum: 0, maximum: 2000, increment: 5, decimalPlaces: 0)]
        public int PanelTopOffsetPx = 90;

        [InputParameter("Panel Width (px)", sortIndex: 1053,
            minimum: 260, maximum: 900, increment: 10, decimalPlaces: 0)]
        public int PanelWidthPx = 470;

        [InputParameter("Font Size", sortIndex: 1054,
            minimum: 7, maximum: 24, increment: 0.5, decimalPlaces: 1)]
        public double FontSize = 10.0;

        private ContextEngine _engine;
        private ContextPainter _painter;
        private GetDepthOfMarketParameters _domParams;
        private ConcurrentQueue<Last> _tradeQueue;
        private double _tickSize = 0.25;
        private bool _l2Subscribed;
        private bool _lastSubscribed;
        private bool _l2Stale = true;
        private DateTime _lastL2EventUtc = DateTime.MinValue;
        private DateTime _lastSampleUtc = DateTime.MinValue;

        public ContextMap() : base()
        {
            this.Name = "Context Map";
            this.SeparateWindow = false;
        }

        public override IList<SettingItem> Settings
        {
            get
            {
                var settings = base.Settings;
                if (settings != null)
                {
                    var detect = new SettingItemSeparatorGroup("Context Map - Detection", 1000);
                    var session = new SettingItemSeparatorGroup("Context Map - Session", 1010);
                    var rails = new SettingItemSeparatorGroup("Context Map - Rails", 1020);
                    var render = new SettingItemSeparatorGroup("Context Map - Render", 1040);
                    foreach (var item in settings)
                    {
                        if (item == null) continue;
                        if (item.SortIndex >= 1000 && item.SortIndex < 1010)
                            item.SeparatorGroup = detect;
                        else if (item.SortIndex >= 1010 && item.SortIndex < 1020)
                            item.SeparatorGroup = session;
                        else if (item.SortIndex >= 1020 && item.SortIndex < 1040)
                            item.SeparatorGroup = rails;
                        else if (item.SortIndex >= 1040 && item.SortIndex < 1070)
                            item.SeparatorGroup = render;
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
                _engine = new ContextEngine(_tickSize);
                _painter = new ContextPainter(_tickSize);
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
                Core.Instance.Loggers.Log($"[{nameof(ContextMap)}] OnInit failed: {ex.Message}", LoggingLevel.Error);
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

                var dom = this.Symbol.DepthOfMarket?.GetDepthOfMarketAggregatedCollections(_domParams);
                if (dom == null
                    || ((dom.Bids == null || dom.Bids.Length == 0)
                        && (dom.Asks == null || dom.Asks.Length == 0)))
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
                _engine.OnBookSample(now, dom);
            }
            catch (Exception ex)
            {
                Core.Instance.Loggers.Log($"[{nameof(ContextMap)}] sample failed: {ex.Message}", LoggingLevel.Error);
            }
        }

        public override void OnPaintChart(PaintChartEventArgs args)
        {
            try
            {
                if (_painter == null || _engine == null) return;
                _painter.BandsEnabled = BandsEnabled;
                _painter.BandActiveAlpha = BandActiveAlpha;
                _painter.BandFadedAlpha = BandFadedAlpha;
                _painter.PanelEnabled = PanelEnabled;
                _painter.LeftOffsetPx = PanelLeftOffsetPx;
                _painter.TopOffsetPx = PanelTopOffsetPx;
                _painter.PanelWidthPx = PanelWidthPx;
                _painter.FontSize = (float)FontSize;
                _painter.L2Stale = _l2Stale;

                _painter.Paint(args, this.CurrentChart, _engine.GetSnapshot(DateTime.UtcNow));
            }
            catch (Exception ex)
            {
                try { Core.Instance.Loggers.Log($"[{nameof(ContextMap)}] paint failed: {ex.Message}", LoggingLevel.Error); }
                catch { }
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
                _tradeQueue = null;
                _engine = null;
                _painter = null;
                _domParams = null;
            }
            catch { }
        }

        private void ApplyEngineConfig()
        {
            _engine.BookLookbackSec = BookLookbackSeconds;
            _engine.EventZThreshold = EventZThreshold;
            _engine.OnStartHHmm = OnStartHHmm;
            _engine.RthStartHHmm = RthStartHHmm;
            _engine.BracketReadyHHmm = BracketReadyHHmm;
            _engine.UpdateCutoffHHmm = UpdateCutoffHHmm;
            _engine.RailBinTicks = RailBinTicks;
            _engine.RailCountEachSide = RailCountEachSide;
            _engine.RailMinDominantWeight = RailMinDominantWeight;
            _engine.RailDominanceRatio = RailDominanceRatio;
            _engine.BreakBufferTicks = BreakBufferTicks;
        }

        private void DrainTrades()
        {
            if (_tradeQueue == null || _engine == null) return;
            ApplyEngineConfig();
            while (_tradeQueue.TryDequeue(out var last))
            {
                try
                {
                    _engine.OnTrade(NormalizeUtc(last.Time), last.Price, last.Size, AggressorSign(last.AggressorFlag));
                }
                catch { }
            }
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
                if (double.IsFinite(p) && p > 0 && double.IsFinite(s) && s > 0)
                    return p;
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
