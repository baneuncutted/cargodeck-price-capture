using System.Drawing;
using System.Drawing.Drawing2D;
using System.Drawing.Imaging;
using System.Runtime.InteropServices;
using System.Text.Json.Nodes;
using Windows.Graphics.Imaging;
using Windows.Media.Ocr;
using Windows.Security.Cryptography;

namespace CargoDeckScanner;

// Texterkennung mit der in Windows eingebauten OCR, alles lokal auf dem PC.
// Liefert das gleiche Format wie der alte ocr.ps1, damit der Server es versteht.
static class Ocr
{
    static OcrEngine _engine;

    static OcrEngine Engine()
    {
        if (_engine != null) return _engine;
        var en = new Windows.Globalization.Language("en-US");
        _engine = OcrEngine.IsLanguageSupported(en) ? OcrEngine.TryCreateFromLanguage(en) : OcrEngine.TryCreateFromUserProfileLanguages();
        if (_engine == null) throw new Exception("Keine Windows Texterkennung gefunden. In Windows unter Sprache eine Sprache mit Texterkennung installieren, zum Beispiel Englisch.");
        return _engine;
    }

    // Max: hellster Farbkanal statt Grau. Rote und orange Schrift (Pyro Terminals) wird in Grau viel zu dunkel.
    record Pass(string Name, bool Invert, double Cx, double Cw, double Zoom, float Contrast = 1f, bool Max = false);

    static readonly Pass[] Plan =
    {
        new("rechts", true, 0.5, 0.5, 2),
        new("links", true, 0.0, 0.5, 2),
        // Zusätzlich mit starkem Kontrast und noch grösser, damit blasse und kleine Zahlen sauber gelesen werden
        new("rechts-k", true, 0.5, 0.5, 3, 1.9f, true),
        new("links-k", true, 0.0, 0.5, 3, 1.9f, true),
        new("invert", true, 0.0, 1.0, 1),
        new("normal", false, 0.0, 1.0, 1),
    };

    record struct Line(string T, int X, int Y, int W, int H);

    // Wörter, die nur auf einem Handelsterminal stehen. Daraus ergibt sich, wo das Terminal im Bild ist.
    static readonly System.Text.RegularExpressions.Regex TermWord =
        new(@"SCU|INVENT|QUANTIT|CARGO|DEMAND|COMMODIT|BALANCE|MARKET|SHOP", System.Text.RegularExpressions.RegexOptions.IgnoreCase);
    // Zeilen mit einem Preis pro SCU, die lesen wir nochmal extra scharf
    static readonly System.Text.RegularExpressions.Regex PriceLine =
        new(@"\S\s*/\s*[S5$s][CcGgOo]?|[¤Ä]\s*\S", System.Text.RegularExpressions.RegexOptions.None);

    public static Task<JsonObject> Run(Bitmap src) => Run(new List<Bitmap> { src });

    // Zuerst PaddleOCR (gleiche Technik wie die Website), nur wenn das nicht geht die Windows Texterkennung
    public static async Task<JsonObject> Run(IList<Bitmap> shots)
    {
        var p = PaddleOcr.Get();
        if (p != null)
        {
            try
            {
                var r = p.Read(ToPaddle(shots[0]));
                if (r["passes"].AsArray().Any(x => x["lines"].AsArray().Count > 0)) return r;
            }
            catch (Exception ex) { PaddleOcr.LoadError ??= ex.Message; }
        }
        return await RunWindows(shots);
    }

    // Bild als BGR Bytes für PaddleOCR
    public static PaddleImage ToPaddle(Bitmap src)
    {
        var data = src.LockBits(new Rectangle(0, 0, src.Width, src.Height), ImageLockMode.ReadOnly, PixelFormat.Format24bppRgb);
        try
        {
            int w = src.Width, h = src.Height, row = w * 3;
            var buf = new byte[row * h];
            for (int y = 0; y < h; y++) Marshal.Copy(data.Scan0 + y * data.Stride, buf, y * row, row);
            return new PaddleImage(w, h, buf);
        }
        finally { src.UnlockBits(data); }
    }

