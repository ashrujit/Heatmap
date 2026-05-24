using System;
using System.Collections.Generic;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Linq;
using TradingPlatform.BusinessLayer;
using TradingPlatform.BusinessLayer.Chart;

namespace TapeLedger
{
    internal sealed class TapeLedgerPainter
    {
        private readonly double _tickSize;

        public bool BandsEnabled = true;
        public bool BannersEnabled = true;
        public bool PanelEnabled = true;
        public int BandAlpha = 72;
        public int BandEdgeAlpha = 220;
        public int BannerAlpha = 218;
        public int LeftOffsetPx = 90;
        public int TopOffsetPx = 86;
        public int PanelWidthPx = 420;
        public float FontSize = 10.0f;

        private static readonly Color Demand = Color.FromArgb(0, 214, 170);
        private static readonly Color Supply = Color.FromArgb(255, 112, 67);
        private static readonly Color Accepted = Color.FromArgb(78, 154, 255);
        private static readonly Color Warning = Color.FromArgb(255, 205, 64);
        private static readonly Color Neutral = Color.FromArgb(215, 220, 228);
        private static readonly Color Muted = Color.FromArgb(178, 184, 193);
        private static readonly Color PanelBg = Color.FromArgb(96, 12, 15, 20);
        private static readonly Color PanelHeader = Color.FromArgb(165, 25, 31, 40);
        private static readonly Color Border = Color.FromArgb(190, 126, 132, 144);

        public TapeLedgerPainter(double tickSize)
        {
            _tickSize = tickSize > 0 ? tickSize : 0.25;
        }

        public void Paint(PaintChartEventArgs args, IChart chart, TapeSnapshot snapshot)
        {
            if (args == null || snapshot == null) return;
            var g = args.Graphics;
            var rect = args.Rectangle;
            if (g == null || rect.Width <= 0 || rect.Height <= 0) return;

            var prev = g.SmoothingMode;
            g.SmoothingMode = SmoothingMode.AntiAlias;
            try
            {
                if (BandsEnabled)
                    DrawBands(g, chart, rect, snapshot.Bands);
                if (BannersEnabled)
                    DrawBanners(g, rect, snapshot.Banners);
                if (PanelEnabled)
                    DrawPanel(g, rect, snapshot);
            }
            finally
            {
                g.SmoothingMode = prev;
            }
        }

        private void DrawBands(Graphics g, IChart chart, Rectangle rect, IReadOnlyList<TapeBandView> bands)
        {
            if (chart == null || bands == null || bands.Count == 0) return;
            var cv = chart.MainWindow?.CoordinatesConverter;
            if (cv == null) return;

            foreach (var band in bands)
            {
                int yTop;
                int yBottom;
                int xStart;
                try
                {
                    yTop = (int)cv.GetChartY((band.MaxTick + 1) * _tickSize);
                    yBottom = (int)cv.GetChartY(band.MinTick * _tickSize);
                    xStart = (int)cv.GetChartX(band.StartUtc);
                }
                catch { continue; }

                if (yTop > yBottom)
                {
                    int tmp = yTop;
                    yTop = yBottom;
                    yBottom = tmp;
                }
                if (yBottom < rect.Top || yTop > rect.Bottom) continue;

                yTop = Math.Max(rect.Top, yTop);
                yBottom = Math.Min(rect.Bottom, Math.Max(yBottom, yTop + 5));
                int x = Math.Max(rect.Left, Math.Min(rect.Right - 16, xStart));
                int w = Math.Max(40, rect.Right - x);

                Color baseColor = SideColor(band.Side);
                int alpha = Clamp(BandAlpha + (band.State == TapeBandState.New ? 28 : 0), 8, 210);
                int edgeAlpha = Clamp(BandEdgeAlpha, 40, 255);
                using var fill = new SolidBrush(Color.FromArgb(alpha, baseColor));
                using var pen = new Pen(Color.FromArgb(edgeAlpha, baseColor), band.State == TapeBandState.New ? 2.2f : 1.35f);
                if (band.Side == TapeSide.Accepted)
                    pen.DashStyle = DashStyle.Dash;

                g.FillRectangle(fill, x, yTop, w, yBottom - yTop);
                g.DrawLine(pen, x, yTop, rect.Right, yTop);
                g.DrawLine(pen, x, yBottom, rect.Right, yBottom);

                DrawBandLabel(g, rect, band, yTop, yBottom, baseColor);
            }
        }

