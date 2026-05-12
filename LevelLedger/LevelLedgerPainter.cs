using System;
using System.Drawing;
using System.Drawing.Drawing2D;
using TradingPlatform.BusinessLayer;

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

        public LevelLedgerPainter(double tickSize)
        {
            _tickSize = tickSize > 0 ? tickSize : 0.25;
        }

        public void Paint(PaintChartEventArgs args, LedgerSnapshot snapshot)
        {
            var g = args.Graphics;
            var rect = args.Rectangle;
            if (rect.Width <= 0 || rect.Height <= 0) return;

            int rowH = Math.Max(15, (int)Math.Ceiling(FontSize + 7));
            int headerH = Math.Max(22, rowH + 5);
            int w = Math.Max(180, PanelWidthPx);
            int h = headerH + Math.Max(1, VisibleRows) * rowH + 8;
            int x = Math.Min(rect.Right - w - 4, Math.Max(rect.Left + 4, rect.Left + LeftOffsetPx));
            int y = Math.Min(rect.Bottom - h - 4, Math.Max(rect.Top + 4, rect.Top + TopOffsetPx));

            LastHitRect = new Rectangle(x, y, w, h);
            if (L2Stale) DrawStaleBadge(g, rect);

            var prev = g.SmoothingMode;
            g.SmoothingMode = SmoothingMode.AntiAlias;
            try
            {
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
            finally
            {
                g.SmoothingMode = prev;
            }
        }

        private void DrawRow(Graphics g, Font font, LedgerRow row, int x, int y, int w)
        {
            string t = ToNy(row.TimeUtc).ToString("HH:mm");
            string price = Abbrev(row.PriceTick);
            string arrow = row.Direction > 0 ? "\u2191" : row.Direction < 0 ? "\u2193" : "\u00B7";
            string updates = row.Updates > 1 && row.Kind != RowKind.SpatialDominance ? $" x{row.Updates}" : "";
            string text = $"{t} {price,7} {arrow} {row.Text}{updates}";

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
    }
}
