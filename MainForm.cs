using System.Drawing;
using System.Drawing.Drawing2D;
using System.Drawing.Imaging;
using System.Net.Http;
using System.Runtime.InteropServices;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Text.RegularExpressions;
using static CargoDeckScanner.Lang;

namespace CargoDeckScanner;

class MainForm : Form
{
    // Farben wie auf der Website
    static readonly Color cBg = Color.FromArgb(0x0c, 0x11, 0x19), cPanel = Color.FromArgb(0x14, 0x1c, 0x28), cPanel2 = Color.FromArgb(0x1a, 0x24, 0x33),
        cLine = Color.FromArgb(0x24, 0x31, 0x42), cLine2 = Color.FromArgb(0x30, 0x40, 0x56), cText = Color.FromArgb(0xee, 0xf3, 0xf9), cMuted = Color.FromArgb(0x8f, 0x9d, 0xb1),
        cDim = Color.FromArgb(0x66, 0x74, 0x8a), cAccent = Color.FromArgb(0x35, 0xd6, 0xcc), cGood = Color.FromArgb(0x4a, 0xde, 0x80), cBad = Color.FromArgb(0xf8, 0x71, 0x71),
        cWarn = Color.FromArgb(0xfb, 0xbf, 0x24), cDark = Color.FromArgb(0x0b, 0x0f, 0x14);

    static readonly Regex TerminalWords = new("COMMODIT|SHOP INVENTOR|LOCAL MARKET|IN DEMAND|YOUR INVENTOR|SHOP QUANTIT", RegexOptions.IgnoreCase);
    static readonly Regex CodeRe = new("^[A-Z2-9]{12}$");
    static readonly HttpClient Http = new() { Timeout = TimeSpan.FromSeconds(30) };

    // Größe in logischen Pixeln: großes Fenster hochkant, kleines Fenster im Vordergrund wie beim Windows Rechner
    const int FW = 400, FH = 790, MW = 300, MH = 172;

    readonly Config cfg = Config.Load();
    readonly bool startInTray;
    bool running, busy, wasScan, wasAuto;
    string lastPrint = "";
    DateTime nextAuto = DateTime.MinValue, lastPing = DateTime.MinValue;
    // Scans, die gewartet haben, weil die Website nicht offen war. Werden gesendet, sobald sie offen ist.
    readonly List<JsonObject> queue = new();
    bool flushing, popped;
    DateTime lastWebCheck = DateTime.MinValue;
    readonly List<string> logLines = new();
    string lastTitle, lastSub, stateTitle, stateSub;
    Color stateCol = cDim;
    int page;

    // Bedienelemente, werden beim Sprachwechsel neu gebaut
    Panel full, mini, pgScan, pgSet, pgHelp;
    Seg nav, langSeg;
    RButton bPin, bUnpin, bStart, bNow, bSave, bMiniScan, bMiniAuto;
    TextBox tUrl, tCode;
    KeyBox kScan, kAuto;
    NumericUpDown nInt;
    Toggle cAutoMode, cSound, cNotify, cAutostart, cTop;
    Label lState, lStateSub, lLast, lLastSub, lEngine, lMiniState, lMiniSub, lMiniLast, lQueue;
    RButton bQueueOpen;
    Panel dot, miniDot;
    ListBox log;
    NotifyIcon tray;
    ToolStripMenuItem miAuto;
    ToolTip tips;
    System.Windows.Forms.Timer timer;
    bool loading;
    // Overlay über dem Spiel (Beta). Erscheint nur, wenn der Server es für dieses Konto erlaubt.
    OverlayForm ovl;
    bool ovlAllowed, ovlBusy;
    DateTime nextOvl = DateTime.MinValue;
    JsonNode ovlData;
    readonly Dictionary<int, bool> keyWas = new();
    CardPanel pOvl, pGlog;
    Toggle cOvl, cGlog;
    Label lGlog;
    GameLogWatcher glog;
    DateTime nextGlog = DateTime.MinValue;
    bool glogBusy;
    string ovlNote; long ovlNoteRev = -1; DateTime ovlNoteUntil;

    float k;
    int S(float v) => (int)Math.Round(v * k);

    readonly bool startRun;
    public MainForm(bool tray, bool run = false)
    {
        startInTray = tray; startRun = run;
        Lang.En = cfg.Lang == "en";
        AutoScaleMode = AutoScaleMode.None;
        k = DeviceDpi / 96f;
        Text = "Cargo Deck Price Capture";
        BackColor = cBg; ForeColor = cText;
        Font = new Font("Segoe UI", 9.75f);
        FormBorderStyle = FormBorderStyle.FixedSingle; MaximizeBox = false;
        StartPosition = FormStartPosition.CenterScreen;
        using (var s = typeof(MainForm).Assembly.GetManifestResourceStream("CargoDeckScanner.app.ico"))
            if (s != null) Icon = new Icon(s);
        stateTitle = T("stopped"); stateSub = T("stopped_sub");
        lastTitle = T("last_none"); lastSub = "";
        Build();
        LoadForm();
        SetupTray();
        ApplyPin(false);
        ovl = new OverlayForm();
        ovl.Command += (c, id) => _ = OvlCmd(c, id);
        ovl.Moved2 += () => { cfg.OvlX = ovl.Left; cfg.OvlY = ovl.Top; cfg.Save(); };
        timer = new System.Windows.Forms.Timer { Interval = 50 };
        timer.Tick += Tick;
        timer.Start();
        // Texterkennung schon mal im Hintergrund laden, der erste Scan ist dann schneller
        Task.Run(() => { PaddleOcr.Get(); try { BeginInvoke(new Action(ShowEngine)); } catch { } });
    }

    [DllImport("dwmapi.dll")] static extern int DwmSetWindowAttribute(IntPtr h, int attr, ref int val, int size);
    protected override void OnHandleCreated(EventArgs e)
    {
        base.OnHandleCreated(e);
        int on = 1; try { DwmSetWindowAttribute(Handle, 20, ref on, 4); } catch { }   // dunkle Titelleiste
        try { int c = 0x00191110; DwmSetWindowAttribute(Handle, 35, ref c, 4); } catch { }   // Titelleiste in der Farbe der Seite (Windows 11)
        try { int r = 2; DwmSetWindowAttribute(Handle, 33, ref r, 4); } catch { }   // runde Ecken (Windows 11)
    }

    // Dunkle Scrollleisten wie im Windows Explorer im Dunkelmodus
    [DllImport("uxtheme.dll", CharSet = CharSet.Unicode)] static extern int SetWindowTheme(IntPtr h, string app, string id);
    static void Dark(Control c) { c.HandleCreated += (s, e) => { try { SetWindowTheme(c.Handle, "DarkMode_Explorer", null); } catch { } }; }

