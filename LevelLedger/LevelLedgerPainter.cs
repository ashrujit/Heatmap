using System;
using System.Collections.Generic;
using System.Drawing;
using System.Drawing.Drawing2D;
using TradingPlatform.BusinessLayer;
using TradingPlatform.BusinessLayer.Chart;

namespace LevelLedger
{
    internal sealed class LevelLedgerPainter
    {
        private readonly double _tickSize;

        public int LeftOffsetPx = 90;
        public int TopOffsetPx = 90;
        public int PanelWidthPx = 300;
        public int VisibleRows = 10;
        public float FontSize = 9.0f;
        public bool PanelEnabled = true;
        public bool VodBuildDotsEnabled = true;
        public int VodBuildDotSizePx = 7;
        public int VodBuildDotAlpha = 175;
        public bool BuildBandsEnabled = true;
        public int BuildBandActiveAlpha = 46;
        public int BuildBandBreachedAlpha = 18;
        public int BuildBandContestedAlpha = 24;
        public bool VodStacksEnabled = true;
        public bool L2Stale;
        public Rectangle LastHitRect;

        private static readonly Color Border = Color.FromArgb(150, 110, 110, 115);
        private static readonly Color Bg = Color.FromArgb(58, 20, 22, 26);
        private static readonly Color HeaderBg = Color.FromArgb(92, 35, 38, 45);
        private static readonly Color HeaderFg = Color.FromArgb(235, 225, 225, 225);
        private static readonly Color Muted = Color.FromArgb(165, 175, 175, 175);
        private static readonly Color BullDominance = Color.FromArgb(90, 225, 135);
        private static readonly Color BearDominance = Color.FromArgb(245, 90, 75);
        private static readonly Color BuyImpulse = Color.FromArgb(115, 190, 235);
        private static readonly Color SellImpulse = Color.FromArgb(235, 135, 95);
        private static readonly Color Neutral = Color.FromArgb(190, 185, 175);
        private static readonly Color Chaos = Color.FromArgb(245, 190, 70);
        private static readonly Color BidChaos = Color.FromArgb(95, 165, 235);
        private static readonly Color AskChaos = Color.FromArgb(238, 132, 72);
        private static readonly Color StackDemand = Color.FromArgb(75, 185, 225);
        private static readonly Color StackSupply = Color.FromArgb(238, 132, 72);

        public LevelLedgerPainter(double tickSize)
        {
            _tickSize = tickSize > 0 ? tickSize : 0.25;
        }

        public void Paint(
            PaintChartEventArgs args,
            IChart chart,
            LedgerSnapshot snapshot,
            IReadOnlyList<VodBuildDot> vodBuildDots,
            IReadOnlyList<BuildBandOverlay> buildBands,
            IReadOnlyList<VodStackOverlay> vodStacks)
        {
            var g = args.Graphics;
            var rect = args.Rectangle;
            if (rect.Width <= 0 || rect.Height <= 0) return;

            var prev = g.SmoothingMode;
            g.SmoothingMode = SmoothingMode.AntiAlias;
            try
            {
                if (BuildBandsEnabled)
                    DrawBuildBands(g, chart, rect, buildBands);
                if (VodStacksEnabled)
                    DrawVodStacks(g, chart, rect, vodStacks);
                if (VodBuildDotsEnabled)
                    DrawVodBuildDots(g, chart, rect, vodBuildDots);
                if (L2Stale)
                    DrawStaleBadge(g, rect);
                if (!PanelEnabled)
                {
                    LastHitRect = Rectangle.Empty;
                    return;
                }
                DrawPanel(g, rect, snapshot);
            }
            finally
            {
                g.SmoothingMode = prev;
            }
        }

