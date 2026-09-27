using System.Reflection;
using System.Text.Json.Nodes;
using System.Text.RegularExpressions;
using Microsoft.ML.OnnxRuntime;
using Microsoft.ML.OnnxRuntime.Tensors;

namespace CargoDeckScanner;

// Texterkennung mit PaddleOCR Modellen, gleiche Technik wie auf der Website.
// PP-OCRv4 findet die Textzeilen, PP-OCRv5 Englisch liest sie. Liest die Terminal Schrift viel besser als die
// Windows Texterkennung, auch rote Pyro Terminals, schräge Aufnahmen und kleine Auflösungen. Alles lokal auf dem PC.
// Bild kommt als BGR Bytes, damit dieser Teil ohne System.Drawing auskommt.
sealed class PaddleImage
{
    public int W, H;
    public byte[] Bgr;   // 3 Bytes je Pixel, Zeile für Zeile
    public PaddleImage(int w, int h, byte[] bgr) { W = w; H = h; Bgr = bgr; }

    // Bilinear lesen, Ergebnis B, G, R
    public void Sample(double x, double y, float[] o)
    {
        x = Math.Min(W - 1.001, Math.Max(0, x)); y = Math.Min(H - 1.001, Math.Max(0, y));
        int x0 = (int)x, y0 = (int)y; double fx = x - x0, fy = y - y0;
        int i00 = (y0 * W + x0) * 3, i10 = i00 + 3, i01 = i00 + W * 3, i11 = i01 + 3;
        for (int c = 0; c < 3; c++)
        {
            double a = Bgr[i00 + c] + (Bgr[i10 + c] - Bgr[i00 + c]) * fx;
            double b = Bgr[i01 + c] + (Bgr[i11 + c] - Bgr[i01 + c]) * fx;
            o[c] = (float)(a + (b - a) * fy);
        }
    }

    public PaddleImage Crop(double x, double y, double w, double h, double z)
    {
        int X = (int)Math.Max(0, Math.Round(x)), Y = (int)Math.Max(0, Math.Round(y));
        int cw = (int)Math.Min(W - X, Math.Round(w)), ch = (int)Math.Min(H - Y, Math.Round(h));
        int nw = Math.Max(1, (int)Math.Round(cw * z)), nh = Math.Max(1, (int)Math.Round(ch * z));
        var o = new byte[nw * nh * 3]; var px = new float[3];
        for (int j = 0; j < nh; j++)
            for (int i = 0; i < nw; i++)
            {
                Sample(X + (i + 0.5) / z - 0.5, Y + (j + 0.5) / z - 0.5, px);
                int k = (j * nw + i) * 3; o[k] = (byte)px[0]; o[k + 1] = (byte)px[1]; o[k + 2] = (byte)px[2];
            }
        return new PaddleImage(nw, nh, o);
    }
}

sealed class PaddleOcr
{
    const int DetMax = 2000, DetMin = 736, RecH = 48;
    const float DetTh = 0.3f, BoxTh = 0.5f, Unclip = 1.6f;

    record struct Box(double Cx, double Cy, double W, double H, double A, double Score);
    record struct Line(string T, int X, int Y, int W, int H, double C, int I);

    static PaddleOcr _inst;
    static readonly object Lock = new();
    public static string LoadError;

    readonly InferenceSession _det, _rec;
    readonly string[] _chars;

    // Einmal laden, Modelle stecken in der exe. Null, wenn es nicht geht, dann liest die Windows Texterkennung.
    public static PaddleOcr Get()
    {
        lock (Lock)
        {
            if (_inst != null || LoadError != null) return _inst;
            try { _inst = new PaddleOcr(Res("det.onnx"), Res("rec.onnx"), System.Text.Encoding.UTF8.GetString(Res("dict.txt"))); }
            catch (Exception e) { LoadError = e.Message; }
            return _inst;
        }
    }

    static byte[] Res(string name)
    {
        var asm = Assembly.GetExecutingAssembly();
        var full = asm.GetManifestResourceNames().FirstOrDefault(n => n.EndsWith(name, StringComparison.OrdinalIgnoreCase))
            ?? throw new Exception("Modell fehlt: " + name);
        using var s = asm.GetManifestResourceStream(full);
        using var ms = new MemoryStream(); s.CopyTo(ms); return ms.ToArray();
    }

