using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using TradingPlatform.BusinessLayer;

namespace L2_Surface
{
    public class L2_Surface : Indicator
    {
        private const string IndicatorVersion = "0.1.0";

        // ── Common (sortIndex 800-803) ──────────────────────────────────────
        [InputParameter("Lookback Seconds (rolling baseline)", sortIndex: 800,
            minimum: 10, maximum: 300, increment: 5, decimalPlaces: 0)]
        public int LookbackSeconds = 30;

        [InputParameter("Event Z Threshold", sortIndex: 801,
            minimum: 1.5, maximum: 6.0, increment: 0.1, decimalPlaces: 2)]
        public double EventZThreshold = 3.0;

        [InputParameter("Sample Interval (ms)", sortIndex: 802,
            minimum: 250, maximum: 5000, increment: 250, decimalPlaces: 0)]
        public int SampleIntervalMs = 1000;

        [InputParameter("Price-Through Buffer (ticks)", sortIndex: 803,
            minimum: 0, maximum: 20, increment: 1, decimalPlaces: 0)]
        public int PriceThroughBufferTicks = 1;

        // ── Events Layer (sortIndex 810-814) ────────────────────────────────
        [InputParameter("Events: Enabled", sortIndex: 810)]
        public bool EventsEnabled = true;

        [InputParameter("Events: Dot Size (px)", sortIndex: 811,
            minimum: 4, maximum: 12, increment: 1, decimalPlaces: 0)]
        public int DotSizePx = 6;

        [InputParameter("Events: Dot Alpha (lower = more density-driven)", sortIndex: 812,
            minimum: 20, maximum: 200, increment: 5, decimalPlaces: 0)]
        public int DotAlpha = 70;

        [InputParameter("Events: Auto-Clear After (min, 0=never)", sortIndex: 813,
            minimum: 0, maximum: 720, increment: 5, decimalPlaces: 0)]
        public int EventsAutoClearMin = 0;

        // ── Inflection Layer (sortIndex 820-825) ────────────────────────────
        [InputParameter("Inflection: Enabled", sortIndex: 820)]
        public bool InflectionEnabled = true;

        [InputParameter("Inflection: Trigger BUILD |z|", sortIndex: 821,
            minimum: 2.5, maximum: 8.0, increment: 0.1, decimalPlaces: 2)]
        public double TriggerBuildZ = 4.0;

        [InputParameter("Inflection: Cum Threshold", sortIndex: 822,
            minimum: 2.0, maximum: 30.0, increment: 0.5, decimalPlaces: 2)]
        public double CumThreshold = 7.0;

        [InputParameter("Inflection: ROC Threshold", sortIndex: 823,
            minimum: 2.0, maximum: 20.0, increment: 0.5, decimalPlaces: 2)]
        public double RocThreshold = 5.0;

        [InputParameter("Inflection: Confirmation Window (sec)", sortIndex: 824,
            minimum: 15, maximum: 300, increment: 5, decimalPlaces: 0)]
        public int ConfirmationWindowSec = 60;

        [InputParameter("Inflection: ROC Window (sec)", sortIndex: 825,
            minimum: 15, maximum: 300, increment: 5, decimalPlaces: 0)]
        public int RocWindowSec = 60;

        // ── Flow Layer (sortIndex 830-839) ──────────────────────────────────
        [InputParameter("Flow: Enabled", sortIndex: 830)]
        public bool FlowEnabled = true;

        [InputParameter("Flow: Climax VOD |z|", sortIndex: 831,
            minimum: 3.0, maximum: 12.0, increment: 0.5, decimalPlaces: 2)]
        public double ClimaxVodZ = 5.0;

        [InputParameter("Flow: Climax BUILD |z|", sortIndex: 832,
            minimum: 2.5, maximum: 8.0, increment: 0.1, decimalPlaces: 2)]
        public double ClimaxBuildZ = 4.0;

        [InputParameter("Flow: Band Window (sec)", sortIndex: 833,
            minimum: 15, maximum: 120, increment: 5, decimalPlaces: 0)]
        public int BandWindowSec = 30;

        [InputParameter("Flow: Band Min Events (in window)", sortIndex: 834,
            minimum: 2, maximum: 30, increment: 1, decimalPlaces: 0)]
        public int BandEventCount = 5;