        private void DrawBandLabel(Graphics g, Rectangle rect, TapeBandView band, int yTop, int yBottom, Color color)
        {
            string side = band.Side switch
            {
                TapeSide.Demand => "DMD",
                TapeSide.Supply => "SUP",
                TapeSide.Accepted => "ACC",
                _ => "SHF",
            };
            string text = $"{side} {band.Text}";
            using var font = new Font("Segoe UI", Math.Max(8.0f, FontSize - 1.0f), FontStyle.Bold);
            SizeF size = g.MeasureString(text, font);
            int padX = 6;
            int h = Math.Max(18, (int)Math.Ceiling(size.Height) + 2);
            int w = Math.Min(rect.Width - 20, (int)Math.Ceiling(size.Width) + padX * 2);
            int x = rect.Right - w - 8;
            int y = Math.Max(rect.Top + 2, Math.Min(rect.Bottom - h - 2, (yTop + yBottom - h) / 2));
            using var bg = new SolidBrush(Color.FromArgb(190, 10, 12, 16));
            using var border = new Pen(Color.FromArgb(235, color), 1f);
            using var fg = new SolidBrush(Color.FromArgb(245, 245, 248, 252));
            g.FillRectangle(bg, x, y, w, h);
            g.DrawRectangle(border, x, y, w, h);
            g.DrawString(TrimToWidth(g, font, text, w - padX * 2), font, fg, x + padX, y + 1);
        }

        private void DrawBanners(Graphics g, Rectangle rect, IReadOnlyList<TapeBannerView> banners)
        {
            if (banners == null || banners.Count == 0) return;
            using var titleFont = new Font("Segoe UI", Math.Max(9.0f, FontSize + 0.5f), FontStyle.Bold);
            using var detailFont = new Font("Segoe UI", Math.Max(8.0f, FontSize - 1.0f), FontStyle.Regular);

            int x = rect.Left + 10;
            int y = rect.Top + 8;
            int w = Math.Min(rect.Width - 20, 780);
            int h = Math.Max(25, (int)Math.Ceiling(FontSize + 17));
            foreach (var banner in banners.Take(4))
            {
                Color color = SideColor(banner.Side);
                using var bg = new SolidBrush(Color.FromArgb(Clamp(BannerAlpha, 60, 255), color));
                using var dark = new SolidBrush(Color.FromArgb(165, 8, 10, 14));
                using var border = new Pen(Color.FromArgb(240, color), 1.4f);
                using var fg = new SolidBrush(Color.FromArgb(255, 255, 255, 255));
                using var sub = new SolidBrush(Color.FromArgb(230, 15, 18, 24));

                g.FillRectangle(bg, x, y, w, h);
                g.FillRectangle(dark, x, y, 7, h);
                g.DrawRectangle(border, x, y, w, h);
                string text = TrimToWidth(g, titleFont, banner.Text, (int)(w * 0.58));
                g.DrawString(text, titleFont, fg, x + 13, y + 3);
                if (!string.IsNullOrWhiteSpace(banner.Detail))
                {
                    string detail = TrimToWidth(g, detailFont, banner.Detail, (int)(w * 0.38));
                    var size = g.MeasureString(detail, detailFont);
                    g.DrawString(detail, detailFont, sub, x + w - size.Width - 10, y + 6);
                }
                y += h + 5;
            }
        }

