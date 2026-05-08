using System;
using System.Drawing;
using System.Drawing.Drawing2D;
using TradingPlatform.BusinessLayer;
using TradingPlatform.BusinessLayer.Chart;

namespace L2_Surface
{
    // Composite painter for the four toggleable surface layers, drawn in
    // z-order (back to front):
    //
    //   1. Flow bands     — vertical translucent strip across full chart height
    //   2. Build bands    — horizontal translucent price-range rectangles
    //   3. Climax lines   — thin amber horizontal lines (full width)
    //   4. Inflection     — thin colored horizontal lines (trigger time → right)
    //   5. Events dots    — small additive-alpha squares at (time, mid)
    //
    // Each layer's "Enabled" toggle gates only its render pass; the engine
    // computes everything regardless. Off-screen filtering happens up front
    // via cv.GetTime(rect.Left/Right) so paint cost stays bounded by
    // visible state, not session totals.
    internal sealed class SurfacePainter
    {
        // Layer toggles — set from the indicator entry point each paint.
        public bool EventsEnabled { get; set; } = true;
        public bool InflectionEnabled { get; set; } = true;
        public bool FlowEnabled { get; set; } = true;
        public bool BuildBandsEnabled { get; set; } = true;

        // Events
        public int DotSizePx { get; set; } = 6;
        public int DotAlpha { get; set; } = 70;

        // Inflection / Climax lines
        public int LineThicknessPx { get; set; } = 2;
        public int LineAlpha { get; set; } = 220;

        // Flow band
        public int FlowBandAlpha { get; set; } = 28;

        // Build bands
        public int BuildBandAlpha { get; set; } = 48;

        // Set by the indicator when L2 book is in stale or unreconcilable state —
        // when true, paint a small badge so the user can see the layers below
        // are frozen (no new events, lines, or bands until the feed recovers).
        public bool L2Stale { get; set; }

        // Bull / bear / neutral palette — shared across all layers.
        private static readonly Color BullColor = Color.FromArgb(60, 130, 220);   // blue
        private static readonly Color BearColor = Color.FromArgb(235, 110, 30);   // orange
        private static readonly Color VodColor  = Color.FromArgb(230, 180, 50);   // amber (VOD/neutral)

