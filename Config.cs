using System.Text.Json;
using Microsoft.Win32;

namespace CargoDeckScanner;

class Config
{
    public string Url { get; set; } = "https://cargodeck.onrender.com";
    public string Code { get; set; } = "";
    public string Mode { get; set; } = "hotkey";   // hotkey oder auto
    public int Interval { get; set; } = 5;
    public string ScanKey { get; set; } = "ö";
    public string AutoKey { get; set; } = "ä";
    public int ScanVk { get; set; }
    public int AutoVk { get; set; }
    public bool Sounds { get; set; } = true;
    public bool Notify { get; set; } = true;
    public bool Autostart { get; set; } = false;
    public bool StartMinimized { get; set; } = false;
    public string Lang { get; set; } = "";          // de oder en, leer = wie Windows
    public bool Pinned { get; set; } = false;       // kleines Fenster immer im Vordergrund, wie beim Windows Rechner
    public bool TopMost { get; set; } = false;      // großes Fenster immer im Vordergrund
    public int PinX { get; set; } = -1;
    public int PinY { get; set; } = -1;

    [System.Runtime.InteropServices.DllImport("kernel32.dll")] static extern ushort GetUserDefaultUILanguage();
    public static string SystemLang() { try { return (GetUserDefaultUILanguage() & 0x3FF) == 0x07 ? "de" : "en"; } catch { return "de"; } }

    static string Dir => Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData), "CargoDeck");
    static string FilePath => Path.Combine(Dir, "scanner.json");
    static readonly JsonSerializerOptions Opt = new() { WriteIndented = true };

    public static Config Load()
    {
        try
        {
            if (File.Exists(FilePath))
            {
                var c = JsonSerializer.Deserialize<Config>(File.ReadAllText(FilePath)) ?? new Config();
                c.Interval = Math.Clamp(c.Interval, 3, 60);
                if (string.IsNullOrEmpty(c.ScanKey)) c.ScanKey = "ö";
                if (string.IsNullOrEmpty(c.AutoKey)) c.AutoKey = "ä";
                if (c.ScanVk <= 0) c.ScanVk = KeyNames.FromChar(c.ScanKey);
                if (c.AutoVk <= 0) c.AutoVk = KeyNames.FromChar(c.AutoKey);
                if (c.Lang != "de" && c.Lang != "en") c.Lang = SystemLang();
                return c;
            }
        }
        catch { }
        var n = new Config(); n.ScanVk = KeyNames.FromChar(n.ScanKey); n.AutoVk = KeyNames.FromChar(n.AutoKey); n.Lang = SystemLang(); return n;
    }

    public void Save()
    {
        try
        {
            Directory.CreateDirectory(Dir);
            File.WriteAllText(FilePath, JsonSerializer.Serialize(this, Opt));
            SetAutostart(Autostart);
        }
        catch { }
    }

    static void SetAutostart(bool on)
    {
        if (Packaged.IsPackaged) { Packaged.SetStartup(on); return; }
        try
        {
            using var k = Registry.CurrentUser.OpenSubKey(@"Software\Microsoft\Windows\CurrentVersion\Run", true);
            if (k == null) return;
            if (on) k.SetValue("CargoDeckScanner", $"\"{Environment.ProcessPath}\" --tray");
            else if (k.GetValue("CargoDeckScanner") != null) k.DeleteValue("CargoDeckScanner");
        }
        catch { }
    }
}
