using System;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Globalization;
using System.IO;
using System.Text.Json;
using System.Text.Json.Serialization;
using TradingPlatform.BusinessLayer;
using TradingPlatform.BusinessLayer.Chart;
using TradingPlatform.BusinessLayer.Native;

namespace DirectiveSketchProbe
{
    public sealed class DirectiveSketchProbe : Indicator
    {
        private const string ProbeVersion = "0.5.0";

        [InputParameter("Draft JSON Path", sortIndex: 10)]
        public string DraftJsonPath =
            @"%USERPROFILE%\Documents\ExecAssistantRuntime\directive-sketch-probe.json";

        [InputParameter("Panel Left Offset (px)", sortIndex: 20,
            minimum: 0, maximum: 2000, increment: 5, decimalPlaces: 0)]
        public int PanelLeftOffsetPx = 24;

        [InputParameter("Panel Top Offset (px)", sortIndex: 21,
            minimum: 0, maximum: 1500, increment: 5, decimalPlaces: 0)]
        public int PanelTopOffsetPx = 28;

        [InputParameter("Panel Width (px)", sortIndex: 22,
            minimum: 180, maximum: 520, increment: 10, decimalPlaces: 0)]
        public int PanelWidthPx = 250;

        [InputParameter("Initial TP Height (ticks)", sortIndex: 23,
            minimum: 1, maximum: 200, increment: 1, decimalPlaces: 0)]
        public int InitialTargetHeightTicks = 8;

        [InputParameter("Minimum Order/Context Height (ticks)", sortIndex: 24,
            minimum: 1, maximum: 200, increment: 1, decimalPlaces: 0)]
        public int MinimumOrderContextHeightTicks = 4;

        [InputParameter("Minimum TP Height (ticks)", sortIndex: 25,
            minimum: 1, maximum: 200, increment: 1, decimalPlaces: 0)]
        public int MinimumTargetHeightTicks = 4;

        private IChart _subscribedChart;
        private Rectangle _panelRect = Rectangle.Empty;
        private SketchState _state = SketchState.Idle;
        private CaptureBox _orderBox;
        private CaptureBox _targetBox;
        private ChartPoint _dragStart;
        private bool _initialDragReachedMinimum;
        private BoundaryHandle _activeHandle = BoundaryHandle.None;
        private bool _dragging;
        private string _status = "click panel to arm";
        private string _lastPath = string.Empty;
        private string _lastError = string.Empty;
        private string _lastJsonSignature = string.Empty;

        public DirectiveSketchProbe()
            : base()
        {
            Name = "Directive Sketch Probe";
            SeparateWindow = false;
            OnBackGround = false;
            AllowFitAuto = false;
        }

        public override void OnPaintChart(PaintChartEventArgs args)
        {
            try
            {
                EnsureChartSubscription();
                PaintSketch(args);
            }
            catch (Exception ex)
            {
                _lastError = ex.Message;
            }
        }

        protected override void OnClear()
        {
            UnsubscribeChart();
            base.OnClear();
        }

        private void EnsureChartSubscription()
        {
            var chart = CurrentChart;
            if (ReferenceEquals(chart, _subscribedChart))
                return;

            UnsubscribeChart();
            _subscribedChart = chart;
            if (_subscribedChart != null)
            {
                _subscribedChart.MouseDown += ChartMouseDown;
                _subscribedChart.MouseMove += ChartMouseMove;
                _subscribedChart.MouseUp += ChartMouseUp;
            }
        }

        private void UnsubscribeChart()
        {
            if (_subscribedChart != null)
            {
                try { _subscribedChart.MouseDown -= ChartMouseDown; } catch { }
                try { _subscribedChart.MouseMove -= ChartMouseMove; } catch { }
                try { _subscribedChart.MouseUp -= ChartMouseUp; } catch { }
            }

            _subscribedChart = null;
            _dragging = false;
        }

