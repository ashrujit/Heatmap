using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using TradingPlatform.BusinessLayer;
using TradingPlatform.BusinessLayer.Chart;

namespace TapeLedger
{
    public class TapeLedger : Indicator
    {
        [InputParameter("RTH Start HHmm", sortIndex: 1200,
            minimum: 0, maximum: 2359, increment: 1, decimalPlaces: 0)]
        public int RthStartHHmm = 930;

        [InputParameter("RTH End HHmm", sortIndex: 1201,
            minimum: 0, maximum: 2359, increment: 1, decimalPlaces: 0)]
        public int RthEndHHmm = 1600;

        [InputParameter("OR Minutes", sortIndex: 1202,
            minimum: 1, maximum: 30, increment: 1, decimalPlaces: 0)]
        public int OrMinutes = 5;

        [InputParameter("IB Minutes", sortIndex: 1203,
            minimum: 30, maximum: 120, increment: 5, decimalPlaces: 0)]
        public int IbMinutes = 60;

        [InputParameter("IB Break Cutoff HHmm", sortIndex: 1204,
            minimum: 0, maximum: 2359, increment: 1, decimalPlaces: 0)]
        public int IbBreakEndHHmm = 1230;

        [InputParameter("Bar Minutes", sortIndex: 1210,
            minimum: 1, maximum: 15, increment: 1, decimalPlaces: 0)]
        public int BarMinutes = 5;

        [InputParameter("Shelf Bin Ticks", sortIndex: 1211,
            minimum: 4, maximum: 80, increment: 1, decimalPlaces: 0)]
        public int ShelfBinTicks = 16;

        [InputParameter("Shelf Lookback Minutes", sortIndex: 1212,
            minimum: 5, maximum: 120, increment: 5, decimalPlaces: 0)]
        public int ShelfLookbackMinutes = 30;

        [InputParameter("Visible Shelf Count", sortIndex: 1213,
            minimum: 1, maximum: 12, increment: 1, decimalPlaces: 0)]
        public int ShelfCount = 6;

        [InputParameter("Min Shelf Volume", sortIndex: 1214,
            minimum: 100, maximum: 20000, increment: 100, decimalPlaces: 0)]
        public double MinShelfVolume = 1200.0;

        [InputParameter("Min Shelf Seconds", sortIndex: 1215,
            minimum: 5, maximum: 300, increment: 5, decimalPlaces: 0)]
        public int MinShelfSeconds = 35;

        [InputParameter("Break Buffer Ticks", sortIndex: 1220,
            minimum: 0, maximum: 120, increment: 1, decimalPlaces: 0)]
        public int BreakBufferTicks = 16;

        [InputParameter("Reclaim Buffer Ticks", sortIndex: 1221,
            minimum: 0, maximum: 80, increment: 1, decimalPlaces: 0)]
        public int ReclaimBufferTicks = 8;

        [InputParameter("Extreme Test Ticks", sortIndex: 1222,
            minimum: 4, maximum: 160, increment: 1, decimalPlaces: 0)]
        public int ExtremeTestTicks = 32;

        [InputParameter("Extreme Cap Ticks", sortIndex: 1223,
            minimum: 4, maximum: 160, increment: 1, decimalPlaces: 0)]
        public int ExtremeCapTicks = 32;

        [InputParameter("Extreme Reject Ticks", sortIndex: 1224,
            minimum: 8, maximum: 240, increment: 1, decimalPlaces: 0)]
        public int ExtremeRejectTicks = 64;

        [InputParameter("Watch 1 Start HHmm", sortIndex: 1230,
            minimum: 0, maximum: 2359, increment: 1, decimalPlaces: 0)]
        public int Watch1StartHHmm = 1115;

        [InputParameter("Watch 1 End HHmm", sortIndex: 1231,
            minimum: 0, maximum: 2359, increment: 1, decimalPlaces: 0)]
        public int Watch1EndHHmm = 1215;

