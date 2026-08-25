using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.Threading;
using System.Threading.Tasks;
using TradingPlatform.BusinessLayer;
using TradingPlatform.BusinessLayer.Chart;

namespace BubbleTape
{
    public class BubbleTape : Indicator
    {
        private const int TradeQueueCap = 100000;

        [InputParameter("Bar Minutes", sortIndex: 1300,
            minimum: 1, maximum: 15, increment: 1, decimalPlaces: 0)]
        public int BarMinutes = 5;

        [InputParameter("Price Band Ticks", sortIndex: 1301,
            minimum: 1, maximum: 80, increment: 1, decimalPlaces: 0)]
        public int PriceBandTicks = 8;

        [InputParameter("Strength Filter (0 Low / 1 Normal / 2 High)", sortIndex: 1302,
            minimum: 0, maximum: 2, increment: 1, decimalPlaces: 0)]
        public int StrengthFilter = 1;

        [InputParameter("Lookback Days", sortIndex: 1303,
            minimum: 1, maximum: 7, increment: 1, decimalPlaces: 0)]
        public int LookbackDays = 3;

        [InputParameter("Bubble Source (0 Trades / 1 Delta / 2 Both)", sortIndex: 1304,
            minimum: 0, maximum: 2, increment: 1, decimalPlaces: 0)]
        public int BubbleSource = 0;

        [InputParameter("Min Cell Volume", sortIndex: 1310,
            minimum: 0, maximum: 1000, increment: 1, decimalPlaces: 0)]
        public double MinCellVolume = 12.0;

        [InputParameter("Min Delta Share", sortIndex: 1311,
            minimum: 0.05, maximum: 0.95, increment: 0.05, decimalPlaces: 2)]
        public double MinDeltaShare = 0.25;

        [InputParameter("Min Bubble Strength", sortIndex: 1312,
            minimum: 0, maximum: 5000, increment: 5, decimalPlaces: 0)]
        public double MinClusterDelta = 30.0;

        [InputParameter("Max Clusters Per Bar/Side", sortIndex: 1313,
            minimum: 1, maximum: 12, increment: 1, decimalPlaces: 0)]
        public int MaxClustersPerBarSide = 4;

        [InputParameter("Min Trade Group Volume", sortIndex: 1314,
            minimum: 1, maximum: 10000, increment: 1, decimalPlaces: 0)]
        public double MinTradeGroupVolume = 50.0;

        [InputParameter("Fallback Group Window (ms)", sortIndex: 1315,
            minimum: 25, maximum: 2000, increment: 25, decimalPlaces: 0)]
        public int FallbackGroupWindowMs = 250;

        [InputParameter("Show Developing Bubble", sortIndex: 1316)]
        public bool ShowDevelopingBubble = true;

        [InputParameter("Min Bubble Diameter (px)", sortIndex: 1320,
            minimum: 2, maximum: 80, increment: 1, decimalPlaces: 0)]
        public double MinBubbleDiameterPx = 9.0;

        [InputParameter("Max Bubble Diameter (px)", sortIndex: 1321,
            minimum: 4, maximum: 160, increment: 1, decimalPlaces: 0)]
        public double MaxBubbleDiameterPx = 38.0;

        [InputParameter("Bubble Alpha", sortIndex: 1322,
            minimum: 10, maximum: 230, increment: 5, decimalPlaces: 0)]
        public int BubbleAlpha = 108;

        [InputParameter("Bubble Edge Alpha", sortIndex: 1323,
            minimum: 30, maximum: 255, increment: 5, decimalPlaces: 0)]
        public int BubbleEdgeAlpha = 205;

        [InputParameter("Historical Warmup Enabled", sortIndex: 1330)]
        public bool HistoricalWarmupEnabled = true;

        [InputParameter("Status Panel Enabled", sortIndex: 1340)]
        public bool StatusPanelEnabled = false;

        [InputParameter("Panel Left Offset (px)", sortIndex: 1341,
            minimum: 0, maximum: 3000, increment: 5, decimalPlaces: 0)]
        public int PanelLeftOffsetPx = 90;

        [InputParameter("Panel Top Offset (px)", sortIndex: 1342,
            minimum: 0, maximum: 2000, increment: 5, decimalPlaces: 0)]
        public int PanelTopOffsetPx = 90;

        [InputParameter("Panel Width (px)", sortIndex: 1343,
            minimum: 220, maximum: 700, increment: 10, decimalPlaces: 0)]
        public int PanelWidthPx = 310;

        [InputParameter("Font Size", sortIndex: 1344,
            minimum: 7, maximum: 18, increment: 0.5, decimalPlaces: 1)]
        public double FontSize = 9.0;

