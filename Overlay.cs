using System.Drawing;
using System.Drawing.Drawing2D;
using System.Globalization;
using System.Runtime.InteropServices;
using System.Text.Json.Nodes;
using static CargoDeckScanner.Lang;

namespace CargoDeckScanner;

// Overlay über dem Spiel (Beta). Zeigt sich, sobald der Kopplungscode zu einem Konto auf der Website gehört.
// Zeigt die aktive Route von Cargo Deck, Stopp für Stopp mit Kauf und Verkauf. Nimmt dem Spiel nie den Fokus,
// bedient wird es über Tastenkürzel oder mit der Maus, wenn der Mauszeiger im Spiel frei ist.
class OverlayForm : Form
{
    static readonly Color cBg = Color.FromArgb(0x10, 0x16, 0x20), cCard = Color.FromArgb(0x14, 0x1c, 0x28), cLine = Color.FromArgb(0x24, 0x31, 0x42),
        cLine2 = Color.FromArgb(0x30, 0x40, 0x56), cText = Color.FromArgb(0xee, 0xf3, 0xf9), cMuted = Color.FromArgb(0x8f, 0x9d, 0xb1),
        cDim = Color.FromArgb(0x66, 0x74, 0x8a), cAccent = Color.FromArgb(0x35, 0xd6, 0xcc), cGood = Color.FromArgb(0x4a, 0xde, 0x80),
        cBeta = Color.FromArgb(0xa7, 0x8b, 0xfa), cDark = Color.FromArgb(0x0b, 0x0f, 0x14);
    // Stoppfarben wie auf der Website (LEGC)
    static readonly Color[] Leg = { C("#38bdf8"), C("#fb923c"), C("#f472b6"), C("#a3e635"), C("#facc15"), C("#2dd4bf"), C("#f87171"), C("#818cf8") };
    static Color C(string h) => ColorTranslator.FromHtml(h);

    const int W = 340;
    float k;
    int S(float v) => (int)Math.Round(v * k);

    JsonNode data;
    string note;
    bool picker;
    int sel;
    // aufgeklappt: eine angepinnte Route mit allen Stopps, einzelne Stopps der aktiven Route mit Preisen, alle Stopps statt vier
    string openPin, activeId;
    readonly HashSet<int> openStops = new();
    bool showAll;
    readonly List<(Rectangle r, string cmd, string id)> hits = new();

    // Befehl an die Website: next, prev, stop, pick (mit id) oder picker (nur hier)
    public event Action<string, string> Command;
    public event Action Moved2;

    public OverlayForm()
    {
        FormBorderStyle = FormBorderStyle.None;
        ShowInTaskbar = false; TopMost = true; StartPosition = FormStartPosition.Manual;
        AutoScaleMode = AutoScaleMode.None;
        BackColor = cBg; Opacity = 0.94;
        SetStyle(ControlStyles.AllPaintingInWmPaint | ControlStyles.OptimizedDoubleBuffer | ControlStyles.UserPaint | ControlStyles.ResizeRedraw, true);
        k = DeviceDpi / 96f;
        Size = new Size(S(W), S(120));
        Text = "Cargo Deck Overlay";
    }

    // Kein Fokus, kein Eintrag in der Taskleiste und bei Alt+Tab
    protected override CreateParams CreateParams
    {
        get { var cp = base.CreateParams; cp.ExStyle |= 0x08000000 | 0x00000080 | 0x00000008; return cp; }
    }
    protected override bool ShowWithoutActivation => true;
    const int WM_MOUSEACTIVATE = 0x21, MA_NOACTIVATE = 3;
    protected override void WndProc(ref Message m)
    {
        if (m.Msg == WM_MOUSEACTIVATE) { m.Result = (IntPtr)MA_NOACTIVATE; return; }
        base.WndProc(ref m);
    }

