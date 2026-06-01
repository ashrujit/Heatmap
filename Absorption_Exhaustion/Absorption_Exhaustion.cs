using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.Threading;
using TradingPlatform.BusinessLayer;

namespace Absorption_Exhaustion
{
    public class Absorption_Exhaustion : Indicator
    {
        private const string IndicatorVersion = "0.1.0";
        private const int TradeQueueCap = 50000;

        // ── Bar/baseline ────────────────────────────────────────────────────
        [InputParameter("Bar Seconds", sortIndex: 800,
            minimum: 1, maximum: 30, increment: 1, decimalPlaces: 0)]
        public int BarSeconds = 5;

        [InputParameter("Lookback Seconds (rolling baseline)", sortIndex: 801,
            minimum: 15, maximum: 600, increment: 5, decimalPlaces: 0)]
        public int LookbackSeconds = 60;

        // ── A1: Stacked imbalance ───────────────────────────────────────────
        [InputParameter("A1 Stacked Levels (consecutive)", sortIndex: 810,
            minimum: 2, maximum: 6, increment: 1, decimalPlaces: 0)]
        public int A1StackedN = 3;

        [InputParameter("A1 Imbalance Threshold", sortIndex: 811,
            minimum: 0.3, maximum: 0.95, increment: 0.05, decimalPlaces: 2)]
        public double A1Imb = 0.5;

        [InputParameter("A1 Min Volume Per Level", sortIndex: 812,
            minimum: 1, maximum: 100, increment: 1, decimalPlaces: 0)]
        public int A1MinVolPerLevel = 10;

        // ── A2: Balanced absorbing bar ──────────────────────────────────────
        [InputParameter("A2 Volume Z-Score Threshold", sortIndex: 820,
            minimum: 1.0, maximum: 8.0, increment: 0.5, decimalPlaces: 1)]
        public double A2VolZ = 3.0;

        [InputParameter("A2 |Delta|/Volume Max", sortIndex: 821,
            minimum: 0.02, maximum: 0.30, increment: 0.01, decimalPlaces: 2)]
        public double A2DeltaRatio = 0.10;

        // ── E1: Single-print at extreme ─────────────────────────────────────
        [InputParameter("E1 Max Vol At Extreme (thin)", sortIndex: 830,
            minimum: 1, maximum: 20, increment: 1, decimalPlaces: 0)]
        public int E1ThinMaxVol = 3;

        [InputParameter("E1 Min Neighbor Volume", sortIndex: 831,
            minimum: 5, maximum: 200, increment: 5, decimalPlaces: 0)]
        public int E1NeighborMinVol = 30;

        [InputParameter("E1 Neighbor Imbalance Threshold", sortIndex: 832,
            minimum: 0.3, maximum: 0.95, increment: 0.05, decimalPlaces: 2)]
        public double E1NeighborMinImb = 0.5;

        // ── E2: Weak-delta extreme ──────────────────────────────────────────
        [InputParameter("E2 |Delta|/Volume Max", sortIndex: 840,
            minimum: 0.02, maximum: 0.40, increment: 0.01, decimalPlaces: 2)]
        public double E2WeakDelta = 0.15;

        // ── Self-clearing & rendering ───────────────────────────────────────
        [InputParameter("Clear K Ticks (band invalidation distance)", sortIndex: 850,
            minimum: 0, maximum: 20, increment: 1, decimalPlaces: 0)]
        public int ClearKTicks = 2;

        [InputParameter("Cleared Fade Seconds", sortIndex: 851,
            minimum: 1, maximum: 20, increment: 1, decimalPlaces: 0)]
        public int ClearedFadeSec = 3;

        [InputParameter("Glyph Retention Seconds", sortIndex: 852,
            minimum: 1, maximum: 60, increment: 1, decimalPlaces: 0)]
        public int GlyphRetentionSec = 8;

        [InputParameter("Band Count → Full Alpha", sortIndex: 853,
            minimum: 1, maximum: 20, increment: 1, decimalPlaces: 0)]
        public int BandFullAlphaCount = 5;

        // ── Internal state ──────────────────────────────────────────────────
        private TradeBuffer _buffer;
        private PrimitiveDetector _detector;
        private PriceBandRegistry _registry;
        private ChartPainter _painter;
        private DetectorParams _params;
        private ConcurrentQueue<Last> _queue;
        private bool _subscribed;
        private double _lastPrice = double.NaN;
        private DateTime _lastTradeTime = DateTime.MinValue;
        private int _queuedTradeCount;
        private long _queueDrops;
        private DateTime _lastQueueDropLogUtc = DateTime.MinValue;

        public Absorption_Exhaustion() : base()
        {
            this.Name = "Absorption / Exhaustion";
            this.SeparateWindow = false;
        }

