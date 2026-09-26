#!/usr/bin/env python3
# Cargo Deck Scanner für Linux
# Liest das Star Citizen Handelsterminal per Texterkennung (Tesseract) und schickt die Preise an Cargo Deck.
# Alles läuft lokal, an die Seite gehen nur der erkannte Text und ein verkleinertes Bild.
import base64, io, json, math, os, queue, re, shutil, socket, struct, subprocess, sys, tempfile, threading, time, urllib.request, wave
from concurrent.futures import ThreadPoolExecutor

VERSION = "1.4.1"
APP = "cargodeck-scanner"
CODE_RE = re.compile(r"^[A-Z2-9]{12}$")
TERMINAL_WORDS = re.compile(r"COMMODIT|SHOP INVENTOR|LOCAL MARKET|IN DEMAND|YOUR INVENTOR|SHOP QUANTIT", re.I)
TERM_WORD = re.compile(r"SCU|INVENT|QUANTIT|CARGO|DEMAND|COMMODIT|BALANCE|MARKET|SHOP", re.I)
PRICE_LINE = re.compile(r"\S\s*/\s*[S5$s][CcGgOo]?|[¤Ä]\s*\S")

CONF_DIR = os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"), "cargodeck")
CONF_FILE = os.path.join(CONF_DIR, "scanner.json")
RUN_DIR = os.environ.get("XDG_RUNTIME_DIR") or tempfile.gettempdir()
SOCK = os.path.join(RUN_DIR, APP + "-" + str(os.getuid()) + ".sock")

# ---------------------------------------------------------------- Sprache
TEXT = {
    "title": ("Cargo Deck Scanner", "Cargo Deck Scanner"),
    "site": ("Website", "Website"),
    "code": ("Code von der Website (Einstellungen)", "Code from the website (settings)"),
    "mode": ("Scannen", "Scanning"),
    "m_hot": ("Per Tastenkürzel", "By hotkey"),
    "m_auto": ("Automatisch alle", "Automatically every"),
    "sec": ("Sekunden", "seconds"),
    "k_scan": ("Scannen", "Scan"),
    "k_auto": ("Automatik an/aus", "Auto on/off"),
    "record": ("Taste setzen", "Set key"),
    "press": ("Tasten drücken…", "Press keys…"),
    "sounds": ("Töne", "Sounds"),
    "notify": ("Meldungen", "Notifications"),
    "autostart": ("Mit dem System starten", "Start with the system"),
    "start": ("Start", "Start"),
    "stop": ("Stopp", "Stop"),
    "save": ("Speichern", "Save"),
    "testshot": ("Screenshot testen", "Test screenshot"),
    "shot": ("Screenshot", "Screenshot"),
    "auto_sel": ("Automatisch wählen", "Pick automatically"),
    "stopped": ("Gestoppt", "Stopped"),
    "ready": ("Bereit", "Ready"),
    "running_hot": ("Läuft, {k} scannt", "Running, {k} scans"),
    "running_auto": ("Läuft, automatisch alle {n} Sekunden", "Running, automatically every {n} seconds"),
    "reading": ("Lese Terminal…", "Reading terminal…"),
    "bad_url": ("Website Adresse prüfen", "Check the website address"),
    "bad_code": ("Code fehlt oder ist falsch, 12 Zeichen von der Website", "Code missing or wrong, 12 characters from the website"),
    "no_tess": ("Tesseract fehlt. Bitte install.sh ausführen oder tesseract installieren.", "Tesseract is missing. Run install.sh or install tesseract."),
    "no_shot": ("Kein Screenshot möglich. Unter Wayland grim, spectacle oder gnome-screenshot installieren.", "No screenshot possible. On Wayland install grim, spectacle or gnome-screenshot."),
    "busy": ("Noch beschäftigt, einen Moment", "Still busy, one moment"),
    "sent_ok": ("{n} Preise erkannt {st}", "{n} prices recognized {st}"),
    "sent_look": ("{n} Preise erkannt {st}, schau auf die Seite", "{n} prices recognized {st}, check the website"),
    "last": ("Letzter Scan {t}, {n} Preise", "Last scan {t}, {n} prices"),
    "no_term": ("Kein Terminal erkannt", "No terminal recognized"),
    "send_fail": ("Senden fehlgeschlagen", "Sending failed"),
    "unreach": ("Seite nicht erreichbar, Adresse prüfen", "Website not reachable, check the address"),
    "ocr_fail": ("Texterkennung ging nicht", "Text recognition failed"),
    "auto_on": ("Automatik an, alle {n} Sekunden", "Auto on, every {n} seconds"),
    "auto_off": ("Automatik aus", "Auto off"),
    "saved": ("Gespeichert", "Saved"),
    "shot_ok": ("Screenshot mit {m}, {w} × {h} Pixel", "Screenshot with {m}, {w} × {h} pixels"),
    "hk_x11": ("Tastenkürzel aktiv", "Hotkeys active"),
    "hk_none": ("Globale Tastenkürzel gehen hier nicht direkt. Lege in den Systemeinstellungen ein Tastenkürzel an mit dem Befehl:", "Global hotkeys don't work directly here. Create a keyboard shortcut in your system settings with the command:"),
    "hk_hint": ("Tipp: Unter Wayland in den Systemeinstellungen ein Tastenkürzel mit dem Befehl anlegen:", "Tip: on Wayland, create a keyboard shortcut in the system settings with the command:"),
    "log": ("Verlauf", "Log"),
    "lang": ("Sprache", "Language"),
    "already": ("Der Scanner läuft schon.", "The scanner is already running."),
    "started": ("Gestartet", "Started"),
}
LANG = "de"
def T(_key, **kw):
    s = TEXT.get(_key, (_key, _key))[0 if LANG == "de" else 1]
    return s.format(**kw) if kw else s

