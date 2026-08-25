using System;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Globalization;
using System.Linq;
using TradingPlatform.BusinessLayer;
using TradingPlatform.BusinessLayer.Chart;

namespace BubbleTape
{
    internal sealed class BubbleTapePainter
    {
        private readonly double _tickSize;

        public double MinBubbleDiameterPx = 9.0;
        public double MaxBubbleDiameterPx = 38.0;
        public int BubbleAlpha = 108;
        public int BubbleEdgeAlpha = 205;
        public bool PanelEnabled = false;
        public int PanelLeftOffsetPx = 90;
        public int PanelTopOffsetPx = 90;
        public int PanelWidthPx = 310;
        public float FontSize = 9.0f;

        private const int SourceTradeGroup = 1;

        private static readonly Color BuyColor = Color.FromArgb(21, 148, 71);
        private static readonly Color SellColor = Color.FromArgb(214, 74, 58);
        private static readonly Color PanelBg = Color.FromArgb(118, 12, 15, 20);
        private static readonly Color PanelBorder = Color.FromArgb(190, 126, 132, 144);
        private static readonly Color PanelText = Color.FromArgb(238, 244, 247, 250);
        private static readonly Color MutedText = Color.FromArgb(205, 184, 190, 198);

        public BubbleTapePainter(double tickSize)
        {
            _tickSize = tickSize > 0 ? tickSize : 0.25;
        }

        public void Paint(PaintChartEventArgs args, IChart chart, BubbleTapeSnapshot snapshot)
        {
            if (args == null || chart == null || snapshot == null) return;
            var g = args.Graphics;
            var rect = args.Rectangle;
            var cv = chart.MainWindow?.CoordinatesConverter;
            if (g == null || cv == null || rect.Width <= 0 || rect.Height <= 0) return;

            var prev = g.SmoothingMode;
            var prevClip = g.Clip;
            g.SmoothingMode = SmoothingMode.AntiAlias;
            g.SetClip(rect);
            try
            {
                DrawBubbles(g, cv, rect, snapshot);
                if (PanelEnabled)
                    DrawPanel(g, rect, snapshot);
            }
            finally
            {
                g.Clip = prevClip;
                g.SmoothingMode = prev;
            }
        }

        private void DrawBubbles(
            Graphics g,
            IChartWindowCoordinatesConverter cv,
            Rectangle rect,
            BubbleTapeSnapshot snapshot)
        {
            var ordered = snapshot.Bubbles
                .OrderBy(b => b.Developing ? 1 : 0)
                .ThenBy(b => b.TimeUtc)
                .ToArray();

            foreach (var bubble in ordered)
            {
                double price = bubble.CenterTick * _tickSize;
                float x;
                float y;
                try
                {
                    x = (float)cv.GetChartX(bubble.TimeUtc);
                    y = (float)cv.GetChartY(price);
                }
                catch
                {
                    continue;
                }

                double diameter = BubbleDiameter(bubble);
                float d = (float)diameter;
                float offset = (float)((bubble.Side > 0 ? 1.0 : -1.0) * Math.Max(2.0, diameter * 0.14));
                x += offset;
                if (x + d < rect.Left || x - d > rect.Right || y + d < rect.Top || y - d > rect.Bottom)
                    continue;

                Color color = bubble.Side > 0 ? BuyColor : SellColor;
                bool tradeGroup = bubble.Source == SourceTradeGroup;
                int alphaBoost = tradeGroup ? 22 : 0;
                int alpha = Clamp((int)((BubbleAlpha + alphaBoost) * (bubble.Developing ? 0.72 : 1.0)), 8, 230);
                int edgeAlpha = Clamp((int)(BubbleEdgeAlpha * (bubble.Developing ? 0.82 : 1.0)), 30, 255);
                float edgeWidth = tradeGroup
                    ? (bubble.IdentityBacked ? 2.05f : 1.65f)
                    : (bubble.Developing ? 1.25f : 1.55f);
                using var fill = new SolidBrush(Color.FromArgb(alpha, color));
                using var pen = new Pen(Color.FromArgb(edgeAlpha, color), edgeWidth);
                if (bubble.Developing)
                    pen.DashStyle = DashStyle.Dash;
                else if (tradeGroup && !bubble.IdentityBacked)
                    pen.DashStyle = DashStyle.Dot;

                float left = x - d / 2.0f;
                float top = y - d / 2.0f;
                g.FillEllipse(fill, left, top, d, d);
                g.DrawEllipse(pen, left, top, d, d);
                DrawSizeLabel(g, bubble, left, top, d);
            }
        }