    // shots[0] ist das Hauptbild, weitere Bilder kurz danach helfen gegen Flimmern im Spiel
    public static async Task<JsonObject> RunWindows(IList<Bitmap> shots)
    {
        var engine = Engine();
        var src = shots[0];
        var passes = new JsonArray();
        var all = new List<(string name, List<Line> lines)>();

        // 1) Die bewährten Durchgänge über das ganze Bild
        foreach (var p in Plan)
        {
            int sx = (int)(src.Width * p.Cx), sw = (int)(src.Width * p.Cw);
            double maxDim = OcrEngine.MaxImageDimension, longest = Math.Max(sw, src.Height), scale = p.Zoom;
            if (p.Zoom == 1 && longest < 2000) scale = Math.Min(1.6, maxDim / longest);
            var lines = await Read(engine, src, new Rectangle(sx, 0, sw, src.Height), scale, p.Invert, p.Contrast, false, p.Max);
            all.Add((p.Name, lines));
        }

        // 2) Terminal finden und nur diesen Ausschnitt nochmal gross lesen, ohne Cockpit und Hintergrund
        var term = FindTerminal(all.SelectMany(a => a.lines).ToList(), src.Width, src.Height);
        if (term.HasValue)
        {
            var t = term.Value;
            int half = t.Width / 2;
            foreach (var (name, r) in new[] { ("terminal-l", new Rectangle(t.X, t.Y, half, t.Height)), ("terminal-r", new Rectangle(t.X + half, t.Y, t.Width - half, t.Height)) })
            {
                double scale = Math.Min(3, OcrEngine.MaxImageDimension / (double)Math.Max(r.Width, r.Height));
                all.Add((name, await Read(engine, src, r, scale, true, 1.6f, false, true)));
            }
        }

        // 3) Preiszeilen einzeln, stark vergrössert und in reinem Schwarz Weiss nochmal lesen, auf jedem Bild
        var regions = PriceRegions(all.SelectMany(a => a.lines).ToList(), src.Width, src.Height);
        if (regions.Count > 0)
        {
            // Vorlage ist der ganze Durchgang mit den meisten Zeilen, darin ersetzen wir die Preise
            var tpl = all.Where(a => a.name == "invert" || a.name == "normal" || a.name.StartsWith("terminal")).OrderByDescending(a => a.lines.Count).First().lines;
            if (term.HasValue) tpl = all.Where(a => a.name.StartsWith("terminal")).SelectMany(a => a.lines).ToList();
            for (int i = 0; i < shots.Count; i++)
            {
                var img = shots[i];
                if (img.Width != src.Width || img.Height != src.Height) continue;
                var fresh = new List<Line>();
                foreach (var r in regions)
                {
                    double scale = Math.Clamp(64.0 / Math.Max(1, r.Height / 1.6), 2, 8);
                    var got = await Read(engine, img, r, scale, false, 1f, true, true);
                    if (got.Count == 0) continue;
                    var txt = string.Join(" ", got.OrderBy(g => g.X).Select(g => g.T));
                    fresh.Add(new Line(txt, got.Min(g => g.X), got.Min(g => g.Y), got.Max(g => g.X + g.W) - got.Min(g => g.X), got.Max(g => g.Y + g.H) - got.Min(g => g.Y)));
                }
                if (fresh.Count == 0) continue;
                var merged = tpl.Where(l => !fresh.Any(f => Overlap(l, f))).Concat(fresh).OrderBy(l => l.Y).ThenBy(l => l.X).ToList();
                all.Add(("preise-" + (i + 1), merged));
            }
        }

        foreach (var (name, lines) in all)
        {
            var arr = new JsonArray();
            foreach (var l in lines) arr.Add(new JsonObject { ["t"] = l.T, ["x"] = l.X, ["y"] = l.Y, ["w"] = l.W, ["h"] = l.H });
            passes.Add(new JsonObject { ["name"] = name, ["w"] = src.Width, ["h"] = src.Height, ["lines"] = arr });
        }
        return new JsonObject { ["ok"] = true, ["passes"] = passes, ["shots"] = shots.Count };
    }

    static bool Overlap(Line a, Line b)
    {
        int x1 = Math.Max(a.X, b.X), x2 = Math.Min(a.X + a.W, b.X + b.W), y1 = Math.Max(a.Y, b.Y), y2 = Math.Min(a.Y + a.H, b.Y + b.H);
        return x2 > x1 && y2 > y1 && (y2 - y1) > Math.Min(a.H, b.H) * 0.4;
    }