        [InputParameter("Flow: Band Min RV (1e-7 units)", sortIndex: 835,
            minimum: 0.01, maximum: 100.0, increment: 0.1, decimalPlaces: 2)]
        public double BandRvScaled = 1.0;          // multiplied by 1e-7 in engine

        [InputParameter("Flow: Band Inner-Thinning |z|", sortIndex: 836,
            minimum: 0.0, maximum: 5.0, increment: 0.1, decimalPlaces: 2)]
        public double BandInnerThinZ = 1.0;

        [InputParameter("Flow: Band Sustain (sec)", sortIndex: 837,
            minimum: 3, maximum: 60, increment: 1, decimalPlaces: 0)]
        public int BandSustainSec = 10;

        [InputParameter("Flow: Band Cooldown (sec)", sortIndex: 838,
            minimum: 10, maximum: 180, increment: 5, decimalPlaces: 0)]
        public int BandCooldownSec = 30;

        [InputParameter("Flow: Band Alpha", sortIndex: 839,
            minimum: 8, maximum: 120, increment: 2, decimalPlaces: 0)]
        public int FlowBandAlpha = 28;

        // ── Build Bands Layer (sortIndex 840-844) ───────────────────────────
        [InputParameter("BuildBands: Enabled", sortIndex: 840)]
        public bool BuildBandsEnabled = true;

        [InputParameter("BuildBands: Cluster Min Events", sortIndex: 841,
            minimum: 2, maximum: 10, increment: 1, decimalPlaces: 0)]
        public int BuildClusterN = 3;

        [InputParameter("BuildBands: Cluster Tick Range", sortIndex: 842,
            minimum: 1, maximum: 40, increment: 1, decimalPlaces: 0)]
        public int BuildClusterTicks = 8;

        [InputParameter("BuildBands: Cluster Window (sec)", sortIndex: 843,
            minimum: 15, maximum: 600, increment: 15, decimalPlaces: 0)]
        public int BuildClusterSec = 90;

        [InputParameter("BuildBands: Band Alpha", sortIndex: 844,
            minimum: 16, maximum: 150, increment: 2, decimalPlaces: 0)]
        public int BuildBandAlpha = 48;

        // ── Render misc (sortIndex 850-851) ─────────────────────────────────
        [InputParameter("Lines: Thickness (px)", sortIndex: 850,
            minimum: 1, maximum: 6, increment: 1, decimalPlaces: 0)]
        public int LineThicknessPx = 2;

        [InputParameter("Lines: Alpha", sortIndex: 851,
            minimum: 60, maximum: 255, increment: 5, decimalPlaces: 0)]
        public int LineAlpha = 220;

        // ── Internal state ──────────────────────────────────────────────────
        private BookState _bookState;
        private SurfaceEngine _engine;
        private SurfacePainter _painter;
        private ConcurrentQueue<Level2Quote> _l2Queue;
        private bool _l2Subscribed;
        private DateTime _lastSampleUtc = DateTime.MinValue;

        public L2_Surface() : base()
        {
            this.Name = "L2 Surface";
            this.SeparateWindow = false;
        }

