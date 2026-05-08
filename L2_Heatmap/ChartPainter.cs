using System;
using System.Collections.Generic;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Drawing.Imaging;
using TradingPlatform.BusinessLayer;
using TradingPlatform.BusinessLayer.Chart;

namespace L2_Heatmap
{
    public sealed class ChartPainter : IDisposable
    {
        // ── Heatmap bitmap caching ─────────────────────────────────────────
        // Persistent off-screen Bitmap matching the current chart rect dims.
        // Most paint frames are cache hits (single g.DrawImage blit, ~1ms).
        // Cache misses split into two paths:
        //   - Append-only delta (one snap added, possibly one rolled off, no pan):
        //     incremental update via AppendLastColumnIncremental — clears only the
        //     leftmost rolloff slice + the rightmost extend-zone, repaints just
        //     the new last column. Independent of snapshot count.
        //   - Anything else (pan, zoom, multi-snap delta, rect resize): full
        //     RebuildHeatmapBitmap. LockBits + raw int* writes for ~10× speedup
        //     over per-cell FillRectangle.
        private Bitmap _heatmapBitmap;
        private int _heatmapBitmapW, _heatmapBitmapH;
        private int _heatmapCachedSnapCount;
        private DateTime _heatmapCachedNewestT;
        private DateTime _heatmapCachedOldestT;
        private double _heatmapCachedFirstX;
        private double _heatmapCachedLastX;
        private bool _disposed;

        // Two-regime alpha lift constants. Sub-saturation regime is the
        // original linear curve. Above-saturation regime lifts alpha by
        // IgnitionGain per t-unit, capped at IgnitionAlphaCap, with the
        // color swapped to the brighter ignition tone.
        private const double IgnitionGain = 130.0;
        private const int IgnitionAlphaCap = 200;

        public LiquidityHeatmapBuffer Heatmap { get; set; }

        // Set by the indicator when L2 book is in stale or unreconcilable
        // state — paint a small badge so the user can see the cloud below
        // is frozen, not normal.
        public bool L2Stale { get; set; }

        public void Dispose()
        {
            if (_disposed) return;
            _disposed = true;
            _heatmapBitmap?.Dispose();
            _heatmapBitmap = null;
        }