    public PaddleOcr(byte[] det, byte[] rec, string dict)
    {
        var opt = new SessionOptions { GraphOptimizationLevel = GraphOptimizationLevel.ORT_ENABLE_ALL, IntraOpNumThreads = Math.Max(1, Math.Min(4, Environment.ProcessorCount - 1)) };
        _det = new InferenceSession(det, opt);
        _rec = new InferenceSession(rec, opt);
        var lines = dict.Replace("\r", "").Split('\n').ToList();
        if (lines.Count > 0 && lines[^1] == "") lines.RemoveAt(lines.Count - 1);
        _chars = new[] { "" }.Concat(lines).Append(" ").ToArray();
    }

    /* ---- Textzeilen finden (DB Modell) ---- */
    List<Box> Detect(PaddleImage img)
    {
        double r = 1;
        if (Math.Max(img.W, img.H) > DetMax) r = DetMax / (double)Math.Max(img.W, img.H);
        if (Math.Min(img.W, img.H) * r < DetMin) r = DetMin / (double)Math.Min(img.W, img.H);
        int W = Math.Max(32, (int)Math.Round(img.W * r / 32) * 32), H = Math.Max(32, (int)Math.Round(img.H * r / 32) * 32);
        double sx = img.W / (double)W, sy = img.H / (double)H;
        int plane = W * H;
        var t = new DenseTensor<float>(new[] { 1, 3, H, W });
        var buf = t.Buffer.Span; var px = new float[3];
        for (int y = 0; y < H; y++)
            for (int x = 0; x < W; x++)
            {
                img.Sample((x + 0.5) * sx - 0.5, (y + 0.5) * sy - 0.5, px);
                int o = y * W + x;   // BGR wie beim Training
                buf[o] = px[0] / 127.5f - 1; buf[plane + o] = px[1] / 127.5f - 1; buf[2 * plane + o] = px[2] / 127.5f - 1;
            }
        float[] pred;
        using (var res = _det.Run(new[] { NamedOnnxValue.CreateFromTensor(_det.InputMetadata.Keys.First(), t) }))
            pred = res.First().AsEnumerable<float>().ToArray();

        var bm = new bool[plane];
        for (int y = 0; y < H; y++)
            for (int x = 0; x < W; x++)
            {
                int o = y * W + x;
                bm[o] = pred[o] > DetTh || (x > 0 && pred[o - 1] > DetTh) || (y > 0 && pred[o - W] > DetTh) || (x > 0 && y > 0 && pred[o - W - 1] > DetTh);
            }
        var lab = new int[plane]; var stack = new int[plane]; var boxes = new List<Box>(); int id = 0;
        var pts = new List<int>();
        for (int p = 0; p < plane; p++)
        {
            if (!bm[p] || lab[p] != 0) continue;
            id++; int sp = 0; stack[sp++] = p; lab[p] = id; pts.Clear(); double sum = 0;
            while (sp > 0)
            {
                int q = stack[--sp]; pts.Add(q); sum += pred[q];
                int qx = q % W, qy = q / W;
                for (int dy = -1; dy <= 1; dy++)
                    for (int dx = -1; dx <= 1; dx++)
                    {
                        if (dx == 0 && dy == 0) continue;
                        int nx = qx + dx, ny = qy + dy;
                        if (nx < 0 || ny < 0 || nx >= W || ny >= H) continue;
                        int n = ny * W + nx;
                        if (bm[n] && lab[n] == 0) { lab[n] = id; stack[sp++] = n; }
                    }
            }
            if (pts.Count < 6 || sum / pts.Count < BoxTh) continue;
            // Ausrichtung über die Hauptachse, damit schräg fotografierte Terminals auch gehen
            double mx = 0, my = 0;
            foreach (var q in pts) { mx += q % W; my += q / W; }
            mx /= pts.Count; my /= pts.Count;
            double cxx = 0, cyy = 0, cxy = 0;
            foreach (var q in pts) { double ddx = q % W - mx, ddy = q / W - my; cxx += ddx * ddx; cyy += ddy * ddy; cxy += ddx * ddy; }
            double a = 0.5 * Math.Atan2(2 * cxy, cxx - cyy);
            if (a > Math.PI / 4) a -= Math.PI / 2; else if (a < -Math.PI / 4) a += Math.PI / 2;
            double ca = Math.Cos(a), sa = Math.Sin(a);
            (double u0, double u1, double v0, double v1) Ext(double c, double s)
            {
                double U0 = 1e18, U1 = -1e18, V0 = 1e18, V1 = -1e18;
                foreach (var q in pts)
                {
                    double ddx = q % W - mx, ddy = q / W - my, u = ddx * c + ddy * s, v = -ddx * s + ddy * c;
                    if (u < U0) U0 = u; if (u > U1) U1 = u; if (v < V0) V0 = v; if (v > V1) V1 = v;
                }
                return (U0, U1 + 1, V0, V1 + 1);
            }
            var (e0, e1, f0, f1) = Ext(ca, sa);
            if (e1 - e0 < (f1 - f0) * 1.6) { a = 0; ca = 1; sa = 0; (e0, e1, f0, f1) = Ext(ca, sa); }
            double bw = e1 - e0, bh = f1 - f0;
            if (Math.Min(bw, bh) < 3) continue;
            double d = bw * bh * Unclip / (2 * (bw + bh));
            double cu = (e0 + e1) / 2, cv = (f0 + f1) / 2;
            bw += 2 * d; bh += 2 * d;
            if (Math.Min(bw, bh) < 5) continue;
            double cx = mx + cu * ca - cv * sa, cy = my + cu * sa + cv * ca;
            boxes.Add(new Box(cx * sx, cy * sy, bw * Math.Sqrt(ca * sx * ca * sx + sa * sy * sa * sy), bh * Math.Sqrt(sa * sx * sa * sx + ca * sy * ca * sy), Math.Atan2(sa * sy, ca * sx), sum / pts.Count));
        }
        return boxes.OrderBy(b => b.Cy - b.H / 2).ThenBy(b => b.Cx).ToList();
    }