    // ---------------- Bausteine ----------------
    static Color FillOf(Control p) => p is CardPanel cp ? cp.Fill : p.BackColor;
    Label L(Control parent, string text, int x, int y, Color? col = null, float size = 9.75f, bool bold = false, int w = 0, int h = 0)
    {
        var l = new Label { Text = text, Left = S(x), Top = S(y), AutoSize = w == 0, ForeColor = col ?? cText, BackColor = FillOf(parent), Font = new Font("Segoe UI", size, bold ? FontStyle.Bold : FontStyle.Regular), UseMnemonic = false };
        if (w > 0) { l.Width = S(w); l.Height = S(h > 0 ? h : 22); }
        parent.Controls.Add(l); return l;
    }
    // Text mit Zeilenumbruch, Höhe passt sich an. Gibt die Unterkante zurück.
    int Wrap(Control parent, string text, int x, int y, int w, Color col, float size = 9.5f, bool bold = false)
    {
        var f = new Font("Segoe UI", size, bold ? FontStyle.Bold : FontStyle.Regular);
        var sz = TextRenderer.MeasureText(text, f, new Size(S(w), int.MaxValue), TextFormatFlags.WordBreak);
        var l = new Label { Text = text, Left = S(x), Top = S(y), Width = S(w), Height = sz.Height + S(2), ForeColor = col, BackColor = FillOf(parent), Font = f, UseMnemonic = false };
        parent.Controls.Add(l);
        return y + (int)Math.Ceiling(l.Height / k);
    }
    TextBox Tb(Control parent, int x, int y, int w, bool mono = false)
    {
        var t = new TextBox { Left = S(x), Top = S(y), Width = S(w), BackColor = cPanel2, ForeColor = cText, BorderStyle = BorderStyle.FixedSingle, Font = mono ? new Font("Consolas", 12.5f, FontStyle.Bold) : new Font("Segoe UI", 11f) };
        parent.Controls.Add(t); return t;
    }
    RButton Btn(Control parent, string text, int x, int y, int w, int h, bool primary, string icon = null, float size = 10.5f)
    {
        var b = new RButton { Text = text, Left = S(x), Top = S(y), Width = S(w), Height = S(h), Primary = primary, Icon = icon, ForeColor = cText, Font = new Font("Segoe UI", size, FontStyle.Bold), Accent = cAccent, Fill = cPanel2, Line = cLine2 };
        parent.Controls.Add(b); return b;
    }
    Toggle Tg(Control parent, string text, int x, int y)
    {
        var t = new Toggle { Text = text, Left = S(x), Top = S(y), BackColor = FillOf(parent), ForeColor = cText, OnColor = cAccent, OffColor = cLine2, Font = new Font("Segoe UI", 10f) };
        t.Size = t.Measure();
        parent.Controls.Add(t); return t;
    }
    KeyBox KB(Control parent, int x, int y)
    {
        var kb = new KeyBox { Left = S(x), Top = S(y), Width = S(96), Height = S(30), FlatStyle = FlatStyle.Flat, Font = new Font("Segoe UI", 10.5f, FontStyle.Bold), Cursor = Cursors.Hand, UseVisualStyleBackColor = false, BackColor = cPanel2, ForeColor = cAccent, TabStop = true };
        kb.FlatAppearance.BorderColor = cLine2; kb.FlatAppearance.MouseOverBackColor = Color.FromArgb(0x21, 0x2d, 0x3e);
        kb.Changed += (s, e) => { bSave.Primary = true; bSave.Invalidate(); Log(T("new_key", KeyNames.Name(kb.Vk))); };
        parent.Controls.Add(kb); return kb;
    }
    CardPanel Card(Control parent, int y, int h, string title, int x = 0, int w = 368)
    {
        var p = new CardPanel { Left = S(x), Top = S(y), Width = S(w), Height = S(h), Fill = cPanel, LineColor = cLine, GlowColor = cAccent, BackColor = cPanel };
        parent.Controls.Add(p);
        if (title != null) L(p, title.ToUpperInvariant(), 16, 12, cMuted, 8.25f, true);
        return p;
    }
    Panel Dot(Control parent, int x, int y, int size)
    {
        var d = new Panel { Left = S(x), Top = S(y), Width = S(size), Height = S(size), BackColor = FillOf(parent) };
        d.Paint += (s, e) =>
        {
            e.Graphics.SmoothingMode = SmoothingMode.AntiAlias;
            var col = stateCol;
            using (var glow = new SolidBrush(Color.FromArgb(50, col))) e.Graphics.FillEllipse(glow, 0, 0, d.Width - 1, d.Height - 1);
            float m = d.Width * 0.22f;
            using var b = new SolidBrush(col); e.Graphics.FillEllipse(b, m, m, d.Width - 1 - 2 * m, d.Height - 1 - 2 * m);
        };
        parent.Controls.Add(d); return d;
    }

    // ---------------- Aufbau ----------------
    void Build()
    {
        SuspendLayout();
        Controls.Clear();
        tips?.Dispose(); tips = new ToolTip();
        full = new Panel { Left = 0, Top = 0, Width = S(FW), Height = S(FH), BackColor = cBg };
        mini = new Panel { Left = 0, Top = 0, Width = S(MW), Height = S(MH), BackColor = cBg, Visible = false };
        Controls.Add(full); Controls.Add(mini);

        // Kopf
        var logo = new PictureBox { Left = S(16), Top = S(16), Width = S(34), Height = S(34), SizeMode = PictureBoxSizeMode.Zoom, BackColor = cBg };
        if (Icon != null) logo.Image = new Icon(Icon, 64, 64).ToBitmap();
        full.Controls.Add(logo);
        var t1 = L(full, "CARGO", 58, 13, cText, 14.5f, true);
        L(full, "DECK", 58 + (int)(t1.PreferredWidth / k), 13, cAccent, 14.5f, true);
        L(full, T("subtitle"), 60, 38, cMuted, 8.75f);
        langSeg = new Seg { Left = S(252), Top = S(18), Width = S(84), Height = S(30), Items = new[] { "DE", "EN" }, Font = new Font("Segoe UI", 9f), ForeColor = cText, Fill = cPanel, Line = cLine, Accent = cAccent, Muted = cMuted };
        langSeg.Selected = Lang.En ? 1 : 0;
        langSeg.Changed += (s, e) => SwitchLang(langSeg.Selected == 1);
        full.Controls.Add(langSeg);
        bPin = Btn(full, "", 344, 18, 40, 30, false, "", 11f);
        tips.SetToolTip(bPin, T("pin"));
        bPin.Click += (s, e) => ApplyPin(true, true);

        // Reiter
        nav = new Seg { Left = S(16), Top = S(64), Width = S(368), Height = S(40), Items = new[] { T("nav_scan"), T("nav_set"), T("nav_help") }, Font = new Font("Segoe UI", 10f), ForeColor = cText, Fill = cPanel, Line = cLine, Accent = cAccent, Muted = cMuted };
        full.Controls.Add(nav);
        pgScan = new Panel { Left = S(16), Top = S(116), Width = S(368), Height = S(FH - 116 - 12), BackColor = cBg };
        pgSet = new Panel { Left = S(16), Top = S(116), Width = S(368), Height = S(FH - 116 - 12), BackColor = cBg, AutoScroll = true, Visible = false };
        pgHelp = new Panel { Left = S(8), Top = S(116), Width = S(384), Height = S(FH - 116 - 12), BackColor = cBg, AutoScroll = true, Visible = false };
        full.Controls.Add(pgScan); full.Controls.Add(pgSet); full.Controls.Add(pgHelp);
        Dark(pgSet); Dark(pgHelp);
        nav.Changed += (s, e) => ShowPage(nav.Selected);

        BuildScan(); BuildSettings(); BuildHelp(); BuildMini();
        ShowPage(page);
        ShowQueue();
        ResumeLayout();
    }