    [DllImport("dwmapi.dll")] static extern int DwmSetWindowAttribute(IntPtr h, int attr, ref int val, int size);
    protected override void OnHandleCreated(EventArgs e)
    {
        base.OnHandleCreated(e);
        try { int r = 2; DwmSetWindowAttribute(Handle, 33, ref r, 4); } catch { }   // runde Ecken (Windows 11)
    }
    protected override void OnDpiChanged(DpiChangedEventArgs e) { base.OnDpiChanged(e); k = DeviceDpi / 96f; Relayout(); }

    public bool PickerOpen => picker;
    public void SetData(JsonNode d, string msg = null)
    {
        data = d; note = msg;
        var pins = d?["pins"] as JsonArray;
        if (pins != null && sel >= pins.Count) sel = Math.Max(0, pins.Count - 1);
        if (openPin != null && (pins == null || !pins.Any(p => p?["id"]?.GetValue<string>() == openPin))) openPin = null;
        // andere aktive Route: Aufgeklapptes zurücksetzen
        var aid = d?["active"]?["id"]?.GetValue<string>();
        if (aid != activeId) { activeId = aid; openStops.Clear(); showAll = false; }
        Relayout();
    }
    public void TogglePicker() { picker = !picker; sel = 0; Relayout(); }
    // Ausgewählte angepinnte Route auf- oder zuklappen (Taste oder Klick)
    public void ToggleOpenSel() { var id = SelectedId(); if (id == null) return; openPin = openPin == id ? null : id; Relayout(); }
    public void ClosePicker() { if (!picker) return; picker = false; Relayout(); }
    public void MoveSel(int d)
    {
        var n = (data?["pins"] as JsonArray)?.Count ?? 0; if (n == 0) return;
        sel = (sel + d + n) % n; Relayout();
    }
    public string SelectedId() => (data?["pins"] as JsonArray)?.ElementAtOrDefault(sel)?["id"]?.GetValue<string>();

    // Höhe an den Inhalt anpassen
    void Relayout()
    {
        if (IsDisposed) return;
        using (var g = CreateGraphics()) { int h = Draw(g, false); if (Height != h) Height = h; }
        Invalidate();
    }

    protected override void OnPaint(PaintEventArgs e)
    {
        var g = e.Graphics;
        g.SmoothingMode = SmoothingMode.AntiAlias;
        g.TextRenderingHint = System.Drawing.Text.TextRenderingHint.ClearTypeGridFit;
        g.Clear(cBg);
        Draw(g, true);
        using var p = new Pen(cLine2); g.DrawRectangle(p, 0, 0, Width - 1, Height - 1);
    }

    static readonly NumberFormatInfo Nf = new() { NumberGroupSeparator = "'", NumberDecimalSeparator = "." };
    static string Num(double v) => Math.Round(v).ToString("#,0", Nf);
    static string Big(double v) => Math.Abs(v) >= 1e6 ? (v / 1e6).ToString("0.00", Nf) + " M" : Math.Abs(v) >= 1e4 ? (v / 1e3).ToString("0", Nf) + " k" : Num(v);

    Font F(float px, bool bold = false) => new("Segoe UI", px * 0.75f, bold ? FontStyle.Bold : FontStyle.Regular);

