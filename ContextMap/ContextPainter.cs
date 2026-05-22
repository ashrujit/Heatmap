using System;
using System.Collections.Generic;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Linq;
using TradingPlatform.BusinessLayer;
using TradingPlatform.BusinessLayer.Chart;

namespace ContextMap
{
    internal sealed class ContextPainter
    {
        private readonly double _tickSize;

        public bool BandsEnabled = true;
        public int BandActiveAlpha = 38;
        public int BandFadedAlpha = 14;
        public bool PanelEnabled = true;
        public int LeftOffsetPx = 90;
        public int TopOffsetPx = 90;
        public int PanelWidthPx = 470;
        public float FontSize = 10.0f;
        public bool L2Stale;

        private static readonly Color Border = Color.FromArgb(150, 112, 112, 118);
        private static readonly Color Bg = Color.FromArgb(66, 18, 20, 24);
        private static readonly Color HeaderBg = Color.FromArgb(98, 35, 38, 45);
        private static readonly Color HeaderFg = Color.FromArgb(235, 230, 230, 230);
        private static readonly Color Muted = Color.FromArgb(168, 178, 178, 178);
        private static readonly Color Demand = Color.FromArgb(78, 188, 232);
        private static readonly Color Supply = Color.FromArgb(239, 128, 72);
        private static readonly Color Neutral = Color.FromArgb(205, 195, 180);
        private static readonly Color Good = Color.FromArgb(108, 225, 150);
        private static readonly Color Warning = Color.FromArgb(246, 193, 82);
        private static readonly Color Stale = Color.FromArgb(220, 70, 60);

        public ContextPainter(double tickSize)
        {
            _tickSize = tickSize > 0 ? tickSize : 0.25;
        }

