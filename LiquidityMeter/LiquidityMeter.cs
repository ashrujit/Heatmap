using System;
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

        // Feed-paused detector. Book is read from QT's DepthOfMarket each
        // sample, so orphan-level corruption can't accumulate. The only
        // remaining stale mode is feed-paused: no L2 events arriving. Above
        // this threshold, sampling pauses and the painter shows a STALE badge.
        [InputParameter("Book Freshness (sec, no-L2-update threshold)", sortIndex: 906,
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

        // L1 sanity gate. DOM should already agree with Symbol.Bid/Ask, but
        // paranoia: if best-of-side from DOM diverges by more than this many
        // ticks, treat as stale. 2 ticks tolerates the natural in-flight
        // skew between QT's L1 cache and DOM aggregation.
        private const int L1ToleranceTicks = 2;

        // ── Internal state ──────────────────────────────────────────────────
        private MeterEngine _engine;
        private MeterPainter _painter;
        private GetDepthOfMarketParameters _domParams;
        private double _tickSize = 0.25;
        private bool _l2Subscribed;
        private DateTime _lastL2EventUtc = DateTime.MinValue;
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
                _tickSize = this.Symbol.TickSize > 0 ? this.Symbol.TickSize : 0.25;

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

                _domParams = new GetDepthOfMarketParameters
                {
                    GetLevel2ItemsParameters = new GetLevel2ItemsParameters
                    {
                        LevelsCount = 30,           // engine uses ≤30 each side
                        CalculateCumulative = false,
                    },
                };

                // We don't process L2 events ourselves anymore — QT's
                // DepthOfMarket eats them and we read the canonical book each
                // sample. NewLevel2 subscription stays only as a heartbeat for
                // IsFresh / STALE-badge logic. See RESEARCH_LOG 2026-05-08.
                this.Symbol.NewLevel2 += Symbol_NewLevel2Heartbeat;
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

        // Heartbeat-only handler. We don't apply L2 deltas ourselves anymore;
        // QT's DepthOfMarket maintains the canonical book and we read from it
        // each sample. This subscription exists to (a) mark the indicator as
        // an L2 consumer so QT keeps the L2 stream live, and (b) timestamp
        // the most recent L2 event for the IsFresh feed-paused detector.
        private void Symbol_NewLevel2Heartbeat(Symbol symbol, Level2Quote l2, DOMQuote dom)
        {
            if (IsSyntheticLevel1Quote(l2)) return;
            _lastL2EventUtc = DateTime.UtcNow;
        }

        private static bool IsSyntheticLevel1Quote(Level2Quote l2)
        {
            if (l2 == null) return false;
            if (string.Equals(l2.Id, "generated_from_level1", StringComparison.OrdinalIgnoreCase))
                return true;
            return !double.IsFinite(l2.Price) || !double.IsFinite(l2.Size);
        }

        protected override void OnUpdate(UpdateArgs args)
        {
            if (_engine == null || this.Symbol == null) return;

            var now = DateTime.UtcNow;
            if ((now - _lastSampleUtc).TotalMilliseconds >= SampleIntervalMs)
            {
                _lastSampleUtc = now;
                try
                {
                    // Freshness gate. With BookState replaced by DepthOfMarket
                    // reads, orphan-level corruption is structurally impossible
                    // — the only remaining stale mode is "feed paused" (no L2
                    // events arriving). When stale, freeze: skip OnSample so
                    // cum/ROC stop updating; painter shows STALE badge.
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

                    // L1 sanity gate. DOM is canonical, but pause if its best
                    // diverges from Symbol.Bid/Ask by more than tolerance.
                    if (!L1Agrees(dom, _tickSize))
                    {
                        _l2Stale = true;
                        return;
                    }

                    _engine.OnSample(now, dom, _tickSize);
                }
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
                    try { this.Symbol.NewLevel2 -= Symbol_NewLevel2Heartbeat; } catch { }
                    _l2Subscribed = false;
                }
                if (_subscribedChart != null)
                {
                    try { _subscribedChart.MouseClick -= Chart_MouseClick; } catch { }
                    _subscribedChart = null;
                }
                _painter = null;
                _engine = null;
                _domParams = null;
                _manualAnchorUtc = null;
            }
            catch { }
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