    // Zeichnet alles. Ohne draw wird nur die Höhe gemessen.
    int Draw(Graphics g, bool draw)
    {
        hits.Clear();
        int pad = S(14), x = pad, w = Width - 2 * pad, y = S(12);
        using var f12 = F(12); using var f12b = F(12, true); using var f14 = F(14); using var f14b = F(14, true); using var f16b = F(16, true);
        void Txt(string s, Font f, Color c, int tx, int ty, int tw, TextFormatFlags fl = TextFormatFlags.Left)
        { if (draw) TextRenderer.DrawText(g, s, f, new Rectangle(tx, ty, tw, S(40)), c, fl | TextFormatFlags.NoPadding | TextFormatFlags.EndEllipsis | TextFormatFlags.SingleLine); }
        int TW(string s, Font f) => TextRenderer.MeasureText(g, s, f, Size.Empty, TextFormatFlags.NoPadding).Width;
        void Box(Rectangle r, Color fill, Color line, float rad, Color? bar = null)
        {
            if (!draw) return;
            using var path = Ui.Round(new RectangleF(r.X + .5f, r.Y + .5f, r.Width - 1, r.Height - 1), rad);
            using (var b = new SolidBrush(fill)) g.FillPath(b, path);
            if (bar is Color bc) { var st = g.Save(); g.SetClip(path); using (var bb = new SolidBrush(bc)) g.FillRectangle(bb, r.X, r.Y, S(3), r.Height); g.Restore(st); }
            using var p = new Pen(line); g.DrawPath(p, path);
        }
        void Button(Rectangle r, string text, bool primary, string cmd, string id = null, Font bf = null)
        {
            Box(r, primary ? cAccent : cCard, primary ? cAccent : cLine2, S(8));
            if (draw) TextRenderer.DrawText(g, text, bf ?? f14b, r, primary ? cDark : cText, TextFormatFlags.HorizontalCenter | TextFormatFlags.VerticalCenter | TextFormatFlags.NoPadding);
            hits.Add((r, cmd, id));
        }

        // Kopf: Titel, Beta Tag, rechts der Stand. Hier lässt sich das Fenster verschieben.
        var act = data?["active"] as JsonObject;
        var stops = act?["stops"] as JsonArray;
        int step = act?["step"]?.GetValue<int>() ?? 0;
        string title = picker ? T("ov_pins") : T("ov_active");
        Txt(title, f14b, cText, x, y, w);
        int tx = x + TW(title, f14b) + S(8);
        var tagR = new Rectangle(tx, y + S(1), TW("Beta", f12) + S(12), S(18));
        Box(tagR, cBg, Color.FromArgb(128, cBeta), S(6));
        if (draw) TextRenderer.DrawText(g, "Beta", f12, tagR, cBeta, TextFormatFlags.HorizontalCenter | TextFormatFlags.VerticalCenter | TextFormatFlags.NoPadding);
        if (!picker && stops != null) Txt(T("ov_stop", step + 1, stops.Count), f12, cMuted, x, y + S(2), w, TextFormatFlags.Right);
        y += S(30);

        if (note != null)
        {
            y = Para(g, draw, note, f12, cMuted, x, y, w) + S(10);
        }

        if (picker)
        {
            var pins = data?["pins"] as JsonArray;
            if (pins == null || pins.Count == 0) y = Para(g, draw, T("ov_nopins"), f12, cMuted, x, y, w) + S(10);
            else for (int i = 0; i < pins.Count; i++)
                {
                    var p = pins[i];
                    string id = p?["id"]?.GetValue<string>();
                    bool open = id != null && id == openPin;
                    // Karte zweimal: erst messen, dann Fläche zeichnen, dann Inhalt
                    int bottom = PinCard(g, false, p, x, y, w, open, f12, f12b, f14b);
                    var r = new Rectangle(x, y, w, bottom - y);
                    Box(r, cCard, i == sel || open ? cAccent : cLine, S(12));
                    PinCard(g, draw, p, x, y, w, open, f12, f12b, f14b);
                    // Klick auf den Kopf klappt auf, der Knopf unten startet
                    hits.Add((new Rectangle(x, y, w, open ? S(34) + TextH(g, PTitle(p), f14b, w - S(20)) : r.Height), "pinopen", id));
                    if (open) hits.Add((new Rectangle(x + S(10), bottom - S(44), w - S(20), S(34)), "pick", id));
                    y = r.Bottom + S(8);
                }
            y += S(2);
            Button(new Rectangle(x, y, w, S(34)), T("ov_back"), false, "picker");
            y += S(44);
            y = Para(g, draw, T("ov_keys_pick"), f12, cDim, x, y, w) - S(20);
            return y + S(26);
        }

        if (stops == null || stops.Count == 0)
        {
            if (note == null)
            {
                Txt(T("ov_none"), f16b, cText, x, y, w); y += S(26);
                y = Para(g, draw, T("ov_none_sub"), f12, cMuted, x, y, w) + S(12);
            }
            Button(new Rectangle(x, y, w, S(34)), T("ov_pins"), true, "picker");
            y += S(44);
            Txt(T("ov_keys_idle"), f12, cDim, x, y, w);
            return y + S(26);
        }

        // Höchstens vier Stopps ab dem letzten erledigten, auf Klick alle
        int from = showAll ? 0 : Math.Max(0, step - 1), to = showAll ? stops.Count : Math.Min(stops.Count, from + 4);
        if (from > 0) { Txt(T("ov_more_done", from) + " · " + T("ov_showall"), f12, cDim, x, y, w); hits.Add((new Rectangle(x, y, w, S(18)), "showall", null)); y += S(20); }
        for (int i = from; i < to; i++)
        {
            var s = stops[i];
            bool done = i < step, here = i == step, next = i == step + 1;
            string name = s?["name"]?.GetValue<string>() ?? "?";
            string tag = done ? T("ov_done") : here ? (step == 0 ? T("ov_start") : T("ov_here")) : next ? T("ov_next") : "";
            bool open = openStops.Contains(i);
            var moves = Moves(s);
            if (done && !open) moves.Clear();
            string place = s?["place"]?.GetValue<string>() ?? "";
            int ch = S(38) + moves.Count * S(22) + (moves.Count > 0 ? S(4) : 0);
            if (open) ch += (place.Length > 0 ? S(18) : 0) + moves.Count(m => m.price > 0) * S(18);
            if (done && !open) ch = S(36);
            var r = new Rectangle(x, y, w, ch);
            var col = Leg[i % Leg.Length];
            Box(r, cCard, here ? cLine2 : cLine, S(12), done ? Color.FromArgb(90, col) : col);
            int ix = x + S(14), iw = w - S(26);
            Txt(name, done ? f14 : f16b, done ? cDim : cText, ix, y + S(done ? 9 : 10), iw - TW(tag, f12) - S(8));
            Txt(tag, f12, here ? cAccent : cMuted, ix, y + S(done ? 10 : 13), iw, TextFormatFlags.Right);
            int my = y + S(36);
            if (open && place.Length > 0) { Txt(place, f12, cMuted, ix, my - S(2), iw); my += S(18); }
            foreach (var (sell, item, qty, price) in moves)
            {
                Txt(sell ? T("ov_sell") : T("ov_buy"), f14, sell ? cGood : cAccent, ix, my, S(70));
                Txt(Num(qty) + " SCU", f14b, cText, ix, my, iw, TextFormatFlags.Right);
                Txt(item, f14, cText, ix + S(70), my, iw - S(70) - TW(Num(qty) + " SCU", f14b) - S(8));
                my += S(22);
                // aufgeklappt: Preis pro SCU und was es zusammen kostet oder bringt
                if (open && price > 0) { Txt(T("ov_each", Num(price), Big(price * qty)), f12, cMuted, ix + S(70), my - S(3), iw - S(70), TextFormatFlags.Right); my += S(18); }
            }
            hits.Add((r, "stopopen", i.ToString()));
            y = r.Bottom + S(8);
        }
        if (to < stops.Count) { Txt(T("ov_more", stops.Count - to) + " · " + T("ov_showall"), f12, cDim, x, y, w); hits.Add((new Rectangle(x, y, w, S(18)), "showall", null)); y += S(20); }
        else if (showAll) { Txt(T("ov_showless"), f12, cDim, x, y, w); hits.Add((new Rectangle(x, y, w, S(18)), "showall", null)); y += S(20); }

        // Knöpfe
        y += S(2);
        int b1 = (int)((w - S(16)) * 0.27), b2 = (int)((w - S(16)) * 0.33), b3 = w - S(16) - b1 - b2;
        Button(new Rectangle(x, y, b1, S(36)), T("ov_prev"), false, "prev", null, f12b);
        Button(new Rectangle(x + b1 + S(8), y, b2, S(36)), T("ov_replan"), false, "replan", null, f12b);
        bool last = step >= stops.Count - 1;
        Button(new Rectangle(x + b1 + b2 + S(16), y, b3, S(36)), last ? T("ov_finish") : T("ov_nextbtn"), true, last ? "stop" : "next");
        y += S(46);
        double profit = act?["profit"]?.GetValue<double>() ?? 0;
        int scu = Scu(act);
        // unten links Gewinn und größte Ladung, rechts zu den angepinnten Routen, darunter der Hinweis
        string pick = T("ov_routes") + " ›"; int pw = TW(pick, f12b);
        if (profit != 0 || scu > 0) Txt((profit != 0 ? T("ov_profit", Num(profit)) : "") + (scu > 0 ? (profit != 0 ? " · " : "") + Num(scu) + " SCU" : ""), f12, cMuted, x, y, w - pw - S(10));
        Txt(pick, f12b, cAccent, x, y, w, TextFormatFlags.Right);
        hits.Add((new Rectangle(x + w - pw - S(6), y - S(4), pw + S(6), S(22)), "picker", null));
        y += S(20);
        Txt(T("ov_keys"), f12, cDim, x, y, w);
        return y + S(24);
    }

