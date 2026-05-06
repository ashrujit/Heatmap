using System;
using System.Drawing;
using System.Drawing.Drawing2D;
using TradingPlatform.BusinessLayer;

namespace LiquidityMeter
{
    // Layout (top to bottom):
    //   ┌─────────────────┐ ┌─┐
    //   │   ROC dial      │ │ │  ← horizontal ROC + vertical VOD strip
    //   │  ◀──█──▶        │ │█│     beside it. VOD lights amber when chaos
    //   └─────────────────┘ └─┘     fires, intensity from rolling 30s count.
    //          ↕ gap
    //         ┌──┐
    //         │  │
    //         │█ │           ← cum bar, smaller / narrower / lower visual weight.
    //         ├──┤              Cum is the slow-moving regime read; ROC is what
    //         │  │              changes minute to minute.
    //         └──┘
    //          ↕ gap
    //   cum -5.3              ← labels stacked, one per line
    //   roc +0.0
    //   vod 2/30s
    //   n=42
    //
    // Right-side mode: same layout reflected — labels left of the meter and
    // the meter near the right edge, configurable. Default stays left-side
    // because L2_Heatmap extends to the chart's right edge.
    internal sealed class MeterPainter
    {
        public int LeftOffsetPx = 70;
        public int CumBarWidth = 18;            // cum-bar width — reduced from 26
        public int RocDialWidth = 90;
        public int RocDialHeight = 22;          // larger so it reads at a glance
        public int VodStripWidth = 14;          // VOD strip beside ROC (visible width)
        public double MeterHeightFraction = 0.50;
        public double CumScale = 30.0;
        public double ROCScale = 10.0;
        public int VodFadeSeconds = 6;
        public int VodCountForFullSteady = 4;   // VOD events in last 30s for max steady-fill

        // Manual-anchor override. When set, painter renders the asterisk + timestamp
        // line and the indicator's MouseClick handler uses LastHitRect to decide
        // whether a click landed on the meter.
        public DateTime? ManualAnchorUtc;
        public Rectangle LastHitRect;           // written each Paint; read by hit-test on click

        private static readonly Color BullColor   = Color.FromArgb(80, 200, 110);
        private static readonly Color BearColor   = Color.FromArgb(225, 75, 75);
        private static readonly Color CenterColor = Color.FromArgb(180, 160, 160, 160);
        private static readonly Color BgColor     = Color.FromArgb(60, 30, 30, 35);
        private static readonly Color BorderColor = Color.FromArgb(120, 80, 80, 80);
        private static readonly Color LabelColor  = Color.FromArgb(230, 220, 220, 220);
        private static readonly Color VodColor    = Color.FromArgb(220, 200, 60);