        public void Paint(PaintChartEventArgs args, IChart currentChart)
        {
            if (currentChart == null || Heatmap == null) return;
            var g = args.Graphics;
            var converter = currentChart.MainWindow.CoordinatesConverter;
            var rect = args.Rectangle;
            g.SmoothingMode = SmoothingMode.AntiAlias;
            DrawLiquidityHeatmapCached(g, converter, rect, Heatmap);
            if (L2Stale) DrawStaleBadge(g, rect);
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

        // Bookmap-inspired liquidity heatmap. Painted as the chart backdrop.
        // Each retained book snapshot is one column; each (tick, size) entry
        // is one cell whose alpha scales with size (capped). Bid cells use
        // HeatmapBidBase RGB (blue), ask uses HeatmapAskBase (orange).
        private void DrawLiquidityHeatmapCached(Graphics g,
            IChartWindowCoordinatesConverter cv, Rectangle rect,
            LiquidityHeatmapBuffer heatmap)
        {
            var snapshots = heatmap.Snapshots;
            if (snapshots.Count == 0 || rect.Width <= 0 || rect.Height <= 0) return;

            // Recreate bitmap if rect dimensions changed (chart resize).
            if (_heatmapBitmap == null
                || _heatmapBitmapW != rect.Width
                || _heatmapBitmapH != rect.Height)
            {
                _heatmapBitmap?.Dispose();
                _heatmapBitmap = new Bitmap(rect.Width, rect.Height, PixelFormat.Format32bppArgb);
                _heatmapBitmapW = rect.Width;
                _heatmapBitmapH = rect.Height;
                _heatmapCachedSnapCount = -1; // force rebuild
            }

            // Identify cache-invalidating state. Walk the queue once for
            // count + oldest T (head) + newest T (tail) + the last two snaps
            // (newest + second-newest). The incremental-append path needs the
            // second-newest to verify "the OLD last snap is now at index n-2"
            // and to do its no-pan drift check.
            DateTime newestT = default, oldestT = default;
            int snapCount = 0;
            LiquidityHeatmapBuffer.BookSnapshot newestSnap = default, secondNewestSnap = default;
            foreach (var s in snapshots)
            {
                if (snapCount == 0) oldestT = s.T;
                secondNewestSnap = newestSnap;
                newestSnap = s;
                newestT = s.T;
                snapCount++;
            }

            // Geometry signature: pixel-X of oldest and newest snapshot. If
            // chart auto-scrolls, pans, or zooms, these drift, indicating the
            // cached bitmap's pixel positions no longer match chart coords.
            double firstX = cv.GetChartX(oldestT) - rect.Left;
            double lastX = cv.GetChartX(newestT) - rect.Left;

            bool needsRebuild =
                _heatmapCachedSnapCount != snapCount
                || _heatmapCachedNewestT != newestT
                || _heatmapCachedOldestT != oldestT
                || Math.Abs(firstX - _heatmapCachedFirstX) > 1
                || Math.Abs(lastX - _heatmapCachedLastX) > 1;

            if (needsRebuild)
            {
                // Try the cheap incremental path first. Falls back to full rebuild
                // if conditions aren't met (pan/zoom, multi-snap delta, etc).
                bool didIncremental = TryAppendIncremental(
                    cv, rect, heatmap,
                    newestSnap, secondNewestSnap,
                    snapCount, oldestT, newestT, firstX, lastX);

                if (!didIncremental)
                    RebuildHeatmapBitmap(cv, rect, heatmap, snapshots, snapCount);

                _heatmapCachedSnapCount = snapCount;
                _heatmapCachedNewestT = newestT;
                _heatmapCachedOldestT = oldestT;
                _heatmapCachedFirstX = firstX;
                _heatmapCachedLastX = lastX;
            }

            g.DrawImage(_heatmapBitmap, rect.Left, rect.Top);
        }

        // Rebuild the cached bitmap via LockBits + raw pointer writes. Skips
        // GDI+ FillRectangle entirely — direct memory writes per cell pixel,
        // ~30ns/pixel vs ~300ns/FillRectangle call.
        private unsafe void RebuildHeatmapBitmap(
            IChartWindowCoordinatesConverter cv, Rectangle rect,
            LiquidityHeatmapBuffer heatmap,
            IReadOnlyCollection<LiquidityHeatmapBuffer.BookSnapshot> snapshots,
            int snapCount)
        {
            int W = _heatmapBitmapW;
            int H = _heatmapBitmapH;
            double tickSize = heatmap.TickSize;
            int window = heatmap.LevelsWindowTicks;
            int alphaMax = heatmap.AlphaMax;
            double sizeAtSat = heatmap.EffectiveSaturation;
            double sizeFloor = heatmap.SizeFloor;
            Color bidBase = Palette.HeatmapBidBase;
            Color askBase = Palette.HeatmapAskBase;
            Color bidIgn = Palette.HeatmapBidIgnition;
            Color askIgn = Palette.HeatmapAskIgnition;

            // Materialize so we can peek next-T to compute column widths.
            var arr = new LiquidityHeatmapBuffer.BookSnapshot[snapCount];
            int n = 0;
            foreach (var s in snapshots) { if (n >= snapCount) break; arr[n++] = s; }

            var bmpRect = new Rectangle(0, 0, W, H);
            BitmapData data = _heatmapBitmap.LockBits(
                bmpRect, ImageLockMode.WriteOnly, PixelFormat.Format32bppArgb);
            try
            {
                byte* scan0 = (byte*)data.Scan0;
                int stride = data.Stride;

                // Clear to transparent — we OVERWRITE per cell, no alpha-composite,
                // so the previous frame's pixels would otherwise leak through.
                for (int y = 0; y < H; y++)
                {
                    int* row = (int*)(scan0 + y * stride);
                    for (int x = 0; x < W; x++) row[x] = 0;
                }

                int bidR = bidBase.R, bidG = bidBase.G, bidB = bidBase.B;
                int askR = askBase.R, askG = askBase.G, askB = askBase.B;
                int bidIgnR = bidIgn.R, bidIgnG = bidIgn.G, bidIgnB = bidIgn.B;
                int askIgnR = askIgn.R, askIgnG = askIgn.G, askIgnB = askIgn.B;

                for (int idx = 0; idx < n; idx++)
                {
                    var snap = arr[idx];
                    int x = (int)cv.GetChartX(snap.T) - rect.Left;
                    // Last (newest) column extends to the chart's right edge so the
                    // current resting book persists across the empty future area —
                    // matches Bookmap behavior. Cache invalidates on pan/zoom (lastX
                    // drift), so as the chart auto-scrolls this redraws to the new W.
                    int xNext = (idx + 1 < n)
                        ? ((int)cv.GetChartX(arr[idx + 1].T) - rect.Left)
                        : W;

                    // Column X-cull (in bitmap-relative coords).
                    if (xNext < 0 || x >= W) continue;
                    int colX = x < 0 ? 0 : x;
                    int colRight = xNext > W ? W : xNext;
                    if (colRight <= colX) continue;

                    long refTick = snap.RefTick;

                    foreach (var kv in snap.BidsByTick)
                    {
                        if (Math.Abs(kv.Key - refTick) > window) continue;
                        WriteHeatmapCellPixels(scan0, stride, W, H,
                            kv.Key, kv.Value, tickSize, colX, colRight,
                            bidR, bidG, bidB, bidIgnR, bidIgnG, bidIgnB,
                            alphaMax, sizeAtSat, sizeFloor, cv, rect);
                    }
                    foreach (var kv in snap.AsksByTick)
                    {
                        if (Math.Abs(kv.Key - refTick) > window) continue;
                        WriteHeatmapCellPixels(scan0, stride, W, H,
                            kv.Key, kv.Value, tickSize, colX, colRight,
                            askR, askG, askB, askIgnR, askIgnG, askIgnB,
                            alphaMax, sizeAtSat, sizeFloor, cv, rect);
                    }
                }
            }
            finally
            {
                _heatmapBitmap.UnlockBits(data);
            }
        }

        // Incremental-on-append fast path. Returns true if the bitmap was updated
        // here; false means caller must fall back to the full RebuildHeatmapBitmap.
        //
        // Conditions for the fast path:
        //   1. Previous frame exists (cached state valid).
        //   2. Snap count delta is exactly +1 (pure append, no rolloff) OR 0 with a
        //      different oldestT (append + rolloff at retention edge).
        //   3. The OLD last snap is now at the new second-to-last position with the
        //      same T as cached.
        //   4. No pan/zoom: OLD last snap's current X matches cached lastX (≤ 1 px).
        //   5. Pure-append additionally requires the oldest's X to be unchanged.
        //
        // Work performed:
        //   - Clear pixels [0, newFirstX): drops the rolled-off snap's leftmost slice.
        //   - Clear pixels [newLastX, W): the area that used to be the previous-last
        //     snap's "extend to edge" zone, now needs the new-last's extend.
        //   - Paint the new last snap's cells into [newLastX, W).
        //
        // The interior region [newFirstX, newLastX) is content-identical to the previous
        // frame: same snapshots at same X positions, with the previous-last now displayed
        // at its narrower native column width — pixel-identical to its previous extended
        // form within that narrower x-range.
        private unsafe bool TryAppendIncremental(
            IChartWindowCoordinatesConverter cv, Rectangle rect,
            LiquidityHeatmapBuffer heatmap,
            LiquidityHeatmapBuffer.BookSnapshot newestSnap,
            LiquidityHeatmapBuffer.BookSnapshot secondNewestSnap,
            int snapCount, DateTime oldestT, DateTime newestT,
            double firstX, double lastX)
        {
            if (_heatmapCachedSnapCount <= 0) return false;
            if (_heatmapBitmap == null) return false;
            if (snapCount < 2) return false;

            bool isAppendOnly = (snapCount == _heatmapCachedSnapCount + 1)
                && (oldestT == _heatmapCachedOldestT);
            bool isAppendPlusRolloff = (snapCount == _heatmapCachedSnapCount)
                && (oldestT != _heatmapCachedOldestT)
                && (newestT != _heatmapCachedNewestT);
            if (!isAppendOnly && !isAppendPlusRolloff) return false;

            // Sanity: the OLD last snap must now be at the new second-to-last position.
            if (secondNewestSnap.T != _heatmapCachedNewestT) return false;

            // No-pan check: OLD last snap's current X must still match cached lastX.
            double oldLastXNow = cv.GetChartX(secondNewestSnap.T) - rect.Left;
            if (Math.Abs(oldLastXNow - _heatmapCachedLastX) > 1) return false;

            // Pure-append: also verify the oldest snap's X didn't drift.
            if (isAppendOnly && Math.Abs(firstX - _heatmapCachedFirstX) > 1) return false;

            int W = _heatmapBitmapW;
            int newLastX = (int)cv.GetChartX(newestSnap.T) - rect.Left;
            // Off-screen cases: bail to full rebuild rather than try to handle here.
            if (newLastX <= 0 || newLastX >= W) return false;

            int newFirstX = (int)firstX;
            if (newFirstX < 0) newFirstX = 0;
            if (newFirstX > W) newFirstX = W;

            AppendLastColumnIncremental(cv, rect, heatmap, newestSnap, newFirstX, newLastX);
            return true;
        }

        // Apply the dirty-rect changes to the cached bitmap: clear leftmost rolloff
        // slice [0, newFirstX), clear rightmost extend-zone [newLastX, W), and repaint
        // just the new last snapshot's cells extended to the chart's right edge.
        // LockBits the full bitmap once; we only write to the slices we need.
        private unsafe void AppendLastColumnIncremental(
            IChartWindowCoordinatesConverter cv, Rectangle rect,
            LiquidityHeatmapBuffer heatmap,
            LiquidityHeatmapBuffer.BookSnapshot newLastSnap,
            int newFirstX, int newLastX)
        {
            int W = _heatmapBitmapW;
            int H = _heatmapBitmapH;
            double tickSize = heatmap.TickSize;
            int window = heatmap.LevelsWindowTicks;
            int alphaMax = heatmap.AlphaMax;
            double sizeAtSat = heatmap.EffectiveSaturation;
            double sizeFloor = heatmap.SizeFloor;
            Color bidBase = Palette.HeatmapBidBase;
            Color askBase = Palette.HeatmapAskBase;
            Color bidIgn = Palette.HeatmapBidIgnition;
            Color askIgn = Palette.HeatmapAskIgnition;

            var bmpRect = new Rectangle(0, 0, W, H);
            BitmapData data = _heatmapBitmap.LockBits(
                bmpRect, ImageLockMode.WriteOnly, PixelFormat.Format32bppArgb);
            try
            {
                byte* scan0 = (byte*)data.Scan0;
                int stride = data.Stride;

                // Clear leftmost rolloff slice [0, newFirstX). Skipped when no rolloff
                // happened and the chart never panned right (newFirstX = 0).
                if (newFirstX > 0)
                {
                    for (int y = 0; y < H; y++)
                    {
                        int* row = (int*)(scan0 + y * stride);
                        for (int x = 0; x < newFirstX; x++) row[x] = 0;
                    }
                }

                // Clear rightmost extend-zone [newLastX, W). This is the area that
                // was previously snap-N-1 extended; now must be snap-N extended.
                for (int y = 0; y < H; y++)
                {
                    int* row = (int*)(scan0 + y * stride);
                    for (int x = newLastX; x < W; x++) row[x] = 0;
                }

                // Paint the new last snapshot into [newLastX, W).
                int colX = newLastX;
                int colRight = W;
                if (colRight <= colX) return;

                long refTick = newLastSnap.RefTick;

                foreach (var kv in newLastSnap.BidsByTick)
                {
                    if (Math.Abs(kv.Key - refTick) > window) continue;
                    WriteHeatmapCellPixels(scan0, stride, W, H,
                        kv.Key, kv.Value, tickSize, colX, colRight,
                        bidBase.R, bidBase.G, bidBase.B,
                        bidIgn.R, bidIgn.G, bidIgn.B,
                        alphaMax, sizeAtSat, sizeFloor, cv, rect);
                }
                foreach (var kv in newLastSnap.AsksByTick)
                {
                    if (Math.Abs(kv.Key - refTick) > window) continue;
                    WriteHeatmapCellPixels(scan0, stride, W, H,
                        kv.Key, kv.Value, tickSize, colX, colRight,
                        askBase.R, askBase.G, askBase.B,
                        askIgn.R, askIgn.G, askIgn.B,
                        alphaMax, sizeAtSat, sizeFloor, cv, rect);
                }
            }
            finally
            {
                _heatmapBitmap.UnlockBits(data);
            }
        }

        // Write one cell's pixels directly into the bitmap's locked memory.
        // Two-regime curve:
        //   t = size / sizeAtSat
        //   t ≤ 1.0  → alpha = t × alphaMax,             color = base RGB
        //   t > 1.0  → alpha = alphaMax + (t−1) × IgnitionGain (capped at IgnitionAlphaCap),
        //              color = ignition RGB
        // Sub-saturation regime is pixel-identical to a plain linear curve. The
        // above-saturation regime lifts alpha and swaps to the brighter tone so
        // the top tail of the size distribution unfolds into a visible gradient
        // instead of clamping flat.
        //
        // Cells overlap with last-write-wins semantics. In practice cells from a
        // single snapshot don't overlap (different prices = different Y), and
        // cross-snapshot overlap is limited to adjacent column edges.
        private static unsafe void WriteHeatmapCellPixels(
            byte* scan0, int stride, int W, int H,
            long tick, double size, double tickSize,
            int colX, int colRight,
            int r, int g, int b, int ignR, int ignG, int ignB,
            int alphaMax, double sizeAtSat, double sizeFloor,
            IChartWindowCoordinatesConverter cv, Rectangle rect)
        {
            if (size < sizeFloor) return;

            double price = tick * tickSize;
            int yMid = (int)cv.GetChartY(price) - rect.Top;
            int yPrev = (int)cv.GetChartY(price - tickSize) - rect.Top;
            int cellH = Math.Max(1, Math.Abs(yPrev - yMid));
            int yTop = yMid - cellH / 2;
            int yBot = yTop + cellH;

            // Y-axis cull + clip to bitmap bounds.
            if (yBot <= 0 || yTop >= H) return;
            if (yTop < 0) yTop = 0;
            if (yBot > H) yBot = H;

            int alpha;
            int rUse, gUse, bUse;
            double t = size / sizeAtSat;
            if (t <= 1.0 || alphaMax >= IgnitionAlphaCap)
            {
                // Sub-saturation regime: original linear curve, base color.
                alpha = (int)(t * alphaMax);
                if (alpha > alphaMax) alpha = alphaMax;
                rUse = r; gUse = g; bUse = b;
            }
            else
            {
                // Above-saturation lift: alpha climbs from alphaMax toward
                // IgnitionAlphaCap; color swaps to the brighter ignition tone.
                alpha = alphaMax + (int)((t - 1.0) * IgnitionGain);
                if (alpha > IgnitionAlphaCap) alpha = IgnitionAlphaCap;
                rUse = ignR; gUse = ignG; bUse = ignB;
            }
            if (alpha <= 0) return;

            // ARGB32 packed: 0xAARRGGBB (alpha in MSB, then R, G, B).
            int pixel = (alpha << 24) | (rUse << 16) | (gUse << 8) | bUse;

            for (int y = yTop; y < yBot; y++)
            {
                int* row = (int*)(scan0 + y * stride);
                for (int x = colX; x < colRight; x++) row[x] = pixel;
            }
        }
    }
}
