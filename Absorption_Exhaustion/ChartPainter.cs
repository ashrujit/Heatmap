using System;
using System.Drawing;
using System.Drawing.Drawing2D;
using TradingPlatform.BusinessLayer;
using TradingPlatform.BusinessLayer.Chart;

namespace Absorption_Exhaustion
{
    // Paints the registry state onto the chart. Two layers:
    //   1. Horizontal bands (one per surviving (price, direction)) drawn from
    //      left to right edge, alpha scaled by count and last-fire recency.
    //      Bands at the same price with both directions blend toward amber.
    //   2. Glyphs at recent fire (price, time) coordinates, fading over the
    //      configured retention window — small filled circles, color by dir.
    //   3. Cleared bands fade out briefly so the user sees "level just broke".
    internal sealed class ChartPainter
    {
        // Color tints. RGB held as Color; alpha computed dynamically.
        private static readonly Color BearColor = Color.FromArgb(220, 70, 70);
        private static readonly Color BullColor = Color.FromArgb(70, 200, 90);
        private static readonly Color BothColor = Color.FromArgb(220, 170, 60); // amber
        private static readonly Color ClearColor = Color.FromArgb(160, 160, 160);

        private readonly double _tickSize;
        public int BandMaxCountForFullAlpha = 5;
        public int BandBaseAlpha = 60;     // alpha at count=1
        public int BandFullAlpha = 180;    // alpha at count >= MaxCountForFullAlpha
        public int BandHalfHeight = 1;     // pixels above/below the price line

        public int GlyphRadius = 3;
        public int GlyphMaxAlpha = 200;
        public int GlyphFadeSec = 5;

        public int ClearedFadeSec = 3;
        public int ClearedMaxAlpha = 120;

        public ChartPainter(double tickSize)
        {
            _tickSize = tickSize;
        }

        public void Paint(PaintChartEventArgs args, IChart chart, PriceBandRegistry reg, DateTime nowUtc)
        {
            if (chart == null || reg == null) return;
            var g = args.Graphics;
            var cv = chart.MainWindow.CoordinatesConverter;
            var rect = args.Rectangle;
            if (rect.Width <= 0 || rect.Height <= 0) return;

            var prevSmoothing = g.SmoothingMode;
            g.SmoothingMode = SmoothingMode.AntiAlias;

            try
            {
                PaintBands(g, cv, rect, reg, nowUtc);
                PaintCleared(g, cv, rect, reg, nowUtc);
                PaintGlyphs(g, cv, rect, reg, nowUtc);
            }
            finally
            {
                g.SmoothingMode = prevSmoothing;
            }
        }

        private void PaintBands(Graphics g, IChartWindowCoordinatesConverter cv,
            Rectangle rect, PriceBandRegistry reg, DateTime nowUtc)
        {
            // Group entries by price tick to detect both-direction overlap.
            var bands = reg.Bands;
            // First pass: collect tick -> (bearEntry?, bullEntry?)
            var byTick = new System.Collections.Generic.Dictionary<long, (PriceBandRegistry.BandEntry b, PriceBandRegistry.BandEntry s)>();
            foreach (var kv in bands)
            {
                var e = kv.Value;
                byTick.TryGetValue(e.PriceTick, out var tup);
                if (e.Direction == FireDirection.Bear) tup.b = e;
                else tup.s = e;
                byTick[e.PriceTick] = tup;
            }

            foreach (var kv in byTick)
            {
                long tick = kv.Key;
                double price = tick * _tickSize;
                int y = (int)cv.GetChartY(price) - rect.Top;
                if (y < 0 || y >= rect.Height) continue;

                var (bear, bull) = kv.Value;
                int alphaBear = bear != null ? AlphaForBand(bear, nowUtc) : 0;
                int alphaBull = bull != null ? AlphaForBand(bull, nowUtc) : 0;

                Color color;
                int alpha;
                if (alphaBear > 0 && alphaBull > 0)
                {
                    color = BothColor;
                    alpha = Math.Min(255, alphaBear + alphaBull);
                }
                else if (alphaBear > 0)
                {
                    color = BearColor; alpha = alphaBear;
                }
                else if (alphaBull > 0)
                {
                    color = BullColor; alpha = alphaBull;
                }
                else continue;

                using var brush = new SolidBrush(Color.FromArgb(alpha, color));
                int bandH = 1 + 2 * BandHalfHeight;
                g.FillRectangle(brush, rect.Left, rect.Top + y - BandHalfHeight, rect.Width, bandH);
            }
        }

        private void PaintCleared(Graphics g, IChartWindowCoordinatesConverter cv,
            Rectangle rect, PriceBandRegistry reg, DateTime nowUtc)
        {
            foreach (var c in reg.Cleared)
            {
                double age = (nowUtc - c.ClearedAt).TotalSeconds;
                if (age < 0 || age > ClearedFadeSec) continue;
                double t = 1.0 - (age / ClearedFadeSec);
                int alpha = (int)(ClearedMaxAlpha * t);
                if (alpha <= 0) continue;
                double price = c.PriceTick * _tickSize;
                int y = (int)cv.GetChartY(price) - rect.Top;
                if (y < 0 || y >= rect.Height) continue;
                using var pen = new Pen(Color.FromArgb(alpha, ClearColor)) { DashStyle = DashStyle.Dash };
                g.DrawLine(pen, rect.Left, rect.Top + y, rect.Right, rect.Top + y);
            }
        }

        private void PaintGlyphs(Graphics g, IChartWindowCoordinatesConverter cv,
            Rectangle rect, PriceBandRegistry reg, DateTime nowUtc)
        {
            foreach (var entry in reg.Bands.Values)
            {
                Color baseColor = entry.Direction == FireDirection.Bear ? BearColor : BullColor;
                double price = entry.PriceTick * _tickSize;
                int y = (int)cv.GetChartY(price) - rect.Top;
                if (y < 0 || y >= rect.Height) continue;
                foreach (var ts in entry.RecentFires)
                {
                    double age = (nowUtc - ts).TotalSeconds;
                    if (age < 0 || age > GlyphFadeSec) continue;
                    int x = (int)cv.GetChartX(ts) - rect.Left;
                    if (x < 0 || x >= rect.Width) continue;
                    double t = 1.0 - (age / GlyphFadeSec);
                    int alpha = (int)(GlyphMaxAlpha * t);
                    if (alpha <= 0) continue;
                    using var brush = new SolidBrush(Color.FromArgb(alpha, baseColor));
                    int r = GlyphRadius;
                    g.FillEllipse(brush, rect.Left + x - r, rect.Top + y - r, r * 2, r * 2);
                }
            }
        }

        private int AlphaForBand(PriceBandRegistry.BandEntry e, DateTime nowUtc)
        {
            if (e.Count <= 0) return 0;
            // Count contribution: scale linearly to BandMaxCountForFullAlpha.
            double countFrac = Math.Min(1.0, (double)e.Count / BandMaxCountForFullAlpha);
            // Recency contribution: 1.0 at fresh, decays linearly to 0.5 over 5 min.
            double age = (nowUtc - e.LastFireTime).TotalSeconds;
            double recencyFrac = age <= 0 ? 1.0 : Math.Max(0.5, 1.0 - age / 300.0);
            double frac = countFrac * recencyFrac;
            int alpha = BandBaseAlpha + (int)((BandFullAlpha - BandBaseAlpha) * frac);
            return Math.Min(255, Math.Max(0, alpha));
        }
    }
}