# ---------------------------------------------------------------- Einstellungen
DEFAULTS = {"url": "https://cargodeck.onrender.com", "code": "", "mode": "hotkey", "interval": 5,
            "scan_key": "<ctrl>+ö", "auto_key": "<ctrl>+ä", "sounds": True, "notify": True, "autostart": False,
            "shot": "auto", "lang": ""}

def load_conf():
    c = dict(DEFAULTS)
    try:
        with open(CONF_FILE, encoding="utf-8") as f: c.update(json.load(f))
    except Exception: pass
    c["interval"] = max(3, min(60, int(c.get("interval") or 5)))
    return c

def save_conf(c):
    os.makedirs(CONF_DIR, exist_ok=True)
    with open(CONF_FILE, "w", encoding="utf-8") as f: json.dump(c, f, indent=2, ensure_ascii=False)
    set_autostart(c.get("autostart"))

def set_autostart(on):
    d = os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"), "autostart")
    f = os.path.join(d, APP + ".desktop")
    try:
        if on:
            os.makedirs(d, exist_ok=True)
            with open(f, "w") as fh:
                fh.write(f"[Desktop Entry]\nType=Application\nName=Cargo Deck Scanner\nExec={sys.executable} {os.path.abspath(__file__)} --minimized\nIcon={APP}\nX-GNOME-Autostart-enabled=true\n")
        elif os.path.exists(f): os.remove(f)
    except Exception: pass

# ---------------------------------------------------------------- Töne
def make_wav(notes, vol=0.07, rate=44100):
    total = max(s + l for _, s, l in notes) + 0.03
    n = int(total * rate); buf = [0.0] * n
    for f, s, l in notes:
        s0, cnt = int(s * rate), int(l * rate)
        for i in range(min(cnt, n - s0)):
            t = i / rate
            env = min(1, t / 0.008) * math.exp(-t * 18 / max(l, 0.05) * 0.35) * min(1, (cnt - i) / (0.02 * rate))
            buf[s0 + i] += env * (math.sin(2 * math.pi * f * t) + 0.25 * math.sin(4 * math.pi * f * t))
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate)
        w.writeframes(b"".join(struct.pack("<h", max(-32767, min(32767, int(v * vol * 32767)))) for v in buf))
    return out.getvalue()

SOUNDS = {"on": [(660, 0, .09), (880, .07, .14)], "off": [(740, 0, .09), (554, .07, .14)],
          "ok": [(784, 0, .08), (988, .06, .08), (1319, .12, .18)], "err": [(330, 0, .16)]}
_sound_files = {}
def play(kind):
    player = next((p for p in ("pw-play", "paplay", "aplay") if shutil.which(p)), None)
    if not player: return
    try:
        if kind not in _sound_files:
            fd, path = tempfile.mkstemp(prefix="cds-", suffix=".wav"); os.close(fd)
            with open(path, "wb") as f: f.write(make_wav(SOUNDS[kind]))
            _sound_files[kind] = path
        args = [player, _sound_files[kind]] if player != "aplay" else [player, "-q", _sound_files[kind]]
        subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception: pass

def notify(text):
    if shutil.which("notify-send"):
        try: subprocess.Popen(["notify-send", "-a", "Cargo Deck Scanner", "-t", "3500", "Cargo Deck", text], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception: pass

# ---------------------------------------------------------------- Screenshot
def _run_png(cmd, use_file=False):
    if use_file:
        fd, path = tempfile.mkstemp(prefix="cds-", suffix=".png"); os.close(fd)
        try:
            subprocess.run([a.replace("{file}", path) for a in cmd], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15, check=True)
            from PIL import Image
            im = Image.open(path); im.load(); return im
        finally:
            try: os.remove(path)
            except Exception: pass
    r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=15, check=True)
    from PIL import Image
    im = Image.open(io.BytesIO(r.stdout)); im.load(); return im

def _pil_grab():
    from PIL import ImageGrab
    return ImageGrab.grab()