        private void ChartMouseDown(object sender, ChartMouseNativeEventArgs e)
        {
            try
            {
                if (e == null)
                    return;

                if (e.Button == NativeMouseButtons.Right && _state != SketchState.Idle)
                {
                    CancelSketch("cancelled");
                    Consume(e, capture: false);
                    return;
                }

                if (e.Button != NativeMouseButtons.Left)
                    return;

                if (_panelRect.Contains(e.X, e.Y))
                {
                    if (_state == SketchState.Idle || _state == SketchState.DraftReady)
                        ArmOrderCapture();
                    else
                        CancelSketch("cancelled");
                    Consume(e, capture: false);
                    return;
                }

                if (_state == SketchState.DraftReady && TryHitHandle(e, out var handle))
                {
                    _activeHandle = handle;
                    _dragging = true;
                    Consume(e, capture: true);
                    return;
                }

                if (_state == SketchState.Idle || _state == SketchState.DraftReady)
                    return;

                if (!TryGetChartPoint(e, out var point))
                {
                    _status = "chart coordinate unavailable";
                    Consume(e, capture: false);
                    return;
                }

                _dragging = true;
                _dragStart = point;
                _activeHandle = BoundaryHandle.None;
                _initialDragReachedMinimum = false;
                UpdateBoxesFromDrag(point);
                Consume(e, capture: true);
            }
            catch (Exception ex)
            {
                _lastError = ex.Message;
            }
        }

        private void ChartMouseMove(object sender, ChartMouseNativeEventArgs e)
        {
            try
            {
                if (!_dragging || e == null)
                    return;

                if (!TryGetChartPoint(e, out var point))
                    return;

                if (_activeHandle != BoundaryHandle.None)
                    UpdateBoundaryFromHandle(_activeHandle, point.Price);
                else
                    UpdateBoxesFromDrag(point);
                Consume(e, capture: true);
            }
            catch (Exception ex)
            {
                _lastError = ex.Message;
            }
        }

        private void ChartMouseUp(object sender, ChartMouseNativeEventArgs e)
        {
            try
            {
                if (!_dragging || e == null)
                    return;

                _dragging = false;
                if (TryGetChartPoint(e, out var point))
                {
                    if (_activeHandle != BoundaryHandle.None)
                        UpdateBoundaryFromHandle(_activeHandle, point.Price);
                    else
                        UpdateBoxesFromDrag(point);
                }

                if (_activeHandle != BoundaryHandle.None)
                {
                    _activeHandle = BoundaryHandle.None;
                    CompleteDraft();
                    Consume(e, capture: false);
                    return;
                }

                if (!SketchIsUsable())
                {
                    _status = "Order/Context box too small";
                    WriteStateSnapshot("incomplete", null, _status);
                    Consume(e, capture: false);
                    return;
                }

                CompleteDraft();

                Consume(e, capture: false);
            }
            catch (Exception ex)
            {
                _lastError = ex.Message;
            }
        }

        private void ArmOrderCapture()
        {
            _state = SketchState.AwaitSketch;
            _orderBox = null;
            _targetBox = null;
            _dragging = false;
            _initialDragReachedMinimum = false;
            _activeHandle = BoundaryHandle.None;
            _lastError = string.Empty;
            _status = "drag toward TP";
            WriteStateSnapshot("armed", null, _status);
        }

        private void CancelSketch(string status)
        {
            _state = SketchState.Idle;
            _orderBox = null;
            _targetBox = null;
            _dragging = false;
            _initialDragReachedMinimum = false;
            _activeHandle = BoundaryHandle.None;
            _status = "click panel to arm";
            WriteStateSnapshot(status, null, "sketch cancelled");
        }

        private void CompleteDraft()
        {
            string side = ResolveSide(_orderBox, _targetBox);
            if (side == null)
            {
                _state = SketchState.AwaitSketch;
                _status = "drag farther from start";
                WriteStateSnapshot("ambiguous", null, _status);
                return;
            }

            var draft = BuildDraft(side);
            _state = SketchState.DraftReady;
            _status = $"{side.ToUpperInvariant()} draft written";
            WriteStateSnapshot("ok", draft, null);
        }

        private SketchDraft BuildDraft(string side)
        {
            double targetPrice = side == "long" ? _targetBox.High : _targetBox.Low;
            return new SketchDraft
            {
                Side = side,
                OrderContextRange = new PriceRange
                {
                    Lower = _orderBox.Low,
                    Upper = _orderBox.High,
                },
                TargetRange = new PriceRange
                {
                    Lower = _targetBox.Low,
                    Upper = _targetBox.High,
                },
                TargetPrice = targetPrice,
                TimeRange = new TimeRange
                {
                    Left = MinTime(_orderBox, _targetBox).ToString("O", CultureInfo.InvariantCulture),
                    Right = MaxTime(_orderBox, _targetBox).ToString("O", CultureInfo.InvariantCulture),
                    LeftTicks = MinTime(_orderBox, _targetBox).Ticks,
                    RightTicks = MaxTime(_orderBox, _targetBox).Ticks,
                },
                Source = new SketchSource
                {
                    Kind = "custom_one_drag_two_box",
                    Version = ProbeVersion,
                },
            };
        }

