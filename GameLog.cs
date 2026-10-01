using System.Globalization;
using System.Text;
using System.Text.Json.Nodes;
using System.Text.RegularExpressions;

namespace CargoDeckScanner;

// Liest die Game.log von Star Citizen mit und erkennt Käufe und Verkäufe am Handelsterminal (Beta, nur Admins).
// Aus jeder Zeile wird nur das genommen, was für den Preis nötig ist: interner Ort, interner Shop Name,
// Kennung der Ware, Preis pro SCU, Menge und Uhrzeit. Spielername und Spieler ID werden nie gelesen oder gesendet.
class GameLogWatcher
{
    public string Path { get; private set; }
    long pos = -1;
    string rest = "";
    string loc;
    readonly Dictionary<string, HashSet<string>> inv = new();
    // Kauf wartet auf die Bestätigung im Log (AddPlayerCommodityItem am selben Shop)
    readonly List<(JsonObject t, string shopId, DateTime at)> waitBuy = new();
    readonly List<JsonObject> ready = new();
    DateTime lastEvent = DateTime.MinValue;

    static readonly Regex ReLoc = new(@"<RequestLocationInventory>.*?Location\[([^\]]{1,120})\]");
    static readonly Regex ReInv = new(@"LoadShopInventoryData.*?shopId\[(\d+)\].*?commodityName\[([^\]]{1,60})\]");
    static readonly Regex ReBuy = new(@"SendCommodityBuyRequest.*?shopId\[(\d+)\].*?shopName\[([^\]]{1,80})\].*?shopPricePerCentiSCU\[([\d.]+)\].*?resourceGUID\[([0-9a-fA-F-]{36})\].*?quantity\[([\d.]+) cSCU\]");
    static readonly Regex ReSell = new(@"SendCommoditySellRequest.*?shopId\[(\d+)\].*?shopName\[([^\]]{1,80})\].*?amount\[([\d.]+)\].*?resourceGUID\[([0-9a-fA-F-]{36})\].*?quantity\[([\d.]+)\]");
    static readonly Regex ReAdd = new(@"AddPlayerCommodityItem.*?shopId\[(\d+)\]");

    public static string Find(string custom)
    {
        if (!string.IsNullOrWhiteSpace(custom))
        {
            var c = custom.Trim().Trim('"');
            if (Directory.Exists(c)) c = System.IO.Path.Combine(c, "Game.log");
            if (File.Exists(c)) return c;
        }
        foreach (var d in DriveInfo.GetDrives().Where(x => x.DriveType == DriveType.Fixed).Select(x => x.Name))
            foreach (var sub in new[] { @"Program Files\Roberts Space Industries\StarCitizen", @"Roberts Space Industries\StarCitizen", @"Games\Roberts Space Industries\StarCitizen", @"StarCitizen" })
                foreach (var ch in new[] { "LIVE", "PTU", "EPTU", "HOTFIX" })
                {
                    var f = System.IO.Path.Combine(d, sub, ch, "Game.log");
                    try { if (File.Exists(f)) return f; } catch { }
                }
        return null;
    }

    public GameLogWatcher(string path) { Path = path; }

    // Neue Zeilen lesen. Beim ersten Mal ab dem Ende, alte Käufe werden nicht nachgeschickt.
    public void Poll()
    {
        if (Path == null) return;
        FileInfo fi;
        try { fi = new FileInfo(Path); if (!fi.Exists) return; } catch { return; }
        long len = fi.Length;
        if (pos < 0) { pos = len; return; }
        if (len < pos) { pos = 0; rest = ""; loc = null; inv.Clear(); waitBuy.Clear(); }   // neues Spiel, neue Datei
        if (len == pos) { Expire(); return; }
        try
        {
            using var fs = new FileStream(Path, FileMode.Open, FileAccess.Read, FileShare.ReadWrite | FileShare.Delete);
            fs.Seek(pos, SeekOrigin.Begin);
            var buf = new byte[Math.Min(len - pos, 8 * 1024 * 1024)];
            int n = fs.Read(buf, 0, buf.Length);
            pos += n;
            var text = rest + Encoding.UTF8.GetString(buf, 0, n);
            int cut = text.LastIndexOf('\n');
            if (cut < 0) { rest = text; return; }
            rest = text[(cut + 1)..];
            foreach (var line in text[..cut].Split('\n')) Line(line);
        }
        catch { }
        Expire();
    }