SHOT_METHODS = [
    # Name, nötiges Programm, Aufruf, nur Wayland
    ("grim", "grim", lambda: _run_png(["grim", "-t", "png", "-"]), True),
    ("spectacle", "spectacle", lambda: _run_png(["spectacle", "-b", "-n", "-f", "-o", "{file}"], True), True),
    ("gnome-screenshot", "gnome-screenshot", lambda: _run_png(["gnome-screenshot", "-f", "{file}"], True), True),
    ("flameshot", "flameshot", lambda: _run_png(["flameshot", "full", "-r"]), False),
    ("x11", None, _pil_grab, False),
    ("maim", "maim", lambda: _run_png(["maim"]), False),
    ("scrot", "scrot", lambda: _run_png(["scrot", "-o", "{file}"], True), False),
    ("import", "import", lambda: _run_png(["import", "-window", "root", "png:-"]), False),
]
_shot_ok = None
def screenshot(pref="auto"):
    """Ganzen Bildschirm aufnehmen. Unter Wayland über die Werkzeuge des Desktops, unter X11 direkt."""
    global _shot_ok
    wayland = bool(os.environ.get("WAYLAND_DISPLAY"))
    order = [m for m in SHOT_METHODS if (m[0] == pref if pref != "auto" else True)]
    if pref == "auto":
        if _shot_ok: order = [m for m in SHOT_METHODS if m[0] == _shot_ok] + [m for m in SHOT_METHODS if m[0] != _shot_ok]
        elif not wayland: order = [m for m in SHOT_METHODS if not m[3]]
    last = None
    for name, need, fn, _ in order:
        if need and not shutil.which(need): continue
        if name == "x11" and not os.environ.get("DISPLAY"): continue
        try:
            im = fn().convert("RGB")
            if im.width < 200 or im.height < 200: continue
            # komplett schwarz heisst meist: Wayland verweigert die Aufnahme
            if max(im.resize((32, 18)).convert("L").tobytes()) < 8: continue
            _shot_ok = name
            return im, name
        except Exception as e: last = e
    raise RuntimeError(T("no_shot") + (f" ({last})" if last else ""))

# ---------------------------------------------------------------- Texterkennung
def tesseract_ok():
    return bool(shutil.which("tesseract"))

def _gray(im, mx=True, invert=False, k=1.0):
    """Hellster Farbkanal (rote und orange Schrift bleibt hell) oder Grau, optional umgedreht und mit mehr Kontrast."""
    from PIL import ImageChops, ImageOps
    if mx:
        r, g, b = im.split(); g2 = ImageChops.lighter(ImageChops.lighter(r, g), b)
    else:
        g2 = im.convert("L")
    if invert: g2 = ImageOps.invert(g2)
    if k != 1.0: g2 = g2.point(lambda v: max(0, min(255, int((v - 128) * k + 128))))
    return g2

def _otsu(g):
    h = g.histogram(); tot = sum(h)
    s = sum(i * h[i] for i in range(256)); sb = 0; wb = 0; best = -1; th = 128
    for t in range(256):
        wb += h[t]
        if wb == 0: continue
        wf = tot - wb
        if wf == 0: break
        sb += t * h[t]
        mb, mf = sb / wb, (s - sb) / wf
        v = wb * wf * (mb - mf) ** 2
        if v > best: best, th = v, t
    bright = sum(h[th + 1:])
    return th, bright < tot / 2

def _tess(img, psm=11):
    buf = io.BytesIO(); img.save(buf, "PNG")
    env = dict(os.environ, OMP_THREAD_LIMIT="1")
    r = subprocess.run(["tesseract", "stdin", "stdout", "-l", "eng", "--psm", str(psm), "tsv"], input=buf.getvalue(),
                       stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=90, env=env)
    return r.stdout.decode("utf-8", "replace")

def _tsv_lines(tsv, scale, ox, oy):
    groups = {}
    for row in tsv.split("\n")[1:]:
        c = row.split("\t")
        if len(c) < 12 or c[0] != "5": continue
        t = c[11].strip()
        try: conf = float(c[10])
        except ValueError: conf = 0
        # Preise in der Terminal Schrift bekommen oft sehr tiefe Sicherheit, die trotzdem behalten
        if not t or (conf < 20 and not re.search(r"\d.*/\s*[S5$]", t, re.I) and not re.fullmatch(r"[\d.,]{3,}", t)): continue
        k = (c[2], c[3], c[4]); x, y, w, h = int(c[6]), int(c[7]), int(c[8]), int(c[9])
        g = groups.get(k)
        if not g: groups[k] = {"t": t, "x1": x, "y1": y, "x2": x + w, "y2": y + h}
        else:
            g["t"] += " " + t; g["x1"] = min(g["x1"], x); g["y1"] = min(g["y1"], y); g["x2"] = max(g["x2"], x + w); g["y2"] = max(g["y2"], y + h)
    return [{"t": g["t"], "x": round(g["x1"] / scale + ox), "y": round(g["y1"] / scale + oy),
             "w": round((g["x2"] - g["x1"]) / scale), "h": round((g["y2"] - g["y1"]) / scale)} for g in groups.values()]