        private static string ResolveSide(CaptureBox order, CaptureBox target)
        {
            if (order == null || target == null)
                return null;
            if (target.Low >= order.High)
                return "long";
            if (target.High <= order.Low)
                return "short";
            return null;
        }

        private bool TryHitHandle(ChartMouseNativeEventArgs e, out BoundaryHandle handle)
        {
            handle = BoundaryHandle.None;
            var converter = e.Window?.CoordinatesConverter
                ?? _subscribedChart?.MainWindow?.CoordinatesConverter
                ?? CurrentChart?.MainWindow?.CoordinatesConverter;
            if (converter == null || _orderBox == null || _targetBox == null)
                return false;

            foreach (var item in GetHandlePoints(converter))
            {
                double dx = e.X - item.X;
                double dy = e.Y - item.Y;
                if (Math.Sqrt(dx * dx + dy * dy) <= 10.0)
                {
                    handle = item.Handle;
                    return true;
                }
            }

            return false;
        }

        private void UpdateBoundaryFromHandle(BoundaryHandle handle, double rawPrice)
        {
            string side = ResolveSide(_orderBox, _targetBox);
            if (side == null)
                return;

            double price = RoundToTick(rawPrice);
            double tick = GetTickSize();
            double minOrderHeight = Math.Max(tick, Math.Max(1, MinimumOrderContextHeightTicks) * tick);
            double minTargetHeight = Math.Max(tick, Math.Max(1, MinimumTargetHeightTicks) * tick);
            DateTime left = MinTime(_orderBox, _targetBox);
            DateTime right = MaxTime(_orderBox, _targetBox);

            if (side == "long")
            {
                double orderLow = _orderBox.Low;
                double shared = _orderBox.High;
                double targetHigh = _targetBox.High;

                switch (handle)
                {
                    case BoundaryHandle.OrderOuter:
                        orderLow = Math.Min(price, shared - minOrderHeight);
                        break;
                    case BoundaryHandle.Shared:
                        shared = Clamp(price, orderLow + minOrderHeight, targetHigh - minTargetHeight);
                        break;
                    case BoundaryHandle.TargetOuter:
                        targetHigh = Math.Max(price, shared + minTargetHeight);
                        break;
                }

                _orderBox = CaptureBox.FromBounds(left, right, orderLow, shared);
                _targetBox = CaptureBox.FromBounds(left, right, shared, targetHigh);
                _status = $"LONG TP {FormatSketchPrice(targetHigh)}";
            }
            else
            {
                double targetLow = _targetBox.Low;
                double shared = _orderBox.Low;
                double orderHigh = _orderBox.High;

                switch (handle)
                {
                    case BoundaryHandle.OrderOuter:
                        orderHigh = Math.Max(price, shared + minOrderHeight);
                        break;
                    case BoundaryHandle.Shared:
                        shared = Clamp(price, targetLow + minTargetHeight, orderHigh - minOrderHeight);
                        break;
                    case BoundaryHandle.TargetOuter:
                        targetLow = Math.Min(price, shared - minTargetHeight);
                        break;
                }

                _orderBox = CaptureBox.FromBounds(left, right, shared, orderHigh);
                _targetBox = CaptureBox.FromBounds(left, right, targetLow, shared);
                _status = $"SHORT TP {FormatSketchPrice(targetLow)}";
            }
        }

