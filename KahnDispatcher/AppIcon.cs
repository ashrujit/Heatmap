using System.Drawing;
using System.Drawing.Drawing2D;
using System.Runtime.InteropServices;

namespace KahnDispatcher;

internal static class AppIcon
{
    public static Icon Create()
    {
        using var bitmap = new Bitmap(32, 32);
        using Graphics g = Graphics.FromImage(bitmap);
        g.SmoothingMode = SmoothingMode.AntiAlias;
        g.Clear(Color.Transparent);

        using var shell = new SolidBrush(Palette.Back);
        using var rim = new Pen(Palette.ButtonBorder, 2.0f);
        g.FillRectangle(shell, 3, 3, 26, 26);
        g.DrawRectangle(rim, 3, 3, 26, 26);

        using var root = new Pen(Color.FromArgb(74, 170, 132), 2.0f);
        using var middle = new Pen(Color.FromArgb(224, 178, 72), 2.0f);
        using var harvest = new Pen(Color.FromArgb(72, 142, 238), 2.0f);
        using var route = new Pen(Color.FromArgb(232, 232, 232), 2.0f)
        {
            StartCap = LineCap.Round,
            EndCap = LineCap.Round,
        };

        g.DrawRectangle(root, 7, 8, 8, 6);
        g.DrawRectangle(middle, 12, 14, 8, 6);
        g.DrawRectangle(harvest, 17, 20, 8, 5);
        g.DrawLine(route, 15, 13, 22, 21);
        g.FillPolygon(
            Brushes.White,
            new[]
            {
                new Point(23, 22),
                new Point(20, 21),
                new Point(22, 19),
            });

        using var kBrush = new SolidBrush(Color.FromArgb(232, 232, 232));
        using var kFont = new Font("Cascadia Mono", 8.0f, FontStyle.Bold, GraphicsUnit.Point);
        g.DrawString("K", kFont, kBrush, 7, 17);

        IntPtr handle = bitmap.GetHicon();
        try
        {
            using Icon icon = Icon.FromHandle(handle);
            return (Icon)icon.Clone();
        }
        finally
        {
            DestroyIcon(handle);
        }
    }

    [DllImport("user32.dll", SetLastError = true)]
    private static extern bool DestroyIcon(IntPtr hIcon);
}