    void BuildScan()
    {
        var p = pgScan;
        var st = Card(p, 0, 94, null);
        dot = Dot(st, 14, 16, 22);
        lState = L(st, stateTitle, 44, 13, cText, 13f, true, 310, 28);
        lStateSub = L(st, stateSub, 45, 44, cMuted, 9.25f, false, 310, 40);

        bStart = Btn(p, running ? T("stop") : T("start"), 0, 106, 368, 54, !running, running ? "  " : "  ", 12f);
        bNow = Btn(p, T("scan_now"), 0, 170, 368, 44, false, "  ", 10.5f);

        var am = Card(p, 226, 62, null);
        cAutoMode = Tg(am, T("auto"), 16, 17);
        L(am, T("every"), 188, 21, cMuted, 9.5f);
        nInt = new NumericUpDown { Left = S(222), Top = S(18), Width = S(52), Minimum = 3, Maximum = 60, Value = 5, BackColor = cPanel2, ForeColor = cText, BorderStyle = BorderStyle.FixedSingle, Font = new Font("Segoe UI", 10f) };
        am.Controls.Add(nInt);
        L(am, T("seconds"), 280, 21, cMuted, 9.5f);

        var ls = Card(p, 300, 96, T("last_title"));
        lLast = L(ls, lastTitle, 16, 34, cText, 12f, true, 336, 26);
        lLastSub = L(ls, lastSub, 16, 62, cMuted, 9f, false, 336, 30);
        bQueueOpen = Btn(ls, T("q_open"), 222, 6, 132, 28, true, null, 9f);
        bQueueOpen.Click += (s, e) => OpenSite();

        var lg = Card(p, 408, FH - 116 - 12 - 408, T("log_title"));
        log = new ListBox { Left = S(12), Top = S(34), Width = S(344), Height = lg.Height - S(44), BackColor = cPanel, ForeColor = cMuted, BorderStyle = BorderStyle.None, IntegralHeight = false, Font = new Font("Segoe UI", 9f), SelectionMode = SelectionMode.None };
        foreach (var l in logLines) log.Items.Add(l);
        Dark(log);
        lg.Controls.Add(log);

        bStart.Click += (s, e) => { if (running) StopScanner(); else StartScanner(); };
        bNow.Click += async (s, e) =>
        {
            if (!running) StartScanner();
            if (!running) return;
            if (!cfg.Pinned) WindowState = FormWindowState.Minimized;
            await Task.Delay(700);
            await Scan(false);
        };
        cAutoMode.CheckedChanged += (s, e) => { if (loading) return; ReadForm(); if (running) ShowRunning(); SyncAuto(); };
        nInt.ValueChanged += (s, e) => { if (!loading) ReadForm(); if (running) ShowRunning(); };
    }

    void BuildSettings()
    {
        var p = pgSet;
        var pv = Card(p, 0, 176, T("conn_title"));
        L(pv, T("url"), 16, 36, cMuted, 9f);
        tUrl = Tb(pv, 16, 56, 336);
        L(pv, T("code"), 16, 96, cMuted, 9f);
        tCode = Tb(pv, 16, 116, 164, true); tCode.CharacterCasing = CharacterCasing.Upper; tCode.MaxLength = 12;
        Wrap(pv, T("code_hint"), 190, 114, 164, cMuted, 8.5f);
        lQueue = L(pv, "", 16, 150, cWarn, 9f, true, 336, 20);

        var pk = Card(p, 188, 186, T("keys_title"));
        L(pk, T("keys_hint"), 16, 30, cDim, 8.5f);
        L(pk, T("key_scan"), 16, 64, cText, 10f);
        L(pk, T("ctrl"), 168, 64, cMuted, 9.5f);
        kScan = KB(pk, 256, 58);
        L(pk, T("key_auto"), 16, 102, cText, 10f, false, 150, 22);
        L(pk, T("ctrl"), 168, 102, cMuted, 9.5f);
        kAuto = KB(pk, 256, 96);
        bSave = Btn(pk, T("save_restart"), 16, 138, 336, 36, false, "  ", 10f);
        bSave.Click += (s, e) => SaveAndRestart();

        var po = Card(p, 386, 176, T("opt_title"));
        cSound = Tg(po, T("opt_sound"), 16, 38);
        cNotify = Tg(po, T("opt_notify"), 16, 70);
        cAutostart = Tg(po, T("opt_autostart"), 16, 102);
        cTop = Tg(po, T("opt_top"), 16, 134);

        var pe = Card(p, 574, 72, T("engine_title"));
        lEngine = L(pe, T("engine_load"), 16, 34, cMuted, 9f, false, 336, 34);
        ShowEngine();

        pOvl = Card(p, 658, 10, T("ov_title"));
        cOvl = Tg(pOvl, T("ov_show"), 16, 38);
        int oy = Wrap(pOvl, T("ov_hint"), 16, 72, 336, cMuted, 8.5f);
        pOvl.Height = S(oy + 14);
        pOvl.Visible = ovlAllowed;
        int gy0 = 658 + oy + 26;
        pGlog = Card(p, gy0, 10, T("gl_title"));
        cGlog = Tg(pGlog, T("gl_on"), 16, 38);
        lGlog = L(pGlog, "", 16, 70, cMuted, 8.5f, false, 220, 20);
        var bPick = Btn(pGlog, T("gl_pick"), 244, 64, 108, 28, false, null, 9f);
        int gy = Wrap(pGlog, T("gl_hint"), 16, 100, 336, cMuted, 8.5f);
        pGlog.Height = S(gy + 14);
        pGlog.Visible = ovlAllowed;
        L(p, " ", 0, gy0 + gy + 20, cBg, 6f);   // Platz unten beim Scrollen
        ShowGlog();
        cGlog.CheckedChanged += (s, e) => { if (loading) return; cfg.GameLog = cGlog.Checked; cfg.Save(); glog = null; ShowGlog(); };
        bPick.Click += (s, e) =>
        {
            using var d = new OpenFileDialog { Filter = "Game.log|Game.log|Log|*.log", FileName = "Game.log" };
            try { var f = GameLogWatcher.Find(cfg.GameLogPath); if (f != null) d.InitialDirectory = System.IO.Path.GetDirectoryName(f); } catch { }
            if (d.ShowDialog(this) == DialogResult.OK) { cfg.GameLogPath = d.FileName; cfg.Save(); glog = null; ShowGlog(); }
        };
        cOvl.CheckedChanged += (s, e) => { if (loading) return; cfg.Overlay = cOvl.Checked; cfg.Save(); ApplyOvl(); };

        cSound.CheckedChanged += (s, e) => { if (loading) return; ReadForm(); if (cfg.Sounds) Sound.Play(Sound.On); };
        cNotify.CheckedChanged += (s, e) => { if (!loading) ReadForm(); };
        cAutostart.CheckedChanged += (s, e) => { if (!loading) ReadForm(); };
        cTop.CheckedChanged += (s, e) => { if (loading) return; ReadForm(); if (!cfg.Pinned) TopMost = cfg.TopMost; };
        tUrl.Leave += (s, e) => { if (!loading) ReadForm(); };
        tCode.TextChanged += (s, e) =>
        {
            var clean = Regex.Replace(tCode.Text.ToUpperInvariant(), "[^A-Z2-9]", "");
            if (clean != tCode.Text) { tCode.Text = clean; tCode.SelectionStart = clean.Length; }
        };
        tCode.Leave += (s, e) => { if (!loading) ReadForm(); };
    }