        private void UpdateBoxesFromDrag(ChartPoint current)
        {
            double tick = GetTickSize();
            double anchor = RoundToTick(_dragStart.Price);
            double price = RoundToTick(current.Price);
            double initialTargetHeight = Math.Max(tick, Math.Max(1, InitialTargetHeightTicks) * tick);
            double minOrderHeight = Math.Max(tick, Math.Max(1, MinimumOrderContextHeightTicks) * tick);
            double minTargetHeight = Math.Max(tick, Math.Max(1, MinimumTargetHeightTicks) * tick);
            _initialDragReachedMinimum = Math.Abs(price - anchor) >= minOrderHeight;

            if (price >= anchor)
            {
                double orderHigh = Math.Max(anchor + minOrderHeight, price);
                double targetHigh = orderHigh + Math.Max(minTargetHeight, initialTargetHeight);
                _orderBox = CaptureBox.FromBounds(_dragStart.Time, current.Time, anchor, orderHigh);
                _targetBox = CaptureBox.FromBounds(_dragStart.Time, current.Time, orderHigh, targetHigh);
                _status = $"LONG order {FormatSketchPrice(anchor)}-{FormatSketchPrice(orderHigh)}";
            }
            else
            {
                double orderLow = Math.Min(anchor - minOrderHeight, price);
                double targetLow = orderLow - Math.Max(minTargetHeight, initialTargetHeight);
                _orderBox = CaptureBox.FromBounds(_dragStart.Time, current.Time, orderLow, anchor);
                _targetBox = CaptureBox.FromBounds(_dragStart.Time, current.Time, targetLow, orderLow);
                _status = $"SHORT order {FormatSketchPrice(orderLow)}-{FormatSketchPrice(anchor)}";
            }
        }

        private bool SketchIsUsable()
        {
            if (_orderBox == null || _targetBox == null || !_initialDragReachedMinimum)
                return false;

            double tick = GetTickSize();
            double minOrderHeight = Math.Max(tick, Math.Max(1, MinimumOrderContextHeightTicks) * tick);
            double minTargetHeight = Math.Max(tick, Math.Max(1, MinimumTargetHeightTicks) * tick);
            return _orderBox.High - _orderBox.Low >= minOrderHeight
                   && _targetBox.High - _targetBox.Low >= minTargetHeight;
        }

        private static double Clamp(double value, double min, double max)
            => value < min ? min : value > max ? max : value;

        private void WriteStateSnapshot(string status, SketchDraft draft, string message)
        {
            try
            {
                var snapshot = new SketchSnapshot
                {
                    SchemaVersion = 1,
                    Source = nameof(DirectiveSketchProbe),
                    Version = ProbeVersion,
                    GeneratedAtUtc = DateTime.UtcNow.ToString("O", CultureInfo.InvariantCulture),
                    Status = status,
                    Message = message,
                    ChartId = _subscribedChart?.ID ?? CurrentChart?.ID,
                    Symbol = Symbol?.Name,
                    TickSize = GetTickSize(),
                    State = _state.ToString(),
                    ActiveDraft = draft,
                    OrderBox = _orderBox?.ToDto(),
                    TargetBox = _targetBox?.ToDto(),
                };

                string signature = snapshot.Signature();
                if (string.Equals(signature, _lastJsonSignature, StringComparison.Ordinal))
                    return;

                string path = ExpandPath(DraftJsonPath);
                string json = JsonSerializer.Serialize(snapshot, JsonOptions);
                AtomicWrite(path, json);
                _lastJsonSignature = signature;
                _lastPath = path;
                _lastError = string.Empty;
            }
            catch (Exception ex)
            {
                _lastError = ex.Message;
            }
        }

        private bool TryGetChartPoint(ChartMouseNativeEventArgs e, out ChartPoint point)
        {
            point = default;
            var converter = e.Window?.CoordinatesConverter
                ?? _subscribedChart?.MainWindow?.CoordinatesConverter
                ?? CurrentChart?.MainWindow?.CoordinatesConverter;
            if (converter == null)
                return false;

            try
            {
                point = new ChartPoint
                {
                    Time = converter.GetTime(e.X),
                    Price = RoundToTick(converter.GetPrice(e.Y)),
                    X = e.X,
                    Y = e.Y,
                };
                return point.Time.Ticks > 0 && double.IsFinite(point.Price) && point.Price > 0;
            }
            catch
            {
                return false;
            }
        }

        private void Consume(ChartMouseNativeEventArgs e, bool capture)
        {
            e.Handled = true;
            e.NeedRedraw = true;
            e.NeedMouseCapture = capture;
            TryRedraw();
        }

        private void PaintSketch(PaintChartEventArgs args)
        {
            if (args?.Graphics == null)
                return;

            var chart = _subscribedChart ?? CurrentChart;
            var converter = chart?.MainWindow?.CoordinatesConverter;
            var rect = args.Rectangle;
            using var oldSmoothing = new SmoothingGuard(args.Graphics, SmoothingMode.AntiAlias);

            PaintCaptureBox(args.Graphics, rect, converter, _orderBox, BoxRole.Order, preview: _dragging);
            PaintCaptureBox(args.Graphics, rect, converter, _targetBox, BoxRole.Target, preview: _dragging);
            PaintBoundaryHandles(args.Graphics, rect, converter);

            PaintPanel(args.Graphics, rect);
        }