    // Kauf und Verkauf eines Stopps, erst verkaufen, dann kaufen, so wie man es am Terminal macht
    static List<(bool sell, string item, int qty, double price)> Moves(JsonNode s)
    {
        var l = new List<(bool, string, int, double)>();
        foreach (var m in s?["sell"] as JsonArray ?? new JsonArray()) l.Add((true, m?["item"]?.GetValue<string>() ?? "?", m?["qty"]?.GetValue<int>() ?? 0, Dbl(m?["price"])));
        foreach (var m in s?["buy"] as JsonArray ?? new JsonArray()) l.Add((false, m?["item"]?.GetValue<string>() ?? "?", m?["qty"]?.GetValue<int>() ?? 0, Dbl(m?["price"])));
        return l;
    }
    static double Dbl(JsonNode n) { try { return n == null ? 0 : n.GetValue<double>(); } catch { return 0; } }
    // Größte Ladung unterwegs, so viel muss ins Schiff passen
    static int Scu(JsonNode r)
    {
        int hold = 0, peak = 0;
        foreach (var s in r?["stops"] as JsonArray ?? new JsonArray())
        {
            foreach (var (sell, _, qty, _) in Moves(s)) if (sell) hold -= qty;
            foreach (var (sell, _, qty, _) in Moves(s)) if (!sell) hold += qty;
            peak = Math.Max(peak, hold);
        }
        return peak;
    }

