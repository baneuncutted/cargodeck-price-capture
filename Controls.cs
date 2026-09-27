using System.Drawing;
using System.Drawing.Drawing2D;
using System.Runtime.InteropServices;

namespace CargoDeckScanner;

// Schalter wie auf der Seite, gut sichtbar an und aus
class Toggle : Control
{
    bool _checked, _hover;
    public Color OnColor { get; set; } = Color.Teal;
    public Color OffColor { get; set; } = Color.Gray;
    public event EventHandler CheckedChanged;

    public Toggle()
    {
        SetStyle(ControlStyles.AllPaintingInWmPaint | ControlStyles.OptimizedDoubleBuffer | ControlStyles.UserPaint | ControlStyles.ResizeRedraw | ControlStyles.Selectable, true);
        Cursor = Cursors.Hand; TabStop = true;
    }

    public bool Checked
    {
        get => _checked;
        set { if (_checked == value) return; _checked = value; Invalidate(); CheckedChanged?.Invoke(this, EventArgs.Empty); }
    }

    float K => DeviceDpi / 96f;

    public Size Measure()
    {
        var ts = TextRenderer.MeasureText(Text, Font);
        return new Size((int)(46 * K) + ts.Width + 4, Math.Max((int)(26 * K), ts.Height + 6));
    }

    protected override void OnTextChanged(EventArgs e) { base.OnTextChanged(e); Invalidate(); }
    protected override void OnMouseEnter(EventArgs e) { _hover = true; Invalidate(); base.OnMouseEnter(e); }
    protected override void OnMouseLeave(EventArgs e) { _hover = false; Invalidate(); base.OnMouseLeave(e); }
    protected override void OnClick(EventArgs e) { Focus(); Checked = !Checked; base.OnClick(e); }
    protected override void OnKeyDown(KeyEventArgs e) { if (e.KeyCode == Keys.Space) Checked = !Checked; base.OnKeyDown(e); }
    protected override void OnGotFocus(EventArgs e) { Invalidate(); base.OnGotFocus(e); }
    protected override void OnLostFocus(EventArgs e) { Invalidate(); base.OnLostFocus(e); }

    protected override void OnPaint(PaintEventArgs e)
    {
        var g = e.Graphics; g.SmoothingMode = SmoothingMode.AntiAlias; g.Clear(Parent is CardPanel cp ? cp.Fill : BackColor);
        float k = K, w = 38 * k, h = 20 * k, y = (Height - h) / 2f;
        using (var path = Pill(new RectangleF(1, y, w, h)))
        {
            using var b = new SolidBrush(_checked ? OnColor : (_hover ? ControlPaint.Light(OffColor, .3f) : OffColor));
            g.FillPath(b, path);
            if (Focused) { using var p = new Pen(Color.FromArgb(120, OnColor), 1.5f * k); g.DrawPath(p, path); }
        }
        float d = h - 6 * k, x = _checked ? 1 + w - d - 3 * k : 1 + 3 * k;
        using (var kb = new SolidBrush(_checked ? Color.FromArgb(0x0b, 0x0f, 0x14) : Color.FromArgb(0xee, 0xf3, 0xf9)))
            g.FillEllipse(kb, x, y + 3 * k, d, d);
        TextRenderer.DrawText(g, Text, Font, new Rectangle((int)(w + 10 * k), 0, Width - (int)(w + 10 * k), Height), ForeColor, TextFormatFlags.VerticalCenter | TextFormatFlags.Left);
    }

    static GraphicsPath Pill(RectangleF r)
    {
        var p = new GraphicsPath(); float d = r.Height;
        p.AddArc(r.X, r.Y, d, d, 90, 180); p.AddArc(r.Right - d, r.Y, d, d, 270, 180); p.CloseFigure(); return p;
    }
}

