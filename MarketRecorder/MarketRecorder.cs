using System;
using System.Collections.Generic;
using TradingPlatform.BusinessLayer;

namespace MarketRecorder
{
    public class MarketRecorder : Indicator
    {
        private const int L1ToleranceTicksDefault = 2;

        [InputParameter("Recorder Enabled", sortIndex: 1100)]
        public bool RecorderEnabled = true;

        [InputParameter("Write Tick Stream", sortIndex: 1101)]
        public bool WriteTicks = true;

        [InputParameter("Write Snapshot Stream", sortIndex: 1102)]
        public bool WriteSnapshots = true;

        [InputParameter("Snapshot Interval (ms)", sortIndex: 1103,
            minimum: 250, maximum: 10000, increment: 250, decimalPlaces: 0)]
        public int SnapshotIntervalMs = 1000;

        [InputParameter("Levels Per Side", sortIndex: 1104,
            minimum: 30, maximum: 200, increment: 10, decimalPlaces: 0)]
        public int LevelsPerSide = 30;

        [InputParameter("Chunk Seconds", sortIndex: 1105,
            minimum: 60, maximum: 1800, increment: 60, decimalPlaces: 0)]
        public int ChunkSeconds = 300;

        [InputParameter("Flush Seconds", sortIndex: 1106,
            minimum: 1, maximum: 30, increment: 1, decimalPlaces: 0)]
        public int FlushSeconds = 5;

        [InputParameter("Capture Retention (days)", sortIndex: 1107,
            minimum: 1, maximum: 365, increment: 1, decimalPlaces: 0)]
        public int RetentionDays = 30;

        [InputParameter("Capture Root Path", sortIndex: 1108)]
        public string CaptureRootPath = @"C:\Quantower\Settings\Scripts\Indicators\MarketRecorder\captures";

        [InputParameter("Book Freshness (sec)", sortIndex: 1110,
            minimum: 1, maximum: 60, increment: 1, decimalPlaces: 0)]
        public int BookFreshnessSec = 5;

        [InputParameter("L1 Tolerance Ticks", sortIndex: 1111,
            minimum: 0, maximum: 20, increment: 1, decimalPlaces: 0)]
        public int L1ToleranceTicks = L1ToleranceTicksDefault;

        [InputParameter("Panel Enabled", sortIndex: 1120)]
        public bool PanelEnabled = true;

        [InputParameter("Panel Left Offset (px)", sortIndex: 1121,
            minimum: 0, maximum: 3000, increment: 5, decimalPlaces: 0)]
        public int PanelLeftOffsetPx = 90;

        [InputParameter("Panel Top Offset (px)", sortIndex: 1122,
            minimum: 0, maximum: 2000, increment: 5, decimalPlaces: 0)]
        public int PanelTopOffsetPx = 90;

        [InputParameter("Panel Width (px)", sortIndex: 1123,
            minimum: 220, maximum: 700, increment: 10, decimalPlaces: 0)]
        public int PanelWidthPx = 340;

        [InputParameter("Font Size", sortIndex: 1124,
            minimum: 7, maximum: 18, increment: 0.5, decimalPlaces: 1)]
        public double FontSize = 9.0;

        private ChunkedCaptureWriter _writer;
        private RecorderPainter _painter;
        private GetDepthOfMarketParameters _domParams;
        private double _tickSize = 0.25;
        private bool _l2Subscribed;
        private bool _lastSubscribed;
        private DateTime _lastL2EventUtc = DateTime.MinValue;
        private DateTime _lastSnapshotAttemptUtc = DateTime.MinValue;
        private string _lastBookState = "starting";

        public MarketRecorder() : base()
        {
            Name = "Market Recorder";
            SeparateWindow = false;
        }