    void BuildHelp()
    {
        var p = pgHelp;
        int y = 0, x = 8, w = 352;
        L(p, T("help_title"), x, y, cText, 13f, true); y += 34;
        var steps = new[] { ("h1_t", T("h1")), ("h2_t", T("h2")), ("h3_t", T("h3")), ("h4_t", T("h4", KeyNames.Name(cfg.ScanVk))), ("h5_t", T("h5")) };
        for (int i = 0; i < steps.Length; i++)
        {
            var c = Card(p, y, 10, null, x, w);
            var num = new Label { Text = (i + 1).ToString(), Left = S(14), Top = S(14), Width = S(28), Height = S(28), TextAlign = ContentAlignment.MiddleCenter, Font = new Font("Segoe UI", 11f, FontStyle.Bold), ForeColor = cDark, BackColor = cPanel };
            num.Paint += (s, e) =>
            {
                e.Graphics.SmoothingMode = SmoothingMode.AntiAlias; e.Graphics.Clear(cPanel);
                using var b = new SolidBrush(cAccent); e.Graphics.FillEllipse(b, 0, 0, num.Width - 1, num.Height - 1);
                TextRenderer.DrawText(e.Graphics, num.Text, num.Font, new Rectangle(0, 0, num.Width, num.Height), cDark, TextFormatFlags.HorizontalCenter | TextFormatFlags.VerticalCenter);
            };
            c.Controls.Add(num);
            int yy = Wrap(c, T(steps[i].Item1), 54, 14, w - 70, cText, 10.5f, true);
            yy = Wrap(c, steps[i].Item2, 54, yy + 2, w - 70, cMuted, 9.25f);
            c.Height = S(Math.Max(yy + 14, 58));
            y += (int)Math.Ceiling(c.Height / k) + 10;
        }
        y += 6;
        var tc = Card(p, y, 10, T("tips_title"), x, w);
        int ty = 36;
        foreach (var tk in new[] { "tip1", "tip2", "tip3", "tip4" })
        {
            L(tc, "•", 16, ty - 1, cAccent, 11f, true);
            ty = Wrap(tc, T(tk), 32, ty, w - 48, cMuted, 9.25f) + 8;
        }
        tc.Height = S(ty + 6);
        y += (int)Math.Ceiling(tc.Height / k) + 12;
        var bo = Btn(p, T("open_site"), x, y, w, 40, true, "  ", 10.5f);
        bo.Click += (s, e) => OpenSite();
        L(p, " ", x, y + 52, cBg, 6f);   // Platz unten beim Scrollen
    }

    // Kleines Fenster, bleibt im Vordergrund wie der Windows Rechner
    void BuildMini()
    {
        var p = mini;
        miniDot = Dot(p, 12, 13, 20);
        lMiniState = L(p, stateTitle, 38, 11, cText, 11.5f, true, 200, 24);
        bUnpin = Btn(p, "", 250, 8, 40, 30, false, "", 11f);
        tips.SetToolTip(bUnpin, T("unpin"));
        bUnpin.Click += (s, e) => ApplyPin(false, true);
        lMiniSub = L(p, stateSub, 39, 36, cMuted, 8.75f, false, 250, 34);
        bMiniScan = Btn(p, T("scan_short"), 12, 76, 134, 42, true, "  ", 10.5f);
        bMiniAuto = Btn(p, T("auto_short"), 154, 76, 134, 42, false, "  ", 10.5f);
        lMiniLast = L(p, lastTitle, 12, 128, cMuted, 8.75f, false, 276, 36);
        bMiniScan.Click += async (s, e) => { if (!running) StartScanner(); if (running) await Scan(false); };
        bMiniAuto.Click += (s, e) => { if (!running) StartScanner(); if (!running) return; cAutoMode.Checked = !cAutoMode.Checked; };
    }

    public void DebugPage(int i) { if (i == 9) ApplyPin(true, true); else ShowPage(i); }
    void ShowPage(int i)
    {
        page = i;
        if (nav != null && nav.Selected != i) nav.Selected = i;
        pgScan.Visible = i == 0; pgSet.Visible = i == 1; pgHelp.Visible = i == 2;
    }

    void ShowEngine()
    {
        if (lEngine == null || lEngine.IsDisposed) return;
        var p = PaddleOcr.Get();
        lEngine.Text = p != null ? T("engine_paddle") : PaddleOcr.LoadError != null ? T("engine_win", PaddleOcr.LoadError) : T("engine_load");
        lEngine.ForeColor = p != null ? cGood : cMuted;
    }

    void SyncAuto()
    {
        if (miAuto != null) miAuto.Checked = cAutoMode.Checked;
        if (bMiniAuto != null) { bMiniAuto.Primary = cAutoMode.Checked; bMiniAuto.Invalidate(); }
    }

    // Sprache umschalten: alles neu aufbauen, Einstellungen und Verlauf bleiben
    void SwitchLang(bool en)
    {
        if (Lang.En == en) return;
        ReadForm();
        Lang.En = en; cfg.Lang = en ? "en" : "de"; cfg.Save();
        if (running) { var (t, s) = RunningText(); stateTitle = t; stateSub = s; }
        else { stateTitle = T("stopped"); stateSub = T("stopped_sub"); }
        if (lastTitle == (en ? "Noch nichts gescannt" : "Nothing scanned yet")) lastTitle = T("last_none");
        Build(); LoadForm(); SetupTray();
        ApplyPin(false);
    }

    // Kleines Fenster im Vordergrund an oder aus
    void ApplyPin(bool toggle, bool fromUser = false)
    {
        if (toggle || fromUser) { if (fromUser) cfg.Pinned = !cfg.Pinned; }
        if (cfg.Pinned)
        {
            full.Visible = false; mini.Visible = true;
            ClientSize = new Size(S(MW), S(MH));
            TopMost = true;
            var wa = Screen.FromControl(this).WorkingArea;
            if (cfg.PinX >= 0 && cfg.PinY >= 0 && Screen.AllScreens.Any(sc => sc.WorkingArea.Contains(cfg.PinX + 20, cfg.PinY + 20))) Location = new Point(cfg.PinX, cfg.PinY);
            else if (fromUser) Location = new Point(wa.Right - Width - S(16), wa.Bottom - Height - S(16));
        }
        else
        {
            mini.Visible = false; full.Visible = true;
            ClientSize = new Size(S(FW), S(FH));
            TopMost = cfg.TopMost;
            if (fromUser) { var wa = Screen.FromControl(this).WorkingArea; Location = new Point(Math.Max(wa.Left, Math.Min(Left, wa.Right - Width)), Math.Max(wa.Top, Math.Min(Top, wa.Bottom - Height))); }
        }
        if (fromUser) cfg.Save();
    }