        public override IList<SettingItem> Settings
        {
            get
            {
                var settings = base.Settings;
                if (settings != null)
                {
                    var grpCommon = new SettingItemSeparatorGroup("Common", 800);
                    var grpEvents = new SettingItemSeparatorGroup("Events Layer (dots)", 810);
                    var grpInfl   = new SettingItemSeparatorGroup("Inflection Layer (cum-joins-ROC lines)", 820);
                    var grpFlow   = new SettingItemSeparatorGroup("Flow Layer (band + climax lines)", 830);
                    var grpBuild  = new SettingItemSeparatorGroup("Build Bands Layer (supply/demand zones)", 840);
                    var grpRender = new SettingItemSeparatorGroup("Render misc", 850);
                    foreach (var item in settings)
                    {
                        if (item == null) continue;
                        int s = item.SortIndex;
                        if (s >= 800 && s < 810) item.SeparatorGroup = grpCommon;
                        else if (s >= 810 && s < 820) item.SeparatorGroup = grpEvents;
                        else if (s >= 820 && s < 830) item.SeparatorGroup = grpInfl;
                        else if (s >= 830 && s < 840) item.SeparatorGroup = grpFlow;
                        else if (s >= 840 && s < 850) item.SeparatorGroup = grpBuild;
                        else if (s >= 850 && s < 860) item.SeparatorGroup = grpRender;
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
                _engine = new SurfaceEngine();
                ApplyEngineConfig();

                _painter = new SurfacePainter();
                ApplyPainterConfig();

                _l2Queue = new ConcurrentQueue<Level2Quote>();
                this.Symbol.NewLevel2 += Symbol_NewLevel2;
                _l2Subscribed = true;
            }
            catch (Exception ex)
            {
                Core.Instance.Loggers.Log(
                    $"[{nameof(L2_Surface)}] OnInit failed: {ex.Message}",
                    LoggingLevel.Error);
            }
        }

        // Push the current InputParameter values into the engine. Called at
        // OnInit and again before each sample so settings-dialog changes take
        // effect without a restart.
        private void ApplyEngineConfig()
        {
            if (_engine == null) return;
            _engine.LookbackSec = LookbackSeconds;
            _engine.EventZThreshold = EventZThreshold;
            _engine.InflectionEnabled = InflectionEnabled;
            _engine.TriggerBuildZ = TriggerBuildZ;
            _engine.CumThreshold = CumThreshold;
            _engine.RocThreshold = RocThreshold;
            _engine.ConfirmationWindowSec = ConfirmationWindowSec;
            _engine.RocWindowSec = RocWindowSec;
            _engine.FlowEnabled = FlowEnabled;
            _engine.ClimaxVodZ = ClimaxVodZ;
            _engine.ClimaxBuildZ = ClimaxBuildZ;
            _engine.BandWindowSec = BandWindowSec;
            _engine.BandEventCount = BandEventCount;
            _engine.BandRvThreshold = BandRvScaled * 1e-7;
            _engine.BandInnerThinZ = BandInnerThinZ;
            _engine.BandSustainSec = BandSustainSec;
            _engine.BandCooldownSec = BandCooldownSec;
            _engine.BuildBandsEnabled = BuildBandsEnabled;
            _engine.BuildClusterN = BuildClusterN;
            _engine.BuildClusterTicks = BuildClusterTicks;
            _engine.BuildClusterSec = BuildClusterSec;
        }

        private void ApplyPainterConfig()
        {
            if (_painter == null) return;
            _painter.EventsEnabled = EventsEnabled;
            _painter.InflectionEnabled = InflectionEnabled;
            _painter.FlowEnabled = FlowEnabled;
            _painter.BuildBandsEnabled = BuildBandsEnabled;
            _painter.DotSizePx = DotSizePx;
            _painter.DotAlpha = DotAlpha;
            _painter.LineThicknessPx = LineThicknessPx;
            _painter.LineAlpha = LineAlpha;
            _painter.FlowBandAlpha = FlowBandAlpha;
            _painter.BuildBandAlpha = BuildBandAlpha;
        }

        private void Symbol_NewLevel2(Symbol symbol, Level2Quote l2, DOMQuote dom)
        {
            if (l2 == null) return;
            _l2Queue?.Enqueue(l2);
        }

        protected override void OnUpdate(UpdateArgs args)
        {
            if (_l2Queue == null || _bookState == null || _engine == null) return;

            while (_l2Queue.TryDequeue(out var q))
            {
                try { _bookState.Apply(q); }
                catch { /* skip bad quote */ }
            }

            var now = DateTime.UtcNow;
            if ((now - _lastSampleUtc).TotalMilliseconds >= SampleIntervalMs)
            {
                _lastSampleUtc = now;
                try
                {
                    ApplyEngineConfig();
                    _engine.OnSample(now, _bookState);
                    _engine.ApplyEventTtl(now, EventsAutoClearMin);
                    _engine.ApplyPriceThrough(PriceThroughBufferTicks);
                }
                catch (Exception ex)
                {
                    Core.Instance.Loggers.Log(
                        $"[{nameof(L2_Surface)}] sample failed: {ex.Message}",
                        LoggingLevel.Error);
                }
            }
        }

        public override void OnPaintChart(PaintChartEventArgs args)
        {
            try
            {
                if (_painter == null || _engine == null) return;
                var chart = this.CurrentChart;
                if (chart == null) return;
                ApplyPainterConfig();
                _painter.Paint(args, chart, _engine);
            }
            catch (Exception ex)
            {
                try
                {
                    Core.Instance.Loggers.Log(
                        $"[{nameof(L2_Surface)}] paint failed: {ex.Message}",
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
                _painter = null;
                _engine = null;
                _bookState?.Clear();
                _bookState = null;
                _l2Queue = null;
            }
            catch { }
        }
    }
}