// Karte mit runden Ecken, Rahmen und leuchtender Oberkante, wie die Karten auf der Website
class CardPanel : Panel
{
    public Color LineColor { get; set; } = Color.Gray;
    public Color GlowColor { get; set; } = Color.Teal;
    public Color Fill { get; set; } = Color.FromArgb(0x14, 0x1c, 0x28);
    public int Radius { get; set; } = 12;
    public bool Glow { get; set; } = true;
    public CardPanel() { SetStyle(ControlStyles.OptimizedDoubleBuffer | ControlStyles.AllPaintingInWmPaint | ControlStyles.ResizeRedraw | ControlStyles.UserPaint, true); }
    float K => DeviceDpi / 96f;
    protected override void OnPaintBackground(PaintEventArgs e)
    {
        var g = e.Graphics; g.SmoothingMode = SmoothingMode.AntiAlias;
        g.Clear(Parent?.BackColor ?? BackColor);
        using var path = Ui.Round(new RectangleF(0.5f, 0.5f, Width - 1.5f, Height - 1.5f), Radius * K);
        using (var b = new SolidBrush(Fill)) g.FillPath(b, path);
        using (var p = new Pen(LineColor)) g.DrawPath(p, path);
        if (Glow)
        {
            using var br = new LinearGradientBrush(new Rectangle(0, 0, Width, 2), Color.Transparent, GlowColor, 0f)
            { InterpolationColors = new ColorBlend { Colors = new[] { Color.Transparent, Color.FromArgb(210, GlowColor), Color.Transparent }, Positions = new[] { 0f, .5f, 1f } } };
            g.FillRectangle(br, Radius * K, 0, Width - 2 * Radius * K, 1.2f);
        }
    }
}

static class Ui
{
    public static GraphicsPath Round(RectangleF r, float rad)
    {
        var p = new GraphicsPath(); float d = Math.Min(rad * 2, Math.Min(r.Width, r.Height));
        if (d < 1) { p.AddRectangle(r); return p; }
        p.AddArc(r.X, r.Y, d, d, 180, 90); p.AddArc(r.Right - d, r.Y, d, d, 270, 90);
        p.AddArc(r.Right - d, r.Bottom - d, d, d, 0, 90); p.AddArc(r.X, r.Bottom - d, d, d, 90, 90); p.CloseFigure(); return p;
    }
}

// Runder Knopf im Stil der Website. Primary ist türkis gefüllt, sonst dunkel mit Rahmen.
class RButton : Control
{
    bool _hover, _down;
    public bool Primary { get; set; }
    public Color Accent { get; set; } = Color.FromArgb(0x35, 0xd6, 0xcc);
    public Color Fill { get; set; } = Color.FromArgb(0x1a, 0x24, 0x33);
    public Color Line { get; set; } = Color.FromArgb(0x30, 0x40, 0x56);
    public string Icon { get; set; }   // Zeichen aus Segoe MDL2 Assets, optional
    public int Radius { get; set; } = 10;
    public RButton()
    {
        SetStyle(ControlStyles.AllPaintingInWmPaint | ControlStyles.OptimizedDoubleBuffer | ControlStyles.UserPaint | ControlStyles.ResizeRedraw | ControlStyles.Selectable | ControlStyles.SupportsTransparentBackColor, true);
        Cursor = Cursors.Hand; TabStop = true;
    }
    float K => DeviceDpi / 96f;
    protected override void OnTextChanged(EventArgs e) { base.OnTextChanged(e); Invalidate(); }
    protected override void OnMouseEnter(EventArgs e) { _hover = true; Invalidate(); base.OnMouseEnter(e); }
    protected override void OnMouseLeave(EventArgs e) { _hover = _down = false; Invalidate(); base.OnMouseLeave(e); }
    protected override void OnMouseDown(MouseEventArgs e) { _down = true; Invalidate(); base.OnMouseDown(e); }
    protected override void OnMouseUp(MouseEventArgs e) { _down = false; Invalidate(); base.OnMouseUp(e); }
    protected override void OnGotFocus(EventArgs e) { Invalidate(); base.OnGotFocus(e); }
    protected override void OnLostFocus(EventArgs e) { Invalidate(); base.OnLostFocus(e); }
    protected override void OnKeyDown(KeyEventArgs e) { if (e.KeyCode is Keys.Enter or Keys.Space) OnClick(EventArgs.Empty); base.OnKeyDown(e); }
    protected override void OnPaint(PaintEventArgs e)
    {
        var g = e.Graphics; g.SmoothingMode = SmoothingMode.AntiAlias; g.TextRenderingHint = System.Drawing.Text.TextRenderingHint.ClearTypeGridFit;
        g.Clear(Parent is CardPanel cp ? cp.Fill : (Parent?.BackColor ?? BackColor));
        Color bg, fg, bd;
        if (Primary) { bg = _down ? Color.FromArgb(0x1a, 0xa3, 0x9b) : _hover ? Color.FromArgb(0x5b, 0xe4, 0xdb) : Accent; fg = Color.FromArgb(0x0b, 0x0f, 0x14); bd = bg; }
        else { bg = _down ? Line : _hover ? Color.FromArgb(0x21, 0x2d, 0x3e) : Fill; fg = _hover ? Accent : ForeColor; bd = _hover ? Color.FromArgb(140, Accent) : Line; }
        if (!Enabled) { fg = Color.FromArgb(0x66, 0x74, 0x8a); }
        using var path = Ui.Round(new RectangleF(0.5f, 0.5f, Width - 1.5f, Height - 1.5f), Radius * K);
        using (var b = new SolidBrush(bg)) g.FillPath(b, path);
        using (var p = new Pen(Focused ? Accent : bd, Focused ? 1.6f : 1f)) g.DrawPath(p, path);
        var r = new Rectangle(0, 0, Width, Height);
        if (!string.IsNullOrEmpty(Icon))
        {
            using var f = new Font("Segoe MDL2 Assets", Font.Size * 1.05f);
            if (string.IsNullOrEmpty(Text)) { TextRenderer.DrawText(g, Icon, f, r, fg, TextFormatFlags.HorizontalCenter | TextFormatFlags.VerticalCenter); return; }
            var tw = TextRenderer.MeasureText(Text, Font).Width; var iw = TextRenderer.MeasureText(Icon, f).Width;
            int x0 = (Width - tw - iw) / 2;
            TextRenderer.DrawText(g, Icon, f, new Rectangle(x0, 0, iw, Height), fg, TextFormatFlags.VerticalCenter);
            TextRenderer.DrawText(g, Text, Font, new Rectangle(x0 + iw, 0, tw + 4, Height), fg, TextFormatFlags.VerticalCenter);
            return;
        }
        TextRenderer.DrawText(g, Text, Font, r, fg, TextFormatFlags.HorizontalCenter | TextFormatFlags.VerticalCenter | TextFormatFlags.WordBreak);
    }
}