        public void Paint(PaintChartEventArgs args, IChart chart, SurfaceEngine engine)
        {
            if (chart == null || engine == null) return;
            var g = args.Graphics;
            var cv = chart.MainWindow.CoordinatesConverter;
            var rect = args.Rectangle;
            if (rect.Width <= 0 || rect.Height <= 0) return;

            // Visible time bounds (used to cull off-screen events/lines).
            DateTime tLeft, tRight;
            try { tLeft = cv.GetTime(rect.Left); tRight = cv.GetTime(rect.Right); }
            catch { tLeft = DateTime.MinValue; tRight = DateTime.MaxValue; }

            var prevSmoothing = g.SmoothingMode;
            g.SmoothingMode = SmoothingMode.None;

            if (FlowEnabled) DrawFlowBands(g, cv, rect, engine);
            if (BuildBandsEnabled) DrawBuildBands(g, cv, rect, engine);
            if (FlowEnabled) DrawClimaxLines(g, cv, rect, engine);
            if (InflectionEnabled) DrawInflections(g, cv, rect, engine);
            if (EventsEnabled) DrawEventDots(g, cv, rect, engine, tLeft, tRight);
            if (L2Stale) DrawStaleBadge(g, rect);

            g.SmoothingMode = prevSmoothing;
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

        private void DrawFlowBands(Graphics g, IChartWindowCoordinatesConverter cv,
                                   Rectangle rect, SurfaceEngine engine)
        {
            int alpha = Clamp(FlowBandAlpha, 1, 255);
            using var bearBrush = new SolidBrush(Color.FromArgb(alpha, BearColor));
            using var bullBrush = new SolidBrush(Color.FromArgb(alpha, BullColor));
            foreach (var fb in engine.FlowBands)
            {
                int x0, x1;
                try
                {
                    x0 = (int)cv.GetChartX(fb.StartTime);
                    x1 = (int)cv.GetChartX(fb.EndTime);
                }
                catch { continue; }
                if (x1 < rect.Left || x0 > rect.Right) continue;
                int xLeft  = Math.Max(rect.Left, x0);
                int xRight = Math.Min(rect.Right, x1);
                if (xRight <= xLeft) continue;
                Brush b = fb.Direction == SurfaceEngine.FlowDir.Bear ? bearBrush : bullBrush;
                g.FillRectangle(b, xLeft, rect.Top, xRight - xLeft, rect.Height);
            }
        }

        private void DrawBuildBands(Graphics g, IChartWindowCoordinatesConverter cv,
                                    Rectangle rect, SurfaceEngine engine)
        {
            int alpha = Clamp(BuildBandAlpha, 1, 255);
            using var supplyBrush = new SolidBrush(Color.FromArgb(alpha, BearColor));
            using var demandBrush = new SolidBrush(Color.FromArgb(alpha, BullColor));
            using var supplyEdge  = new Pen(Color.FromArgb(Math.Min(255, alpha + 60), BearColor), 1);
            using var demandEdge  = new Pen(Color.FromArgb(Math.Min(255, alpha + 60), BullColor), 1);

            foreach (var bb in engine.BuildBands)
            {
                int xStart;
                try { xStart = (int)cv.GetChartX(bb.StartTime); }
                catch { continue; }
                int xLeft  = Math.Max(rect.Left, xStart);
                int xRight = rect.Right;
                if (xRight <= xLeft) continue;

                int yMin, yMax;
                try
                {
                    yMin = (int)cv.GetChartY(bb.MaxPrice);   // higher price → smaller Y
                    yMax = (int)cv.GetChartY(bb.MinPrice);
                }
                catch { continue; }

                if (yMax < rect.Top || yMin > rect.Bottom) continue;
                int yTop = Math.Max(rect.Top, yMin);
                int yBot = Math.Min(rect.Bottom, yMax);
                if (yBot <= yTop) yBot = yTop + 1;     // 1-tick band still gets one row

                Brush b = bb.Side == SurfaceEngine.BandSide.Supply ? supplyBrush : demandBrush;
                Pen pen = bb.Side == SurfaceEngine.BandSide.Supply ? supplyEdge : demandEdge;
                g.FillRectangle(b, xLeft, yTop, xRight - xLeft, yBot - yTop);
                // Top + bottom edge for band visibility on thin price ranges.
                g.DrawLine(pen, xLeft, yTop, xRight, yTop);
                g.DrawLine(pen, xLeft, yBot, xRight, yBot);
            }
        }

        private void DrawClimaxLines(Graphics g, IChartWindowCoordinatesConverter cv,
                                     Rectangle rect, SurfaceEngine engine)
        {
            int alpha = Clamp(LineAlpha, 1, 255);
            using var pen = new Pen(Color.FromArgb(alpha, VodColor), LineThicknessPx);
            foreach (var cl in engine.ClimaxLines)
            {
                int y;
                try { y = (int)cv.GetChartY(cl.Price); }
                catch { continue; }
                if (y < rect.Top || y > rect.Bottom) continue;
                int xStart;
                try { xStart = (int)cv.GetChartX(cl.Time); }
                catch { continue; }
                int xLeft = Math.Max(rect.Left, xStart);
                if (rect.Right <= xLeft) continue;
                g.DrawLine(pen, xLeft, y, rect.Right, y);
            }
        }

        private void DrawInflections(Graphics g, IChartWindowCoordinatesConverter cv,
                                     Rectangle rect, SurfaceEngine engine)
        {
            int alpha = Clamp(LineAlpha, 1, 255);
            using var bullPen = new Pen(Color.FromArgb(alpha, BullColor), LineThicknessPx);
            using var bearPen = new Pen(Color.FromArgb(alpha, BearColor), LineThicknessPx);
            foreach (var inf in engine.Inflections)
            {
                int y;
                try { y = (int)cv.GetChartY(inf.Price); }
                catch { continue; }
                if (y < rect.Top || y > rect.Bottom) continue;
                int xStart;
                try { xStart = (int)cv.GetChartX(inf.TriggerTime); }
                catch { continue; }
                int xLeft = Math.Max(rect.Left, xStart);
                if (rect.Right <= xLeft) continue;
                Pen pen = inf.Bias > 0 ? bullPen : bearPen;
                g.DrawLine(pen, xLeft, y, rect.Right, y);
            }
        }

        private void DrawEventDots(Graphics g, IChartWindowCoordinatesConverter cv,
                                   Rectangle rect, SurfaceEngine engine,
                                   DateTime tLeft, DateTime tRight)
        {
            int half = DotSizePx / 2;
            int alpha = Clamp(DotAlpha, 1, 255);
            using var bullBrush = new SolidBrush(Color.FromArgb(alpha, BullColor));
            using var bearBrush = new SolidBrush(Color.FromArgb(alpha, BearColor));
            using var vodBrush  = new SolidBrush(Color.FromArgb(alpha, VodColor));

            foreach (var ev in engine.Events)
            {
                if (ev.Time < tLeft || ev.Time > tRight) continue;
                int x, y;
                try
                {
                    x = (int)cv.GetChartX(ev.Time);
                    y = (int)cv.GetChartY(ev.Price);
                }
                catch { continue; }
                if (x < rect.Left - half || x > rect.Right + half) continue;
                if (y < rect.Top  - half || y > rect.Bottom + half) continue;
                Brush b = ev.Bias > 0 ? bullBrush :
                          ev.Bias < 0 ? bearBrush :
                          vodBrush;
                g.FillRectangle(b, x - half, y - half, DotSizePx, DotSizePx);
            }
        }

        private static int Clamp(int v, int lo, int hi) => v < lo ? lo : (v > hi ? hi : v);
    }
}
