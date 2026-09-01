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
        using var harvest = new Pen(Color.FromArgb(224, 178, 72), 2.0f);
        using var route = new Pen(Color.FromArgb(232, 232, 232), 2.0f)
        {
            StartCap = LineCap.Round,
            EndCap = LineCap.Round,
        };

        g.DrawRectangle(root, 7, 8, 10, 8);
        g.DrawRectangle(harvest, 15, 16, 10, 7);
        g.DrawLine(route, 17, 14, 22, 18);
        g.FillPolygon(
            Brushes.White,
            new[]
            {
                new Point(23, 19),
                new Point(20, 18),
                new Point(22, 16),
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