    // Umrandung aller Terminal Wörter, mit etwas Rand. Nichts gefunden oder fast das ganze Bild, dann kein Ausschnitt.
    static Rectangle? FindTerminal(List<Line> lines, int W, int H)
    {
        var hits = lines.Where(l => TermWord.IsMatch(l.T)).ToList();
        if (hits.Count < 3) return null;
        int x1 = hits.Min(l => l.X), y1 = hits.Min(l => l.Y), x2 = hits.Max(l => l.X + l.W), y2 = hits.Max(l => l.Y + l.H);
        int padX = (int)(W * 0.06), padY = (int)(H * 0.05);
        var r = Rectangle.FromLTRB(Math.Max(0, x1 - padX), Math.Max(0, y1 - padY), Math.Min(W, x2 + padX), Math.Min(H, y2 + padY));
        if (r.Width < W * 0.2 || r.Height < H * 0.2) return null;
        if ((double)r.Width * r.Height > W * (double)H * 0.85) return null;
        return r;
    }

    // Stellen im Bild, an denen ein Preis steht. Gleiche Stellen aus mehreren Durchgängen werden zusammengefasst.
    static List<Rectangle> PriceRegions(List<Line> lines, int W, int H)
    {
        var boxes = new List<Rectangle>();
        foreach (var l in lines.Where(l => PriceLine.IsMatch(l.T) && l.H > 4 && l.H < H / 8 && l.W < W / 3))
        {
            var r = new Rectangle(l.X - l.H, l.Y - l.H / 3, l.W + l.H * 2, l.H + l.H * 2 / 3);
            r.Intersect(new Rectangle(0, 0, W, H));
            int j = boxes.FindIndex(b => b.IntersectsWith(r) && Math.Abs((b.Y + b.Height / 2) - (r.Y + r.Height / 2)) < Math.Max(b.Height, r.Height) / 2);
            if (j >= 0) boxes[j] = Rectangle.Union(boxes[j], r); else boxes.Add(r);
        }
        return boxes.Where(b => b.Width > 8 && b.Height > 6).Take(24).ToList();
    }

    // Ausschnitt vergrössern, einfärben und lesen. Koordinaten kommen zurück ins Originalbild.
    static async Task<List<Line>> Read(OcrEngine engine, Bitmap src, Rectangle r, double scale, bool invert, float k, bool binar, bool maxCh = false)
    {
        double maxDim = OcrEngine.MaxImageDimension;
        if (Math.Max(r.Width, r.Height) * scale > maxDim) scale = maxDim / Math.Max(r.Width, r.Height);
        int w = Math.Max(1, (int)(r.Width * scale)), h = Math.Max(1, (int)(r.Height * scale));
        int pad = binar ? Math.Max(8, h / 4) : 0;

        using var bmp = new Bitmap(w + pad * 2, h + pad * 2, PixelFormat.Format32bppArgb);
        using (var g = Graphics.FromImage(bmp))
        {
            g.Clear(Color.White);
            g.InterpolationMode = InterpolationMode.HighQualityBicubic;
            g.PixelOffsetMode = PixelOffsetMode.HighQuality;
            if (maxCh) g.DrawImage(src, new Rectangle(pad, pad, w, h), r.X, r.Y, r.Width, r.Height, GraphicsUnit.Pixel);
            else
            {
                float a = (invert ? -0.3f : 0.3f) * k, b = (invert ? -0.59f : 0.59f) * k, c = (invert ? -0.11f : 0.11f) * k;
                float o = (invert ? 1f : 0f) * k - (k - 1f) / 2f;
                var cm = new ColorMatrix(new[]
                {
                    new[] { a, a, a, 0f, 0f },
                    new[] { b, b, b, 0f, 0f },
                    new[] { c, c, c, 0f, 0f },
                    new[] { 0f, 0f, 0f, 1f, 0f },
                    new[] { o, o, o, 0f, 1f },
                });
                using var ia = new ImageAttributes();
                ia.SetColorMatrix(cm);
                g.DrawImage(src, new Rectangle(pad, pad, w, h), r.X, r.Y, r.Width, r.Height, GraphicsUnit.Pixel, ia);
            }
        }
        if (maxCh && !binar) MaxChannel(bmp, invert, k);
        if (binar) Binarize(bmp, pad);

        var sb = ToSoftwareBitmap(bmp);
        var res = await engine.RecognizeAsync(sb);
        sb.Dispose();

        var lines = new List<Line>();
        foreach (var l in res.Lines)
        {
            double x1 = 1e9, y1 = 1e9, x2 = 0, y2 = 0;
            foreach (var wd in l.Words)
            {
                var b = wd.BoundingRect;
                x1 = Math.Min(x1, b.X); y1 = Math.Min(y1, b.Y);
                x2 = Math.Max(x2, b.X + b.Width); y2 = Math.Max(y2, b.Y + b.Height);
            }
            lines.Add(new Line(l.Text, (int)((x1 - pad) / scale + r.X), (int)((y1 - pad) / scale + r.Y), (int)((x2 - x1) / scale), (int)((y2 - y1) / scale)));
        }
        return lines;
    }