        public void Paint(PaintChartEventArgs args, IChart chart, ContextSnapshot snapshot)
        {
            var g = args.Graphics;
            var rect = args.Rectangle;
            if (rect.Width <= 0 || rect.Height <= 0) return;

            var prev = g.SmoothingMode;
            g.SmoothingMode = SmoothingMode.AntiAlias;
            try
            {
                if (BandsEnabled)
                    DrawBands(g, chart, rect, snapshot.Rails);
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

        private void DrawBands(Graphics g, IChart chart, Rectangle rect, IReadOnlyList<RailView> rails)
        {
            if (chart == null || rails == null || rails.Count == 0) return;
            var cv = chart.MainWindow?.CoordinatesConverter;
            if (cv == null) return;

            foreach (var rail in rails)
            {
                int yTop;
                int yBottom;
                try
                {
                    yTop = (int)cv.GetChartY(rail.MaxTick * _tickSize);
                    yBottom = (int)cv.GetChartY(rail.MinTick * _tickSize);
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
                yBottom = Math.Min(rect.Bottom, Math.Max(yBottom, yTop + 1));

                Color baseColor = SideColor(rail.Side);
                bool faded = rail.Freshness == RailFreshness.Old;
                int alpha = Clamp(faded ? BandFadedAlpha : BandActiveAlpha, 1, 255);
                int edgeAlpha = Clamp(alpha + (faded ? 20 : 65), 1, 255);
                using var fill = new SolidBrush(Color.FromArgb(alpha, baseColor));
                using var pen = new Pen(Color.FromArgb(edgeAlpha, baseColor), rail.Strength >= 3 ? 1.5f : 1.0f);
                if (rail.Ratio < 1.45)
                    pen.DashStyle = DashStyle.Dash;

                g.FillRectangle(fill, rect.Left, yTop, rect.Width, yBottom - yTop);
                g.DrawLine(pen, rect.Left, yTop, rect.Right, yTop);
                g.DrawLine(pen, rect.Left, yBottom, rect.Right, yBottom);
            }
        }

        private void DrawPanel(Graphics g, Rectangle rect, ContextSnapshot snapshot)
        {
            int rowH = Math.Max(16, (int)Math.Ceiling(FontSize + 8));
            int headerH = Math.Max(24, rowH + 6);
            int sectionH = rowH * 2;
            int msgRows = 5;
            int w = Math.Max(260, PanelWidthPx);
            int h = headerH + sectionH * 4 + rowH * msgRows + 14;
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

            g.DrawString("Context Map", headerFont, headerBrush, x + 8, y + 3);
            string status = PhaseText(snapshot.Phase);
            var statusSize = g.MeasureString(status, rowFont);
            g.DrawString(status, rowFont, mutedBrush, x + w - statusSize.Width - 8, y + 6);

            int rowY = y + headerH + 5;
            DrawInfoRow(g, rowFont, "FRAME", FrameText(snapshot), x + 8, rowY, w - 16, Neutral);
            rowY += rowH;
            DrawInfoRow(g, rowFont, "BRKT", BracketText(snapshot), x + 8, rowY, w - 16, Muted);
            rowY += rowH + 4;

            DrawInfoRow(g, rowFont, "LEG", LegText(snapshot), x + 8, rowY, w - 16, LegColor(snapshot.Leg));
            rowY += rowH + 4;

            var reference = snapshot.LastTradeTick ?? snapshot.RthOpenTick ?? 0;
            var below = snapshot.Rails
                .Where(r => r.CenterTick <= reference)
                .OrderByDescending(r => r.CenterTick)
                .Take(4)
                .ToArray();
            var above = snapshot.Rails
                .Where(r => r.CenterTick > reference)
                .OrderBy(r => r.CenterTick)
                .Take(4)
                .ToArray();

            DrawInfoRow(g, rowFont, "BELOW", RailsText(below), x + 8, rowY, w - 16, Demand);
            rowY += rowH;
            DrawInfoRow(g, rowFont, "ABOVE", RailsText(above), x + 8, rowY, w - 16, Supply);
            rowY += rowH + 4;

            if (snapshot.Messages != null)
            {
                foreach (var msg in snapshot.Messages.Take(msgRows))
                {
                    DrawInfoRow(g, rowFont, TimeLabel(msg.TimeUtc), msg.Text ?? "", x + 8, rowY, w - 16, MessageColor(msg.Kind));
                    rowY += rowH;
                }
            }
        }

        private void DrawInfoRow(Graphics g, Font font, string label, string text, int x, int y, int width, Color color)
        {
            using var labelBrush = new SolidBrush(Muted);
            using var textBrush = new SolidBrush(color);
            string left = (label ?? "").PadRight(6).Substring(0, Math.Min(6, Math.Max(0, (label ?? "").Length))).PadRight(6);
            g.DrawString(left, font, labelBrush, x, y);
            int labelW = (int)g.MeasureString("000000", font).Width + 4;
            string trimmed = TrimToWidth(g, font, text ?? "", width - labelW);
            g.DrawString(trimmed, font, textBrush, x + labelW, y);
        }

        private string FrameText(ContextSnapshot snapshot)
        {
            string frame = string.IsNullOrEmpty(snapshot.Frame) ? "building" : snapshot.Frame;
            if (snapshot.RthOpenTick.HasValue && snapshot.RthHighTick.HasValue && snapshot.RthLowTick.HasValue)
                return $"{frame}  O {Abbrev(snapshot.RthOpenTick.Value)} H {Abbrev(snapshot.RthHighTick.Value)} L {Abbrev(snapshot.RthLowTick.Value)}";
            return frame;
        }

        private string BracketText(ContextSnapshot snapshot)
        {
            string low = snapshot.ActiveLow != null ? RailToken(snapshot.ActiveLow) : "-";
            string high = snapshot.ActiveHigh != null ? RailToken(snapshot.ActiveHigh) : "-";
            return $"low {low} / high {high}";
        }

        private string LegText(ContextSnapshot snapshot)
        {
            if (snapshot.Leg == null || snapshot.Leg.Rail == null)
                return "waiting for rail resolution";
            string dir = snapshot.Leg.Direction == Direction.Up ? "UP" : "DN";
            string quality = QualityText(snapshot.Leg.Quality?.Label ?? QualityLabel.Probing);
            return $"{dir} {Abbrev(snapshot.Leg.Rail.CenterTick)}->{Abbrev(snapshot.Leg.ExtremeTick)} {quality} " +
                   $"A{snapshot.Leg.Quality?.AcceptedBins ?? 0}/{snapshot.Leg.Quality?.Bins ?? 0} " +
                   $"R{(snapshot.Leg.Quality?.Retrace ?? 0):0.00}";
        }

        private string RailsText(IReadOnlyList<RailView> rails)
        {
            if (rails == null || rails.Count == 0) return "-";
            return string.Join("  ", rails.Select(RailToken));
        }

        private string RailToken(RailView rail)
        {
            string side = rail.Side == RailSide.Demand ? "D" : "S";
            string fresh = rail.Freshness == RailFreshness.Fresh ? "f" : "o";
            return $"{Abbrev(rail.CenterTick)} {side}{rail.Strength}{fresh}";
        }

        private string QualityText(QualityLabel label)
        {
            return label switch
            {
                QualityLabel.ThinMixed => "thin/mixed",
                QualityLabel.FastNoBuild => "fast/no-build",
                QualityLabel.Building => "building",
                QualityLabel.Accepted => "accepted",
                _ => "probing",
            };
        }

        private Color LegColor(LegView leg)
        {
            if (leg == null || leg.Quality == null) return Muted;
            return leg.Quality.Label switch
            {
                QualityLabel.Accepted => Good,
                QualityLabel.Building => Neutral,
                QualityLabel.ThinMixed => Warning,
                QualityLabel.FastNoBuild => Warning,
                _ => Muted,
            };
        }

        private static Color MessageColor(MessageKind kind)
        {
            return kind switch
            {
                MessageKind.Accepted => Good,
                MessageKind.Quality => Warning,
                MessageKind.Failed => Warning,
                MessageKind.AddRisk => Warning,
                MessageKind.UpBreak => Neutral,
                MessageKind.DownBreak => Neutral,
                _ => Muted,
            };
        }

        private static string PhaseText(ContextPhase phase)
        {
            return phase switch
            {
                ContextPhase.ON => "ON",
                ContextPhase.RthBuild => "IB",
                ContextPhase.RthUpdate => "UPDATE",
                ContextPhase.AfterCutoff => "FROZEN",
                _ => "WAIT",
            };
        }

        private static Color SideColor(RailSide side)
        {
            return side switch
            {
                RailSide.Demand => Demand,
                RailSide.Supply => Supply,
                _ => Neutral,
            };
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

        private static int Clamp(int value, int min, int max)
        {
            if (value < min) return min;
            if (value > max) return max;
            return value;
        }
    }
}