        private void DrawPanel(Graphics g, Rectangle rect, LedgerSnapshot snapshot)
        {
            int rowH = Math.Max(15, (int)Math.Ceiling(FontSize + 7));
            int headerH = Math.Max(22, rowH + 5);
            int w = Math.Max(180, PanelWidthPx);
            int h = headerH + Math.Max(1, VisibleRows) * rowH + 8;
            int x = Math.Min(rect.Right - w - 4, Math.Max(rect.Left + 4, rect.Left + LeftOffsetPx));
            int y = Math.Min(rect.Bottom - h - 4, Math.Max(rect.Top + 4, rect.Top + TopOffsetPx));

            LastHitRect = new Rectangle(x, y, w, h);
            using (var bg = new SolidBrush(Bg))
                g.FillRectangle(bg, x, y, w, h);
            using (var header = new SolidBrush(HeaderBg))
                g.FillRectangle(header, x, y, w, headerH);
            using (var pen = new Pen(Border, 1f))
                g.DrawRectangle(pen, x, y, w, h);

            using var headerFont = new Font("Segoe UI", FontSize, FontStyle.Bold);
            using var rowFont = new Font("Consolas", Math.Max(7.0f, FontSize - 0.2f), FontStyle.Regular);
            using var headerBrush = new SolidBrush(HeaderFg);
            using var mutedBrush = new SolidBrush(Muted);

            string title = "Level Ledger";
            g.DrawString(title, headerFont, headerBrush, x + 8, y + 3);

            string status = snapshot.IsActive
                ? $"@{ToNy(snapshot.ActivatedUtc.Value):HH:mm}  -{snapshot.LookbackMinutes}m"
                : "click";
            if (snapshot.IsActive && snapshot.FocusTick.HasValue)
                status += $"  {Abbrev(snapshot.FocusTick.Value)}";
            var statusSize = g.MeasureString(status, rowFont);
            g.DrawString(status, rowFont, mutedBrush, x + w - statusSize.Width - 8, y + 5);

            if (!snapshot.IsActive || snapshot.Rows == null || snapshot.Rows.Count == 0)
                return;

            int rowY = y + headerH + 4;
            foreach (var row in snapshot.Rows)
            {
                DrawRow(g, rowFont, row, x + 8, rowY, w - 16);
                rowY += rowH;
                if (rowY > y + h - rowH) break;
            }
        }

        private void DrawBuildBands(Graphics g, IChart chart, Rectangle rect, IReadOnlyList<BuildBandOverlay> bands)
        {
            if (chart == null || bands == null || bands.Count == 0) return;
            var cv = chart.MainWindow?.CoordinatesConverter;
            if (cv == null) return;

            foreach (var band in bands)
            {
                int xStart;
                try { xStart = (int)cv.GetChartX(band.StartUtc); }
                catch { continue; }

                int xLeft = Math.Max(rect.Left, xStart);
                int xRight = rect.Right;
                if (xRight <= xLeft) continue;

                int yTop, yBottom;
                try
                {
                    yTop = (int)cv.GetChartY(band.MaxTick * _tickSize);
                    yBottom = (int)cv.GetChartY(band.MinTick * _tickSize);
                }
                catch { continue; }

                if (yBottom < rect.Top || yTop > rect.Bottom) continue;
                yTop = Math.Max(rect.Top, yTop);
                yBottom = Math.Min(rect.Bottom, yBottom);
                if (yBottom <= yTop) yBottom = yTop + 1;

                if (band.Role == BuildBandRole.Contested)
                {
                    int contestedFillAlpha = Clamp(BuildBandContestedAlpha, 1, 255);
                    int contestedEdgeAlpha = Clamp(contestedFillAlpha + 70, 1, 255);
                    using var contestedFill = new SolidBrush(Color.FromArgb(contestedFillAlpha, Chaos));
                    using var contestedEdge = new Pen(Color.FromArgb(contestedEdgeAlpha, Chaos), 1.2f)
                    {
                        DashStyle = DashStyle.Dash,
                    };
                    g.FillRectangle(contestedFill, xLeft, yTop, xRight - xLeft, yBottom - yTop);
                    g.DrawLine(contestedEdge, xLeft, yTop, xRight, yTop);
                    g.DrawLine(contestedEdge, xLeft, yBottom, xRight, yBottom);
                    continue;
                }

                bool failed = band.State == BuildBandState.Failed || band.BreachedUtc.HasValue;
                bool thesis = band.IsThesis && !failed;
                int baseAlpha = failed ? BuildBandBreachedAlpha : BuildBandActiveAlpha;
                if (band.State == BuildBandState.Tested && !failed)
                    baseAlpha += 12;
                if (thesis)
                    baseAlpha += 24;

                int fillAlpha = Clamp(baseAlpha, 1, 255);
                int edgeAlpha = Clamp(fillAlpha + (failed ? 28 : thesis ? 105 : 65), 1, 255);
                Color sideColor = band.Side == BuildBandSide.Supply ? BearDominance : BullDominance;

                using var railFill = new SolidBrush(Color.FromArgb(fillAlpha, sideColor));
                using var edge = new Pen(Color.FromArgb(edgeAlpha, sideColor), thesis ? 2.2f : failed ? 1f : 1.4f);
                if (failed)
                    edge.DashStyle = DashStyle.Dot;

                g.FillRectangle(railFill, xLeft, yTop, xRight - xLeft, yBottom - yTop);
                g.DrawLine(edge, xLeft, yTop, xRight, yTop);
                g.DrawLine(edge, xLeft, yBottom, xRight, yBottom);
                if (thesis)
                {
                    int capW = 5;
                    using var cap = new SolidBrush(Color.FromArgb(Clamp(edgeAlpha + 25, 1, 255), sideColor));
                    g.FillRectangle(cap, rect.Right - capW, yTop, capW, Math.Max(2, yBottom - yTop));
                }
            }
        }