    /* ---- Zeilen lesen (CTC) ---- */
    (string t, double c)[] Recognize(PaddleImage img, List<Box> boxes, int batch = 8)
    {
        var outp = new (string, double)[boxes.Count];
        var order = Enumerable.Range(0, boxes.Count).OrderBy(i => boxes[i].W / boxes[i].H).ToList();
        var px = new float[3];
        for (int k = 0; k < order.Count; k += batch)
        {
            var ids = order.Skip(k).Take(batch).ToList();
            double ratio = Math.Max(320.0 / RecH, ids.Max(i => boxes[i].W / boxes[i].H));
            int IW = Math.Min(3200, (int)Math.Ceiling(RecH * ratio)), plane = IW * RecH;
            var t = new DenseTensor<float>(new[] { ids.Count, 3, RecH, IW });
            var buf = t.Buffer.Span;
            for (int n = 0; n < ids.Count; n++)
            {
                var b = boxes[ids[n]];
                int ww = Math.Max(1, Math.Min(IW, (int)Math.Ceiling(RecH * b.W / b.H)));
                double ca = Math.Cos(b.A), sa = Math.Sin(b.A); int bas = n * 3 * plane;
                for (int y = 0; y < RecH; y++)
                    for (int x = 0; x < ww; x++)
                    {
                        double u = ((x + 0.5) / ww - 0.5) * b.W, v = ((y + 0.5) / RecH - 0.5) * b.H;
                        img.Sample(b.Cx + u * ca - v * sa, b.Cy + u * sa + v * ca, px);
                        int o = bas + y * IW + x;
                        buf[o] = px[0] / 127.5f - 1; buf[plane + o] = px[1] / 127.5f - 1; buf[2 * plane + o] = px[2] / 127.5f - 1;
                    }
            }
            using var res = _rec.Run(new[] { NamedOnnxValue.CreateFromTensor(_rec.InputMetadata.Keys.First(), t) });
            var ot = res.First().AsTensor<float>();
            int T = ot.Dimensions[1], C = ot.Dimensions[2];
            var p = ot.ToArray();
            for (int n = 0; n < ids.Count; n++)
            {
                var sb = new System.Text.StringBuilder(); double conf = 0; int cnt = 0, last = 0;
                for (int s = 0; s < T; s++)
                {
                    int best = 0; float bv = -1; int off = (n * T + s) * C;
                    for (int c = 0; c < C; c++) if (p[off + c] > bv) { bv = p[off + c]; best = c; }
                    if (best != 0 && best != last) { if (best < _chars.Length) sb.Append(_chars[best]); conf += bv; cnt++; }
                    last = best;
                }
                outp[ids[n]] = (sb.ToString(), cnt > 0 ? conf / cnt : 0);
            }
        }
        return outp;
    }

