using System.Drawing;
using System.Drawing.Drawing2D;
using System.Runtime.InteropServices;

namespace EarDispatcher;

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

        using var bid = new Pen(Color.FromArgb(74, 170, 132), 3.0f)
        {
            StartCap = LineCap.Round,
            EndCap = LineCap.Round,
        };
        using var ask = new Pen(Color.FromArgb(213, 96, 82), 3.0f)
        {
            StartCap = LineCap.Round,
            EndCap = LineCap.Round,
        };
        using var mid = new Pen(Color.FromArgb(224, 178, 72), 3.0f)
        {
            StartCap = LineCap.Round,
            EndCap = LineCap.Round,
        };

        g.DrawLine(bid, 9, 10, 20, 10);
        g.DrawLine(mid, 9, 16, 23, 16);
        g.DrawLine(ask, 9, 22, 17, 22);

        using var arrow = new Pen(Color.FromArgb(232, 232, 232), 2.0f)
        {
            StartCap = LineCap.Round,
            EndCap = LineCap.Round,
        };
        g.DrawLine(arrow, 20, 23, 25, 18);
        g.FillPolygon(
            Brushes.White,
            new[]
            {
                new Point(26, 17),
                new Point(23, 18),
                new Point(25, 20),
            });

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