        private void DrawVodStacks(Graphics g, IChart chart, Rectangle rect, IReadOnlyList<VodStackOverlay> stacks)
        {
            if (chart == null || stacks == null || stacks.Count == 0) return;
            var cv = chart.MainWindow?.CoordinatesConverter;
            if (cv == null) return;

            foreach (var stack in stacks)
            {
                bool faded = stack.FadedUtc.HasValue;
                DrawVodStackCenter(g, cv, rect, stack, faded);

                if (stack.Edges == null) continue;
                foreach (var edge in stack.Edges)
                {
                    if (!edge.ConfirmedUtc.HasValue) continue;
                    DrawVodStackEdge(g, cv, rect, edge, faded);
                }
            }
        }

        private void DrawVodStackCenter(
            Graphics g,
            IChartWindowCoordinatesConverter cv,
            Rectangle rect,
            VodStackOverlay stack,
            bool faded)
        {
            int xStart;
            int y;
            try
            {
                xStart = (int)cv.GetChartX(stack.StartUtc);
                y = (int)cv.GetChartY(stack.CenterTick * _tickSize);
            }
            catch { return; }

            if (y < rect.Top || y > rect.Bottom) return;
            int xLeft = Math.Max(rect.Left, xStart);
            if (rect.Right <= xLeft) return;

            int alpha = faded ? 42 : 165;
            using var pen = new Pen(Color.FromArgb(alpha, Chaos), faded ? 1.0f : 1.4f)
            {
                DashStyle = DashStyle.Dot,
            };
            g.DrawLine(pen, xLeft, y, rect.Right, y);
        }

        private void DrawVodStackEdge(
            Graphics g,
            IChartWindowCoordinatesConverter cv,
            Rectangle rect,
            VodStackEdge edge,
            bool stackFaded)
        {
            int xStart;
            int y;
            try
            {
                xStart = (int)cv.GetChartX(edge.EventUtc);
                y = (int)cv.GetChartY(edge.CenterTick * _tickSize);
            }
            catch { return; }

            if (y < rect.Top || y > rect.Bottom) return;
            int xLeft = Math.Max(rect.Left, xStart);
            if (rect.Right <= xLeft) return;

            bool breached = edge.BreachedUtc.HasValue;
            int alpha = stackFaded ? 38 : (breached ? 58 : 175);
            float width = stackFaded || breached ? 1.0f : 1.5f;
            Color color = edge.Side == VodStackEdgeSide.Supply ? StackSupply : StackDemand;
            using var pen = new Pen(Color.FromArgb(alpha, color), width)
            {
                DashStyle = DashStyle.Dot,
            };
            g.DrawLine(pen, xLeft, y, rect.Right, y);
        }

        private void DrawVodBuildDots(Graphics g, IChart chart, Rectangle rect, IReadOnlyList<VodBuildDot> dots)
        {
            if (chart == null || dots == null || dots.Count == 0) return;
            var cv = chart.MainWindow?.CoordinatesConverter;
            if (cv == null) return;

            DateTime tLeft, tRight;
            try
            {
                tLeft = cv.GetTime(rect.Left);
                tRight = cv.GetTime(rect.Right);
            }
            catch
            {
                tLeft = DateTime.MinValue;
                tRight = DateTime.MaxValue;
            }

            int size = Math.Max(3, VodBuildDotSizePx);
            int half = size / 2;
            int fillAlpha = Clamp(VodBuildDotAlpha, 1, 255);
            int rimAlpha = Clamp(fillAlpha + 55, 1, 255);
            using var fill = new SolidBrush(Color.FromArgb(fillAlpha, Chaos));
            using var bidPen = new Pen(Color.FromArgb(rimAlpha, BidChaos), 1.6f);
            using var askPen = new Pen(Color.FromArgb(rimAlpha, AskChaos), 1.6f);
            using var mixedPen = new Pen(Color.FromArgb(rimAlpha, Neutral), 1.3f);

            foreach (var dot in dots)
            {
                if (dot.TimeUtc < tLeft || dot.TimeUtc > tRight) continue;

                int x, y;
                try
                {
                    x = (int)cv.GetChartX(dot.TimeUtc);
                    y = (int)cv.GetChartY(dot.PriceTick * _tickSize);
                }
                catch { continue; }

                if (x < rect.Left - half || x > rect.Right + half) continue;
                if (y < rect.Top - half || y > rect.Bottom + half) continue;

                var bounds = new RectangleF(x - half, y - half, size, size);
                g.FillEllipse(fill, bounds);
                switch (dot.ChaosSide)
                {
                    case VodChaosSide.Bid:
                        g.DrawEllipse(bidPen, bounds);
                        break;
                    case VodChaosSide.Ask:
                        g.DrawEllipse(askPen, bounds);
                        break;
                    default:
                        g.DrawArc(bidPen, bounds, 90, 180);
                        g.DrawArc(askPen, bounds, 270, 180);
                        g.DrawEllipse(mixedPen, bounds);
                        break;
                }
            }
        }