        private void PaintBoundaryHandles(
            Graphics g,
            Rectangle chartRect,
            IChartWindowCoordinatesConverter converter)
        {
            if (converter == null || _orderBox == null || _targetBox == null)
                return;

            foreach (var item in GetHandlePoints(converter))
            {
                if (item.X < chartRect.Left || item.X > chartRect.Right
                    || item.Y < chartRect.Top || item.Y > chartRect.Bottom)
                    continue;

                bool active = _activeHandle == item.Handle;
                int size = active ? 10 : 8;
                int half = size / 2;
                var rect = new Rectangle(item.X - half, item.Y - half, size, size);
                using var fill = new SolidBrush(Color.FromArgb(active ? 235 : 210, 8, 24, 32));
                using var edge = new Pen(
                    active ? Color.FromArgb(255, 255, 246, 0) : Color.FromArgb(215, 158, 170, 178),
                    active ? 1.7f : 1.2f);
                g.FillEllipse(fill, rect);
                g.DrawEllipse(edge, rect);
            }
        }

        private HandlePoint[] GetHandlePoints(IChartWindowCoordinatesConverter converter)
        {
            string side = ResolveSide(_orderBox, _targetBox);
            if (side == null || converter == null)
                return Array.Empty<HandlePoint>();

            DateTime left = MinTime(_orderBox, _targetBox);
            DateTime right = MaxTime(_orderBox, _targetBox);
            double xLeft = converter.GetChartX(left);
            double xRight = converter.GetChartX(right);
            int x = (int)Math.Round((xLeft + xRight) / 2.0);

            if (side == "long")
            {
                return new[]
                {
                    new HandlePoint(BoundaryHandle.TargetOuter, x, (int)Math.Round(converter.GetChartY(_targetBox.High))),
                    new HandlePoint(BoundaryHandle.Shared, x, (int)Math.Round(converter.GetChartY(_orderBox.High))),
                    new HandlePoint(BoundaryHandle.OrderOuter, x, (int)Math.Round(converter.GetChartY(_orderBox.Low))),
                };
            }

            return new[]
            {
                new HandlePoint(BoundaryHandle.OrderOuter, x, (int)Math.Round(converter.GetChartY(_orderBox.High))),
                new HandlePoint(BoundaryHandle.Shared, x, (int)Math.Round(converter.GetChartY(_orderBox.Low))),
                new HandlePoint(BoundaryHandle.TargetOuter, x, (int)Math.Round(converter.GetChartY(_targetBox.Low))),
            };
        }

        private void PaintPanel(Graphics g, Rectangle chartRect)
        {
            int w = Math.Max(180, PanelWidthPx);
            int h = string.IsNullOrWhiteSpace(_lastError) ? 58 : 76;
            int x = Math.Min(chartRect.Right - w - 4,
                Math.Max(chartRect.Left + 4, chartRect.Left + PanelLeftOffsetPx));
            int y = Math.Min(chartRect.Bottom - h - 4,
                Math.Max(chartRect.Top + 4, chartRect.Top + PanelTopOffsetPx));
            _panelRect = new Rectangle(x, y, w, h);

            Color panelColor = _state == SketchState.Idle || _state == SketchState.DraftReady
                ? Color.FromArgb(178, 8, 24, 32)
                : Color.FromArgb(205, 9, 36, 48);
            Color edgeColor = _state == SketchState.Idle || _state == SketchState.DraftReady
                ? Color.FromArgb(120, 22, 42, 54)
                : Color.FromArgb(205, 55, 219, 186);

            using var bg = new SolidBrush(panelColor);
            using var edge = new Pen(edgeColor, 1.0f);
            using var titleBrush = new SolidBrush(Color.FromArgb(255, 255, 246, 0));
            using var bodyBrush = new SolidBrush(Color.FromArgb(240, 255, 246, 0));
            using var warnBrush = new SolidBrush(Color.FromArgb(240, 245, 190, 90));
            using var titleFont = new Font("Consolas", 8.5f, FontStyle.Bold);
            using var bodyFont = new Font("Consolas", 8.0f, FontStyle.Bold);

            g.FillRectangle(bg, _panelRect);
            g.DrawRectangle(edge, _panelRect);
            g.DrawString("Directive Sketch", titleFont, titleBrush, x + 8, y + 5);
            g.DrawString(_status, bodyFont, bodyBrush, x + 8, y + 25);
            string path = string.IsNullOrWhiteSpace(_lastPath) ? ExpandPath(DraftJsonPath) : _lastPath;
            g.DrawString(AbbrevPath(path), bodyFont, bodyBrush, x + 8, y + 42);
            if (!string.IsNullOrWhiteSpace(_lastError))
                g.DrawString(_lastError, bodyFont, warnBrush, x + 8, y + 59);
        }