        public override IList<SettingItem> Settings
        {
            get
            {
                var settings = base.Settings;
                if (settings != null)
                {
                    var grpBar = new SettingItemSeparatorGroup("A/E — Bar & Baseline", 800);
                    var grpA1 = new SettingItemSeparatorGroup("A/E — A1 Stacked Imbalance", 810);
                    var grpA2 = new SettingItemSeparatorGroup("A/E — A2 Balanced Absorbing", 820);
                    var grpE1 = new SettingItemSeparatorGroup("A/E — E1 Single Print", 830);
                    var grpE2 = new SettingItemSeparatorGroup("A/E — E2 Weak Delta", 840);
                    var grpRen = new SettingItemSeparatorGroup("A/E — Clearing & Render", 850);
                    foreach (var item in settings)
                    {
                        if (item == null) continue;
                        int s = item.SortIndex;
                        if (s >= 800 && s < 810) item.SeparatorGroup = grpBar;
                        else if (s >= 810 && s < 820) item.SeparatorGroup = grpA1;
                        else if (s >= 820 && s < 830) item.SeparatorGroup = grpA2;
                        else if (s >= 830 && s < 840) item.SeparatorGroup = grpE1;
                        else if (s >= 840 && s < 850) item.SeparatorGroup = grpE2;
                        else if (s >= 850 && s < 860) item.SeparatorGroup = grpRen;
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

                _buffer = new TradeBuffer(tickSize, BarSeconds, LookbackSeconds);
                _params = new DetectorParams
                {
                    StackedN = A1StackedN,
                    StackedImb = A1Imb,
                    StackedMinVolPerLevel = A1MinVolPerLevel,
                    BalancedVolZ = A2VolZ,
                    BalancedDeltaRatio = A2DeltaRatio,
                    ThinExtremeMaxVol = E1ThinMaxVol,
                    ThinNeighborMinVol = E1NeighborMinVol,
                    ThinNeighborMinImb = E1NeighborMinImb,
                    WeakDeltaRatio = E2WeakDelta,
                };
                _detector = new PrimitiveDetector(_buffer, _params);
                _registry = new PriceBandRegistry(ClearKTicks, ClearedFadeSec, GlyphRetentionSec);
                _painter = new ChartPainter(tickSize)
                {
                    BandMaxCountForFullAlpha = BandFullAlphaCount,
                    GlyphFadeSec = GlyphRetentionSec,
                    ClearedFadeSec = ClearedFadeSec,
                };
                _queue = new ConcurrentQueue<Last>();
                _queuedTradeCount = 0;
                _queueDrops = 0;

                this.Symbol.NewLast += Symbol_NewLast;
                _subscribed = true;
            }
            catch (Exception ex)
            {
                Core.Instance.Loggers.Log(
                    $"[{nameof(Absorption_Exhaustion)}] OnInit failed: {ex.Message}",
                    LoggingLevel.Error);
            }
        }

        private void Symbol_NewLast(Symbol symbol, Last last)
        {
            if (last == null) return;
            if (double.IsNaN(last.Price) || last.Price <= 0) return;
            var queue = _queue;
            if (queue == null) return;
            if (Interlocked.Increment(ref _queuedTradeCount) > TradeQueueCap)
            {
                Interlocked.Decrement(ref _queuedTradeCount);
                Interlocked.Increment(ref _queueDrops);
                MaybeLogTradeQueueDrops();
                return;
            }
            queue.Enqueue(last);
        }

        private void MaybeLogTradeQueueDrops()
        {
            var now = DateTime.UtcNow;
            if ((now - _lastQueueDropLogUtc).TotalSeconds < 30) return;
            _lastQueueDropLogUtc = now;
            long drops = Interlocked.Read(ref _queueDrops);
            try
            {
                Core.Instance.Loggers.Log(
                    $"[{nameof(Absorption_Exhaustion)}] trade queue overloaded; dropped {drops} prints (cap={TradeQueueCap})",
                    LoggingLevel.Error);
            }
            catch { }
        }

        protected override void OnUpdate(UpdateArgs args)
        {
            DrainTrades();
            // Even with no new trades, close stale bars and re-evaluate clearing
            // against last known price (handles quiet stretches).
            if (_buffer != null && !double.IsNaN(_lastPrice))
            {
                var nowUtc = DateTime.UtcNow;
                var stale = _buffer.TryCloseStaleBar(nowUtc);
                if (stale != null) RunDetectors(stale);
                _registry?.OnPriceUpdate(_buffer.PriceToTicks(_lastPrice), nowUtc);
            }
        }

        private void DrainTrades()
        {
            if (_queue == null || _buffer == null) return;
            while (_queue.TryDequeue(out var last))
            {
                Interlocked.Decrement(ref _queuedTradeCount);
                try
                {
                    int sign = AggressorSign(last.AggressorFlag);
                    var t = last.Time;
                    if (t == default) t = DateTime.UtcNow;
                    var closed = _buffer.OnTrade(t, last.Price, last.Size, sign);
                    if (closed != null) RunDetectors(closed);
                    _lastPrice = last.Price;
                    _lastTradeTime = t;
                    _registry?.OnPriceUpdate(_buffer.PriceToTicks(last.Price), t);
                }
                catch
                {
                    // One bad print shouldn't kill the drain.
                }
            }
        }

        private void RunDetectors(TradeBuffer.Bar closed)
        {
            if (_detector == null || _registry == null) return;
            foreach (var fire in _detector.EvaluateClosedBar(closed))
                _registry.OnFire(fire);
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

        public override void OnPaintChart(PaintChartEventArgs args)
        {
            try
            {
                if (_painter != null && _registry != null && this.CurrentChart != null)
                    _painter.Paint(args, this.CurrentChart, _registry, DateTime.UtcNow);
            }
            catch (Exception ex)
            {
                try
                {
                    Core.Instance.Loggers.Log(
                        $"[{nameof(Absorption_Exhaustion)}] paint failed: {ex.Message}",
                        LoggingLevel.Error);
                }
                catch { }
            }
        }

        protected override void OnClear()
        {
            try
            {
                if (_subscribed && this.Symbol != null)
                {
                    try { this.Symbol.NewLast -= Symbol_NewLast; } catch { }
                    _subscribed = false;
                }
                _registry?.Clear();
                _registry = null;
                _painter = null;
                _detector = null;
                _buffer = null;
                _queue = null;
                _queuedTradeCount = 0;
            }
            catch { }
        }
    }
}