        private readonly ConcurrentQueue<TradePrint> _tradeQueue = new();
        private BubbleTapeEngine _engine;
        private BubbleTapePainter _painter;
        private CancellationTokenSource _warmupCts;
        private Task<WarmupResult> _warmupTask;
        private DateTime _warmupBoundaryUtc;
        private double _tickSize = 0.25;
        private bool _subscribed;
        private bool _warmupPending;
        private bool _warmupApplied;
        private string _settingsKey = "";
        private bool _lastHistoricalWarmupEnabled = true;
        private int _queuedTradeCount;
        private long _tradeQueueDrops;
        private DateTime _lastTradeDropLogUtc = DateTime.MinValue;

        public BubbleTape() : base()
        {
            Name = "BubbleTape";
            SeparateWindow = false;
        }

        public override IList<SettingItem> Settings
        {
            get
            {
                var settings = base.Settings;
                if (settings != null)
                {
                    var detection = new SettingItemSeparatorGroup("BubbleTape - Detection", 1300);
                    var advanced = new SettingItemSeparatorGroup("BubbleTape - Advanced Detection", 1310);
                    var render = new SettingItemSeparatorGroup("BubbleTape - Render", 1320);
                    var warmup = new SettingItemSeparatorGroup("BubbleTape - Warmup", 1330);
                    var panel = new SettingItemSeparatorGroup("BubbleTape - Status Panel", 1340);
                    foreach (var item in settings)
                    {
                        if (item == null) continue;
                        if (item.SortIndex >= 1300 && item.SortIndex < 1310)
                            item.SeparatorGroup = detection;
                        else if (item.SortIndex >= 1310 && item.SortIndex < 1320)
                            item.SeparatorGroup = advanced;
                        else if (item.SortIndex >= 1320 && item.SortIndex < 1330)
                            item.SeparatorGroup = render;
                        else if (item.SortIndex >= 1330 && item.SortIndex < 1340)
                            item.SeparatorGroup = warmup;
                        else if (item.SortIndex >= 1340 && item.SortIndex < 1350)
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
                if (Symbol == null) return;
                _tickSize = Symbol.TickSize > 0 ? Symbol.TickSize : 0.25;
                _engine = new BubbleTapeEngine(_tickSize);
                _painter = new BubbleTapePainter(_tickSize);
                _queuedTradeCount = 0;
                _tradeQueueDrops = 0;
                _warmupApplied = false;
                ApplySettings();
                _settingsKey = CurrentSettingsKey();
                _lastHistoricalWarmupEnabled = HistoricalWarmupEnabled;

                _warmupBoundaryUtc = DateTime.UtcNow;
                Symbol.NewLast += Symbol_NewLast;
                _subscribed = true;

                if (HistoricalWarmupEnabled)
                    StartWarmup(Symbol, _warmupBoundaryUtc);
                else
                    _engine.SetStatus("live only");
            }
            catch (Exception ex)
            {
                Core.Instance.Loggers.Log($"[{nameof(BubbleTape)}] OnInit failed: {ex.Message}", LoggingLevel.Error);
            }
        }

        private void StartWarmup(Symbol symbol, DateTime boundaryUtc)
        {
            try
            {
                _warmupCts?.Cancel();
                _warmupCts?.Dispose();
                _warmupCts = new CancellationTokenSource();
                _warmupPending = true;
                _engine.SetStatus("warming history");
                int lookback = Math.Max(1, LookbackDays);
                DateTime fromUtc = boundaryUtc.AddDays(-lookback);
                var token = _warmupCts.Token;
                _warmupTask = Task.Run(() => LoadWarmup(symbol, fromUtc, boundaryUtc, token), token);
            }
            catch (Exception ex)
            {
                _warmupPending = false;
                _engine.SetStatus("warmup failed");
                Core.Instance.Loggers.Log($"[{nameof(BubbleTape)}] warmup start failed: {ex.Message}", LoggingLevel.Error);
            }
        }

        private WarmupResult LoadWarmup(Symbol symbol, DateTime fromUtc, DateTime toUtc, CancellationToken token)
        {
            var result = new WarmupResult();
            try
            {
                if (symbol == null)
                    return result.Fail("no symbol");

                using HistoricalData history = symbol.GetTickHistory(HistoryType.Last, fromUtc, toUtc);
                foreach (var item in history)
                {
                    token.ThrowIfCancellationRequested();
                    if (item is not HistoryItemLast last) continue;
                    if (!double.IsFinite(last.Price) || last.Price <= 0) continue;
                    if (!double.IsFinite(last.Volume) || last.Volume <= 0) continue;
                    result.Trades.Add(new TradePrint(
                        last.TimeLeft,
                        last.Price,
                        last.Volume,
                        AggressorSign(last.AggressorFlag),
                        null,
                        last.Buyer,
                        last.Seller));
                }
                result.Trades.Sort((a, b) => a.TimeUtc.CompareTo(b.TimeUtc));
                result.Success = true;
                return result;
            }
            catch (OperationCanceledException)
            {
                return result.Fail("warmup cancelled");
            }
            catch (Exception ex)
            {
                return result.Fail(ex.Message);
            }
        }

        private void Symbol_NewLast(Symbol symbol, Last last)
        {
            if (last == null) return;
            if (!double.IsFinite(last.Price) || last.Price <= 0) return;
            if (!double.IsFinite(last.Size) || last.Size <= 0) return;
            if (Interlocked.Increment(ref _queuedTradeCount) > TradeQueueCap)
            {
                Interlocked.Decrement(ref _queuedTradeCount);
                Interlocked.Increment(ref _tradeQueueDrops);
                MaybeLogTradeQueueDrops();
                return;
            }

            DateTime utc = last.Time == default ? DateTime.UtcNow : NormalizeUtc(last.Time);
            _tradeQueue.Enqueue(new TradePrint(
                utc,
                last.Price,
                last.Size,
                AggressorSign(last.AggressorFlag),
                last.TradeId,
                last.Buyer,
                last.Seller));
        }

        protected override void OnUpdate(UpdateArgs args)
        {
            if (_engine == null) return;
            ApplySettings();
            ApplyWarmupIfReady();
            if (_warmupPending) return;
            DrainTrades();
        }

        private void ApplyWarmupIfReady()
        {
            if (!_warmupPending || _warmupTask == null || !_warmupTask.IsCompleted)
                return;

            _warmupPending = false;
            var task = _warmupTask;
            _warmupTask = null;
            try
            {
                WarmupResult result = task.Result;
                if (result.Success)
                {
                    int warmupTradeCount = result.Trades.Count;
                    _engine.ResetAndWarm(result.Trades, _warmupBoundaryUtc);
                    result.Trades.Clear();
                    _engine.SetStatus($"warm {warmupTradeCount} ticks");
                    _warmupApplied = true;
                }
                else
                {
                    _engine.SetStatus("warmup failed");
                    Core.Instance.Loggers.Log($"[{nameof(BubbleTape)}] warmup failed: {result.Error}", LoggingLevel.Error);
                }
            }
            catch (Exception ex)
            {
                _engine.SetStatus("warmup failed");
                try { Core.Instance.Loggers.Log($"[{nameof(BubbleTape)}] warmup apply failed: {ex.Message}", LoggingLevel.Error); }
                catch { }
            }
            finally
            {
                try { _warmupCts?.Dispose(); } catch { }
                _warmupCts = null;
            }
        }

        private void DrainTrades()
        {
            int drained = 0;
            while (drained < 25000 && _tradeQueue.TryDequeue(out var trade))
            {
                Interlocked.Decrement(ref _queuedTradeCount);
                try
                {
                    if (_warmupApplied && trade.TimeUtc <= _warmupBoundaryUtc)
                        continue;
                    _engine.OnTrade(trade);
                }
                catch (Exception ex)
                {
                    Core.Instance.Loggers.Log($"[{nameof(BubbleTape)}] trade drain failed: {ex.Message}", LoggingLevel.Error);
                }
                drained++;
            }
        }

        public override void OnPaintChart(PaintChartEventArgs args)
        {
            try
            {
                if (_engine == null || _painter == null || CurrentChart == null) return;
                ApplySettings();
                _painter.Paint(args, CurrentChart, _engine.GetSnapshot(DateTime.UtcNow));
            }
            catch (Exception ex)
            {
                try { Core.Instance.Loggers.Log($"[{nameof(BubbleTape)}] paint failed: {ex.Message}", LoggingLevel.Error); }
                catch { }
            }
        }

        protected override void OnSettingsUpdated()
        {
            try
            {
                // Base Indicator.OnSettingsUpdated calls Refresh(); BubbleTape preserves live tape state.
                ApplySettings();
                ReloadWarmupIfSettingsRequireIt();
                CurrentChart?.RedrawBuffer();
            }
            catch (Exception ex)
            {
                try { Core.Instance.Loggers.Log($"[{nameof(BubbleTape)}] settings update failed: {ex.Message}", LoggingLevel.Error); }
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
                try { _warmupCts?.Cancel(); } catch { }
                try { _warmupCts?.Dispose(); } catch { }
                _warmupCts = null;
                _warmupTask = null;
                _queuedTradeCount = 0;
            }
            catch { }
            base.OnClear();
        }

        private void ApplySettings()
        {
            if (_engine != null)
            {
                _engine.UpdateSettings(new BubbleTapeSettings
                {
                    BarMinutes = BarMinutes,
                    PriceBandTicks = PriceBandTicks,
                    StrengthFilter = StrengthFilter,
                    LookbackDays = LookbackDays,
                    BubbleSource = BubbleSource,
                    MinCellVolume = MinCellVolume,
                    MinDeltaShare = MinDeltaShare,
                    MinClusterDelta = MinClusterDelta,
                    MaxClustersPerBarSide = MaxClustersPerBarSide,
                    MinTradeGroupVolume = MinTradeGroupVolume,
                    FallbackGroupWindowMs = FallbackGroupWindowMs,
                    ShowDeveloping = ShowDevelopingBubble,
                });
            }

            if (_painter != null)
            {
                _painter.MinBubbleDiameterPx = Math.Max(2.0, MinBubbleDiameterPx);
                _painter.MaxBubbleDiameterPx = Math.Max(_painter.MinBubbleDiameterPx, MaxBubbleDiameterPx);
                _painter.BubbleAlpha = Clamp(BubbleAlpha, 10, 230);
                _painter.BubbleEdgeAlpha = Clamp(BubbleEdgeAlpha, 30, 255);
                _painter.PanelEnabled = StatusPanelEnabled;
                _painter.PanelLeftOffsetPx = PanelLeftOffsetPx;
                _painter.PanelTopOffsetPx = PanelTopOffsetPx;
                _painter.PanelWidthPx = PanelWidthPx;
                _painter.FontSize = (float)Math.Max(7.0, Math.Min(18.0, FontSize));
            }
        }

        private void ReloadWarmupIfSettingsRequireIt()
        {
            string key = CurrentSettingsKey();
            bool wasWarmupEnabled = _lastHistoricalWarmupEnabled;
            bool warmupToggledOn = HistoricalWarmupEnabled && !wasWarmupEnabled;
            bool changed = !string.Equals(key, _settingsKey, StringComparison.Ordinal);
            _settingsKey = key;
            _lastHistoricalWarmupEnabled = HistoricalWarmupEnabled;

            if (!HistoricalWarmupEnabled)
            {
                if (wasWarmupEnabled)
                    CancelWarmup("live only");
                return;
            }

            if (Symbol == null || !_subscribed)
                return;
            if (!changed && !warmupToggledOn)
                return;

            ClearTradeQueue();
            _warmupApplied = false;
            _warmupBoundaryUtc = DateTime.UtcNow;
            StartWarmup(Symbol, _warmupBoundaryUtc);
        }

        private void CancelWarmup(string status)
        {
            try { _warmupCts?.Cancel(); } catch { }
            _warmupPending = false;
            _engine?.SetStatus(status);
        }

        private string CurrentSettingsKey()
        {
            return string.Join("|",
                BarMinutes,
                PriceBandTicks,
                StrengthFilter,
                LookbackDays,
                BubbleSource,
                MinCellVolume.ToString("0.####"),
                MinDeltaShare.ToString("0.####"),
                MinClusterDelta.ToString("0.####"),
                MaxClustersPerBarSide,
                MinTradeGroupVolume.ToString("0.####"),
                FallbackGroupWindowMs);
        }

        private void ClearTradeQueue()
        {
            while (_tradeQueue.TryDequeue(out _)) { }
            _queuedTradeCount = 0;
        }

        private void MaybeLogTradeQueueDrops()
        {
            var now = DateTime.UtcNow;
            if ((now - _lastTradeDropLogUtc).TotalSeconds < 30) return;
            _lastTradeDropLogUtc = now;
            long drops = Interlocked.Read(ref _tradeQueueDrops);
            try
            {
                Core.Instance.Loggers.Log(
                    $"[{nameof(BubbleTape)}] trade queue overloaded; dropped {drops} prints (cap={TradeQueueCap})",
                    LoggingLevel.Error);
            }
            catch { }
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

        private static DateTime NormalizeUtc(DateTime time)
        {
            if (time == default) return DateTime.UtcNow;
            if (time.Kind == DateTimeKind.Utc) return time;
            if (time.Kind == DateTimeKind.Local) return time.ToUniversalTime();
            return DateTime.SpecifyKind(time, DateTimeKind.Utc);
        }

        private static int Clamp(int value, int min, int max)
        {
            if (value < min) return min;
            if (value > max) return max;
            return value;
        }

        private sealed class WarmupResult
        {
            public bool Success;
            public string Error = "";
            public readonly List<TradePrint> Trades = new();

            public WarmupResult Fail(string error)
            {
                Success = false;
                Error = error ?? "";
                return this;
            }
        }
    }
}