        private void PaintCaptureBox(
            Graphics g,
            Rectangle chartRect,
            IChartWindowCoordinatesConverter converter,
            CaptureBox box,
            BoxRole role,
            bool preview = false)
        {
            if (box == null || converter == null)
                return;

            int xLeft;
            int xRight;
            int yTop;
            int yBottom;
            try
            {
                xLeft = (int)Math.Round(converter.GetChartX(box.LeftTime));
                xRight = (int)Math.Round(converter.GetChartX(box.RightTime));
                yTop = (int)Math.Round(converter.GetChartY(box.High));
                yBottom = (int)Math.Round(converter.GetChartY(box.Low));
            }
            catch
            {
                return;
            }

            if (xRight < xLeft)
                (xLeft, xRight) = (xRight, xLeft);
            if (yBottom < yTop)
                (yTop, yBottom) = (yBottom, yTop);

            xLeft = Math.Max(chartRect.Left, xLeft);
            xRight = Math.Min(chartRect.Right, xRight);
            yTop = Math.Max(chartRect.Top, yTop);
            yBottom = Math.Min(chartRect.Bottom, yBottom);
            if (xRight <= xLeft)
                xRight = Math.Min(chartRect.Right, xLeft + 2);
            if (yBottom <= yTop)
                yBottom = Math.Min(chartRect.Bottom, yTop + 2);

            string side = ResolveSide(_orderBox, _targetBox);
            Color color = BoxColor(role, side);
            int fillAlpha = preview ? 38 : 56;
            int edgeAlpha = preview ? 118 : 168;
            using var fill = new SolidBrush(Color.FromArgb(fillAlpha, color));
            using var edge = new Pen(Color.FromArgb(edgeAlpha, color), preview ? 1.0f : 1.3f);
            if (preview)
                edge.DashStyle = DashStyle.Dash;

            var drawRect = new Rectangle(xLeft, yTop, Math.Max(2, xRight - xLeft), Math.Max(2, yBottom - yTop));
            g.FillRectangle(fill, drawRect);
            g.DrawRectangle(edge, drawRect);

            string label = role == BoxRole.Order
                ? $"{SideTitle(side)} Order/Context: {FormatSketchPrice(box.Low)} - {FormatSketchPrice(box.High)}"
                : $"TP Target: {FormatSketchPrice(role == BoxRole.Target ? TargetLabelPrice(box) : box.High)}";
            var placement = LabelPlacement.TopOutside;
            if (role == BoxRole.Target && side == "short")
                placement = LabelPlacement.BottomOutside;
            else if (role == BoxRole.Order && side == "long")
                placement = LabelPlacement.BottomOutside;
            DrawBoxLabel(g, drawRect, label, placement);
        }

        private static Color BoxColor(BoxRole role, string side)
        {
            if (role == BoxRole.Target)
                return Color.FromArgb(72, 142, 238);
            if (side == "long")
                return Color.FromArgb(55, 205, 118);
            if (side == "short")
                return Color.FromArgb(235, 96, 47);
            return Color.FromArgb(158, 170, 178);
        }

        private static string SideTitle(string side)
        {
            if (side == "long")
                return "LONG";
            if (side == "short")
                return "SHORT";
            return "Order";
        }

        private double TargetLabelPrice(CaptureBox target)
        {
            string side = ResolveSide(_orderBox, target);
            if (side == "short")
                return target.Low;
            return target.High;
        }

