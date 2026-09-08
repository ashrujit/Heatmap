using System.Reflection;
using System.Text.Json;
using KahnDispatcher;

internal static class Program
{
    [STAThread]
    private static int Main()
    {
        try
        {
            Application.EnableVisualStyles();
            var settings = new DispatcherSettings();
            settings.NormalizeRuntimeProfiles();
            using var form = new MainForm(settings, observeRuntime: false);
            const BindingFlags flags = BindingFlags.NonPublic | BindingFlags.Instance;
            T Field<T>(string name) => (T)typeof(MainForm).GetField(name, flags)!.GetValue(form)!;
            Field<TextBox>("_rootRange").Text = "29000-29010";
            Field<TextBox>("_harvestRange").Text = "29190-29200";
            Field<RadioButton>("_longSide").Checked = true;
            Field<RadioButton>("_scaleMode").Checked = true;
            Field<TextBox>("_baseQuantity").Text = "2";
            Field<TextBox>("_maxQuantity").Text = "10";
            var command = typeof(MainForm).GetMethod("BuildKahnCommand", flags)!.Invoke(form, [true])!;
            var arguments = (IReadOnlyList<string>)command.GetType().GetProperty("Arguments")!.GetValue(command)!;
            Check(!arguments.Contains("--press") && !arguments.Contains("--no-add"), "legacy geography emitted");
            Check(arguments[arguments.ToList().IndexOf("--arena") + 1] == "29000:29200", "wrong envelope");
            Check(arguments.Contains("--dry-run") && !arguments.Contains("--dispatch"), "preview dispatched");
            var parser = typeof(MainForm).GetMethod("TryParseSketchImport", BindingFlags.NonPublic | BindingFlags.Static)!;
            string sketch = """{"schema_version":2,"status":"ok","active_draft":{"side":"long","root_range":{"lower":29000,"upper":29010},"harvest_range":{"lower":29190,"upper":29200}}}""";
            object?[] values = [sketch, null];
            Check((bool)parser.Invoke(null, values)!, "two-box import rejected");
            Check(!(bool)values[1]!.GetType().GetProperty("Legacy")!.GetValue(values[1])!, "new sketch is legacy");
            values = [sketch.Replace("\"schema_version\":2", "\"schema_version\":1"), null];
            Check((bool)parser.Invoke(null, values)! && (bool)values[1]!.GetType().GetProperty("Legacy")!.GetValue(values[1])!, "legacy conversion not explicit");
            var directory = Path.GetFullPath(Path.Combine(".tmp", "kahn-dispatcher-layout"));
            Directory.CreateDirectory(directory);
            form.StartPosition = FormStartPosition.Manual;
            form.Location = new Point(-32000, -32000);
            form.ShowInTaskbar = false;
            form.Opacity = 0;
            form.Show();
            foreach (var size in new[] { new Size(620, 540), new Size(900, 620) })
            {
                form.Size = size;
                form.CreateControl();
                form.PerformLayout();
                using var bitmap = new Bitmap(form.Width, form.Height);
                form.DrawToBitmap(bitmap, new Rectangle(Point.Empty, bitmap.Size));
                bitmap.Save(Path.Combine(directory, $"dispatcher-{size.Width}.png"));
            }
            form.Close();
            Console.WriteLine("PASS Dispatcher geometry/import contracts; captured minimum and desktop layouts.");
            return 0;
        }
        catch (Exception error) { Console.Error.WriteLine(error); return 1; }
    }
    private static void Check(bool value, string message) { if (!value) throw new Exception(message); }
}