    static long TimeOf(string line)
    {
        if (line.Length > 26 && line[0] == '<' && DateTime.TryParse(line.Substring(1, 24), CultureInfo.InvariantCulture, DateTimeStyles.AdjustToUniversal | DateTimeStyles.AssumeUniversal, out var t))
            return new DateTimeOffset(t, TimeSpan.Zero).ToUnixTimeMilliseconds();
        return DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
    }
    static double D(string s) => double.Parse(s, CultureInfo.InvariantCulture);

    void Line(string l)
    {
        if (l.Contains("<RequestLocationInventory>")) { var m = ReLoc.Match(l); if (m.Success) loc = m.Groups[1].Value; return; }
        if (l.Contains("LoadShopInventoryData")) { var m = ReInv.Match(l); if (m.Success) { if (!inv.TryGetValue(m.Groups[1].Value, out var set)) inv[m.Groups[1].Value] = set = new(); if (set.Count < 40) set.Add(m.Groups[2].Value); } return; }
        if (l.Contains("SendCommodityBuyRequest"))
        {
            var m = ReBuy.Match(l); if (!m.Success || loc == null) return;
            var t = Trade("buy", m.Groups[2].Value, m.Groups[4].Value, D(m.Groups[3].Value) * 100, D(m.Groups[5].Value) / 100, TimeOf(l), m.Groups[1].Value);
            waitBuy.Add((t, m.Groups[1].Value, DateTime.Now)); lastEvent = DateTime.Now; return;
        }
        if (l.Contains("AddPlayerCommodityItem"))
        {
            var m = ReAdd.Match(l); if (!m.Success) return;
            int i = waitBuy.FindIndex(w => w.shopId == m.Groups[1].Value);
            if (i >= 0) { ready.Add(waitBuy[i].t); waitBuy.RemoveAt(i); lastEvent = DateTime.Now; }
            return;
        }
        if (l.Contains("SendCommoditySellRequest"))
        {
            var m = ReSell.Match(l); if (!m.Success || loc == null) return;
            double q = D(m.Groups[5].Value); if (q <= 0) return;
            ready.Add(Trade("sell", m.Groups[2].Value, m.Groups[4].Value, D(m.Groups[3].Value) / q, q, TimeOf(l), m.Groups[1].Value)); lastEvent = DateTime.Now;
        }
    }

    JsonObject Trade(string kind, string shop, string guid, double price, double qty, long time, string shopId)
    {
        var a = new JsonArray(); if (inv.TryGetValue(shopId, out var set)) foreach (var s in set) a.Add(s);
        return new JsonObject { ["kind"] = kind, ["loc"] = loc, ["shop"] = shop, ["guid"] = guid.ToLowerInvariant(), ["inv"] = a, ["price"] = Math.Round(price, 2), ["qty"] = Math.Round(qty, 2), ["time"] = time };
    }

    // Kauf ohne Bestätigung nach 15 Sekunden verwerfen, dann ging er wohl nicht durch
    void Expire() { waitBuy.RemoveAll(w => DateTime.Now - w.at > TimeSpan.FromSeconds(15)); }

    // Fertige Käufe und Verkäufe, sobald 12 Sekunden nichts Neues kam. So landen mehrere Käufe an einer Station in einem Scan.
    public List<JsonObject> Take()
    {
        if (ready.Count == 0 || waitBuy.Count > 0 || DateTime.Now - lastEvent < TimeSpan.FromSeconds(12)) return null;
        var list = ready.ToList(); ready.Clear(); return list;
    }
}
