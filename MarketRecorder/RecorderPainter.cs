using System;
using System.Drawing;
using System.Drawing.Drawing2D;
using TradingPlatform.BusinessLayer;

namespace MarketRecorder
{
    internal sealed class RecorderPainter
    {
        public bool PanelEnabled = true;
        public int LeftOffsetPx = 90;
        public int TopOffsetPx = 90;
        public int PanelWidthPx = 340;
        public float FontSize = 9.0f;

        private static readonly Color Border = Color.FromArgb(150, 112, 112, 118);
        private static readonly Color Bg = Color.FromArgb(68, 18, 20, 24);
        private static readonly Color HeaderBg = Color.FromArgb(100, 35, 38, 45);
        private static readonly Color HeaderFg = Color.FromArgb(235, 230, 230, 230);
        private static readonly Color Muted = Color.FromArgb(170, 178, 178, 178);
        private static readonly Color Good = Color.FromArgb(105, 225, 150);
        private static readonly Color Warning = Color.FromArgb(246, 193, 82);
        private static readonly Color Bad = Color.FromArgb(230, 82, 70);
        private static readonly Color Neutral = Color.FromArgb(205, 195, 180);

        public void Paint(PaintChartEventArgs args, RecorderStatusSnapshot status)
        {
            if (!PanelEnabled || status == null) return;
            var g = args.Graphics;
            var rect = args.Rectangle;
            if (rect.Width <= 0 || rect.Height <= 0) return;

            var prev = g.SmoothingMode;
            g.SmoothingMode = SmoothingMode.AntiAlias;
            try { DrawPanel(g, rect, status); }
            finally { g.SmoothingMode = prev; }
        }

        private void DrawPanel(Graphics g, Rectangle rect, RecorderStatusSnapshot status)
        {
            int rowH = Math.Max(15, (int)Math.Ceiling(FontSize + 7));
            int headerH = Math.Max(22, rowH + 5);
            int w = Math.Max(220, PanelWidthPx);
            int rows = string.IsNullOrWhiteSpace(status.LastError) ? 5 : 6;
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
            using var rowFont = new Font("Consolas", Math.Max(7.0f, FontSize - 0.2f), FontStyle.Regular);
            using var headerBrush = new SolidBrush(HeaderFg);
            using var mutedBrush = new SolidBrush(Muted);

            g.DrawString("Market Recorder", headerFont, headerBrush, x + 8, y + 3);
            string overall = Overall(status);
            using (var overallBrush = new SolidBrush(OverallColor(status)))
            {
                var size = g.MeasureString(overall, rowFont);
                g.DrawString(overall, rowFont, overallBrush, x + w - size.Width - 8, y + 5);
            }

            int rowY = y + headerH + 4;
            DrawRow(g, rowFont, "BOOK", status.BookState ?? "", x + 8, rowY, w - 16, BookColor(status));
            rowY += rowH;
            DrawRow(g, rowFont, "TICK", StreamText(status.LastTickUtc, status.TickRowsWritten, status.TickQueueRows, status.TickFiles), x + 8, rowY, w - 16, status.TicksEnabled ? Good : Muted);
            rowY += rowH;
            DrawRow(g, rowFont, "SNAP", StreamText(status.LastSnapshotUtc, status.SnapshotRowsWritten, status.SnapshotQueueRows, status.SnapshotFiles), x + 8, rowY, w - 16, SnapshotColor(status));
            rowY += rowH;
            DrawRow(g, rowFont, "CFG", $"{status.LevelsPerSide}lv {status.ChunkSeconds}s chunks", x + 8, rowY, w - 16, Neutral);
            rowY += rowH;
            DrawRow(g, rowFont, "ROOT", LastPathPart(status.Root), x + 8, rowY, w - 16, Muted);
            rowY += rowH;
            if (!string.IsNullOrWhiteSpace(status.LastError))
                DrawRow(g, rowFont, "ERR", status.LastError, x + 8, rowY, w - 16, Bad);
        }