        [InputParameter("Watch 2 Start HHmm", sortIndex: 1232,
            minimum: 0, maximum: 2359, increment: 1, decimalPlaces: 0)]
        public int Watch2StartHHmm = 1215;

        [InputParameter("Watch 2 End HHmm", sortIndex: 1233,
            minimum: 0, maximum: 2359, increment: 1, decimalPlaces: 0)]
        public int Watch2EndHHmm = 1315;

        [InputParameter("Bands Enabled", sortIndex: 1240)]
        public bool BandsEnabled = true;

        [InputParameter("Banners Enabled", sortIndex: 1241)]
        public bool BannersEnabled = true;

        [InputParameter("Panel Enabled", sortIndex: 1242)]
        public bool PanelEnabled = true;

        [InputParameter("Band Alpha", sortIndex: 1243,
            minimum: 10, maximum: 180, increment: 2, decimalPlaces: 0)]
        public int BandAlpha = 72;

        [InputParameter("Banner Alpha", sortIndex: 1244,
            minimum: 80, maximum: 255, increment: 5, decimalPlaces: 0)]
        public int BannerAlpha = 218;

        [InputParameter("Panel Left Offset (px)", sortIndex: 1245,
            minimum: 0, maximum: 3000, increment: 5, decimalPlaces: 0)]
        public int PanelLeftOffsetPx = 90;

        [InputParameter("Panel Top Offset (px)", sortIndex: 1246,
            minimum: 0, maximum: 2000, increment: 5, decimalPlaces: 0)]
        public int PanelTopOffsetPx = 86;

        [InputParameter("Panel Width (px)", sortIndex: 1247,
            minimum: 300, maximum: 900, increment: 10, decimalPlaces: 0)]
        public int PanelWidthPx = 420;

        [InputParameter("Font Size", sortIndex: 1248,
            minimum: 7, maximum: 24, increment: 0.5, decimalPlaces: 1)]
        public double FontSize = 10.0;

        private readonly ConcurrentQueue<Last> _tradeQueue = new();
        private TapeLedgerEngine _engine;
        private TapeLedgerPainter _painter;
        private double _tickSize = 0.25;
        private bool _subscribed;

        public TapeLedger() : base()
        {
            Name = "Tape Ledger";
            SeparateWindow = false;
        }