    protected override void OnMove(EventArgs e)
    {
        base.OnMove(e);
        if (cfg != null && cfg.Pinned && WindowState == FormWindowState.Normal && Visible) { cfg.PinX = Left; cfg.PinY = Top; }
    }

    void LoadForm()
    {
        loading = true;
        tUrl.Text = cfg.Url; tCode.Text = cfg.Code;
        cAutoMode.Checked = cfg.Mode == "auto";
        nInt.Value = Math.Clamp(cfg.Interval, 3, 60);
        kScan.Vk = cfg.ScanVk; kAuto.Vk = cfg.AutoVk;
        cSound.Checked = cfg.Sounds; cNotify.Checked = cfg.Notify; cAutostart.Checked = cfg.Autostart; cTop.Checked = cfg.TopMost;
        if (cOvl != null) cOvl.Checked = cfg.Overlay;
        if (cGlog != null) cGlog.Checked = cfg.GameLog;
        if (running) foreach (var t in new[] { tUrl, tCode }) { t.ReadOnly = true; t.ForeColor = cMuted; t.BackColor = cPanel; }
        loading = false;
        SyncAuto();
    }

    void ReadForm()
    {
        cfg.Url = tUrl.Text.Trim().TrimEnd('/');
        cfg.Code = tCode.Text.Trim().ToUpperInvariant();
        cfg.Mode = cAutoMode.Checked ? "auto" : "hotkey";
        cfg.Interval = (int)nInt.Value;
        if (kScan.Vk > 0) { cfg.ScanVk = kScan.Vk; cfg.ScanKey = KeyNames.Name(kScan.Vk); }
        if (kAuto.Vk > 0) { cfg.AutoVk = kAuto.Vk; cfg.AutoKey = KeyNames.Name(kAuto.Vk); }
        cfg.Sounds = cSound.Checked; cfg.Notify = cNotify.Checked; cfg.Autostart = cAutostart.Checked; cfg.TopMost = cTop.Checked;
        cfg.Save();
    }

    // ---------------- Tray ----------------
    void SetupTray()
    {
        var menu = new ContextMenuStrip();
        menu.Items.Add(T("tray_open"), null, (s, e) => ShowWindow());
        menu.Items.Add(T("scan_now"), null, async (s, e) => { if (!running) StartScanner(); if (running) await Scan(false); });
        miAuto = new ToolStripMenuItem(T("auto"), null, (s, e) => { cAutoMode.Checked = !cAutoMode.Checked; }) { Checked = cAutoMode.Checked };
        menu.Items.Add(miAuto);
        if (ovlAllowed) menu.Items.Add(new ToolStripMenuItem(T("ov_tray"), null, (s, e) => { cfg.Overlay = !cfg.Overlay; cfg.Save(); ApplyOvl(); }) { Checked = cfg.Overlay });
        menu.Items.Add(new ToolStripSeparator());
        menu.Items.Add(T("tray_quit"), null, (s, e) => Close());
        if (tray == null) { tray = new NotifyIcon { Icon = Icon, Text = "Cargo Deck Price Capture", Visible = true }; tray.DoubleClick += (s, e) => ShowWindow(); }
        var old = tray.ContextMenuStrip; tray.ContextMenuStrip = menu; old?.Dispose();
    }

    void ShowWindow() { Show(); WindowState = FormWindowState.Normal; ShowInTaskbar = true; Activate(); }

    protected override void OnResize(EventArgs e)
    {
        base.OnResize(e);
        if (WindowState == FormWindowState.Minimized && running) { Hide(); ShowInTaskbar = false; }
    }

    protected override void OnShown(EventArgs e)
    {
        base.OnShown(e);
        Log(T("ready"));
        if ((startInTray || startRun || cfg.Autostart) && CodeRe.IsMatch(cfg.Code) && cfg.Url.StartsWith("http"))
        {
            StartScanner();
            if (startInTray && !cfg.Pinned) { WindowState = FormWindowState.Minimized; }
        }
        else if (!CodeRe.IsMatch(cfg.Code)) ShowPage(2);   // noch nicht eingerichtet, dann gleich die Anleitung
    }

    protected override void OnFormClosing(FormClosingEventArgs e)
    {
        ReadForm();
        tray.Visible = false; tray.Dispose();
        base.OnFormClosing(e);
    }

    void SaveAndRestart()
    {
        try
        {
            ReadForm(); cfg.Save();
            Log(T("saved_restart"));
            var args = running ? "--restart --run" : "--restart";
            // Aus dem Store über den App Alias neu starten, sonst direkt die exe
            if (Packaged.IsPackaged) System.Diagnostics.Process.Start(new System.Diagnostics.ProcessStartInfo(Packaged.Alias, args) { UseShellExecute = true });
            else System.Diagnostics.Process.Start(new System.Diagnostics.ProcessStartInfo(Environment.ProcessPath, args) { UseShellExecute = false });
            tray.Visible = false;
            Application.Exit();
        }
        catch (Exception ex) { Log(T("save_fail", ex.Message)); }
    }

    // ---------------- Zustand ----------------
    void SetState(string title, string sub, Color col)
    {
        stateTitle = title; stateSub = sub ?? ""; stateCol = col;
        foreach (var l in new[] { lState, lMiniState }) if (l != null) l.Text = title;
        foreach (var l in new[] { lStateSub, lMiniSub }) if (l != null) l.Text = stateSub;
        dot?.Invalidate(); miniDot?.Invalidate();
    }
    void SetLast(string title, string sub)
    {
        lastTitle = title; lastSub = sub ?? "";
        if (lLast != null) lLast.Text = title;
        if (lLastSub != null) lLastSub.Text = lastSub;
        if (lMiniLast != null) lMiniLast.Text = title;
    }
    void Log(string text)
    {
        var line = DateTime.Now.ToString("HH:mm:ss") + "   " + text;
        logLines.Insert(0, line); while (logLines.Count > 60) logLines.RemoveAt(logLines.Count - 1);
        if (log == null || log.IsDisposed) return;
        log.Items.Insert(0, line);
        while (log.Items.Count > 60) log.Items.RemoveAt(log.Items.Count - 1);
    }
    void Notify(string text)
    {
        if (!cfg.Notify) return;
        try { tray.ShowBalloonTip(2500, "Cargo Deck", text, ToolTipIcon.None); } catch { }
    }
    void Beep(Sound.Kind kind)
    {
        if (cfg.Sounds) Sound.Play(kind);
    }
    (string, string) RunningText() => cfg.Mode == "auto" ? (T("run_auto"), T("run_auto_sub", cfg.Interval)) : (T("run_hot"), T("run_hot_sub", cfg.ScanKey));
    void ShowRunning() { if (queue.Count > 0) { ShowQueue(); return; } var (t, s) = RunningText(); SetState(t, s, cGood); }