        private void DrawRow(Graphics g, Font font, LedgerRow row, int x, int y, int w)
        {
            string t = ToNy(row.TimeUtc).ToString("HH:mm");
            string price = Abbrev(row.PriceTick);
            string arrow = row.Direction > 0 ? "\u2191" : row.Direction < 0 ? "\u2193" : "\u00B7";
            string marker = IsNewDominance(row) ? "+" : " ";
            string zBadge = ZBadge(row);
            string updates = row.Updates > 1 && row.Kind != RowKind.SpatialDominance ? $" x{row.Updates}" : "";
            string text = $"{marker} {t} {price,7} {arrow} {row.Text}{zBadge}{updates}";

            Color baseColor = RowColor(row);
            int alpha = row.Superseded ? 95 : RowAlpha(row);
            using var brush = new SolidBrush(Color.FromArgb(alpha, baseColor));

            if (row.Superseded)
            {
                using var strikePen = new Pen(Color.FromArgb(80, baseColor), 1f);
                g.DrawLine(strikePen, x, y + font.Height / 2 + 1, x + Math.Min(w, 235), y + font.Height / 2 + 1);
            }

            g.DrawString(text, font, brush, x, y);
        }

        private static bool IsNewDominance(LedgerRow row)
        {
            if (row.Kind != RowKind.SpatialDominance) return false;
            if (row.Direction == 0 || row.Superseded) return false;
            return row.Updates == 1;
        }

        private static string ZBadge(LedgerRow row)
        {
            if (row.Kind != RowKind.TradeImpulse && row.Kind != RowKind.Chaos)
                return "";
            if (!double.IsFinite(row.DisplayZ) || row.DisplayZ <= 0)
                return "";

            int bucket = Math.Max(1, (int)Math.Round(row.DisplayZ, MidpointRounding.AwayFromZero));
            return $" z{bucket}";
        }

        private static Color RowColor(LedgerRow row)
        {
            switch (row.Kind)
            {
                case RowKind.SpatialDominance:
                    return row.Direction > 0 ? BullDominance
                         : row.Direction < 0 ? BearDominance
                         : Neutral;
                case RowKind.TradeImpulse:
                    return row.Direction > 0 ? BuyImpulse
                         : row.Direction < 0 ? SellImpulse
                         : Neutral;
                case RowKind.Chaos:
                    return Chaos;
                case RowKind.NodeMigration:
                    return row.Direction > 0 ? Color.FromArgb(125, 205, 165)
                         : row.Direction < 0 ? Color.FromArgb(220, 125, 110)
                         : Neutral;
                case RowKind.NodeBuild:
                default:
                    return Neutral;
            }
        }

        private static int RowAlpha(LedgerRow row)
        {
            switch (row.Kind)
            {
                case RowKind.SpatialDominance:
                    return 240;
                case RowKind.Chaos:
                    return 235;
                case RowKind.TradeImpulse:
                    return 210;
                case RowKind.NodeMigration:
                    return 200;
                case RowKind.NodeBuild:
                default:
                    return 185;
            }
        }

        private string Abbrev(long tick)
        {
            double price = tick * _tickSize;
            int whole = (int)Math.Floor(price);
            int last = ((whole % 1000) + 1000) % 1000;
            double frac = price - whole;
            if (Math.Abs(frac) < 0.0001)
                return last.ToString("000");
            return $"{last:000}{frac:0.00}".Replace("0.", ".");
        }

        private static DateTime ToNy(DateTime utc)
        {
            try
            {
                var ny = TimeZoneInfo.FindSystemTimeZoneById("Eastern Standard Time");
                return TimeZoneInfo.ConvertTimeFromUtc(DateTime.SpecifyKind(utc, DateTimeKind.Utc), ny);
            }
            catch
            {
                return utc;
            }
        }

        private static void DrawStaleBadge(Graphics g, Rectangle rect)
        {
            const string text = "L2 STALE";
            using var font = new Font("Segoe UI", 9, FontStyle.Bold);
            var size = g.MeasureString(text, font);
            int pad = 4;
            int w = (int)Math.Ceiling(size.Width) + pad * 2;
            int h = (int)Math.Ceiling(size.Height) + pad;
            int x = rect.Right - w - 8;
            int y = rect.Top + 8;
            using var bg = new SolidBrush(Color.FromArgb(190, 200, 30, 30));
            using var fg = new SolidBrush(Color.White);
            g.FillRectangle(bg, x, y, w, h);
            g.DrawString(text, font, fg, x + pad, y + pad / 2);
        }

        private static int Clamp(int v, int lo, int hi) => v < lo ? lo : (v > hi ? hi : v);
    }
}