        private static void DrawSizeLabel(Graphics g, BubbleView bubble, float left, float top, float diameter)
        {
            string label = SizeLabel(bubble.AbsDelta);
            if (string.IsNullOrEmpty(label)) return;

            float fontPx = Math.Min(7.0f, Math.Max(5.0f, diameter * 0.22f));
            using var font = new Font("Segoe UI", fontPx, FontStyle.Bold, GraphicsUnit.Pixel);
            using var brush = new SolidBrush(Color.FromArgb(bubble.Developing ? 180 : 238, Color.White));
            using var format = new StringFormat
            {
                Alignment = StringAlignment.Center,
                LineAlignment = StringAlignment.Center,
                Trimming = StringTrimming.None,
                FormatFlags = StringFormatFlags.NoWrap,
            };

            var box = new RectangleF(left, top + 0.5f, diameter, diameter);
            g.DrawString(label, font, brush, box, format);
        }

        private static string SizeLabel(double value)
        {
            if (double.IsNaN(value) || double.IsInfinity(value) || value <= 0.0) return string.Empty;
            if (value < 1000.0) return value.ToString("0", CultureInfo.InvariantCulture);
            double thousands = value / 1000.0;
            return thousands < 10.0
                ? thousands.ToString("0.#", CultureInfo.InvariantCulture) + "k"
                : thousands.ToString("0", CultureInfo.InvariantCulture) + "k";
        }

        private double BubbleDiameter(BubbleView bubble)
        {
            double min = Math.Max(2.0, MinBubbleDiameterPx);
            double max = Math.Max(min, MaxBubbleDiameterPx);
            double strength = Math.Max(0.0, Math.Min(1.0, bubble.Visual01));
            return min + strength * (max - min);
        }

        private void DrawPanel(Graphics g, Rectangle rect, BubbleTapeSnapshot snapshot)
        {
            int w = Math.Min(Math.Max(220, PanelWidthPx), Math.Max(1, rect.Width - 8));
            int rowH = Math.Max(17, (int)Math.Ceiling(FontSize + 8));
            int h = rowH * 5 + 12;
            int x = Math.Min(Math.Max(rect.Left + 4, rect.Left + PanelLeftOffsetPx), rect.Right - w - 4);
            int y = Math.Min(Math.Max(rect.Top + 4, rect.Top + PanelTopOffsetPx), rect.Bottom - h - 4);

            using var bg = new SolidBrush(PanelBg);
            using var border = new Pen(PanelBorder, 1f);
            using var titleFont = new Font("Segoe UI", Math.Max(8.0f, FontSize + 1.0f), FontStyle.Bold);
            using var rowFont = new Font("Consolas", Math.Max(7.5f, FontSize), FontStyle.Regular);
            using var titleBrush = new SolidBrush(PanelText);
            using var muted = new SolidBrush(MutedText);

            g.FillRectangle(bg, x, y, w, h);
            g.DrawRectangle(border, x, y, w, h);
            g.DrawString("BubbleTape", titleFont, titleBrush, x + 8, y + 5);

            int rowY = y + rowH + 7;
            DrawRow(g, rowFont, muted, titleBrush, x + 8, rowY, w - 16, "state", snapshot.Status);
            rowY += rowH;
            DrawRow(g, rowFont, muted, titleBrush, x + 8, rowY, w - 16, "bubbles", snapshot.Bubbles.Length.ToString());
            rowY += rowH;
            DrawRow(g, rowFont, muted, titleBrush, x + 8, rowY, w - 16, "thresh", snapshot.Threshold.ToString("0"));
            rowY += rowH;
            string last = snapshot.LastTradeTick.HasValue
                ? Abbrev(snapshot.LastTradeTick.Value)
                : "waiting";
            DrawRow(g, rowFont, muted, titleBrush, x + 8, rowY, w - 16, "last", last);
        }

        private static void DrawRow(
            Graphics g,
            Font font,
            Brush labelBrush,
            Brush textBrush,
            int x,
            int y,
            int width,
            string label,
            string text)
        {
            string left = (label ?? "").PadRight(8);
            if (left.Length > 8) left = left.Substring(0, 8);
            g.DrawString(left, font, labelBrush, x, y);
            int labelW = (int)g.MeasureString("00000000", font).Width + 4;
            g.DrawString(TrimToWidth(g, font, text ?? "", width - labelW), font, textBrush, x + labelW, y);
        }

        private string Abbrev(long tick)
        {
            double price = tick * _tickSize;
            int whole = (int)Math.Floor(price);
            int last = ((whole % 1000) + 1000) % 1000;
            double frac = price - whole;
            if (Math.Abs(frac) < 0.0001)
                return last.ToString("000");
            return last.ToString("000") + frac.ToString(".00").TrimEnd('0');
        }

        private static string TrimToWidth(Graphics g, Font font, string text, int maxWidth)
        {
            if (string.IsNullOrEmpty(text) || maxWidth <= 12) return "";
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

        private static int Clamp(int value, int min, int max)
        {
            if (value < min) return min;
            if (value > max) return max;
            return value;
        }
    }
}