    void StartScanner()
    {
        ReadForm();
        if (!Regex.IsMatch(cfg.Url, "^https?://[^/]+")) { ShowPage(1); MessageBox.Show(this, T("bad_url"), "Cargo Deck Price Capture"); return; }
        if (!CodeRe.IsMatch(cfg.Code)) { ShowPage(1); MessageBox.Show(this, T("bad_code"), "Cargo Deck Price Capture"); tCode.Focus(); return; }
        running = true; lastPrint = ""; nextAuto = DateTime.Now; lastPing = DateTime.MinValue;
        bStart.Text = T("stop"); bStart.Icon = "  "; bStart.Primary = false; bStart.Invalidate();
        foreach (var t in new[] { tUrl, tCode }) { t.ReadOnly = true; t.ForeColor = cMuted; t.BackColor = cPanel; }
        ShowRunning(); Log(T("started", cfg.ScanKey)); Beep(Sound.On);
    }

    void StopScanner()
    {
        running = false;
        bStart.Text = T("start"); bStart.Icon = "  "; bStart.Primary = true; bStart.Invalidate();
        foreach (var t in new[] { tUrl, tCode }) { t.ReadOnly = false; t.ForeColor = cText; t.BackColor = cPanel2; }
        SetState(T("stopped"), T("stopped_sub"), cDim); Log(T("stopped_log"));
    }

