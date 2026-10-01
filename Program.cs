using System.Drawing;

namespace CargoDeckScanner;

static class Program
{
    [STAThread]
    static int Main(string[] args)
    {
        // Zahlen und Texte immer invariant wie bisher, egal welche Sprache Windows hat
        var inv = System.Globalization.CultureInfo.InvariantCulture;
        System.Globalization.CultureInfo.DefaultThreadCurrentCulture = inv;
        System.Globalization.CultureInfo.DefaultThreadCurrentUICulture = inv;
        System.Globalization.CultureInfo.CurrentCulture = inv;
        System.Globalization.CultureInfo.CurrentUICulture = inv;
        // Prüfmodus, liest ein Bild und schreibt das Ergebnis der Texterkennung in eine Datei
        if (args.Length >= 3 && args[0] == "--ocr-test")
        {
            try
            {
                using var bmp = new Bitmap(args[1]);
                var res = Ocr.Run(bmp).GetAwaiter().GetResult();
                File.WriteAllText(args[2], res.ToJsonString());
                return 0;
            }
            catch (Exception ex) { File.WriteAllText(args[2], "{\"ok\":false,\"error\":" + System.Text.Json.JsonSerializer.Serialize(ex.ToString()) + "}"); return 1; }
        }

        // Fehler abfangen und in eine Datei schreiben statt abzustürzen
        Application.SetUnhandledExceptionMode(UnhandledExceptionMode.CatchException);
        Application.ThreadException += (s, e) => Crash(e.Exception, true);
        AppDomain.CurrentDomain.UnhandledException += (s, e) => Crash(e.ExceptionObject as Exception, false);
        TaskScheduler.UnobservedTaskException += (s, e) => { Crash(e.Exception, false); e.SetObserved(); };

        Lang.En = Config.Load().Lang == "en";
        using var mutex = new Mutex(true, "CargoDeckScanner_single", out bool first);
        if (!first && args.Contains("--restart"))
        {
            // Beim Neustart warten, bis die alte App zu ist
            try { first = mutex.WaitOne(10000); } catch (AbandonedMutexException) { first = true; }
        }
        if (!first && !args.Contains("--ui-shot"))
        {
            MessageBox.Show(Lang.T("already"), "Cargo Deck Price Capture");
            return 0;
        }
        ApplicationConfiguration.Initialize();
        var form = new MainForm(args.Contains("--tray") || Packaged.StartedByWindows(), args.Contains("--run"));
        // Prüfmodus für Bilder der Oberfläche: bestimmten Reiter zeigen
        int pg = Array.IndexOf(args, "--page");
        if (pg >= 0 && pg + 1 < args.Length && int.TryParse(args[pg + 1], out var pgi)) form.Shown += (s, e) => form.DebugPage(pgi);
        // Prüfmodus, speichert ein Bild vom Fenster und beendet sich
        int ui = Array.IndexOf(args, "--ui-shot");
        if (ui >= 0 && ui + 1 < args.Length)
        {
            var path = args[ui + 1];
            form.Shown += async (s, e) =>
            {
                await Task.Delay(800);
                using var b = new Bitmap(form.Width, form.Height);
                form.DrawToBitmap(b, new Rectangle(0, 0, form.Width, form.Height));
                b.Save(path);
                form.Close();
            };
        }
        Application.Run(form);
        return 0;
    }

    static void Crash(Exception ex, bool show)
    {
        try
        {
            var dir = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData), "CargoDeck");
            Directory.CreateDirectory(dir);
            File.AppendAllText(Path.Combine(dir, "scanner-fehler.log"), $"{DateTime.Now:yyyy-MM-dd HH:mm:ss}  {ex}\r\n\r\n");
        }
        catch { }
        if (show) try { MessageBox.Show(Lang.T("crash") + "\n\n" + ex?.Message + "\n\n" + Lang.T("crash_log"), "Cargo Deck Price Capture"); } catch { }
    }
}

