using System;
using System.Collections.Generic;
using System.Drawing;
using System.Drawing.Drawing2D;
using TradingPlatform.BusinessLayer;
using TradingPlatform.BusinessLayer.Chart;

namespace ON_ContextMap
{
    internal sealed class ScenarioPainter
    {
        private readonly double _tickSize;

        public bool BandsEnabled = true;
        public int BandActiveAlpha = 42;
        public int BandFadedAlpha = 16;
        public bool PanelEnabled = true;
        public int LeftOffsetPx = 90;
        public int TopOffsetPx = 90;
        public int PanelWidthPx = 390;
        public int VisibleRows = 10;
        public float FontSize = 10.0f;
        public bool L2Stale;

        private static readonly Color Border = Color.FromArgb(150, 112, 112, 118);
        private static readonly Color Bg = Color.FromArgb(62, 18, 20, 24);
        private static readonly Color HeaderBg = Color.FromArgb(96, 35, 38, 45);
        private static readonly Color HeaderFg = Color.FromArgb(235, 230, 230, 230);
        private static readonly Color Muted = Color.FromArgb(168, 178, 178, 178);
        private static readonly Color Demand = Color.FromArgb(78, 188, 232);
        private static readonly Color Supply = Color.FromArgb(239, 128, 72);
        private static readonly Color Neutral = Color.FromArgb(205, 195, 180);
        private static readonly Color Held = Color.FromArgb(108, 225, 150);
        private static readonly Color Warning = Color.FromArgb(246, 193, 82);
        private static readonly Color Stale = Color.FromArgb(220, 70, 60);

        public ScenarioPainter(double tickSize)
        {
            _tickSize = tickSize > 0 ? tickSize : 0.25;
        }

        public void Paint(PaintChartEventArgs args, IChart chart, ScenarioSnapshot snapshot)
        {
            var g = args.Graphics;
            var rect = args.Rectangle;
            if (rect.Width <= 0 || rect.Height <= 0) return;

            var prev = g.SmoothingMode;
            g.SmoothingMode = SmoothingMode.AntiAlias;
            try
            {
                if (BandsEnabled)
                    DrawBands(g, chart, rect, snapshot.Zones);
                if (L2Stale)
                    DrawStaleBadge(g, rect);
                if (PanelEnabled)
                    DrawPanel(g, rect, snapshot);
            }
            finally
            {
                g.SmoothingMode = prev;
            }
        }

        private void DrawBands(Graphics g, IChart chart, Rectangle rect, IReadOnlyList<ScenarioZone> zones)
        {
            if (chart == null || zones == null || zones.Count == 0) return;
            var cv = chart.MainWindow?.CoordinatesConverter;
            if (cv == null) return;

            foreach (var zone in zones)
            {
                int xStart;
                int yTop;
                int yBottom;
                try
                {
                    xStart = (int)cv.GetChartX(zone.FirstUtc);
                    yTop = (int)cv.GetChartY(zone.MaxTick * _tickSize);
                    yBottom = (int)cv.GetChartY(zone.MinTick * _tickSize);
                }
                catch { continue; }

                int xLeft = Math.Max(rect.Left, xStart);
                int xRight = rect.Right;
                if (xRight <= xLeft) continue;
                if (yTop > yBottom)
                {
                    int tmp = yTop;
                    yTop = yBottom;
                    yBottom = tmp;
                }
                if (yBottom < rect.Top || yTop > rect.Bottom) continue;
                yTop = Math.Max(rect.Top, yTop);
                yBottom = Math.Min(rect.Bottom, Math.Max(yBottom, yTop + 1));

                Color baseColor = SideColor(zone.Side);
                bool faded = IsFaded(zone.State);
                int alpha = Clamp(faded ? BandFadedAlpha : BandActiveAlpha, 1, 255);
                int edgeAlpha = Clamp(alpha + (faded ? 20 : 70), 1, 255);
                using var fill = new SolidBrush(Color.FromArgb(alpha, baseColor));
                using var pen = new Pen(Color.FromArgb(edgeAlpha, baseColor), faded ? 1.0f : 1.35f);
                if (zone.State == ZoneState.Unresolved || zone.State == ZoneState.Swept)
                    pen.DashStyle = DashStyle.Dot;
                else if (zone.State == ZoneState.Contested || zone.State == ZoneState.Tested)
                    pen.DashStyle = DashStyle.Dash;

                g.FillRectangle(fill, xLeft, yTop, xRight - xLeft, yBottom - yTop);
                g.DrawLine(pen, xLeft, yTop, xRight, yTop);
                g.DrawLine(pen, xLeft, yBottom, xRight, yBottom);
            }
        }