    // ---------------- Tasten und Takt ----------------
    [DllImport("user32.dll")] static extern short GetAsyncKeyState(int vKey);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)] static extern short VkKeyScan(char ch);
    static bool Down(int vk) => vk > 0 && (GetAsyncKeyState(vk) & 0x8000) != 0;


    async void Tick(object sender, EventArgs e)
    {
        try { OverlayTick(); } catch (Exception ex) { Log(T("err", ex.Message)); }
        if (!running) return;
        try
        {
            bool ctrl = Down(0xA2);
            bool scan = ctrl && Down(cfg.ScanVk), auto = ctrl && Down(cfg.AutoVk);
            bool scanEdge = scan && !wasScan, autoEdge = auto && !wasAuto;
            wasScan = scan; wasAuto = auto;
            if (autoEdge)
            {
                if (cAutoMode.Checked) { cAutoMode.Checked = false; Log(T("auto_off")); Beep(Sound.Off); Notify(T("auto_off")); }
                else { cAutoMode.Checked = true; Log(T("auto_on", cfg.Interval)); Beep(Sound.On); Notify(T("auto_on", cfg.Interval)); }
            }
            if (DateTime.Now - lastPing > TimeSpan.FromSeconds(30)) { lastPing = DateTime.Now; _ = Ping(); }
            if (queue.Count > 0 && !flushing && DateTime.Now - lastWebCheck > TimeSpan.FromSeconds(4)) _ = Flush();
            if (scanEdge) await Scan(false);
            else if (cAutoMode.Checked && !busy && DateTime.Now >= nextAuto) { nextAuto = DateTime.Now.AddSeconds(cfg.Interval); await Scan(true); }
        }
        catch (Exception ex) { Log(T("err", ex.Message)); busy = false; }
    }

    // ---------------- Overlay ----------------
    bool Edge(int vk, bool combo)
    {
        bool d = combo && Down(vk), was = keyWas.TryGetValue(vk, out var w) && w;
        keyWas[vk] = d; return d && !was;
    }
    void OverlayTick()
    {
        bool combo = Down(0x11) && Down(0x12);   // Strg und Alt
        bool kO = Edge(0x4F, combo), kR = Edge(0x52, combo), kL = Edge(0x25, combo), kRt = Edge(0x27, combo), kU = Edge(0x26, combo), kD = Edge(0x28, combo), kE = Edge(0x0D, combo), kN = Edge(0x4E, combo);
        if (ovlAllowed)
        {
            if (kO) { cfg.Overlay = !cfg.Overlay; cfg.Save(); ApplyOvl(); Log(T(cfg.Overlay ? "ov_on" : "ov_off")); }
            if (ovl.Visible)
            {
                if (kR) ovl.TogglePicker();
                if (ovl.PickerOpen) { if (kU) ovl.MoveSel(-1); if (kD) ovl.MoveSel(1); if (kRt) ovl.ToggleOpenSel(); if (kE) { var id = ovl.SelectedId(); if (id != null) _ = OvlCmd("pick", id); } if (kL) ovl.ClosePicker(); }
                else { if (kRt) _ = OvlCmd("next", null); if (kL) _ = OvlCmd("prev", null); if (kN) _ = OvlCmd("replan", null); }
            }
        }
        // Game.log jede Sekunde auf neue Käufe prüfen
        if (ovlAllowed && cfg.GameLog && DateTime.Now >= nextGlog)
        {
            nextGlog = DateTime.Now.AddSeconds(1);
            if (glog == null) { var f = GameLogWatcher.Find(cfg.GameLogPath); if (f != null) glog = new GameLogWatcher(f); else nextGlog = DateTime.Now.AddSeconds(30); ShowGlog(); }
            if (glog != null) { glog.Poll(); var list = glog.Take(); if (list != null && !glogBusy) _ = SendTrades(list); }
        }
        if (DateTime.Now >= nextOvl && !ovlBusy)
        {
            nextOvl = DateTime.Now.AddSeconds(ovl.Visible ? 3 : ovlAllowed ? 20 : 60);
            _ = OvlFetch();
        }
    }
    string OvlUrl => cfg.Url.TrimEnd('/') + "/api/pair/" + cfg.Code + "/overlay";
    async Task OvlFetch()
    {
        if (ovlBusy || !CodeRe.IsMatch(cfg.Code) || !cfg.Url.StartsWith("http")) return;
        ovlBusy = true;
        try
        {
            var r = await Http.GetAsync(OvlUrl);
            if ((int)r.StatusCode == 404 || (int)r.StatusCode == 403) SetOvlAllowed(false);
            else if (r.IsSuccessStatusCode)
            {
                ovlData = JsonNode.Parse(await r.Content.ReadAsStringAsync());
                SetOvlAllowed(true);
                long rev = ovlData?["rev"]?.GetValue<long>() ?? 0;
                ovl.SetData(ovlData, ovlNote != null && rev == ovlNoteRev && DateTime.Now < ovlNoteUntil ? ovlNote : null);
            }
        }
        catch { if (ovl.Visible) ovl.SetData(ovlData, T("ov_offline")); }
        finally { ovlBusy = false; }
    }
    async Task OvlCmd(string cmd, string id)
    {
        if (!CodeRe.IsMatch(cfg.Code)) return;
        if (cmd == "pick") ovl.ClosePicker();
        try
        {
            using var c = new StringContent(JsonSerializer.Serialize(new { cmd, id }), Encoding.UTF8, "application/json");
            var r = await Http.PostAsync(OvlUrl, c);
            var txt = await r.Content.ReadAsStringAsync();
            if (r.IsSuccessStatusCode)
            {
                ovlData = JsonNode.Parse(txt); Beep(Sound.On);
                if (cmd == "replan") { bool web = (bool?)ovlData?["web"] ?? false; ovlNote = web ? T("ov_replan_wait") : T("ov_replan_web"); ovlNoteRev = ovlData?["rev"]?.GetValue<long>() ?? 0; ovlNoteUntil = DateTime.Now.AddSeconds(web ? 20 : 8); }
                ovl.SetData(ovlData, cmd == "replan" ? ovlNote : null);
            }
            else Log(T("ov_cmd_fail", (string)JsonNode.Parse(txt)?["error"] ?? ((int)r.StatusCode).ToString()));
        }
        catch (Exception ex) { Log(T("ov_cmd_fail", ex.Message)); }
        nextOvl = DateTime.Now.AddSeconds(3);
    }
    void ShowGlog()
    {
        if (lGlog == null || lGlog.IsDisposed) return;
        var f = glog?.Path ?? (cfg.GameLog ? GameLogWatcher.Find(cfg.GameLogPath) : null);
        lGlog.Text = f != null ? T("gl_found", f.Length > 34 ? "…" + f[^33..] : f) : cfg.GameLog ? T("gl_none") : "";
        lGlog.ForeColor = f != null ? cMuted : cWarn;
    }
    async Task SendTrades(List<JsonObject> list)
    {
        glogBusy = true;
        try
        {
            // Genau das, was gesendet wird, steht im Verlauf der App
            foreach (var t in list) Log(T("gl_out", T((string)t["kind"] == "buy" ? "gl_buy" : "gl_sell"), (double)t["qty"], Math.Round((double)t["price"]), (string)t["loc"]));
            var arr = new JsonArray(); foreach (var t in list) arr.Add(t.DeepClone());
            var body = new JsonObject { ["pair"] = cfg.Code, ["trades"] = arr };
            using var c = new StringContent(body.ToJsonString(), Encoding.UTF8, "application/json");
            var r = await Http.PostAsync(cfg.Url.TrimEnd('/') + "/api/pair/trade", c);
            var j = JsonNode.Parse(await r.Content.ReadAsStringAsync());
            if (!r.IsSuccessStatusCode) { Log(T("gl_fail", (string)j?["error"] ?? ((int)r.StatusCode).ToString())); return; }
            foreach (var x in j?["results"] as JsonArray ?? new JsonArray())
            {
                var st = ((string)x?["station"] ?? "").Split(" > ").LastOrDefault() ?? "";
                Log(T("gl_ok", (string)x?["item"], (string)x?["action"] == "SELLS" ? T("gl_buy") : T("gl_sell"), Math.Round((double?)x?["price"] ?? 0), st));
            }
            Beep(Sound.Success); Notify(T("gl_notify"));
            if (!((bool?)j?["web"] ?? false)) Log(T("gl_web"));
        }
        catch (Exception ex) { Log(T("gl_fail", ex.Message)); }
        finally { glogBusy = false; }
    }
    void SetOvlAllowed(bool a)
    {
        if (ovlAllowed == a) return;
        ovlAllowed = a;
        if (pOvl != null) pOvl.Visible = a;
        if (pGlog != null) pGlog.Visible = a;
        ApplyOvl(); SetupTray();
    }
    void ApplyOvl()
    {
        bool show = ovlAllowed && cfg.Overlay;
        if (cOvl != null && cOvl.Checked != cfg.Overlay) { loading = true; cOvl.Checked = cfg.Overlay; loading = false; }
        if (show && !ovl.Visible)
        {
            var sc = Screen.PrimaryScreen.Bounds;
            bool ok = cfg.OvlX >= 0 && cfg.OvlY >= 0 && Screen.AllScreens.Any(s => s.Bounds.Contains(cfg.OvlX + 20, cfg.OvlY + 20));
            ovl.Location = ok ? new Point(cfg.OvlX, cfg.OvlY) : new Point(sc.Right - ovl.Width - S(24), sc.Top + S(24));
            ovl.Show();
            ovl.SetData(ovlData);
            nextOvl = DateTime.Now;
        }
        else if (!show && ovl.Visible) ovl.Hide();
        SetupTray();
    }

    // Fragt nebenbei, ob die Website mit diesem Code gerade offen ist
    async Task<bool> Ping()
    {
        lastWebCheck = DateTime.Now;
        try
        {
            using var c = new StringContent(JsonSerializer.Serialize(new { pair = cfg.Code }), Encoding.UTF8, "application/json");
            var r = await Http.PostAsync(cfg.Url + "/api/pair/ping", c);
            var j = JsonNode.Parse(await r.Content.ReadAsStringAsync());
            return r.IsSuccessStatusCode && ((bool?)j?["web"] ?? false);
        }
        catch { return false; }
    }

    void OpenSite()
    {
        try { System.Diagnostics.Process.Start(new System.Diagnostics.ProcessStartInfo(string.IsNullOrWhiteSpace(cfg.Url) ? "https://cargodeck.onrender.com" : cfg.Url) { UseShellExecute = true }); } catch { }
    }

    // Website nicht offen: Scan merken, leiser Ton, Fenster zeigt sich ohne dem Spiel den Fokus zu nehmen
    void Enqueue(JsonObject body)
    {
        body["auto"] = false;
        queue.Add(body); while (queue.Count > 40) queue.RemoveAt(0);
        Log(T("q_log", queue.Count));
        Beep(Sound.Queued); Notify(T("q_notify"));
        ShowQueue(); PopUp();
    }

    void ShowQueue()
    {
        int n = queue.Count;
        if (lQueue != null) lQueue.Text = n > 0 ? T("q_code", n) : "";
        if (bQueueOpen != null) bQueueOpen.Visible = n > 0;
        if (n > 0)
        {
            SetState(n == 1 ? T("q_title1") : T("q_title", n), T("q_sub"), cWarn);
            SetLast(n == 1 ? T("q_title1") : T("q_title", n), T("q_sub"));
        }
    }

    [DllImport("user32.dll")] static extern bool ShowWindow(IntPtr h, int cmd);
    [DllImport("user32.dll")] static extern bool SetWindowPos(IntPtr h, IntPtr after, int x, int y, int cx, int cy, uint flags);
    bool noActivate;
    protected override bool ShowWithoutActivation => noActivate || base.ShowWithoutActivation;
    void PopUp()
    {
        try
        {
            noActivate = true;
            if (!Visible) Show();
            if (WindowState == FormWindowState.Minimized) ShowWindow(Handle, 4);   // wiederherstellen ohne Fokus
            if (!cfg.Pinned) ShowPage(0);
            SetWindowPos(Handle, new IntPtr(-1), 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0010);   // kurz ganz nach vorne, ohne Fokus
            popped = true;
        }
        catch { }
        finally { noActivate = false; }
    }

    // Sobald die Website offen ist, alles Gespeicherte der Reihe nach senden
    async Task Flush()
    {
        if (flushing || queue.Count == 0) return;
        flushing = true;
        try
        {
            if (!await Ping()) return;
            int sent = 0;
            while (queue.Count > 0)
            {
                var body = queue[0];
                try
                {
                    using var content = new StringContent(body.ToJsonString(), Encoding.UTF8, "application/json");
                    var resp = await Http.PostAsync(cfg.Url + "/api/pair/scan", content);
                    if ((int)resp.StatusCode == 429) break;
                }
                catch { break; }
                queue.RemoveAt(0); sent++;
            }
            if (sent > 0)
            {
                Log(T("q_sent", sent)); Beep(Sound.Success); Notify(T("q_sent", sent));
                SetLast(T("q_sent", sent), T("last_look"));
            }
            ShowQueue();
            if (queue.Count == 0)
            {
                if (running) ShowRunning();
                if (popped) { popped = false; if (!cfg.Pinned && !cfg.TopMost) SetWindowPos(Handle, new IntPtr(-2), 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0010); }
            }
        }
        finally { flushing = false; }
    }

    // ---------------- Scannen ----------------
    [DllImport("user32.dll")] static extern IntPtr GetForegroundWindow();
    [DllImport("user32.dll")] static extern bool GetWindowRect(IntPtr h, out RECT r);
    [StructLayout(LayoutKind.Sequential)] struct RECT { public int Left, Top, Right, Bottom; }

    static Bitmap TakeShot()
    {
        GetWindowRect(GetForegroundWindow(), out var r);
        int w = r.Right - r.Left, h = r.Bottom - r.Top;
        if (w < 400 || h < 300) { var b = Screen.PrimaryScreen.Bounds; r.Left = b.X; r.Top = b.Y; w = b.Width; h = b.Height; }
        var bmp = new Bitmap(w, h, PixelFormat.Format32bppArgb);
        using var g = Graphics.FromImage(bmp);
        g.CopyFromScreen(r.Left, r.Top, 0, 0, new Size(w, h));
        return bmp;
    }

    // Kleiner Fingerabdruck, damit ein unverändertes Bild im Automatik Modus nicht erneut gelesen wird
    static string Print(Bitmap bmp)
    {
        using var small = new Bitmap(40, 24);
        using (var g = Graphics.FromImage(small)) g.DrawImage(bmp, 0, 0, 40, 24);
        var sb = new StringBuilder(960);
        for (int y = 0; y < 24; y++) for (int x = 0; x < 40; x++) { var p = small.GetPixel(x, y); sb.Append((char)(65 + (p.R + p.G + p.B) / 48)); }
        return sb.ToString();
    }

    // Verkleinertes JPG als Nachweis für UEX
    static string Jpeg64(Bitmap bmp)
    {
        double scale = Math.Min(1.0, 1920.0 / bmp.Width);
        int w = (int)(bmp.Width * scale), h = (int)(bmp.Height * scale);
        using var outB = new Bitmap(w, h);
        using (var g = Graphics.FromImage(outB)) { g.InterpolationMode = InterpolationMode.HighQualityBicubic; g.DrawImage(bmp, 0, 0, w, h); }
        var enc = ImageCodecInfo.GetImageEncoders().First(c => c.MimeType == "image/jpeg");
        using var ep = new EncoderParameters(1);
        ep.Param[0] = new EncoderParameter(System.Drawing.Imaging.Encoder.Quality, 78L);
        using var ms = new MemoryStream();
        outB.Save(ms, enc, ep);
        return Convert.ToBase64String(ms.ToArray());
    }

    // Bilder, die gemacht wurden, während das letzte noch gelesen wird. Werden danach der Reihe nach gelesen
    readonly Queue<Bitmap> backlog = new();

    async Task Scan(bool auto, Bitmap pre = null)
    {
        if (busy && pre == null)
        {
            if (auto) return;
            // Noch am Lesen: das neue Bild trotzdem sofort machen, Ton, und danach lesen.
            // So kann man im Terminal runterscrollen und direkt nochmal drücken, ohne zu warten
            try { backlog.Enqueue(TakeShot()); } catch (Exception ex) { Log(ex.Message); return; }
            Beep(Sound.Shot); Log(T("held", backlog.Count));
            return;
        }
        busy = true;
        try
        {
            using var bmp = pre ?? TakeShot();
            // Bild ist gemacht: gleich der Ton, dann darf man weiterscrollen
            if (!auto && pre == null) Beep(Sound.Shot);
            if (auto)
            {
                var pr = Print(bmp);
                if (pr == lastPrint) return;
                lastPrint = pr;
            }
            if (!auto) SetState(T("reading"), stateSub, cWarn);
            // Zwei weitere Bilder kurz danach braucht nur die Windows Texterkennung, das Terminal flimmert im Spiel leicht.
            // PaddleOCR liest nur das erste, dann keine weiteren Bilder, sonst wäre schon runtergescrollt
            var shots = new List<Bitmap> { bmp };
            var fg = GetForegroundWindow();
            for (int i = 0; i < (pre == null && PaddleOcr.LoadError != null ? (auto ? 1 : 2) : 0); i++)
            {
                await Task.Delay(350);
                if (GetForegroundWindow() != fg) break;
                try { shots.Add(TakeShot()); } catch { break; }
            }
            var img = Jpeg64(bmp);
            JsonObject ocr;
            try { ocr = await Task.Run(() => Ocr.Run(shots)); }
            catch (Exception ex) { Log(T("ocr_err", ex.Message)); if (!auto) SetState(T("ocr_fail"), ex.Message, cBad); return; }
            finally { foreach (var s in shots.Skip(1)) s.Dispose(); }

            if (auto)
            {
                var txt = string.Join(" ", ocr["passes"].AsArray().SelectMany(p => p["lines"].AsArray().Select(l => (string)l["t"])));
                if (!TerminalWords.IsMatch(txt)) return;
            }

            var body = new JsonObject { ["pair"] = cfg.Code, ["auto"] = auto, ["ocr"] = ocr, ["image"] = img, ["time"] = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds() };
            // Nur senden, wenn die Website offen ist. Sonst in der App stapeln, bis sie offen ist.
            if (queue.Count > 0 || !await Ping())
            {
                Enqueue(body);
                return;
            }
            HttpResponseMessage resp;
            string raw;
            try
            {
                using var content = new StringContent(body.ToJsonString(), Encoding.UTF8, "application/json");
                resp = await Http.PostAsync(cfg.Url + "/api/pair/scan", content);
                raw = await resp.Content.ReadAsStringAsync();
            }
            catch (Exception ex)
            {
                Log(T("send_fail", ex.Message)); SetState(T("unreach"), cfg.Url, cBad);
                if (!auto) { Beep(Sound.Error); Notify(T("send_fail_n")); }
                return;
            }

            JsonNode r = null; try { r = JsonNode.Parse(raw); } catch { }
            int rows = 0; try { rows = (int?)r?["rows"] ?? 0; } catch { }
            if (rows > 0)
            {
                string st = ""; try { st = ((string)r["station"] ?? "").Split(" > ").Last(); } catch { }
                Log(T("rows_ok", rows, st).Trim());
                ShowRunning();
                SetLast(T("last_ok", rows, DateTime.Now.ToString("HH:mm")) + (st.Length > 0 ? ", " + st : ""), T("last_look"));
                Beep(Sound.Success); Notify(T("rows_notify", rows, st).Replace("  ", " "));
            }
            else if (!auto)
            {
                string n = T("no_term");
                try { n = (string)r?["error"] ?? (string)r?["note"] ?? n; } catch { }
                if (!resp.IsSuccessStatusCode && r?["error"] == null) n = T("http_err", (int)resp.StatusCode);
                Log(n); SetState(n, RunningText().Item2, cWarn); Beep(Sound.Error);
            }
        }
        finally
        {
            busy = false;
            if (running && !auto && stateTitle == T("reading")) ShowRunning();
            // gemerkte Bilder der Reihe nach lesen
            if (backlog.Count > 0) { var nx = backlog.Dequeue(); _ = Scan(false, nx); }
        }
    }
}