        private static void DrawBoxLabel(Graphics g, Rectangle rect, string text, LabelPlacement placement)
        {
            using var font = new Font("Consolas", 8.0f, FontStyle.Bold);
            SizeF size = g.MeasureString(text, font);
            int padX = 5;
            int padY = 2;
            float labelWidth = size.Width + padX * 2;
            float labelHeight = size.Height + padY * 2;
            float x = Math.Max(0, rect.Left + (rect.Width - labelWidth) / 2.0f);
            float y = placement == LabelPlacement.BottomOutside
                ? rect.Bottom + 5
                : Math.Max(0, rect.Top - labelHeight - 5);
            var bgRect = new RectangleF(x, y, labelWidth, labelHeight);

            using var bg = new SolidBrush(Color.FromArgb(190, 8, 24, 32));
            using var brush = new SolidBrush(Color.FromArgb(255, 255, 246, 0));
            using var format = new StringFormat
            {
                Alignment = StringAlignment.Center,
                LineAlignment = StringAlignment.Center,
                Trimming = StringTrimming.EllipsisCharacter,
            };
            g.FillRectangle(bg, bgRect);
            g.DrawString(text, font, brush, bgRect, format);
        }

        private string FormatSketchPrice(double price)
        {
            try
            {
                if (Symbol != null)
                    return Symbol.FormatPrice(price);
            }
            catch { }

            return price.ToString("0.00", CultureInfo.InvariantCulture);
        }

        private double RoundToTick(double price)
        {
            double tick = GetTickSize();
            if (tick <= 0 || !double.IsFinite(price))
                return price;
            return Math.Round(price / tick, MidpointRounding.AwayFromZero) * tick;
        }

        private double GetTickSize()
            => Symbol?.TickSize > 0
                ? Symbol.TickSize
                : _subscribedChart?.TickSize > 0 ? _subscribedChart.TickSize : 0.25;

        private static DateTime MinTime(CaptureBox a, CaptureBox b)
            => a.LeftTime <= b.LeftTime ? a.LeftTime : b.LeftTime;

        private static DateTime MaxTime(CaptureBox a, CaptureBox b)
            => a.RightTime >= b.RightTime ? a.RightTime : b.RightTime;

        private static string ExpandPath(string path)
        {
            string expanded = Environment.ExpandEnvironmentVariables(
                string.IsNullOrWhiteSpace(path)
                    ? @"%USERPROFILE%\Documents\ExecAssistantRuntime\directive-sketch-probe.json"
                    : path);
            return Path.GetFullPath(expanded);
        }

        private static void AtomicWrite(string path, string content)
        {
            string directory = Path.GetDirectoryName(path);
            if (!string.IsNullOrEmpty(directory))
                Directory.CreateDirectory(directory);

            string temp = path + "." + Guid.NewGuid().ToString("N", CultureInfo.InvariantCulture) + ".tmp";
            File.WriteAllText(temp, content);
            File.Move(temp, path, overwrite: true);
        }

        private static string AbbrevPath(string path)
        {
            if (string.IsNullOrWhiteSpace(path) || path.Length <= 44)
                return path;
            return "..." + path.Substring(path.Length - 41);
        }

        private void TryRedraw()
        {
            try { _subscribedChart?.RedrawBuffer(); } catch { }
        }

        private static readonly JsonSerializerOptions JsonOptions = new()
        {
            WriteIndented = true,
            PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
            DefaultIgnoreCondition = JsonIgnoreCondition.WhenWritingNull,
        };

        private enum SketchState
        {
            Idle,
            AwaitSketch,
            DraftReady,
        }

        private enum BoxRole
        {
            Order,
            Target,
        }

        private enum BoundaryHandle
        {
            None,
            OrderOuter,
            Shared,
            TargetOuter,
        }

        private enum LabelPlacement
        {
            TopOutside,
            BottomOutside,
        }

        private readonly struct HandlePoint
        {
            public BoundaryHandle Handle { get; }
            public int X { get; }
            public int Y { get; }

            public HandlePoint(BoundaryHandle handle, int x, int y)
            {
                Handle = handle;
                X = x;
                Y = y;
            }
        }

        private readonly struct ChartPoint
        {
            public DateTime Time { get; init; }
            public double Price { get; init; }
            public int X { get; init; }
            public int Y { get; init; }
        }

        private sealed class CaptureBox
        {
            private ChartPoint Start { get; init; }
            private ChartPoint End { get; init; }

            public DateTime LeftTime => Start.Time <= End.Time ? Start.Time : End.Time;
            public DateTime RightTime => Start.Time >= End.Time ? Start.Time : End.Time;
            public double Low => Math.Min(Start.Price, End.Price);
            public double High => Math.Max(Start.Price, End.Price);