    // Hellster Kanal als Grauwert, optional umgedreht und mit mehr Kontrast
    static void MaxChannel(Bitmap bmp, bool invert, float k)
    {
        var data = bmp.LockBits(new Rectangle(0, 0, bmp.Width, bmp.Height), ImageLockMode.ReadWrite, PixelFormat.Format32bppArgb);
        try
        {
            int n = data.Stride * bmp.Height;
            var px = new byte[n];
            Marshal.Copy(data.Scan0, px, 0, n);
            for (int y = 0; y < bmp.Height; y++)
                for (int x = 0; x < bmp.Width; x++)
                {
                    int i = y * data.Stride + x * 4;
                    int v = Math.Max(px[i], Math.Max(px[i + 1], px[i + 2]));
                    if (invert) v = 255 - v;
                    v = (int)Math.Clamp((v - 128) * k + 128, 0, 255);
                    px[i] = px[i + 1] = px[i + 2] = (byte)v; px[i + 3] = 255;
                }
            Marshal.Copy(px, 0, data.Scan0, n);
        }
        finally { bmp.UnlockBits(data); }
    }

    // Reines Schwarz Weiss mit automatischer Schwelle (Otsu). Schrift wird immer schwarz auf weiss.
    static void Binarize(Bitmap bmp, int pad)
    {
        var rect = new Rectangle(0, 0, bmp.Width, bmp.Height);
        var data = bmp.LockBits(rect, ImageLockMode.ReadWrite, PixelFormat.Format32bppArgb);
        try
        {
            int n = data.Stride * bmp.Height;
            var px = new byte[n];
            Marshal.Copy(data.Scan0, px, 0, n);
            var hist = new int[256];
            int cnt = 0;
            for (int y = pad; y < bmp.Height - pad; y++)
                for (int x = pad; x < bmp.Width - pad; x++)
                {
                    int i = y * data.Stride + x * 4;
                    hist[Math.Max(px[i], Math.Max(px[i + 1], px[i + 2]))]++; cnt++;
                }
            if (cnt == 0) return;
            double sum = 0; for (int t = 0; t < 256; t++) sum += t * hist[t];
            double sumB = 0, best = -1; int wB = 0, th = 128;
            for (int t = 0; t < 256; t++)
            {
                wB += hist[t]; if (wB == 0) continue;
                int wF = cnt - wB; if (wF == 0) break;
                sumB += t * hist[t];
                double mB = sumB / wB, mF = (sum - sumB) / wF, v = (double)wB * wF * (mB - mF) * (mB - mF);
                if (v > best) { best = v; th = t; }
            }
            int bright = 0; for (int t = th + 1; t < 256; t++) bright += hist[t];
            bool textBright = bright < cnt / 2; // die Schrift ist die kleinere Fläche
            for (int y = 0; y < bmp.Height; y++)
                for (int x = 0; x < bmp.Width; x++)
                {
                    int i = y * data.Stride + x * 4;
                    bool inside = x >= pad && y >= pad && x < bmp.Width - pad && y < bmp.Height - pad;
                    int g = Math.Max(px[i], Math.Max(px[i + 1], px[i + 2]));
                    bool text = inside && (textBright ? g > th : g <= th);
                    byte v = text ? (byte)0 : (byte)255;
                    px[i] = px[i + 1] = px[i + 2] = v; px[i + 3] = 255;
                }
            Marshal.Copy(px, 0, data.Scan0, n);
        }
        finally { bmp.UnlockBits(data); }
    }

    static SoftwareBitmap ToSoftwareBitmap(Bitmap bmp)
    {
        var data = bmp.LockBits(new Rectangle(0, 0, bmp.Width, bmp.Height), ImageLockMode.ReadOnly, PixelFormat.Format32bppArgb);
        try
        {
            var bytes = new byte[bmp.Width * bmp.Height * 4];
            for (int y = 0; y < bmp.Height; y++)
                Marshal.Copy(data.Scan0 + y * data.Stride, bytes, y * bmp.Width * 4, bmp.Width * 4);
            var buf = CryptographicBuffer.CreateFromByteArray(bytes);
            return SoftwareBitmap.CreateCopyFromBuffer(buf, BitmapPixelFormat.Bgra8, bmp.Width, bmp.Height, BitmapAlphaMode.Premultiplied);
        }
        finally { bmp.UnlockBits(data); }
    }
}