    // Angepinnte Route als Karte. Zu: Titel und kurz die Eckdaten. Auf: jeder Stopp mit Kauf und Verkauf, Preisen und ein Knopf zum Starten
    int PinCard(Graphics g, bool draw, JsonNode p, int x, int y, int w, bool open, Font f12, Font f12b, Font f14b)
    {
        string pt = PTitle(p);
        var stops = p?["stops"] as JsonArray ?? new JsonArray();
        double pr = Dbl(p?["profit"]);
        int scu = Scu(p);
        string sub = (p?["ship"]?.GetValue<string>() ?? "") + " · " + T("ov_nstops", stops.Count) + (scu > 0 ? " · " + Num(scu) + " SCU" : "") + (pr > 0 ? " · " + Big(pr) + " aUEC" : "");
        int ix = x + S(10), iw = w - S(20);
        void Txt(string s, Font f, Color c, int tx, int ty, int tw, TextFormatFlags fl = TextFormatFlags.Left)
        { if (draw) TextRenderer.DrawText(g, s, f, new Rectangle(tx, ty, tw, S(40)), c, fl | TextFormatFlags.NoPadding | TextFormatFlags.EndEllipsis | TextFormatFlags.SingleLine); }
        int yy = Para(g, draw, pt, f14b, cText, ix, y + S(8), iw);
        Txt(sub, f12, cMuted, ix, yy + S(2), iw);
        yy += S(26);
        if (!open) { if (draw) Txt(T("ov_tap"), f12, cDim, ix, yy - S(2), iw); return yy + S(14); }
        for (int j = 0; j < stops.Count; j++)
        {
            var s = stops[j];
            var col = Leg[j % Leg.Length];
            if (draw) { using var b = new SolidBrush(col); g.FillEllipse(b, ix, yy + S(4), S(8), S(8)); }
            Txt(s?["name"]?.GetValue<string>() ?? "?", f12b, cText, ix + S(14), yy, iw - S(14));
            yy += S(18);
            foreach (var (sell, item, qty, price) in Moves(s))
            {
                Txt(sell ? T("ov_sell") : T("ov_buy"), f12, sell ? cGood : cAccent, ix + S(14), yy, S(60));
                string right = Num(qty) + " SCU" + (price > 0 ? " · " + T("ov_each_short", Num(price)) : "");
                Txt(right, f12, cText, ix, yy, iw, TextFormatFlags.Right);
                int rw = TextRenderer.MeasureText(g, right, f12, Size.Empty, TextFormatFlags.NoPadding).Width;
                Txt(item, f12, cText, ix + S(74), yy, iw - S(74) - rw - S(6));
                yy += S(17);
            }
            yy += S(5);
        }
        // Knopf zum Starten
        var br = new Rectangle(ix, yy + S(2), iw, S(34));
        if (draw)
        {
            using var path = Ui.Round(new RectangleF(br.X + .5f, br.Y + .5f, br.Width - 1, br.Height - 1), S(8));
            using (var b = new SolidBrush(cAccent)) g.FillPath(b, path);
            TextRenderer.DrawText(g, T("ov_pick_start"), f12b, br, cDark, TextFormatFlags.HorizontalCenter | TextFormatFlags.VerticalCenter | TextFormatFlags.NoPadding);
        }
        return br.Bottom + S(10);
    }