        public override IList<SettingItem> Settings
        {
            get
            {
                var settings = base.Settings;
                if (settings != null)
                {
                    var capture = new SettingItemSeparatorGroup("Market Recorder - Capture", 1100);
                    var health = new SettingItemSeparatorGroup("Market Recorder - Health", 1110);
                    var panel = new SettingItemSeparatorGroup("Market Recorder - Panel", 1120);
                    foreach (var item in settings)
                    {
                        if (item == null) continue;
                        if (item.SortIndex >= 1100 && item.SortIndex < 1110)
                            item.SeparatorGroup = capture;
                        else if (item.SortIndex >= 1110 && item.SortIndex < 1120)
                            item.SeparatorGroup = health;
                        else if (item.SortIndex >= 1120 && item.SortIndex < 1130)
                            item.SeparatorGroup = panel;
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
                _painter = new RecorderPainter();
                ApplyPainterSettings();

                if (!RecorderEnabled || Symbol == null)
                    return;

                _tickSize = Symbol.TickSize > 0 ? Symbol.TickSize : 0.25;
                int levels = Math.Max(30, Math.Min(200, LevelsPerSide));
                _domParams = new GetDepthOfMarketParameters
                {
                    GetLevel2ItemsParameters = new GetLevel2ItemsParameters
                    {
                        LevelsCount = levels,
                        CalculateCumulative = false,
                    },
                };

                _writer = new ChunkedCaptureWriter(
                    CaptureRootPath,
                    Symbol.Name ?? "UNKNOWN",
                    levels,
                    ChunkSeconds,
                    FlushSeconds,
                    RetentionDays,
                    WriteTicks,
                    WriteSnapshots);
                _writer.Start();

                if (WriteTicks)
                {
                    Symbol.NewLast += Symbol_NewLast;
                    _lastSubscribed = true;
                }
                if (WriteSnapshots)
                {
                    Symbol.NewLevel2 += Symbol_NewLevel2Heartbeat;
                    _l2Subscribed = true;
                }

                Core.Instance.Loggers.Log(
                    $"[MarketRecorder] enabled root={CaptureRootPath} symbol={Symbol.Name} levels={levels} chunkSec={ChunkSeconds}",
                    LoggingLevel.System);
            }
            catch (Exception ex)
            {
                Core.Instance.Loggers.Log($"[{nameof(MarketRecorder)}] OnInit failed: {ex.Message}", LoggingLevel.Error);
            }
        }

        private void Symbol_NewLevel2Heartbeat(Symbol symbol, Level2Quote l2, DOMQuote dom)
        {
            _lastL2EventUtc = DateTime.UtcNow;
        }

        private void Symbol_NewLast(Symbol symbol, Last last)
        {
            if (last == null || _writer == null) return;
            _writer.EnqueueTick(last.Time == default ? DateTime.UtcNow : last.Time, last.Price, last.Size, last.AggressorFlag);
        }

        protected override void OnUpdate(UpdateArgs args)
        {
            if (_writer == null || Symbol == null || !WriteSnapshots) return;

            DateTime now = DateTime.UtcNow;
            if (_lastSnapshotAttemptUtc != DateTime.MinValue
                && (now - _lastSnapshotAttemptUtc).TotalMilliseconds < Math.Max(250, SnapshotIntervalMs))
                return;
            _lastSnapshotAttemptUtc = now;

            bool fresh = _lastL2EventUtc != DateTime.MinValue
                      && (now - _lastL2EventUtc).TotalSeconds <= Math.Max(1, BookFreshnessSec);
            if (!fresh)
            {
                SetBookState("book stale");
                _writer.NoteSnapshotSkipped("book stale");
                return;
            }

            DepthOfMarketAggregatedCollections dom = null;
            try
            {
                dom = Symbol.DepthOfMarket?.GetDepthOfMarketAggregatedCollections(_domParams);
            }
            catch (Exception ex)
            {
                SetBookState("DOM read failed");
                _writer.NoteSnapshotSkipped("DOM read failed: " + ex.Message);
                return;
            }

            if (dom == null
                || (dom.Bids == null || dom.Bids.Length == 0)
                && (dom.Asks == null || dom.Asks.Length == 0))
            {
                SetBookState("DOM empty");
                _writer.NoteSnapshotSkipped("DOM empty");
                return;
            }

            if (!L1Agrees(dom, _tickSize))
            {
                SetBookState("L1/DOM mismatch");
                _writer.NoteSnapshotSkipped("L1/DOM mismatch");
                return;
            }

            SetBookState("book ok");
            _writer.EnqueueSnapshot(now, dom, _tickSize);
        }

        public override void OnPaintChart(PaintChartEventArgs args)
        {
            try
            {
                if (_painter == null) return;
                ApplyPainterSettings();
                var status = _writer?.GetStatus() ?? DisabledStatus();
                _painter.Paint(args, status);
            }
            catch (Exception ex)
            {
                try { Core.Instance.Loggers.Log($"[{nameof(MarketRecorder)}] paint failed: {ex.Message}", LoggingLevel.Error); }
                catch { }
            }
        }

        protected override void OnClear()
        {
            try
            {
                if (_l2Subscribed && Symbol != null)
                {
                    try { Symbol.NewLevel2 -= Symbol_NewLevel2Heartbeat; } catch { }
                    _l2Subscribed = false;
                }
                if (_lastSubscribed && Symbol != null)
                {
                    try { Symbol.NewLast -= Symbol_NewLast; } catch { }
                    _lastSubscribed = false;
                }
                try { _writer?.Dispose(); } catch { }
                _writer = null;
                _domParams = null;
            }
            catch { }
        }

        private void ApplyPainterSettings()
        {
            if (_painter == null) return;
            _painter.PanelEnabled = PanelEnabled;
            _painter.LeftOffsetPx = PanelLeftOffsetPx;
            _painter.TopOffsetPx = PanelTopOffsetPx;
            _painter.PanelWidthPx = PanelWidthPx;
            _painter.FontSize = (float)Math.Max(7.0, Math.Min(18.0, FontSize));
        }

        private void SetBookState(string state)
        {
            _lastBookState = state;
            _writer?.SetBookState(state);
        }

        private bool L1Agrees(DepthOfMarketAggregatedCollections dom, double tickSize)
        {
            double symBid = Symbol.Bid;
            double symAsk = Symbol.Ask;
            if (!double.IsFinite(symBid) || !double.IsFinite(symAsk) || symBid <= 0 || symAsk <= 0)
                return true;

            double domBid = FirstValidPrice(dom.Bids);
            double domAsk = FirstValidPrice(dom.Asks);
            int tolerance = Math.Max(0, L1ToleranceTicks);
            if (double.IsFinite(domBid))
            {
                long d = Math.Abs((long)Math.Round(domBid / tickSize) - (long)Math.Round(symBid / tickSize));
                if (d > tolerance) return false;
            }
            if (double.IsFinite(domAsk))
            {
                long d = Math.Abs((long)Math.Round(domAsk / tickSize) - (long)Math.Round(symAsk / tickSize));
                if (d > tolerance) return false;
            }
            return true;
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

        private RecorderStatusSnapshot DisabledStatus()
        {
            return new RecorderStatusSnapshot
            {
                Version = "0.1.0",
                NowUtc = DateTime.UtcNow.ToString("O"),
                Symbol = Symbol?.Name ?? "UNKNOWN",
                TicksEnabled = WriteTicks,
                SnapshotsEnabled = WriteSnapshots,
                BookState = RecorderEnabled ? _lastBookState : "disabled",
                LastError = RecorderEnabled ? "" : "recorder disabled",
            };
        }
    }
}