    // Preis wie "01.8.050/SCU" (¤ als 0 gelesen) aufräumen: ein Preis beginnt nie mit 0
    static readonly Regex Cjk = new(@"[　-鿿＀-￯]");
    static readonly Regex PriceRe = new(@"^[^0-9]{0,2}?([0-9][0-9.,' ]*)(\s*/\s*[S5$][CcGgOo0][UuVv0l1]?.*)$");
    static readonly Regex SuffixRe = new(@"^(\s*/\s*)[S5$][CcGgOo0][A-Za-z0-9]{0,2}");
    public static string Tidy(string t)
    {
        t = Cjk.Replace(t, "").Trim();
        var m = PriceRe.Match(t);
        if (m.Success)
        {
            var n = Regex.Replace(m.Groups[1].Value, "[^0-9]", "").TrimStart('0');
            if (n.Length > 0) t = n + SuffixRe.Replace(m.Groups[2].Value, "$1SCU");
        }
        return t;
    }

    static List<Line> ToLines(List<Box> boxes, (string t, double c)[] texts, double ox = 0, double oy = 0, double z = 1)
    {
        var lines = new List<Line>();
        for (int i = 0; i < boxes.Count; i++)
        {
            var (tx, c) = texts[i];
            if (string.IsNullOrEmpty(tx) || c < 0.35) continue;
            var t = Tidy(tx); if (t.Length == 0) continue;
            var b = boxes[i];
            lines.Add(new Line(t, (int)Math.Round((b.Cx - b.W / 2) / z + ox), (int)Math.Round((b.Cy - b.H / 2) / z + oy), (int)Math.Round(b.W / z), (int)Math.Round(b.H / z), Math.Round(c, 2), i));
        }
        return lines;
    }

    static readonly Regex TermRe = new(@"SHOP|INVENT|QUANTIT|CARGO|DEMAND|COMMODIT|BALANCE|MARKET|STOCK", RegexOptions.IgnoreCase);
    static readonly Regex QtyRe = new(@"/\s*S|SC[UO0]", RegexOptions.IgnoreCase);
    static readonly Regex WordRe = new(@"[A-Za-z]{5,}");

    /* Ganzer Ablauf: ganzes Bild, dann das Terminal vergrössert, dann Preise und Mengen einzeln.
       Ergebnis im gleichen Format wie die Website und die alte Texterkennung. */
    public JsonObject Read(PaddleImage img)
    {
        var passes = new List<(string name, List<Line> lines)>();
        var b1 = Detect(img);
        var l1 = ToLines(b1, Recognize(img, b1));
        passes.Add(("paddle", l1));
        var hits = l1.Where(l => TermRe.IsMatch(l.T)).ToList();
        if (hits.Count >= 3)
        {
            double x1 = hits.Min(l => l.X), y1 = hits.Min(l => l.Y), x2 = hits.Max(l => l.X + l.W), y2 = hits.Max(l => l.Y + l.H);
            double X = Math.Max(0, x1 - img.W * .08), Y = Math.Max(0, y1 - img.H * .08);
            double W = Math.Min(img.W, x2 + img.W * .08) - X, H = Math.Min(img.H, y2 + img.H * .08) - Y;
            if (W > 100 && H > 100 && W * H < img.W * (double)img.H * .8)
            {
                double z = Math.Max(1, Math.Min(2.5, 1600 / Math.Max(W, H)));
                var c = img.Crop(X, Y, W, H, z);
                var b2 = Detect(c);
                passes.Add(("paddle-t", ToLines(b2, Recognize(c, b2), Math.Round(X), Math.Round(Y), z)));
            }
        }
        var pi = l1.Where(l => QtyRe.IsMatch(l.T) && !WordRe.IsMatch(l.T)).ToList();
        if (pi.Count > 0)
        {
            var pb = pi.Select(l => { var b = b1[l.I]; return b with { W = b.W + b.H * 0.6, H = b.H * 0.9 }; }).ToList();
            var l3 = ToLines(pb, Recognize(img, pb));
            var repl = new Dictionary<int, Line>();
            foreach (var n in l3) repl[pi[n.I].I] = n;
            passes.Add(("paddle-p", l1.Select(l => repl.TryGetValue(l.I, out var n) ? n : l).ToList()));
        }
        var arr = new JsonArray();
        foreach (var (name, lines) in passes)
        {
            var la = new JsonArray();
            foreach (var l in lines) la.Add(new JsonObject { ["t"] = l.T, ["x"] = l.X, ["y"] = l.Y, ["w"] = l.W, ["h"] = l.H, ["c"] = l.C });
            arr.Add(new JsonObject { ["name"] = name, ["w"] = img.W, ["h"] = img.H, ["lines"] = la });
        }
        return new JsonObject { ["ok"] = true, ["engine"] = "paddle", ["passes"] = arr };
    }
}