        private void DrawPanel(Graphics g, Rectangle rect, TapeSnapshot snapshot)
        {
            int rowH = Math.Max(18, (int)Math.Ceiling(FontSize + 8));
            int headerH = Math.Max(28, rowH + 8);
            int bandRows = Math.Min(6, snapshot.Bands?.Length ?? 0);
            int msgRows = Math.Min(8, snapshot.Messages?.Length ?? 0);
            int h = headerH + rowH * (4 + bandRows + msgRows) + 18;
            int w = Math.Max(300, PanelWidthPx);
            int x = Math.Min(rect.Right - w - 4, Math.Max(rect.Left + 4, rect.Left + LeftOffsetPx));
            int y = Math.Min(rect.Bottom - h - 4, Math.Max(rect.Top + 4, rect.Top + TopOffsetPx));

            using var bg = new SolidBrush(PanelBg);
            using var head = new SolidBrush(PanelHeader);
            using var border = new Pen(Border, 1f);
            g.FillRectangle(bg, x, y, w, h);
            g.FillRectangle(head, x, y, w, headerH);
            g.DrawRectangle(border, x, y, w, h);

            using var titleFont = new Font("Segoe UI", FontSize + 1.0f, FontStyle.Bold);
            using var rowFont = new Font("Consolas", Math.Max(7.5f, FontSize - 0.5f), FontStyle.Regular);
            using var titleBrush = new SolidBrush(Color.FromArgb(245, 245, 248, 252));
            using var muted = new SolidBrush(Muted);

            g.DrawString("Tape Ledger", titleFont, titleBrush, x + 9, y + 4);
            string price = snapshot.LastTradeTick.HasValue ? Abbrev(snapshot.LastTradeTick.Value) : "waiting";
            var priceSize = g.MeasureString(price, rowFont);
            g.DrawString(price, rowFont, muted, x + w - priceSize.Width - 9, y + 8);

            int rowY = y + headerH + 6;
            DrawRow(g, rowFont, "RTH", RthText(snapshot), x + 9, rowY, w - 18, Neutral);
            rowY += rowH;
            DrawRow(g, rowFont, "OR5", RangeText(snapshot.OrLowTick, snapshot.OrHighTick), x + 9, rowY, w - 18, Warning);
            rowY += rowH;
            DrawRow(g, rowFont, "IB", RangeText(snapshot.IbLowTick, snapshot.IbHighTick), x + 9, rowY, w - 18, Accepted);
            rowY += rowH + 4;

            if (snapshot.Bands != null && snapshot.Bands.Length > 0)
            {
                DrawRow(g, rowFont, "SHELF", "active traded zones", x + 9, rowY, w - 18, Muted);
                rowY += rowH;
                foreach (var b in snapshot.Bands.Take(6))
                {
                    DrawRow(g, rowFont, SideToken(b.Side), b.Text, x + 9, rowY, w - 18, SideColor(b.Side));
                    rowY += rowH;
                }
            }

            if (snapshot.Messages != null && snapshot.Messages.Length > 0)
            {
                rowY += 3;
                foreach (var m in snapshot.Messages.Take(8))
                {
                    DrawRow(g, rowFont, TimeLabel(m.TimeUtc), m.Text, x + 9, rowY, w - 18, SideColor(m.Side));
                    rowY += rowH;
                }
            }
        }

        private void DrawRow(Graphics g, Font font, string label, string text, int x, int y, int width, Color color)
        {
            using var labelBrush = new SolidBrush(Muted);
            using var textBrush = new SolidBrush(color);
            string l = (label ?? "").PadRight(6);
            if (l.Length > 6) l = l.Substring(0, 6);
            g.DrawString(l, font, labelBrush, x, y);
            int labelW = (int)g.MeasureString("000000", font).Width + 5;
            g.DrawString(TrimToWidth(g, font, text ?? "", width - labelW), font, textBrush, x + labelW, y);
        }

        private string RthText(TapeSnapshot s)
        {
            if (!s.RthOpenTick.HasValue || !s.RthHighTick.HasValue || !s.RthLowTick.HasValue)
                return "waiting for RTH tape";
            return $"O {Abbrev(s.RthOpenTick.Value)} H {Abbrev(s.RthHighTick.Value)} L {Abbrev(s.RthLowTick.Value)}";
        }

        private string RangeText(long? low, long? high)
        {
            if (!low.HasValue || !high.HasValue) return "building";
            return $"{Abbrev(low.Value)} - {Abbrev(high.Value)}";
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

        private string TimeLabel(DateTime utc)
        {
            try
            {
                var eastern = TimeZoneInfo.FindSystemTimeZoneById("Eastern Standard Time");
                return TimeZoneInfo.ConvertTimeFromUtc(utc, eastern).ToString("HH:mm");
            }
            catch
            {
                return utc.ToString("HH:mm");
            }
        }

        private static string SideToken(TapeSide side)
        {
            return side switch
            {
                TapeSide.Demand => "DMD",
                TapeSide.Supply => "SUP",
                TapeSide.Accepted => "ACC",
                TapeSide.Warning => "WARN",
                _ => "ZONE",
            };
        }

        private static Color SideColor(TapeSide side)
        {
            return side switch
            {
                TapeSide.Demand => Demand,
                TapeSide.Supply => Supply,
                TapeSide.Accepted => Accepted,
                TapeSide.Warning => Warning,
                _ => Neutral,
            };
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