        private void DrawPanel(Graphics g, Rectangle rect, ScenarioSnapshot snapshot)
        {
            int rowH = Math.Max(16, (int)Math.Ceiling(FontSize + 8));
            int headerH = Math.Max(24, rowH + 6);
            int w = Math.Max(220, PanelWidthPx);
            int rows = Math.Max(1, VisibleRows);
            int h = headerH + rows * rowH + 8;
            int x = Math.Min(rect.Right - w - 4, Math.Max(rect.Left + 4, rect.Left + LeftOffsetPx));
            int y = Math.Min(rect.Bottom - h - 4, Math.Max(rect.Top + 4, rect.Top + TopOffsetPx));

            using (var bg = new SolidBrush(Bg))
                g.FillRectangle(bg, x, y, w, h);
            using (var header = new SolidBrush(HeaderBg))
                g.FillRectangle(header, x, y, w, headerH);
            using (var pen = new Pen(Border, 1f))
                g.DrawRectangle(pen, x, y, w, h);

            using var headerFont = new Font("Segoe UI", FontSize, FontStyle.Bold);
            using var rowFont = new Font("Consolas", Math.Max(7.0f, FontSize - 0.5f), FontStyle.Regular);
            using var headerBrush = new SolidBrush(HeaderFg);
            using var mutedBrush = new SolidBrush(Muted);

            string title = "ON Context";
            g.DrawString(title, headerFont, headerBrush, x + 8, y + 3);

            string status = PhaseText(snapshot.Phase);
            var statusSize = g.MeasureString(status, rowFont);
            g.DrawString(status, rowFont, mutedBrush, x + w - statusSize.Width - 8, y + 6);

            if (snapshot.Rows == null || snapshot.Rows.Count == 0)
                return;

            int rowY = y + headerH + 4;
            for (int i = 0; i < snapshot.Rows.Count && i < rows; i++)
            {
                DrawRow(g, rowFont, snapshot.Rows[i], x + 8, rowY, w - 16);
                rowY += rowH;
            }
        }

        private void DrawRow(Graphics g, Font font, ScenarioRow row, int x, int y, int width)
        {
            Color color = RowColor(row);
            string glyph = Glyph(row.State);
            using var glyphBrush = new SolidBrush(color);
            using var textBrush = new SolidBrush(row.State == ZoneState.Info ? Muted : color);
            g.DrawString(glyph, font, glyphBrush, x, y);
            var glyphSize = g.MeasureString(glyph, font);
            string text = TrimToWidth(g, font, row.Text ?? "", width - (int)glyphSize.Width - 4);
            g.DrawString(text, font, textBrush, x + glyphSize.Width + 4, y);
        }

        private static string PhaseText(ScenarioPhase phase)
        {
            return phase switch
            {
                ScenarioPhase.ON => "ON",
                ScenarioPhase.RthBuild => "IB",
                ScenarioPhase.RthUpdate => "UPDATE",
                ScenarioPhase.AfterCutoff => "FROZEN",
                _ => "WAIT",
            };
        }

        private static string Glyph(ZoneState state)
        {
            return state switch
            {
                ZoneState.Unresolved => ".",
                ZoneState.Tested => "?",
                ZoneState.Held => "H",
                ZoneState.Rebuilt => "R",
                ZoneState.ResolvedUp => "^",
                ZoneState.ResolvedDown => "v",
                ZoneState.Contested => "x",
                ZoneState.Swept => "~",
                ZoneState.Accepted => "A",
                _ => "i",
            };
        }

        private static Color RowColor(ScenarioRow row)
        {
            if (row.State == ZoneState.Info) return Neutral;
            if (row.State == ZoneState.Held || row.State == ZoneState.Rebuilt || row.State == ZoneState.Accepted)
                return Held;
            if (row.State == ZoneState.Contested || row.State == ZoneState.Tested)
                return Warning;
            if (row.State == ZoneState.ResolvedUp || row.State == ZoneState.ResolvedDown || row.State == ZoneState.Swept)
                return Muted;
            return SideColor(row.Side);
        }

        private static Color SideColor(ZoneSide side)
        {
            return side switch
            {
                ZoneSide.Demand => Demand,
                ZoneSide.Supply => Supply,
                _ => Neutral,
            };
        }

        private static bool IsFaded(ZoneState state)
        {
            return state == ZoneState.ResolvedUp
                || state == ZoneState.ResolvedDown
                || state == ZoneState.Swept;
        }

        private static string TrimToWidth(Graphics g, Font font, string text, int maxWidth)
        {
            if (maxWidth <= 10 || string.IsNullOrEmpty(text)) return "";
            if (g.MeasureString(text, font).Width <= maxWidth) return text;
            const string ellipsis = "...";
            for (int len = text.Length - 1; len > 0; len--)
            {
                string candidate = text.Substring(0, len) + ellipsis;
                if (g.MeasureString(candidate, font).Width <= maxWidth)
                    return candidate;
            }
            return ellipsis;
        }

        private void DrawStaleBadge(Graphics g, Rectangle rect)
        {
            using var font = new Font("Segoe UI", 8.5f, FontStyle.Bold);
            string s = "STALE";
            var size = g.MeasureString(s, font);
            int x = rect.Right - (int)size.Width - 12;
            int y = rect.Top + 8;
            using var bg = new SolidBrush(Color.FromArgb(170, 65, 16, 16));
            using var fg = new SolidBrush(Stale);
            g.FillRectangle(bg, x - 4, y - 2, size.Width + 8, size.Height + 4);
            g.DrawString(s, font, fg, x, y);
        }

        private static int Clamp(int value, int min, int max)
        {
            if (value < min) return min;
            if (value > max) return max;
            return value;
        }
    }
}
