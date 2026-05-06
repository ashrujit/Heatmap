using System;
using System.Collections.Generic;
using System.Drawing;
using System.Drawing.Drawing2D;
using TradingPlatform.BusinessLayer;
using TradingPlatform.BusinessLayer.Chart;

namespace SinglePrints
{
    // Renders single-print zones as horizontal boundary lines and/or low-alpha
    // box fills, extending from the zone's formed-at time to the chart right
    // edge. Older sessions fade by retention age — newest is brightest.
    internal sealed class Painter
    {
        public bool ShowBoundaries = true;
        public bool ShowFill = false;
        public int BoundaryAlphaMax = 180;
        public int FillAlphaMax = 40;
        public int RetentionSessions = 3;

        // Color: a muted slate-blue. Same hue for all zones — the alpha fade is
        // the only thing that distinguishes "this session" from "n sessions back".
        // Resisted color-coding by direction or strength: that would be
        // classification. A single print is a single print.
        private static readonly Color ZoneColor = Color.FromArgb(255, 130, 165, 200);

        public void Paint(PaintChartEventArgs args, IChart chart, IReadOnlyList<Zone> zones, DateTime nowUtc)
        {
            if (chart == null || zones == null || zones.Count == 0) return;
            var g = args.Graphics;
            var rect = args.Rectangle;
            if (rect.Width <= 0 || rect.Height <= 0) return;
            var cv = chart.MainWindow?.CoordinatesConverter;
            if (cv == null) return;

            var prevSmooth = g.SmoothingMode;
            g.SmoothingMode = SmoothingMode.AntiAlias;

            try
            {
                // Index sessions by distance back from newest, for alpha fade.
                // Sessions sorted descending by SessionDateNy → idx 0 = newest.
                var sessionAge = new Dictionary<DateTime, int>();
                {
                    var dates = new SortedSet<DateTime>();
                    foreach (var z in zones) dates.Add(z.SessionDateNy);
                    int idx = 0;
                    var arr = new DateTime[dates.Count];
                    dates.CopyTo(arr);
                    Array.Reverse(arr);
                    foreach (var d in arr) sessionAge[d] = idx++;
                }

                int chartRight = rect.Right;

                foreach (var z in zones)
                {
                    if (z.Filled) continue;
                    if (!sessionAge.TryGetValue(z.SessionDateNy, out int age)) continue;
                    // Linear fade by session age. Newest = full alpha, oldest in
                    // retention window = ~30%. Beyond retention = invisible.
                    double ageFrac = RetentionSessions <= 1
                        ? 1.0
                        : 1.0 - (double)age / Math.Max(1, RetentionSessions - 1) * 0.7;
                    if (ageFrac <= 0) continue;

                    int yTop = (int)cv.GetChartY(z.TopPrice);
                    int yBot = (int)cv.GetChartY(z.BottomPrice);
                    if (yTop > yBot) (yTop, yBot) = (yBot, yTop);  // Y increases downward
                    if (yBot < rect.Top || yTop > rect.Bottom) continue;

                    int xStart = (int)cv.GetChartX(z.FormedAtUtc);
                    if (xStart < rect.Left) xStart = rect.Left;
                    if (xStart > chartRight) continue;
                    int xEnd = chartRight;

                    if (ShowFill)
                    {
                        int a = (int)(FillAlphaMax * ageFrac);
                        if (a > 0)
                        {
                            using var fill = new SolidBrush(Color.FromArgb(a, ZoneColor));
                            g.FillRectangle(fill, xStart, yTop, xEnd - xStart, yBot - yTop);
                        }
                    }

                    if (ShowBoundaries)
                    {
                        int a = (int)(BoundaryAlphaMax * ageFrac);
                        if (a > 0)
                        {
                            using var pen = new Pen(Color.FromArgb(a, ZoneColor), 1.0f);
                            g.DrawLine(pen, xStart, yTop, xEnd, yTop);
                            g.DrawLine(pen, xStart, yBot, xEnd, yBot);
                        }
                    }
                }
            }
            finally
            {
                g.SmoothingMode = prevSmooth;
            }
        }
    }
}