    static int TextH(Graphics g, string s, Font f, int w) =>
        TextRenderer.MeasureText(g, s, f, new Size(w, int.MaxValue), TextFormatFlags.WordBreak | TextFormatFlags.NoPadding).Height;
    static int Para(Graphics g, bool draw, string s, Font f, Color c, int x, int y, int w)
    {
        int h = TextH(g, s, f, w);
        if (draw) TextRenderer.DrawText(g, s, f, new Rectangle(x, y, w, h + 2), c, TextFormatFlags.WordBreak | TextFormatFlags.NoPadding);
        return y + h;
    }

    // Klick auf Knöpfe, Ziehen am Kopf verschiebt das Fenster
    [DllImport("user32.dll")] static extern bool ReleaseCapture();
    [DllImport("user32.dll")] static extern IntPtr SendMessage(IntPtr h, int msg, IntPtr w, IntPtr l);
    protected override void OnMouseDown(MouseEventArgs e)
    {
        base.OnMouseDown(e);
        if (e.Button != MouseButtons.Left) return;
        foreach (var (r, cmd, id) in hits)
            if (r.Contains(e.Location))
            {
                if (cmd == "picker") TogglePicker();
                else if (cmd == "pinopen") { openPin = openPin == id ? null : id; var pins = data?["pins"] as JsonArray; if (pins != null) { int k2 = pins.ToList().FindIndex(p => p?["id"]?.GetValue<string>() == id); if (k2 >= 0) sel = k2; } Relayout(); }
                else if (cmd == "stopopen") { int si = int.Parse(id); if (!openStops.Remove(si)) openStops.Add(si); Relayout(); }
                else if (cmd == "showall") { showAll = !showAll; Relayout(); }
                else Command?.Invoke(cmd, id);
                return;
            }
        if (e.Y < S(40)) { ReleaseCapture(); SendMessage(Handle, 0xA1, (IntPtr)2, IntPtr.Zero); Moved2?.Invoke(); }
    }
    protected override void OnMouseMove(MouseEventArgs e)
    {
        base.OnMouseMove(e);
        Cursor = hits.Any(h => h.r.Contains(e.Location)) ? Cursors.Hand : e.Y < S(40) ? Cursors.SizeAll : Cursors.Default;
    }
    static string PTitle(System.Text.Json.Nodes.JsonNode? p) => (p?["title"]?.GetValue<string>() ?? "?").Replace("➜", "›").Replace("→", "›");
}