        public void Paint(PaintChartEventArgs args, MeterEngine engine)
        {
            if (engine == null) return;
            var g = args.Graphics;
            var rect = args.Rectangle;
            if (rect.Width <= 0 || rect.Height <= 0) return;

            double cum = engine.Cumulative;
            double roc = engine.RateOfChange;
            DateTime nowUtc = DateTime.UtcNow;

            // ── Region partitioning ─────────────────────────────────────
            // Region is centered vertically on the chart pane. Top to bottom:
            //   topPad → ROC dial → gap → cum bar → gap → label stack →
            //   bottomPad. Cum bar height is the residual after fixed-cost
            //   slots — this means making the chart taller scales cum
            //   proportionally, while ROC / labels stay readable.
            int regionH = Math.Max(180, (int)(rect.Height * MeterHeightFraction));
            int regionTop = rect.Top + (rect.Height - regionH) / 2;

            const int topPad = 10;
            const int gap = 14;
            const int labelLineHeight = 14;
            int labelsCount = ManualAnchorUtc.HasValue ? 5 : 4;  // extra @HH:MM:SS line
            int labelsH = labelsCount * labelLineHeight + 4;

            int rocTop = regionTop + topPad;
            int rocBottom = rocTop + RocDialHeight;
            int cumTop = rocBottom + gap;
            int labelsTop = regionTop + regionH - labelsH;
            int cumBottom = labelsTop - gap;
            int cumH = Math.Max(60, cumBottom - cumTop);

            // Horizontal alignment: ROC dial centered on a vertical axis;
            // cum bar's center lines up with the same axis. VOD strip sits
            // immediately to the right of the ROC dial. Labels left-aligned
            // to the ROC dial's left edge.
            int axisX = rect.Left + LeftOffsetPx + RocDialWidth / 2;
            int rocLeft = axisX - RocDialWidth / 2;
            int rocRight = rocLeft + RocDialWidth;
            int rocCenterX = axisX;
            int rocCenterY = rocTop + RocDialHeight / 2;
            int halfRocW = RocDialWidth / 2;

            int vodGap = 6;
            int vodLeft = rocRight + vodGap;
            int vodTop = rocTop;
            int vodHeight = RocDialHeight;
            int vodWidth = VodStripWidth;

            int cumLeft = axisX - CumBarWidth / 2;
            int cumCenterY = cumTop + cumH / 2;
            int halfCumH = cumH / 2;

            int labelLeft = rocLeft;

            var prev = g.SmoothingMode;
            g.SmoothingMode = SmoothingMode.AntiAlias;

            try
            {
                // ── ROC dial ────────────────────────────────────────────
                using (var bg = new SolidBrush(BgColor))
                    g.FillRectangle(bg, rocLeft, rocTop, RocDialWidth, RocDialHeight);
                using (var border = new Pen(BorderColor, 1f))
                    g.DrawRectangle(border, rocLeft, rocTop, RocDialWidth, RocDialHeight);

                // Quarter-tick marks on top edge
                using (var tick = new Pen(BorderColor, 1f))
                {
                    foreach (double frac in new[] { 0.25, 0.50, 0.75, 1.0 })
                    {
                        int dx = (int)(frac * halfRocW);
                        g.DrawLine(tick, rocCenterX + dx, rocTop, rocCenterX + dx, rocTop + 4);
                        g.DrawLine(tick, rocCenterX - dx, rocTop, rocCenterX - dx, rocTop + 4);
                    }
                }
                // Vertical centerline (zero of the ROC dial)
                using (var c = new Pen(CenterColor, 1.5f))
                    g.DrawLine(c, rocCenterX, rocTop - 3, rocCenterX, rocBottom + 3);

                if (Math.Abs(roc) > 1e-3)
                {
                    int rocPx = Math.Min(halfRocW, (int)((Math.Abs(roc) / ROCScale) * halfRocW));
                    Color fc = roc > 0 ? BullColor : BearColor;
                    using var fb = new SolidBrush(Color.FromArgb(190, fc));
                    if (roc > 0)
                        g.FillRectangle(fb, rocCenterX, rocTop + 2, rocPx, RocDialHeight - 4);
                    else
                        g.FillRectangle(fb, rocCenterX - rocPx, rocTop + 2, rocPx, RocDialHeight - 4);

                    // Triangle pointer at leading edge — direction unambiguous
                    int tipX = roc > 0 ? rocCenterX + rocPx : rocCenterX - rocPx;
                    int dirSign = roc > 0 ? +1 : -1;
                    var pts = new[]
                    {
                        new Point(tipX, rocCenterY - 7),
                        new Point(tipX, rocCenterY + 7),
                        new Point(tipX + dirSign * 10, rocCenterY),
                    };
                    using var nb = new SolidBrush(fc);
                    g.FillPolygon(nb, pts);
                }

                // ── VOD strip (vertical, beside ROC dial) ───────────────
                // Two-channel intensity:
                //   - Steady amber from VodCount30s (rolling 30-sec count
                //     normalized to VodCountForFullSteady)
                //   - Pulse on top from time-since-last-fire
                // Total alpha is the max of the two channels — gives a
                // "flash on each fire, glow if many recent" composite.
                using (var bg = new SolidBrush(BgColor))
                    g.FillRectangle(bg, vodLeft, vodTop, vodWidth, vodHeight);
                using (var border = new Pen(BorderColor, 1f))
                    g.DrawRectangle(border, vodLeft, vodTop, vodWidth, vodHeight);

                int steadyAlpha = 0;
                if (engine.VodCount30s > 0)
                {
                    double frac = Math.Min(1.0, (double)engine.VodCount30s / Math.Max(1, VodCountForFullSteady));
                    steadyAlpha = (int)(60 + frac * 140);   // 60..200
                }
                int pulseAlpha = 0;
                double vodAge = engine.LastVodTime == DateTime.MinValue
                    ? double.PositiveInfinity
                    : (nowUtc - engine.LastVodTime).TotalSeconds;
                if (vodAge >= 0 && vodAge <= VodFadeSeconds)
                    pulseAlpha = (int)(230 * (1.0 - vodAge / VodFadeSeconds));
                int vodAlpha = Math.Max(steadyAlpha, pulseAlpha);
                if (vodAlpha > 0)
                {
                    using var vodFill = new SolidBrush(Color.FromArgb(vodAlpha, VodColor));
                    g.FillRectangle(vodFill, vodLeft + 1, vodTop + 1, vodWidth - 1, vodHeight - 1);
                }
                // Tiny "VOD" tag below the strip so it's identifiable at a glance
                using (var tagFont = new Font("Consolas", 7.0f))
                using (var tagBrush = new SolidBrush(Color.FromArgb(180, 200, 200, 200)))
                    g.DrawString("vod", tagFont, tagBrush, vodLeft - 1, vodTop + vodHeight + 1);

                // ── Cum bar ─────────────────────────────────────────────
                using (var bg = new SolidBrush(BgColor))
                    g.FillRectangle(bg, cumLeft, cumTop, CumBarWidth, cumH);
                using (var border = new Pen(BorderColor, 1f))
                    g.DrawRectangle(border, cumLeft, cumTop, CumBarWidth, cumH);

                using (var tick = new Pen(BorderColor, 1f))
                {
                    foreach (double frac in new[] { 0.25, 0.50, 0.75, 1.0 })
                    {
                        int dy = (int)(frac * halfCumH);
                        g.DrawLine(tick, cumLeft, cumCenterY - dy, cumLeft + 3, cumCenterY - dy);
                        g.DrawLine(tick, cumLeft, cumCenterY + dy, cumLeft + 3, cumCenterY + dy);
                    }
                }
                // Horizontal centerline kept short — meter stays self-contained,
                // doesn't extend across the chart.
                using (var c = new Pen(CenterColor, 1.5f))
                    g.DrawLine(c, cumLeft - 4, cumCenterY, cumLeft + CumBarWidth + 4, cumCenterY);

                if (Math.Abs(cum) > 1e-3)
                {
                    int cumPx = Math.Min(halfCumH, (int)((Math.Abs(cum) / CumScale) * halfCumH));
                    Color fc = cum > 0 ? BullColor : BearColor;
                    using var fb = new SolidBrush(Color.FromArgb(170, fc));
                    if (cum > 0)
                        g.FillRectangle(fb, cumLeft, cumCenterY - cumPx, CumBarWidth, cumPx);
                    else
                        g.FillRectangle(fb, cumLeft, cumCenterY, CumBarWidth, cumPx);
                }

                // ── Labels (cleanly stacked) ────────────────────────────
                using var labelFont = new Font("Consolas", 8.5f);
                using var labelBrush = new SolidBrush(LabelColor);

                int y = labelsTop;
                string cumTag = ManualAnchorUtc.HasValue ? "cum*" : "cum";
                g.DrawString($"{cumTag} {(cum >= 0 ? "+" : "")}{cum:0.0}",
                             labelFont, labelBrush, labelLeft, y);
                y += labelLineHeight;
                g.DrawString($"roc {(roc >= 0 ? "+" : "")}{roc:0.0}",
                             labelFont, labelBrush, labelLeft, y);

                y += labelLineHeight;
                g.DrawString($"vod {engine.VodCount30s}/30s",
                             labelFont, labelBrush, labelLeft, y);

                y += labelLineHeight;
                g.DrawString($"n={engine.EventCount}",
                             labelFont, labelBrush, labelLeft, y);

                if (ManualAnchorUtc.HasValue)
                {
                    y += labelLineHeight;
                    string anchorLocal;
                    try
                    {
                        var ny = TimeZoneInfo.FindSystemTimeZoneById("Eastern Standard Time");
                        var t = TimeZoneInfo.ConvertTime(ManualAnchorUtc.Value, ny);
                        anchorLocal = t.ToString("HH:mm:ss");
                    }
                    catch { anchorLocal = ManualAnchorUtc.Value.ToString("HH:mm:ss") + "Z"; }
                    using var anchorBrush = new SolidBrush(Color.FromArgb(220, 200, 180, 80));
                    g.DrawString($"@{anchorLocal}", labelFont, anchorBrush, labelLeft, y);
                }

                // Hit rect spans the visual region (ROC dial + VOD strip + cum bar +
                // labels block). Indicator's MouseClick handler reads this to tell
                // meter-region clicks from chart-area clicks.
                int hitLeft = Math.Min(rocLeft, cumLeft) - 4;
                int hitRight = Math.Max(vodLeft + vodWidth, cumLeft + CumBarWidth) + 4;
                // Labels can extend right of the dial — give a generous right pad
                // since "vod 12/30s" is wider than the dial when count is 2-digit.
                hitRight = Math.Max(hitRight, labelLeft + 80);
                int hitTop = rocTop - 4;
                int hitBottom = labelsTop + labelsH + 2;
                LastHitRect = new Rectangle(hitLeft, hitTop, hitRight - hitLeft, hitBottom - hitTop);
            }
            finally
            {
                g.SmoothingMode = prev;
            }
        }
    }
}