// Umschalter mit mehreren Feldern, wie die Reiter auf der Website
class Seg : Control
{
    string[] _items = Array.Empty<string>();
    int _sel, _hover = -1;
    public Color Accent { get; set; } = Color.FromArgb(0x35, 0xd6, 0xcc);
    public Color Fill { get; set; } = Color.FromArgb(0x14, 0x1c, 0x28);
    public Color Line { get; set; } = Color.FromArgb(0x24, 0x31, 0x42);
    public Color Muted { get; set; } = Color.FromArgb(0x8f, 0x9d, 0xb1);
    public event EventHandler Changed;
    public Seg() { SetStyle(ControlStyles.AllPaintingInWmPaint | ControlStyles.OptimizedDoubleBuffer | ControlStyles.UserPaint | ControlStyles.ResizeRedraw, true); Cursor = Cursors.Hand; }
    public string[] Items { get => _items; set { _items = value ?? Array.Empty<string>(); Invalidate(); } }
    public int Selected { get => _sel; set { if (_sel == value) return; _sel = value; Invalidate(); Changed?.Invoke(this, EventArgs.Empty); } }
    float K => DeviceDpi / 96f;
    int At(int x) => _items.Length == 0 ? -1 : Math.Clamp(x * _items.Length / Math.Max(1, Width), 0, _items.Length - 1);
    protected override void OnMouseMove(MouseEventArgs e) { var h = At(e.X); if (h != _hover) { _hover = h; Invalidate(); } base.OnMouseMove(e); }
    protected override void OnMouseLeave(EventArgs e) { _hover = -1; Invalidate(); base.OnMouseLeave(e); }
    protected override void OnMouseClick(MouseEventArgs e) { var i = At(e.X); if (i >= 0) Selected = i; base.OnMouseClick(e); }
    protected override void OnPaint(PaintEventArgs e)
    {
        var g = e.Graphics; g.SmoothingMode = SmoothingMode.AntiAlias;
        g.Clear(Parent is CardPanel cp ? cp.Fill : (Parent?.BackColor ?? BackColor));
        float k = K;
        using (var path = Ui.Round(new RectangleF(0.5f, 0.5f, Width - 1.5f, Height - 1.5f), 10 * k))
        {
            using var b = new SolidBrush(Fill); g.FillPath(b, path);
            using var p = new Pen(Line); g.DrawPath(p, path);
        }
        float w = (Width - 6 * k) / Math.Max(1, _items.Length);
        for (int i = 0; i < _items.Length; i++)
        {
            var r = new RectangleF(3 * k + i * w, 3 * k, w, Height - 6 * k);
            if (i == _sel)
            {
                using var path = Ui.Round(r, 8 * k);
                using var b = new SolidBrush(Color.FromArgb(40, Accent)); g.FillPath(b, path);
                using var p = new Pen(Color.FromArgb(120, Accent)); g.DrawPath(p, path);
            }
            var col = i == _sel ? Accent : i == _hover ? ForeColor : Muted;
            using var f = new Font(Font, i == _sel ? FontStyle.Bold : FontStyle.Regular);
            TextRenderer.DrawText(g, _items[i], f, Rectangle.Round(r), col, TextFormatFlags.HorizontalCenter | TextFormatFlags.VerticalCenter | TextFormatFlags.EndEllipsis);
        }
    }
}