def _read(src, box, scale, mx=True, invert=True, k=1.0, binar=False, psm=11):
    from PIL import Image
    x, y, w, h = box
    crop = src.crop((x, y, x + w, y + h))
    nw, nh = max(1, int(w * scale)), max(1, int(h * scale))
    crop = crop.resize((nw, nh), Image.BICUBIC)
    g = _gray(crop, mx=mx, invert=invert and not binar, k=k)
    if binar:
        th, text_bright = _otsu(g)
        g = g.point(lambda v: 0 if (v > th) == text_bright else 255)
        pad = max(8, nh // 4)
        canvas = Image.new("L", (nw + pad * 2, nh + pad * 2), 255); canvas.paste(g, (pad, pad)); g = canvas
        lines = _tsv_lines(_tess(g, psm), scale, x - pad / scale, y - pad / scale)
    else:
        lines = _tsv_lines(_tess(g, psm), scale, x, y)
    return lines

def _find_terminal(lines, W, H):
    hits = [l for l in lines if TERM_WORD.search(l["t"])]
    if len(hits) < 3: return None
    x1 = min(l["x"] for l in hits); y1 = min(l["y"] for l in hits)
    x2 = max(l["x"] + l["w"] for l in hits); y2 = max(l["y"] + l["h"] for l in hits)
    px, py = int(W * .06), int(H * .05)
    r = (max(0, x1 - px), max(0, y1 - py), min(W, x2 + px), min(H, y2 + py))
    w, h = r[2] - r[0], r[3] - r[1]
    if w < W * .2 or h < H * .2 or w * h > W * H * .85: return None
    return (r[0], r[1], w, h)

def _price_regions(lines, W, H):
    boxes = []
    for l in lines:
        if not PRICE_LINE.search(l["t"]) or not (4 < l["h"] < H / 8) or l["w"] > W / 3: continue
        r = [max(0, l["x"] - l["h"]), max(0, l["y"] - l["h"] // 3), l["w"] + l["h"] * 2, l["h"] + l["h"] * 2 // 3]
        r[2] = min(r[2], W - r[0]); r[3] = min(r[3], H - r[1])
        for b in boxes:
            if b[0] < r[0] + r[2] and r[0] < b[0] + b[2] and b[1] < r[1] + r[3] and r[1] < b[1] + b[3] and abs((b[1] + b[3] / 2) - (r[1] + r[3] / 2)) < max(b[3], r[3]) / 2:
                nx, ny = min(b[0], r[0]), min(b[1], r[1]); b[2] = max(b[0] + b[2], r[0] + r[2]) - nx; b[3] = max(b[1] + b[3], r[1] + r[3]) - ny; b[0], b[1] = nx, ny
                break
        else: boxes.append(r)
    return [tuple(b) for b in boxes if b[2] > 8 and b[3] > 6][:24]

def _overlap(a, b):
    x1, x2 = max(a["x"], b["x"]), min(a["x"] + a["w"], b["x"] + b["w"])
    y1, y2 = max(a["y"], b["y"]), min(a["y"] + a["h"], b["y"] + b["h"])
    return x2 > x1 and y2 > y1 and (y2 - y1) > min(a["h"], b["h"]) * .4

def run_ocr(shots, quick=False):
    """Mehrere Durchgänge, gleiches Format wie die Windows App, damit die Website es gleich auswertet."""
    src = shots[0]; W, H = src.size
    zoom = lambda sw, z: max(.5, min(z, 3000 / max(sw, 1)))
    plan = [("rechts", (W // 2, 0, W - W // 2, H), 2, True, True, 1.0),
            ("rechts-k", (int(W * .55), 0, W - int(W * .55), H), 2.4, True, True, 1.7),
            ("links", (0, 0, W // 2, H), 2, True, True, 1.0),
            ("invert", (0, 0, W, H), 1.6 if W < 2000 else 1, True, True, 1.0),
            ("normal", (0, 0, W, H), 1.6 if W < 2000 else 1, False, False, 1.0)]
    if quick: plan = [plan[3]]
    passes = []
    with ThreadPoolExecutor(max_workers=min(4, os.cpu_count() or 2)) as ex:
        futs = [(p[0], ex.submit(_read, src, p[1], zoom(p[1][2], p[2]), p[3], p[4], p[5])) for p in plan]
        for name, f in futs: passes.append((name, f.result()))
        if not quick:
            allLines = [l for _, ls in passes for l in ls]
            term = _find_terminal(allLines, W, H)
            if term:
                x, y, w, h = term; half = w // 2
                tf = [(n, ex.submit(_read, src, b, min(3, 2600 / max(b[2], b[3])), True, True, 1.6))
                      for n, b in (("terminal-l", (x, y, half, h)), ("terminal-r", (x + half, y, w - half, h)))]
                for n, f in tf: passes.append((n, f.result()))
            regions = _price_regions([l for _, ls in passes for l in ls], W, H)
            if regions:
                tpl = [l for n, ls in passes if n.startswith("terminal") for l in ls] or max((ls for n, ls in passes if n in ("invert", "normal")), key=len)
                for i, img in enumerate(shots):
                    if img.size != src.size: continue
                    jobs = [ex.submit(_read, img, r, max(2, min(8, 64 / max(1, r[3] / 1.6))), True, False, 1.0, True, 7) for r in regions]
                    fresh = []
                    for f in jobs:
                        got = f.result()
                        if not got: continue
                        got.sort(key=lambda g: g["x"])
                        x1 = min(g["x"] for g in got); y1 = min(g["y"] for g in got)
                        fresh.append({"t": " ".join(g["t"] for g in got), "x": x1, "y": y1, "w": max(g["x"] + g["w"] for g in got) - x1, "h": max(g["y"] + g["h"] for g in got) - y1})
                    if fresh:
                        merged = [l for l in tpl if not any(_overlap(l, f) for f in fresh)] + fresh
                        merged.sort(key=lambda l: (l["y"], l["x"]))
                        passes.append((f"preise-{i + 1}", merged))
    return {"ok": True, "passes": [{"name": n, "w": W, "h": H, "lines": ls} for n, ls in passes], "shots": len(shots)}

def jpeg64(im):
    from PIL import Image
    s = min(1.0, 1920 / im.width)
    small = im.resize((int(im.width * s), int(im.height * s)), Image.BILINEAR) if s < 1 else im
    buf = io.BytesIO(); small.save(buf, "JPEG", quality=72)
    return base64.b64encode(buf.getvalue()).decode()

def fingerprint(im):
    return im.resize((40, 24)).convert("L").point(lambda v: v // 16).tobytes()

# ---------------------------------------------------------------- Netz
def post(url, body, timeout=40):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"content-type": "application/json", "user-agent": f"CargoDeckScanner-Linux/{VERSION}"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, r.read().decode("utf-8", "replace")

# ---------------------------------------------------------------- Tastenkürzel
class Hotkeys:
    """Globale Tastenkürzel über pynput (X11 und Spiele unter XWayland). Unter reinem Wayland über den Befehl mit --scan."""
    def __init__(self, on_scan, on_auto):
        self.on_scan, self.on_auto, self.listener, self.ok = on_scan, on_auto, None, False
    def start(self, scan_key, auto_key):
        self.stop()
        try:
            from pynput import keyboard
            if not os.environ.get("DISPLAY"): return False
            self.listener = keyboard.GlobalHotKeys({scan_key: self.on_scan, auto_key: self.on_auto})
            self.listener.start(); self.ok = True
        except Exception:
            self.listener, self.ok = None, False
        return self.ok
    def stop(self):
        try:
            if self.listener: self.listener.stop()
        except Exception: pass
        self.listener, self.ok = None, False

def pretty_key(k):
    return "+".join(p.strip("<>").capitalize() if p.startswith("<") else p.upper() for p in k.split("+"))

# ---------------------------------------------------------------- Befehle von aussen (Tastenkürzel unter Wayland)
def send_command(cmd):
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM); s.settimeout(2); s.connect(SOCK); s.sendall(cmd.encode()); s.close(); return True
    except Exception: return False

def serve_commands(handler):
    try:
        if os.path.exists(SOCK): os.remove(SOCK)
        srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM); srv.bind(SOCK); os.chmod(SOCK, 0o600); srv.listen(4)
    except Exception: return
    def loop():
        while True:
            try:
                c, _ = srv.accept(); data = c.recv(64).decode(errors="ignore").strip(); c.close()
                if data: handler(data)
            except Exception: time.sleep(.2)
    threading.Thread(target=loop, daemon=True).start()

# ---------------------------------------------------------------- Kern: scannen und senden
class Scanner:
    def __init__(self, conf, ui):
        self.c, self.ui = conf, ui
        self.running = False; self.busy = False; self.last_print = None; self.next_auto = 0; self.next_ping = 0
        self.hot = Hotkeys(lambda: self.trigger("scan"), lambda: self.trigger("toggle"))
        threading.Thread(target=self.loop, daemon=True).start()

    def trigger(self, what):
        if what == "scan": threading.Thread(target=self.scan, args=(False,), daemon=True).start()
        elif what == "toggle":
            self.c["mode"] = "hotkey" if self.c["mode"] == "auto" else "auto"
            on = self.c["mode"] == "auto"
            self.ui.event("mode", self.c["mode"])
            self.ui.log(T("auto_on", n=self.c["interval"]) if on else T("auto_off"))
            if self.c["sounds"]: play("on" if on else "off")
            if self.c["notify"]: notify(T("auto_on", n=self.c["interval"]) if on else T("auto_off"))
            self.next_auto = 0
        elif what == "show": self.ui.event("show", None)

    def start(self):
        if not re.match(r"^https?://[^/]+", self.c["url"]): self.ui.state(T("bad_url"), "bad"); return False
        if not CODE_RE.match(self.c["code"]): self.ui.state(T("bad_code"), "bad"); return False
        if not tesseract_ok(): self.ui.state(T("no_tess"), "bad"); return False
        self.running = True; self.next_auto = 0; self.next_ping = 0
        self.ui.event("running", True)
        hk = self.hot.start(self.c["scan_key"], self.c["auto_key"])
        self.ui.log(T("started") + ("" if not hk else ", " + T("hk_x11") + " " + pretty_key(self.c["scan_key"])))
        if not hk: self.ui.log(T("hk_none") + f"  {APP} --scan")
        self.show_running()
        if self.c["sounds"]: play("on")
        return True

    def stop(self):
        self.running = False; self.hot.stop()
        self.ui.event("running", False)
        self.ui.state(T("stopped"), "muted"); self.ui.log(T("stopped"))
        if self.c["sounds"]: play("off")

    def show_running(self):
        self.ui.state(T("running_auto", n=self.c["interval"]) if self.c["mode"] == "auto" else T("running_hot", k=pretty_key(self.c["scan_key"])), "good")

    def loop(self):
        while True:
            time.sleep(.25)
            if not self.running: continue
            now = time.time()
            if now >= self.next_ping:
                self.next_ping = now + 60
                threading.Thread(target=self.ping, daemon=True).start()
            if self.c["mode"] == "auto" and not self.busy and now >= self.next_auto:
                self.next_auto = now + self.c["interval"]
                self.scan(True)

    def ping(self):
        try: post(self.c["url"] + "/api/pair/ping", {"pair": self.c["code"]}, 10)
        except Exception: pass

    def scan(self, auto):
        if self.busy:
            if not auto: self.ui.log(T("busy"))
            return
        if not self.running and not auto:
            if not self.start(): return
        self.busy = True
        try:
            try: im, how = screenshot(self.c.get("shot", "auto"))
            except Exception as e:
                self.ui.log(str(e))
                if not auto: self.ui.state(T("no_shot"), "bad"); play("err") if self.c["sounds"] else None
                return
            if auto:
                fp = fingerprint(im)
                if fp == self.last_print: return
                self.last_print = fp
                # erst kurz schauen, ob überhaupt ein Terminal zu sehen ist
                quick = run_ocr([im], quick=True)
                txt = " ".join(l["t"] for p in quick["passes"] for l in p["lines"])
                if not TERMINAL_WORDS.search(txt): return
            else:
                self.ui.state(T("reading"), "warn")
            shots = [im]
            for _ in range(1 if auto else 2):
                time.sleep(.35)
                try: shots.append(screenshot(self.c.get("shot", "auto"))[0])
                except Exception: break
            try: ocr = run_ocr(shots)
            except Exception as e:
                self.ui.log(T("ocr_fail") + f" {e}")
                if not auto: self.ui.state(T("ocr_fail"), "bad")
                return
            body = {"pair": self.c["code"], "auto": auto, "ocr": ocr, "image": jpeg64(im)}
            try: status, raw = post(self.c["url"] + "/api/pair/scan", body)
            except Exception as e:
                self.ui.log(T("send_fail") + f" {e}"); self.ui.state(T("unreach"), "bad")
                if not auto:
                    if self.c["sounds"]: play("err")
                    if self.c["notify"]: notify(T("send_fail"))
                return
            try: r = json.loads(raw)
            except Exception: r = {}
            rows = int(r.get("rows") or 0)
            if rows > 0:
                st = (r.get("station") or "").split(" > ")[-1]
                self.ui.log(T("sent_ok", n=rows, st=st).strip())
                self.ui.state(T("last", t=time.strftime("%H:%M"), n=rows), "good")
                if self.c["sounds"]: play("ok")
                if self.c["notify"]: notify(T("sent_look", n=rows, st=st).replace("  ", " "))
            elif not auto:
                n = r.get("error") or r.get("note") or T("no_term")
                self.ui.log(n); self.ui.state(n, "warn")
                if self.c["sounds"]: play("err")
        finally:
            self.busy = False
            if self.running and not auto: pass

# ---------------------------------------------------------------- Oberfläche
C = {"bg": "#0c1119", "panel": "#141c28", "line": "#243142", "text": "#e6edf5", "muted": "#8a9bb0", "acc": "#35d6cc", "good": "#4ade80", "warn": "#fbbf24", "bad": "#f87171"}

class App:
    def __init__(self, conf, minimized=False):
        import tkinter as tk
        from tkinter import ttk
        self.tk, self.c = tk, conf
        self.q = queue.Queue()
        self.root = root = tk.Tk()
        root.title(T("title")); root.configure(bg=C["bg"]); root.geometry("560x720"); root.minsize(480, 560)
        try:
            icon = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cargodeck-scanner.png")
            if os.path.exists(icon): root.iconphoto(True, tk.PhotoImage(file=icon))
        except Exception: pass
        st = ttk.Style(root)
        try: st.theme_use("clam")
        except Exception: pass
        st.configure(".", background=C["bg"], foreground=C["text"], fieldbackground=C["panel"], bordercolor=C["line"], font=("Sans", 10))
        st.configure("TLabel", background=C["bg"], foreground=C["text"])
        st.configure("M.TLabel", foreground=C["muted"])
        st.configure("H.TLabel", font=("Sans", 16, "bold"))
        st.configure("TEntry", fieldbackground=C["panel"], foreground=C["text"], insertcolor=C["text"])
        st.configure("TCheckbutton", background=C["bg"], foreground=C["text"])
        st.configure("TRadiobutton", background=C["bg"], foreground=C["text"])
        for w in ("TCheckbutton", "TRadiobutton"):
            st.configure(w, indicatorbackground=C["panel"], indicatorforeground=C["acc"], indicatorcolor=C["panel"], indicatorrelief="flat")
            st.map(w, background=[("active", C["bg"])], foreground=[("active", C["text"])], indicatorcolor=[("selected", C["acc"]), ("!selected", C["panel"])])
        st.configure("TButton", background=C["panel"], foreground=C["text"], padding=6)
        st.map("TButton", background=[("active", C["line"])])
        st.configure("A.TButton", background=C["acc"], foreground="#021715", font=("Sans", 11, "bold"), padding=8)
        st.map("A.TButton", background=[("active", "#1aa39b")])
        st.configure("TSpinbox", fieldbackground=C["panel"], foreground=C["text"], arrowcolor=C["acc"])
        st.configure("TCombobox", fieldbackground=C["panel"], foreground=C["text"], arrowcolor=C["acc"])
        st.map("TCombobox", fieldbackground=[("readonly", C["panel"])], foreground=[("readonly", C["text"])], selectbackground=[("readonly", C["panel"])], selectforeground=[("readonly", C["text"])])
        root.option_add("*TCombobox*Listbox.background", C["panel"]); root.option_add("*TCombobox*Listbox.foreground", C["text"])
        root.option_add("*TCombobox*Listbox.selectBackground", C["acc"]); root.option_add("*TCombobox*Listbox.selectForeground", "#021715")

        f = ttk.Frame(root, padding=16); f.pack(fill="both", expand=True)
        top = ttk.Frame(f); top.pack(fill="x")
        ttk.Label(top, text="CARGO DECK  Scanner", style="H.TLabel").pack(side="left")
        self.langv = tk.StringVar(value=LANG)
        lb = ttk.Frame(top); lb.pack(side="right")
        for l in ("de", "en"):
            ttk.Radiobutton(lb, text=l.upper(), value=l, variable=self.langv, command=self.set_lang).pack(side="left")
        ttk.Label(f, text=f"v{VERSION} · Linux", style="M.TLabel").pack(anchor="w")

        self.state_lbl = tk.Label(f, text=T("ready"), bg=C["panel"], fg=C["muted"], anchor="w", padx=12, pady=10, font=("Sans", 11, "bold"))
        self.state_lbl.pack(fill="x", pady=(10, 12))

        def row(label):
            ttk.Label(f, text=label, style="M.TLabel").pack(anchor="w", pady=(6, 2))
        self.labels = {}
        row(T("site")); self.url = ttk.Entry(f); self.url.insert(0, conf["url"]); self.url.pack(fill="x")
        row(T("code")); self.code = ttk.Entry(f, font=("Monospace", 13)); self.code.insert(0, conf["code"]); self.code.pack(fill="x")

        row(T("mode"))
        self.mode = tk.StringVar(value=conf["mode"])
        m = ttk.Frame(f); m.pack(fill="x")
        ttk.Radiobutton(m, text=T("m_hot"), value="hotkey", variable=self.mode, command=self.apply).pack(side="left")
        ttk.Radiobutton(m, text=T("m_auto"), value="auto", variable=self.mode, command=self.apply).pack(side="left", padx=(16, 4))
        self.interval = tk.IntVar(value=conf["interval"])
        ttk.Spinbox(m, from_=3, to=60, width=4, textvariable=self.interval, command=self.apply).pack(side="left")
        ttk.Label(m, text=T("sec")).pack(side="left", padx=4)

        k = ttk.Frame(f); k.pack(fill="x", pady=(10, 0))
        self.keys = {}
        for i, (name, lbl) in enumerate((("scan_key", T("k_scan")), ("auto_key", T("k_auto")))):
            ttk.Label(k, text=lbl, style="M.TLabel").grid(row=i, column=0, sticky="w", pady=2)
            v = tk.StringVar(value=pretty_key(conf[name])); self.keys[name] = v
            tk.Label(k, textvariable=v, bg=C["panel"], fg=C["acc"], font=("Monospace", 11, "bold"), padx=10, pady=4, width=14).grid(row=i, column=1, padx=8, sticky="w")
            ttk.Button(k, text=T("record"), command=lambda n=name: self.record(n)).grid(row=i, column=2, sticky="w")

        row(T("shot"))
        self.shot = tk.StringVar(value=conf.get("shot", "auto"))
        opts = ["auto"] + [mm[0] for mm in SHOT_METHODS if not mm[1] or shutil.which(mm[1])]
        sh = ttk.Frame(f); sh.pack(fill="x")
        ttk.Combobox(sh, values=opts, textvariable=self.shot, state="readonly", width=18).pack(side="left")
        ttk.Button(sh, text=T("testshot"), command=self.test_shot).pack(side="left", padx=8)

        chk = ttk.Frame(f); chk.pack(fill="x", pady=(10, 0))
        self.sounds = tk.BooleanVar(value=conf["sounds"]); self.notif = tk.BooleanVar(value=conf["notify"]); self.autost = tk.BooleanVar(value=conf["autostart"])
        for txt, var in ((T("sounds"), self.sounds), (T("notify"), self.notif), (T("autostart"), self.autost)):
            ttk.Checkbutton(chk, text=txt, variable=var, command=self.apply).pack(side="left", padx=(0, 14))

        b = ttk.Frame(f); b.pack(fill="x", pady=12)
        self.startbtn = ttk.Button(b, text=T("start"), style="A.TButton", command=self.toggle_run); self.startbtn.pack(side="left")
        ttk.Button(b, text=T("k_scan"), command=lambda: self.sc.trigger("scan")).pack(side="left", padx=8)
        ttk.Button(b, text=T("save"), command=lambda: (self.apply(), self.log(T("saved")))).pack(side="left")

        hint = ttk.Label(f, text=T("hk_hint") + f"\n{APP} --scan    ·    {APP} --toggle", style="M.TLabel", wraplength=520, justify="left")
        hint.pack(anchor="w", pady=(0, 8))

        ttk.Label(f, text=T("log"), style="M.TLabel").pack(anchor="w")
        self.logbox = tk.Text(f, height=10, bg=C["panel"], fg=C["text"], relief="flat", font=("Monospace", 9), wrap="word", highlightthickness=0)
        self.logbox.pack(fill="both", expand=True)

        self.sc = Scanner(conf, self)
        serve_commands(lambda cmd: self.q.put(("cmd", cmd)))
        root.protocol("WM_DELETE_WINDOW", self.quit)
        root.after(100, self.pump)
        self.log(T("ready"))
        if not tesseract_ok(): self.state(T("no_tess"), "bad")
        if minimized or conf.get("autostart") or "--was-running" in sys.argv:
            if CODE_RE.match(conf["code"]): root.after(400, self.toggle_run)
            if minimized: root.after(200, root.iconify)

    # Aufrufe aus anderen Threads laufen über die Warteschlange
    def log(self, t): self.q.put(("log", t))
    def state(self, t, kind): self.q.put(("state", (t, kind)))
    def event(self, what, val): self.q.put((what, val))

    def pump(self):
        try:
            while True:
                kind, v = self.q.get_nowait()
                if kind == "log":
                    self.logbox.insert("1.0", time.strftime("%H:%M:%S  ") + v + "\n"); self.logbox.delete("200.0", "end")
                elif kind == "state":
                    t, k = v; self.state_lbl.config(text=t, fg=C.get(k, C["muted"]))
                elif kind == "mode":
                    self.mode.set(v); self.save(); self.sc.show_running() if self.sc.running else None
                elif kind == "running":
                    self.startbtn.config(text=T("stop") if v else T("start"))
                elif kind == "show":
                    self.root.deiconify(); self.root.lift()
                elif kind == "cmd":
                    if v in ("scan", "toggle"): self.sc.trigger(v)
                    elif v == "show": self.root.deiconify(); self.root.lift()
        except queue.Empty: pass
        self.root.after(80, self.pump)

    def read(self):
        self.c["url"] = self.url.get().strip().rstrip("/")
        self.c["code"] = self.code.get().strip().upper().replace(" ", "")
        self.c["mode"] = self.mode.get()
        try: self.c["interval"] = max(3, min(60, int(self.interval.get())))
        except Exception: pass
        self.c["sounds"] = self.sounds.get(); self.c["notify"] = self.notif.get(); self.c["autostart"] = self.autost.get()
        self.c["shot"] = self.shot.get() or "auto"; self.c["lang"] = LANG

    def save(self):
        try: save_conf(self.c)
        except Exception as e: self.log(str(e))

    def apply(self):
        self.read(); self.save()
        if self.sc.running:
            self.sc.show_running()
            self.sc.hot.start(self.c["scan_key"], self.c["auto_key"])

    def toggle_run(self):
        self.read(); self.save()
        if self.sc.running: self.sc.stop()
        else: self.sc.start()

    def test_shot(self):
        self.read()
        def go():
            try:
                im, how = screenshot(self.c["shot"]); self.log(T("shot_ok", m=how, w=im.width, h=im.height))
            except Exception as e: self.log(str(e))
        threading.Thread(target=go, daemon=True).start()

    def record(self, name):
        """Nächste Tastenkombination im Fenster aufnehmen, im Format von pynput."""
        self.keys[name].set(T("press"))
        mods = {"Control_L": "<ctrl>", "Control_R": "<ctrl>", "Alt_L": "<alt>", "Alt_R": "<alt>", "Shift_L": "<shift>", "Shift_R": "<shift>", "Super_L": "<cmd>", "Super_R": "<cmd>"}
        held = []
        def down(e):
            if e.keysym in mods:
                if mods[e.keysym] not in held: held.append(mods[e.keysym])
                return "break"
            key = e.char.lower() if e.char and e.char.isprintable() and len(e.char) == 1 and e.char != " " else "<" + e.keysym.lower() + ">"
            if re.fullmatch(r"<f\d+>", key) or held:
                combo = "+".join(held + [key]); self.c[name] = combo; self.keys[name].set(pretty_key(combo))
                self.root.unbind("<KeyPress>"); self.apply()
            return "break"
        self.root.bind("<KeyPress>", down); self.root.focus_force()

    def set_lang(self):
        global LANG
        LANG = self.langv.get(); self.read(); self.c["lang"] = LANG; self.save()
        # neu starten, damit alle Texte in der neuen Sprache erscheinen
        self.sc.hot.stop()
        try: os.remove(SOCK)
        except Exception: pass
        os.execv(sys.executable, [sys.executable, os.path.abspath(__file__)] + (["--was-running"] if self.sc.running else []))

    def quit(self):
        try: self.read(); self.save()
        except Exception: pass
        self.sc.hot.stop()
        try: os.remove(SOCK)
        except Exception: pass
        self.root.destroy(); os._exit(0)

    def run(self): self.root.mainloop()

# ---------------------------------------------------------------- Start
def main():
    global LANG
    args = sys.argv[1:]
    if "--version" in args: print(VERSION); return
    for cmd in ("scan", "toggle", "show"):
        if f"--{cmd}" in args:
            if not send_command(cmd): print("Cargo Deck Scanner läuft nicht / is not running"); sys.exit(1)
            return
    if args[:1] == ["--ocr-test"] and len(args) >= 3:
        from PIL import Image
        im = Image.open(args[1]).convert("RGB")
        t = time.time(); r = run_ocr([im]); r["seconds"] = round(time.time() - t, 1)
        with open(args[2], "w") as f: json.dump(r, f)
        print(f"{sum(len(p['lines']) for p in r['passes'])} Zeilen in {r['seconds']} s"); return
    if "--shot-test" in args:
        im, how = screenshot(); print(how, im.size); return
    conf = load_conf()
    LANG = conf.get("lang") or ("de" if os.environ.get("LANG", "").lower().startswith("de") else "en")
    # nur eine Instanz, eine zweite holt das Fenster nach vorne
    if send_command("show"): print(T("already")); return
    try:
        import PIL  # noqa: F401
    except ImportError:
        print("Pillow fehlt / is missing: sudo apt install python3-pil  (oder / or: pip install --user pillow)"); sys.exit(1)
    App(conf, minimized="--minimized" in args).run()

if __name__ == "__main__":
    main()