        private static void DrawRow(Graphics g, Font font, string label, string text, int x, int y, int width, Color color)
        {
            using var labelBrush = new SolidBrush(Muted);
            using var textBrush = new SolidBrush(color);
            string left = (label ?? "").PadRight(5);
            g.DrawString(left, font, labelBrush, x, y);
            int labelW = (int)g.MeasureString("00000", font).Width + 4;
            string trimmed = TrimToWidth(g, font, text ?? "", width - labelW);
            g.DrawString(trimmed, font, textBrush, x + labelW, y);
        }

        private static string StreamText(string lastUtc, long rowsWritten, int queuedRows, long files)
        {
            string last = ShortTime(lastUtc);
            return $"{last} rows={rowsWritten} q={queuedRows} files={files}";
        }

        private static string Overall(RecorderStatusSnapshot s)
        {
            if (!string.IsNullOrWhiteSpace(s.LastError)) return "ERROR";
            if ((s.BookState ?? "").IndexOf("ok", StringComparison.OrdinalIgnoreCase) >= 0) return "OK";
            if ((s.BookState ?? "").IndexOf("disabled", StringComparison.OrdinalIgnoreCase) >= 0) return "OFF";
            return "WAIT";
        }

        private static Color OverallColor(RecorderStatusSnapshot s)
        {
            if (!string.IsNullOrWhiteSpace(s.LastError)) return Bad;
            if ((s.BookState ?? "").IndexOf("ok", StringComparison.OrdinalIgnoreCase) >= 0) return Good;
            if ((s.BookState ?? "").IndexOf("disabled", StringComparison.OrdinalIgnoreCase) >= 0) return Muted;
            return Warning;
        }

        private static Color BookColor(RecorderStatusSnapshot s)
        {
            string text = s.BookState ?? "";
            if (text.IndexOf("ok", StringComparison.OrdinalIgnoreCase) >= 0) return Good;
            if (text.IndexOf("disabled", StringComparison.OrdinalIgnoreCase) >= 0) return Muted;
            if (text.IndexOf("stale", StringComparison.OrdinalIgnoreCase) >= 0) return Bad;
            return Warning;
        }

        private static Color SnapshotColor(RecorderStatusSnapshot s)
        {
            if (!s.SnapshotsEnabled) return Muted;
            if (s.SnapshotWriteFailures > 0) return Bad;
            if ((s.BookState ?? "").IndexOf("ok", StringComparison.OrdinalIgnoreCase) >= 0) return Good;
            return Warning;
        }

        private static string ShortTime(string utc)
        {
            if (string.IsNullOrWhiteSpace(utc)) return "--:--:--";
            if (!DateTime.TryParse(utc, out var t)) return "--:--:--";
            return t.ToLocalTime().ToString("HH:mm:ss");
        }

        private static string LastPathPart(string path)
        {
            if (string.IsNullOrWhiteSpace(path)) return "";
            path = path.TrimEnd('\\', '/');
            int i = Math.Max(path.LastIndexOf('\\'), path.LastIndexOf('/'));
            return i >= 0 && i + 1 < path.Length ? path[(i + 1)..] : path;
        }

        private static string TrimToWidth(Graphics g, Font font, string text, int width)
        {
            if (string.IsNullOrEmpty(text) || width <= 0) return "";
            if (g.MeasureString(text, font).Width <= width) return text;
            const string ellipsis = "...";
            int lo = 0;
            int hi = text.Length;
            while (lo < hi)
            {
                int mid = (lo + hi + 1) / 2;
                string candidate = text.Substring(0, mid) + ellipsis;
                if (g.MeasureString(candidate, font).Width <= width)
                    lo = mid;
                else
                    hi = mid - 1;
            }
            return text.Substring(0, Math.Max(0, lo)) + ellipsis;
        }
    }
}