        public override IList<SettingItem> Settings
        {
            get
            {
                var settings = base.Settings;
                if (settings != null)
                {
                    var session = new SettingItemSeparatorGroup("Tape Ledger - Session", 1200);
                    var shelves = new SettingItemSeparatorGroup("Tape Ledger - Shelves", 1210);
                    var quality = new SettingItemSeparatorGroup("Tape Ledger - Auction Quality", 1220);
                    var watch = new SettingItemSeparatorGroup("Tape Ledger - Watch Windows", 1230);
                    var render = new SettingItemSeparatorGroup("Tape Ledger - Render", 1240);
                    foreach (var item in settings)
                    {
                        if (item == null) continue;
                        if (item.SortIndex >= 1200 && item.SortIndex < 1210)
                            item.SeparatorGroup = session;
                        else if (item.SortIndex >= 1210 && item.SortIndex < 1220)
                            item.SeparatorGroup = shelves;
                        else if (item.SortIndex >= 1220 && item.SortIndex < 1230)
                            item.SeparatorGroup = quality;
                        else if (item.SortIndex >= 1230 && item.SortIndex < 1240)
                            item.SeparatorGroup = watch;
                        else if (item.SortIndex >= 1240 && item.SortIndex < 1260)
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
                if (Symbol == null) return;
                _tickSize = Symbol.TickSize > 0 ? Symbol.TickSize : 0.25;
                _engine = new TapeLedgerEngine(_tickSize);
                _painter = new TapeLedgerPainter(_tickSize);
                ApplySettings();
                Symbol.NewLast += Symbol_NewLast;
                _subscribed = true;
            }
            catch (Exception ex)
            {
                Core.Instance.Loggers.Log($"[{nameof(TapeLedger)}] OnInit failed: {ex.Message}", LoggingLevel.Error);
            }
        }

        private void Symbol_NewLast(Symbol symbol, Last last)
        {
            if (last == null) return;
            if (!double.IsFinite(last.Price) || last.Price <= 0) return;
            _tradeQueue.Enqueue(last);
        }

        protected override void OnUpdate(UpdateArgs args)
        {
            if (_engine == null) return;
            ApplySettings();
            int drained = 0;
            while (drained < 20000 && _tradeQueue.TryDequeue(out var last))
            {
                try
                {
                    _engine.OnTrade(NormalizeUtc(last.Time), last.Price, last.Size, AggressorSign(last.AggressorFlag));
                }
                catch (Exception ex)
                {
                    Core.Instance.Loggers.Log($"[{nameof(TapeLedger)}] trade drain failed: {ex.Message}", LoggingLevel.Error);
                }
                drained++;
            }
        }

        public override void OnPaintChart(PaintChartEventArgs args)
        {
            try
            {
                if (_engine == null || _painter == null) return;
                ApplySettings();
                _painter.Paint(args, CurrentChart, _engine.GetSnapshot(DateTime.UtcNow));
            }
            catch (Exception ex)
            {
                try { Core.Instance.Loggers.Log($"[{nameof(TapeLedger)}] paint failed: {ex.Message}", LoggingLevel.Error); }
                catch { }
            }
        }

        protected override void OnClear()
        {
            try
            {
                if (_subscribed && Symbol != null)
                {
                    try { Symbol.NewLast -= Symbol_NewLast; } catch { }
                    _subscribed = false;
                }
            }
            catch { }
            base.OnClear();
        }

        private void ApplySettings()
        {
            if (_engine != null)
            {
                _engine.RthStartHHmm = RthStartHHmm;
                _engine.RthEndHHmm = RthEndHHmm;
                _engine.OrMinutes = OrMinutes;
                _engine.IbMinutes = IbMinutes;
                _engine.IbBreakEndHHmm = IbBreakEndHHmm;
                _engine.BarMinutes = BarMinutes;
                _engine.ShelfBinTicks = ShelfBinTicks;
                _engine.ShelfLookbackMinutes = ShelfLookbackMinutes;
                _engine.ShelfCount = ShelfCount;
                _engine.MinShelfVolume = MinShelfVolume;
                _engine.MinShelfSeconds = MinShelfSeconds;
                _engine.BreakBufferTicks = BreakBufferTicks;
                _engine.ReclaimBufferTicks = ReclaimBufferTicks;
                _engine.ExtremeTestTicks = ExtremeTestTicks;
                _engine.ExtremeCapTicks = ExtremeCapTicks;
                _engine.ExtremeRejectTicks = ExtremeRejectTicks;
                _engine.Watch1StartHHmm = Watch1StartHHmm;
                _engine.Watch1EndHHmm = Watch1EndHHmm;
                _engine.Watch2StartHHmm = Watch2StartHHmm;
                _engine.Watch2EndHHmm = Watch2EndHHmm;
            }
            if (_painter != null)
            {
                _painter.BandsEnabled = BandsEnabled;
                _painter.BannersEnabled = BannersEnabled;
                _painter.PanelEnabled = PanelEnabled;
                _painter.BandAlpha = BandAlpha;
                _painter.BannerAlpha = BannerAlpha;
                _painter.LeftOffsetPx = PanelLeftOffsetPx;
                _painter.TopOffsetPx = PanelTopOffsetPx;
                _painter.PanelWidthPx = PanelWidthPx;
                _painter.FontSize = (float)FontSize;
            }
        }

        private static DateTime NormalizeUtc(DateTime time)
        {
            if (time == default) return DateTime.UtcNow;
            if (time.Kind == DateTimeKind.Utc) return time;
            if (time.Kind == DateTimeKind.Local) return time.ToUniversalTime();
            return DateTime.SpecifyKind(time, DateTimeKind.Utc);
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
    }
}