            public static CaptureBox FromStart(ChartPoint point)
                => new() { Start = point, End = point };

            public static CaptureBox FromBounds(DateTime timeA, DateTime timeB, double low, double high)
                => new()
                {
                    Start = new ChartPoint
                    {
                        Time = timeA <= timeB ? timeA : timeB,
                        Price = high,
                    },
                    End = new ChartPoint
                    {
                        Time = timeA >= timeB ? timeA : timeB,
                        Price = low,
                    },
                };

            public CaptureBox WithEnd(ChartPoint point)
                => new() { Start = Start, End = point };

            public CaptureBox Normalized(double tickSize)
                => new()
                {
                    Start = new ChartPoint
                    {
                        Time = LeftTime,
                        Price = High,
                        X = Math.Min(Start.X, End.X),
                        Y = Math.Min(Start.Y, End.Y),
                    },
                    End = new ChartPoint
                    {
                        Time = RightTime,
                        Price = Low,
                        X = Math.Max(Start.X, End.X),
                        Y = Math.Max(Start.Y, End.Y),
                    },
                };

            public bool IsUsable(double tickSize)
                => RightTime > LeftTime
                   && High - Low >= Math.Max(tickSize, 0.01);

            public CaptureBoxDto ToDto()
                => new()
                {
                    Low = Low,
                    High = High,
                    Left = LeftTime.ToString("O", CultureInfo.InvariantCulture),
                    Right = RightTime.ToString("O", CultureInfo.InvariantCulture),
                    LeftTicks = LeftTime.Ticks,
                    RightTicks = RightTime.Ticks,
                };
        }

        private sealed class SmoothingGuard : IDisposable
        {
            private readonly Graphics _graphics;
            private readonly SmoothingMode _previous;

            public SmoothingGuard(Graphics graphics, SmoothingMode mode)
            {
                _graphics = graphics;
                _previous = graphics.SmoothingMode;
                graphics.SmoothingMode = mode;
            }

            public void Dispose()
            {
                _graphics.SmoothingMode = _previous;
            }
        }

        private sealed class SketchSnapshot
        {
            public int SchemaVersion { get; set; }
            public string Source { get; set; }
            public string Version { get; set; }
            public string GeneratedAtUtc { get; set; }
            public string Status { get; set; }
            public string Message { get; set; }
            public string ChartId { get; set; }
            public string Symbol { get; set; }
            public double TickSize { get; set; }
            public string State { get; set; }
            public CaptureBoxDto OrderBox { get; set; }
            public CaptureBoxDto TargetBox { get; set; }
            public SketchDraft ActiveDraft { get; set; }

            public string Signature()
                => string.Join("|",
                    Status ?? string.Empty,
                    State ?? string.Empty,
                    OrderBox?.Low.ToString("R", CultureInfo.InvariantCulture) ?? string.Empty,
                    OrderBox?.High.ToString("R", CultureInfo.InvariantCulture) ?? string.Empty,
                    TargetBox?.Low.ToString("R", CultureInfo.InvariantCulture) ?? string.Empty,
                    TargetBox?.High.ToString("R", CultureInfo.InvariantCulture) ?? string.Empty,
                    ActiveDraft?.Side ?? string.Empty,
                    ActiveDraft?.TargetPrice.ToString("R", CultureInfo.InvariantCulture) ?? string.Empty);
        }

        private sealed class SketchDraft
        {
            public string Side { get; set; }
            public PriceRange OrderContextRange { get; set; }
            public PriceRange TargetRange { get; set; }
            public double TargetPrice { get; set; }
            public TimeRange TimeRange { get; set; }
            public SketchSource Source { get; set; }
        }

        private sealed class PriceRange
        {
            public double Lower { get; set; }
            public double Upper { get; set; }
        }

        private sealed class TimeRange
        {
            public string Left { get; set; }
            public string Right { get; set; }
            public long LeftTicks { get; set; }
            public long RightTicks { get; set; }
        }

        private sealed class SketchSource
        {
            public string Kind { get; set; }
            public string Version { get; set; }
        }

        private sealed class CaptureBoxDto
        {
            public double Low { get; set; }
            public double High { get; set; }
            public string Left { get; set; }
            public string Right { get; set; }
            public long LeftTicks { get; set; }
            public long RightTicks { get; set; }
        }
    }
}