// Namen und Codes für Tasten
static class KeyNames
{
    [DllImport("user32.dll", CharSet = CharSet.Unicode)] static extern short VkKeyScan(char ch);
    [DllImport("user32.dll")] static extern uint MapVirtualKey(uint code, uint type);
    public static int FromChar(string s) { if (string.IsNullOrEmpty(s)) return 0; var v = VkKeyScan(s[0]); return v == -1 ? 0 : v & 0xFF; }
    public static string Name(int vk)
    {
        if (vk <= 0) return "?";
        try
        {
            var k = (Keys)vk;
            if ((k >= Keys.A && k <= Keys.Z) || (k >= Keys.D0 && k <= Keys.D9) || k >= Keys.Oem1)
            {
                var ch = (char)(MapVirtualKey((uint)vk, 2) & 0x7FFF);
                if (ch > ' ') return char.ToUpper(ch).ToString();
            }
            if (k >= Keys.NumPad0 && k <= Keys.NumPad9) return "Num " + (vk - (int)Keys.NumPad0);
            if (Lang.En) return k switch { Keys.Next => "Page Down", Keys.PageUp => "Page Up", Keys.Space => "Space", _ => k.ToString() };
            return k switch { Keys.Next => "Bild ab", Keys.PageUp => "Bild auf", Keys.Insert => "Einfg", Keys.Delete => "Entf", Keys.Home => "Pos1", Keys.End => "Ende", Keys.Space => "Leertaste", _ => k.ToString() };
        }
        catch { return "Taste " + vk; }
    }
}

// Knopf, der die nächste gedrückte Taste aufnimmt
class KeyBox : Button
{
    int _vk; bool _capture;
    public event EventHandler Changed;
    public int Vk { get => _vk; set { _vk = value; if (!_capture) Text = KeyNames.Name(value); } }
    public KeyBox() { Click += (s, e) => { _capture = true; Text = Lang.En ? "Key…" : "Taste…"; Focus(); }; LostFocus += (s, e) => { if (_capture) { _capture = false; Text = KeyNames.Name(_vk); } }; }
    protected override bool IsInputKey(Keys keyData) => _capture || base.IsInputKey(keyData);
    protected override bool ProcessDialogKey(Keys keyData) => _capture ? true : base.ProcessDialogKey(keyData);
    protected override void OnKeyDown(KeyEventArgs e)
    {
        if (!_capture) { base.OnKeyDown(e); return; }
        e.Handled = true; e.SuppressKeyPress = true;
        var k = e.KeyCode;
        if (k is Keys.ControlKey or Keys.ShiftKey or Keys.Menu or Keys.LControlKey or Keys.RControlKey or Keys.LWin or Keys.RWin) return;
        _capture = false;
        if (k != Keys.Escape) { _vk = (int)k; Changed?.Invoke(this, EventArgs.Empty); }
        Text = KeyNames.Name(_vk);
    }
}
