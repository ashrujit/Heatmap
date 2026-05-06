using System.Drawing;

namespace L2_Heatmap
{
    public static class Palette
    {
        // Bid = blue family; ask = orange family. Base tone for sub-saturation cells;
        // ignition tone for cells that exceed the saturation point (lifted alpha).
        public static readonly Color HeatmapBidBase     = Color.FromArgb(255,  80, 170, 230);
        public static readonly Color HeatmapAskBase     = Color.FromArgb(255, 230, 130,  90);
        public static readonly Color HeatmapBidIgnition = Color.FromArgb(255, 160, 220, 255);
        public static readonly Color HeatmapAskIgnition = Color.FromArgb(255, 255, 200, 130);
    }
}
