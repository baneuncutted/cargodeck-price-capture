#!/usr/bin/env python3
# Cargo Deck Price Capture für Linux
# Liest das Star Citizen Handelsterminal per Texterkennung (Tesseract) und schickt die Preise an Cargo Deck.
# Alles läuft lokal, an die Seite gehen nur der erkannte Text und ein verkleinertes Bild.
import base64, io, json, math, os, queue, re, shutil, socket, struct, subprocess, sys, tempfile, threading, time, urllib.request, wave
from concurrent.futures import ThreadPoolExecutor

VERSION = "1.6.0"
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
    "title": ("Cargo Deck Price Capture", "Cargo Deck Price Capture"),
    "subtitle": ("Liest Preise vom Handelsterminal", "Reads prices from the trade terminal"),
    "nav_scan": ("Erfassen", "Capture"), "nav_set": ("Einstellungen", "Settings"), "nav_help": ("Anleitung", "Guide"),
    "scan_now": ("Jetzt scannen", "Scan now"), "auto": ("Automatik", "Auto mode"), "auto_short": ("Auto", "Auto"), "every": ("alle", "every"),
    "last_title": ("Letzter Scan", "Last scan"), "last_none": ("Noch nichts gescannt", "Nothing scanned yet"),
    "last_ok": ("{n} Preise um {t}", "{n} prices at {t}"), "last_look": ("Schau auf die Website, dort prüfen und übernehmen.", "Check the website, review and apply them there."),
    "conn_title": ("Verbindung", "Connection"), "code_lbl": ("Kopplungscode", "Pairing code"),
    "code_hint": ("Steht auf der Website unter Einstellungen, Price Capture.", "Shown on the website under Settings, Price Capture."),
    "keys_title": ("Tasten", "Keys"),
    "keys_hint": ("Unter Wayland fragt das System beim Start nach den Tasten. Geht das nicht, in den Systemeinstellungen ein Tastenkürzel mit diesem Befehl anlegen.", "On Wayland the system asks for the keys when starting. If that does not work, create a shortcut in the system settings with this command."),
    "opt_title": ("Optionen", "Options"), "engine_title": ("Texterkennung", "Text recognition"), "engine_load": ("wird geladen…", "loading…"),
    "engine_paddle_s": ("PaddleOCR, die gleiche Technik wie auf der Website", "PaddleOCR, the same technology as the website"),
    "engine_tess_s": ("Tesseract, bitte install.sh nochmal ausführen für die neue Erkennung", "Tesseract, please run install.sh again for the new recognition"),
    "sub_hot": ("{k} am Terminal im Spiel drücken", "Press {k} at the terminal in game"),
    "sub_auto": ("Alle {n} Sekunden, nur wenn ein Terminal zu sehen ist", "Every {n} seconds, only when a terminal is visible"),
    "sub_stopped": ("Drück auf Start, dann wartet Price Capture auf deine Taste.", "Press Start, then Price Capture waits for your key."),
    "help_title": ("So funktioniert es", "How it works"),
    "h1_t": ("Code holen", "Get the code"), "h1": ("Öffne Cargo Deck im Browser, geh auf Einstellungen und kopiere den Code unter Price Capture.", "Open Cargo Deck in your browser, go to Settings and copy the code under Price Capture."),
    "h2_t": ("Code eintragen", "Enter the code"), "h2": ("Unter Einstellungen den Code einfügen. Die Adresse der Website stimmt schon.", "Paste the code under Settings. The website address is already correct."),
    "h3_t": ("Starten", "Start"), "h3": ("Auf Start drücken. Der Punkt wird grün. Unter Wayland kommt einmal ein Fenster vom System für die Tasten, dort bestätigen.", "Press Start. The dot turns green. On Wayland the system shows a window for the keys once, confirm it there."),
    "h4_t": ("Im Spiel scannen", "Scan in game"), "h4": ("Am Handelsterminal {k} drücken. Oder Automatik einschalten, dann liest er von selbst, sobald ein Terminal zu sehen ist.", "At the trade terminal press {k}. Or turn on auto mode, then it reads by itself whenever a terminal is visible."),
    "h5_t": ("Auf der Website übernehmen", "Apply on the website"), "h5": ("Der Scan erscheint auf der Website. Kurz prüfen und übernehmen, dann fließen die Preise in deine Routen.", "The scan shows up on the website. Check it quickly and apply it, then the prices flow into your routes."),
    "tips_title": ("Tipps", "Tips"),
    "tip1": ("Setz auf der Website deinen Standort, bei der Station auf „Ich bin hier“. Dann ist die Station sofort klar und alles geht schneller.", "Set your location on the website, click “I'm here” on the station. Then the station is clear right away and everything is faster."),
    "tip2": ("Das Terminal sollte groß und gut lesbar im Bild sein. Mit Screenshot testen siehst du, was Price Capture sieht.", "The terminal should be large and readable on screen. Test screenshot shows what Price Capture sees."),
    "tip3": ("Mit der Nadel oben rechts bleibt ein kleines Fenster immer im Vordergrund, wie beim Windows Rechner.", "The pin at the top right keeps a small window always on top, like the Windows calculator."),
    "tip4": ("Mehrere Bildschirme gehen automatisch, Price Capture nimmt den mit dem Spiel.", "Multiple screens work automatically, Price Capture takes the one with the game."),
    "open_site": ("Website öffnen", "Open website"),

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
    "topmost": ("Immer im Vordergrund", "Always on top"),
    "autostart": ("Mit dem System starten", "Start with the system"),
    "start": ("Starten", "Start"),
    "stop": ("Stoppen", "Stop"),
    "save": ("Speichern", "Save"),
    "testshot": ("Screenshot testen", "Test screenshot"),
    "shot": ("Screenshot", "Screenshot"),
    "screen": ("Bildschirm", "Screen"),
    "scr_auto": ("Automatisch, der mit dem Spiel", "Automatic, the one with the game"),
    "scr_all": ("Alle Bildschirme", "All screens"),
    "auto_sel": ("Automatisch wählen", "Pick automatically"),
    "stopped": ("Gestoppt", "Stopped"),
    "ready": ("Bereit", "Ready"),
    "running_hot": ("Läuft", "Running"),
    "running_auto": ("Läuft automatisch", "Running automatically"),
    "reading": ("Lese Terminal…", "Reading terminal…"),
    "bad_url": ("Website Adresse prüfen", "Check the website address"),
    "bad_code": ("Code fehlt oder ist falsch, 12 Zeichen von der Website", "Code missing or wrong, 12 characters from the website"),
    "no_tess": ("Tesseract fehlt. Bitte install.sh ausführen oder tesseract installieren.", "Tesseract is missing. Run install.sh or install tesseract."),
    "no_shot": ("Kein Screenshot möglich. Unter Wayland grim, spectacle oder gnome-screenshot installieren.", "No screenshot possible. On Wayland install grim, spectacle or gnome-screenshot."),
    "busy": ("Noch beschäftigt, einen Moment", "Still busy, one moment"),
    "sent_ok": ("{n} Preise erkannt {st}", "{n} prices recognized {st}"),
    "sent_look": ("{n} Preise erkannt {st}, schau auf die Seite", "{n} prices recognized {st}, check the website"),
    "q_title": ("{n} Scans warten", "{n} scans waiting"),
    "q_title1": ("1 Scan wartet", "1 scan waiting"),
    "q_sub": ("Öffne Cargo Deck im Browser, dann werden sie automatisch hochgeladen.", "Open Cargo Deck in your browser, then they upload automatically."),
    "q_log": ("Website nicht offen, Scan gespeichert ({n} warten)", "Website not open, scan stored ({n} waiting)"),
    "q_code": ("{n} gespeicherte Scans für diesen Code", "{n} stored scans for this code"),
    "q_notify": ("Scan gespeichert. Öffne Cargo Deck im Browser, dann wird er hochgeladen.", "Scan stored. Open Cargo Deck in your browser, then it gets uploaded."),
    "q_sent": ("{n} gespeicherte Scans hochgeladen, prüf sie auf der Website", "{n} stored scans uploaded, check them on the website"),
    "last": ("Letzter Scan {t}, {n} Preise", "Last scan {t}, {n} prices"),
    "no_term": ("Kein Terminal erkannt", "No terminal recognized"),
    "send_fail": ("Senden fehlgeschlagen", "Sending failed"),
    "unreach": ("Seite nicht erreichbar, Adresse prüfen", "Website not reachable, check the address"),
    "ocr_fail": ("Texterkennung ging nicht", "Text recognition failed"),
    "paddle_fail": ("Neue Texterkennung ging nicht, nehme Tesseract", "New text recognition failed, using Tesseract"),
    "engine_paddle": ("Texterkennung bereit (PaddleOCR, wie auf der Website)", "Text recognition ready (PaddleOCR, same as the website)"),
    "engine_tess": ("Neue Texterkennung fehlt, lese mit Tesseract. Bitte install.sh nochmal ausführen.", "New text recognition missing, reading with Tesseract. Please run install.sh again."),
    "auto_on": ("Automatik an, alle {n} Sekunden", "Auto on, every {n} seconds"),
    "auto_off": ("Automatik aus", "Auto off"),
    "saved": ("Gespeichert", "Saved"),
    "shot_ok": ("Screenshot mit {m}, {w} × {h} Pixel", "Screenshot with {m}, {w} × {h} pixels"),
    "shot_saved": ("Zum Anschauen gespeichert: {p}", "Saved for checking: {p}"),
    "hk_x11": ("Tastenkürzel aktiv", "Hotkeys active"),
    "hk_none": ("Globale Tastenkürzel gehen hier nicht direkt. Lege in den Systemeinstellungen ein Tastenkürzel an mit dem Befehl:", "Global hotkeys don't work directly here. Create a keyboard shortcut in your system settings with the command:"),
    "hk_portal": ("Tastenkürzel vom System aktiv, Scannen mit {k}", "System hotkeys active, scan with {k}"),
    "hk_portal_wait": ("Tastenkürzel werden beim System angemeldet. Falls ein Fenster erscheint, dort bestätigen.", "Registering hotkeys with the system. If a window pops up, confirm it there."),
    "hk_portal_no": ("Tastenkürzel wurden im System Fenster abgelehnt.", "Hotkeys were declined in the system window."),
    "hk_portal_unset": ("(noch keine Taste, in den Systemeinstellungen unter Tastenkürzel festlegen)", "(no key yet, set it in the system settings under shortcuts)"),
    "hk_portal_err": ("Tastenkürzel über das System gingen nicht", "System hotkeys failed"),
    "hk_game": ("Zusätzlich direkt im Spiel Fenster", "Also directly in the game window"),
    "hk_hint": ("Tipp: Unter Wayland in den Systemeinstellungen ein Tastenkürzel mit dem Befehl anlegen:", "Tip: on Wayland, create a keyboard shortcut in the system settings with the command:"),
    "log": ("Verlauf", "Log"),
    "keys_swapped": ("Deine Tastatur hat diese Taste nicht, darum jetzt {k} zum Scannen und {a} für die Automatik", "Your keyboard doesn't have that key, so now {k} scans and {a} toggles auto"),
    "lang": ("Sprache", "Language"),
    "already": ("Price Capture läuft schon.", "Price Capture is already running."),
    "started": ("Gestartet", "Started"),
}
LANG = "de"
def T(_key, **kw):
    s = TEXT.get(_key, (_key, _key))[0 if LANG == "de" else 1]
    return s.format(**kw) if kw else s

# ---------------------------------------------------------------- Einstellungen
DEFAULTS = {"url": "https://cargodeck.onrender.com", "code": "", "mode": "hotkey", "interval": 5,
            "scan_key": "<ctrl>+ö", "auto_key": "<ctrl>+ä", "sounds": True, "notify": True, "autostart": False,
            "shot": "auto", "screen": "auto", "lang": "", "topmost": False, "pinned": False, "pin_x": -1, "pin_y": -1}

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
                fh.write(f"[Desktop Entry]\nType=Application\nName=Cargo Deck Price Capture\nExec={sys.executable} {os.path.abspath(__file__)} --minimized\nIcon={APP}\nX-GNOME-Autostart-enabled=true\n")
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
          "ok": [(784, 0, .08), (988, .06, .08), (1319, .12, .18)], "err": [(330, 0, .16)], "queued": [(698, 0, .12)]}
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
        try: subprocess.Popen(["notify-send", "-a", "Cargo Deck Price Capture", "-t", "3500", "Cargo Deck", text], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
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

# ---------------------------------------------------------------- Nur der Bildschirm mit dem Spiel
_last_mon = None   # zuletzt erkannter Bildschirm des Spiels
_SELF_TITLE = "Cargo Deck Price Capture"

def monitors():
    """Alle Bildschirme als (Name, x, y, Breite, Höhe) in X11 Koordinaten, auch unter XWayland."""
    out = []
    if os.environ.get("DISPLAY") and shutil.which("xrandr"):
        try:
            r = subprocess.run(["xrandr", "--listactivemonitors"], capture_output=True, text=True, timeout=5).stdout
            for line in r.splitlines()[1:]:
                m = re.search(r"(\d+)/\d+x(\d+)/\d+\+(-?\d+)\+(-?\d+)\s+(\S+)\s*$", line)
                if m: out.append((m.group(5), int(m.group(3)), int(m.group(4)), int(m.group(1)), int(m.group(2))))
        except Exception: pass
    if not out and os.environ.get("DISPLAY"):
        try:
            from Xlib import display
            from Xlib.ext import randr
            d = display.Display()
            for mo in randr.get_monitors(d.screen().root).monitors:
                out.append((d.get_atom_name(mo.name), mo.x, mo.y, mo.width_in_pixels, mo.height_in_pixels))
            d.close()
        except Exception: pass
    return out

def _game_point():
    """Mitte des aktiven Fensters, wenn es nicht der Scanner selbst ist. Sonst die Maus."""
    if not os.environ.get("DISPLAY"): return None
    try:
        from Xlib import display, X
        d = display.Display(); root = d.screen().root
        try:
            prop = root.get_full_property(d.intern_atom("_NET_ACTIVE_WINDOW"), X.AnyPropertyType)
            wid = prop.value[0] if prop and len(prop.value) else 0
            if wid:
                w = d.create_resource_object("window", wid)
                nm = w.get_full_property(d.intern_atom("_NET_WM_NAME"), 0)
                name = (nm.value.decode("utf-8", "ignore") if nm and isinstance(nm.value, bytes) else str(nm.value) if nm else "") or (w.get_wm_name() or "")
                if _SELF_TITLE not in str(name):
                    g = w.get_geometry(); t = root.translate_coords(w, 0, 0)
                    if g.width > 100 and g.height > 100: return (t.x + g.width // 2, t.y + g.height // 2)
            p = root.query_pointer(); return (p.root_x, p.root_y)
        finally: d.close()
    except Exception: pass
    if shutil.which("xdotool"):
        try:
            r = subprocess.run(["xdotool", "getmouselocation", "--shell"], capture_output=True, text=True, timeout=3).stdout
            v = dict(l.split("=", 1) for l in r.split() if "=" in l); return (int(v["X"]), int(v["Y"]))
        except Exception: pass
    return None

_last_mon_t = 0.0

def forget_monitor():
    """Beim nächsten Bild neu suchen, auf welchem Bildschirm das Terminal ist."""
    global _last_mon_t
    _last_mon_t = 0.0

def _terminal_center(im):
    """Kurz und grob lesen, wo auf dem Gesamtbild die Terminal Wörter stehen."""
    try:
        from PIL import Image
        sc = min(1.0, 2400 / im.width)
        small = im.resize((max(1, int(im.width * sc)), max(1, int(im.height * sc))), Image.BILINEAR) if sc < 1 else im
        lines = _tsv_lines(_tess(_gray(small, mx=True, invert=True, k=1.3), 11), sc, 0, 0)
        hits = [l for l in lines if TERM_WORD.search(l["t"])]
        if len(hits) < 2: return None
        xs = sorted(l["x"] + l["w"] / 2 for l in hits); ys = sorted(l["y"] + l["h"] / 2 for l in hits)
        return (xs[len(xs) // 2], ys[len(ys) // 2])
    except Exception:
        return None

def pick_monitor(im, want="auto"):
    """Bildschirm wählen: fest eingestellt, sonst der, auf dem das Terminal zu sehen ist."""
    global _last_mon, _last_mon_t
    mons = monitors()
    if len(mons) <= 1 or want == "all": return None, mons
    if want not in ("auto", "", None):
        for m in mons:
            if m[0] == want: return m, mons
    by = {m[0]: m for m in mons}
    if _last_mon in by and time.time() - _last_mon_t < 120: return by[_last_mon], mons
    # 1. wo steht das Terminal? Das ist sicherer als Maus oder Fokus, die oft beim Scanner selbst sind
    c = _terminal_center(im)
    if c:
        x0 = min(m[1] for m in mons); y0 = min(m[2] for m in mons)
        sx = im.width / max(1, max(m[1] + m[3] for m in mons) - x0); sy = im.height / max(1, max(m[2] + m[4] for m in mons) - y0)
        px, py = c[0] / sx + x0, c[1] / sy + y0
        for m in mons:
            if m[1] <= px < m[1] + m[3] and m[2] <= py < m[2] + m[4]:
                _last_mon, _last_mon_t = m[0], time.time(); return m, mons
    # 2. sonst das aktive Fenster, wenn es nicht der Scanner ist, dann der zuletzt benutzte
    pt = _game_point()
    if pt:
        for m in mons:
            if m[1] <= pt[0] < m[1] + m[3] and m[2] <= pt[1] < m[2] + m[4]: return m, mons
    if _last_mon in by: return by[_last_mon], mons
    return mons[0], mons

def crop_to(im, mon, mons):
    """Aus einem Bild aller Bildschirme nur den gewählten ausschneiden, auch bei Skalierung."""
    if not mon or not mons: return im
    x0 = min(m[1] for m in mons); y0 = min(m[2] for m in mons)
    x1 = max(m[1] + m[3] for m in mons); y1 = max(m[2] + m[4] for m in mons)
    sx, sy = im.width / max(1, x1 - x0), im.height / max(1, y1 - y0)
    box = (round((mon[1] - x0) * sx), round((mon[2] - y0) * sy), round((mon[1] - x0 + mon[3]) * sx), round((mon[2] - y0 + mon[4]) * sy))
    return im.crop(box)

SHOT_METHODS = [
    # Name, nötiges Programm, Aufruf, nur Wayland. Immer der ganze Desktop, den richtigen Bildschirm schneiden wir selbst aus.
    ("grim", "grim", lambda: _run_png(["grim", "-t", "png", "-"]), True),
    ("spectacle", "spectacle", lambda: _run_png(["spectacle", "-b", "-n", "-f", "-o", "{file}"], True), True),
    ("portal", None, lambda: portal_screenshot(), True),
    ("gnome-screenshot", "gnome-screenshot", lambda: _run_png(["gnome-screenshot", "-f", "{file}"], True), True),
    ("flameshot", "flameshot", lambda: _run_png(["flameshot", "full", "-r"]), False),
    ("x11", None, _pil_grab, False),
    ("maim", "maim", lambda: _run_png(["maim"]), False),
    ("scrot", "scrot", lambda: _run_png(["scrot", "-o", "{file}"], True), False),
    ("import", "import", lambda: _run_png(["import", "-window", "root", "png:-"]), False),
]
_shot_ok = None
def screenshot(pref="auto", screen="auto"):
    """Nur den Bildschirm mit dem Spiel aufnehmen. Unter Wayland über die Werkzeuge des Desktops, unter X11 direkt."""
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
        if name == "portal" and not portal_ok(): continue
        try:
            full = fn().convert("RGB")
            if full.width < 200 or full.height < 200: continue
            if max(full.resize((32, 18)).convert("L").tobytes()) < 8: continue
            im = full
            mon, mons = pick_monitor(full, screen)
            if mon:
                im = crop_to(full, mon, mons); name = f"{name}, {mon[0]}"
                # schwarzer Bildschirm gewählt, dann lieber alles nehmen
                if max(im.resize((32, 18)).convert("L").tobytes()) < 8: im, name = full, name.split(",")[0]
            # komplett schwarz heisst meist: Wayland verweigert die Aufnahme
            if max(im.resize((32, 18)).convert("L").tobytes()) < 8: continue
            _shot_ok = name.split(",")[0]
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

# ---------------------------------------------------------------- PaddleOCR (gleiche Technik wie die Website)
# PP-OCRv4 findet die Textzeilen, PP-OCRv5 Englisch liest sie. Liest die Terminal Schrift viel besser als Tesseract,
# auch rote Pyro Terminals, schräge Aufnahmen und kleine Auflösungen. Braucht numpy und onnxruntime, sonst Tesseract.
OCR_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ocr")
PADDLE_TERM = re.compile(r"SHOP|INVENT|QUANTIT|CARGO|DEMAND|COMMODIT|BALANCE|MARKET|STOCK", re.I)
PADDLE_PRICE = re.compile(r"^[^0-9]{0,2}?([0-9][0-9.,' ]*)(\s*/\s*[S5$][CcGgOo0][UuVv0l1]?.*)$")

class Paddle:
    DET_MAX, DET_MIN, DET_TH, BOX_TH, UNCLIP, REC_H = 2000, 736, 0.3, 0.5, 1.6, 48

    def __init__(self, base=OCR_DIR):
        import numpy as np, onnxruntime as ort
        self.np = np
        so = ort.SessionOptions()
        so.intra_op_num_threads = max(1, min(4, (os.cpu_count() or 2) - 1))
        so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        so.log_severity_level = 3
        prov = ["CPUExecutionProvider"]
        self.det = ort.InferenceSession(os.path.join(base, "det.onnx"), so, providers=prov)
        self.rec = ort.InferenceSession(os.path.join(base, "rec.onnx"), so, providers=prov)
        with open(os.path.join(base, "dict.txt"), encoding="utf-8") as f: lines = f.read().split("\n")
        if lines and lines[-1] == "": lines.pop()
        self.chars = [""] + lines + [" "]

    # ---- Textzeilen finden
    def detect(self, im):
        np = self.np
        from PIL import Image
        w0, h0 = im.size
        r = 1.0
        if max(w0, h0) > self.DET_MAX: r = self.DET_MAX / max(w0, h0)
        if min(w0, h0) * r < self.DET_MIN: r = self.DET_MIN / min(w0, h0)
        W, H = max(32, round(w0 * r / 32) * 32), max(32, round(h0 * r / 32) * 32)
        a = np.asarray(im.resize((W, H), Image.BILINEAR), dtype=np.float32)[:, :, ::-1] / 127.5 - 1.0
        t = np.ascontiguousarray(a.transpose(2, 0, 1)[None])
        pred = self.det.run(None, {self.det.get_inputs()[0].name: t})[0][0, 0]
        b = pred > self.DET_TH
        bm = b.copy(); bm[:, 1:] |= b[:, :-1]; bm[1:, :] |= b[:-1, :]; bm[1:, 1:] |= b[:-1, :-1]
        cs = np.concatenate([np.zeros((H, 1), np.float64), np.cumsum(pred, axis=1, dtype=np.float64)], axis=1)
        # Läufe je Zeile, dann zusammenhängende Flächen (8er Nachbarschaft) über Union Find
        pad = np.zeros((H, W + 2), np.int8); pad[:, 1:-1] = bm
        d = np.diff(pad, axis=1)
        ys, xs = np.nonzero(d == 1); ye, xe = np.nonzero(d == -1)
        runs = list(zip(ys.tolist(), xs.tolist(), (xe - 1).tolist()))   # (y, x0, x1), sortiert nach y, x
        parent = list(range(len(runs)))
        def find(i):
            while parent[i] != i: parent[i] = parent[parent[i]]; i = parent[i]
            return i
        prev_start = prev_end = 0; i = 0; n = len(runs)
        while i < n:
            y = runs[i][0]; j = i
            while j < n and runs[j][0] == y: j += 1
            if prev_end > prev_start and runs[prev_start][0] == y - 1:
                k = prev_start
                for q in range(i, j):
                    _, a0, a1 = runs[q]
                    while k < prev_end and runs[k][2] < a0 - 1: k += 1
                    kk = k
                    while kk < prev_end and runs[kk][1] <= a1 + 1:
                        ra, rb = find(q), find(kk)
                        if ra != rb: parent[ra] = rb
                        kk += 1
            prev_start, prev_end = i, j; i = j
        comps = {}
        for idx, (y, x0, x1) in enumerate(runs):
            comps.setdefault(find(idx), []).append((y, x0, x1))
        sx, sy = w0 / W, h0 / H
        boxes = []
        for rs in comps.values():
            cnt = sum(x1 - x0 + 1 for _, x0, x1 in rs)
            if cnt < 6: continue
            score = sum(cs[y, x1 + 1] - cs[y, x0] for y, x0, x1 in rs) / cnt
            if score < self.BOX_TH: continue
            s_x = s_y = s_xx = s_yy = s_xy = 0.0
            for y, x0, x1 in rs:
                c = x1 - x0 + 1; sxr = c * (x0 + x1) / 2
                sxx = (x1 * (x1 + 1) * (2 * x1 + 1) - (x0 - 1) * x0 * (2 * x0 - 1)) / 6
                s_x += sxr; s_y += c * y; s_xx += sxx; s_yy += c * y * y; s_xy += y * sxr
            mx, my = s_x / cnt, s_y / cnt
            cxx = s_xx - cnt * mx * mx; cyy = s_yy - cnt * my * my; cxy = s_xy - cnt * mx * my
            ang = 0.5 * math.atan2(2 * cxy, cxx - cyy)
            if ang > math.pi / 4: ang -= math.pi / 2
            elif ang < -math.pi / 4: ang += math.pi / 2
            def ext(ca, sa):
                u0 = v0 = 1e18; u1 = v1 = -1e18
                for y, x0, x1 in rs:
                    dy = y - my
                    for x in (x0, x1):
                        dx = x - mx; u = dx * ca + dy * sa; v = -dx * sa + dy * ca
                        if u < u0: u0 = u
                        if u > u1: u1 = u
                        if v < v0: v0 = v
                        if v > v1: v1 = v
                return u0, u1 + 1, v0, v1 + 1
            ca, sa = math.cos(ang), math.sin(ang)
            u0, u1, v0, v1 = ext(ca, sa)
            if (u1 - u0) < (v1 - v0) * 1.6:
                ang, ca, sa = 0.0, 1.0, 0.0; u0, u1, v0, v1 = ext(ca, sa)
            bw, bh = u1 - u0, v1 - v0
            if min(bw, bh) < 3: continue
            dd = bw * bh * self.UNCLIP / (2 * (bw + bh))
            cu, cv = (u0 + u1) / 2, (v0 + v1) / 2
            bw += 2 * dd; bh += 2 * dd
            if min(bw, bh) < 5: continue
            cx, cy = mx + cu * ca - cv * sa, my + cu * sa + cv * ca
            boxes.append({"cx": cx * sx, "cy": cy * sy, "w": bw * math.hypot(ca * sx, sa * sy), "h": bh * math.hypot(sa * sx, ca * sy),
                          "a": math.atan2(sa * sy, ca * sx), "score": score})
        boxes.sort(key=lambda b: (b["cy"] - b["h"] / 2, b["cx"]))
        return boxes

    # ---- Zeilen lesen
    def recognize(self, im, boxes, batch=8):
        np = self.np
        from PIL import Image
        H = self.REC_H; out = [None] * len(boxes)
        order = sorted(range(len(boxes)), key=lambda i: boxes[i]["w"] / boxes[i]["h"])
        for k in range(0, len(order), batch):
            ids = order[k:k + batch]
            ratio = max([320 / H] + [boxes[i]["w"] / boxes[i]["h"] for i in ids])
            IW = min(3200, math.ceil(H * ratio))
            t = np.zeros((len(ids), 3, H, IW), np.float32)
            for n, i in enumerate(ids):
                b = boxes[i]; ww = max(1, min(IW, math.ceil(H * b["w"] / b["h"])))
                ca, sa = math.cos(b["a"]), math.sin(b["a"]); su, sv = b["w"] / ww, b["h"] / H
                coef = (su * ca, -sv * sa, b["cx"] - ww / 2 * su * ca + H / 2 * sv * sa,
                        su * sa, sv * ca, b["cy"] - ww / 2 * su * sa - H / 2 * sv * ca)
                c = im.transform((ww, H), Image.AFFINE, coef, resample=Image.BILINEAR)
                a = np.asarray(c, dtype=np.float32)[:, :, ::-1] / 127.5 - 1.0
                t[n, :, :, :ww] = a.transpose(2, 0, 1)
            p = self.rec.run(None, {self.rec.get_inputs()[0].name: t})[0]
            best = p.argmax(axis=2); prob = p.max(axis=2)
            for n, i in enumerate(ids):
                txt = []; conf = []; last = 0
                for s, c in enumerate(best[n].tolist()):
                    if c and c != last: txt.append(self.chars[c] if c < len(self.chars) else ""); conf.append(float(prob[n, s]))
                    last = c
                out[i] = ("".join(txt), sum(conf) / len(conf) if conf else 0.0)
        return out

    @staticmethod
    def tidy(t):
        t = re.sub(r"[　-鿿＀-￯]", "", t).strip()
        m = PADDLE_PRICE.match(t)
        if m:
            n = re.sub(r"[^0-9]", "", m.group(1)).lstrip("0")
            if n: t = n + re.sub(r"^(\s*/\s*)[S5$][CcGgOo0][A-Za-z0-9]{0,2}", r"\1SCU", m.group(2))
        return t

    def lines(self, boxes, texts, ox=0, oy=0, z=1.0):
        out = []
        for i, b in enumerate(boxes):
            r = texts[i]
            if not r or not r[0] or r[1] < 0.35: continue
            t = self.tidy(r[0])
            if not t: continue
            w, h = b["w"], b["h"]
            out.append({"t": t, "x": round((b["cx"] - w / 2) / z + ox), "y": round((b["cy"] - h / 2) / z + oy), "w": round(w / z), "h": round(h / z), "c": round(r[1], 2), "i": i})
        return out

    def read(self, im):
        """Ganzes Bild, dann das Terminal vergrössert, dann Preise und Mengen einzeln. Gleiches Format wie die Website."""
        from PIL import Image
        im = im.convert("RGB"); W, H = im.size
        passes = []
        b1 = self.detect(im); l1 = self.lines(b1, self.recognize(im, b1))
        passes.append({"name": "paddle", "w": W, "h": H, "lines": l1})
        hits = [l for l in l1 if PADDLE_TERM.search(l["t"])]
        if len(hits) >= 3:
            x1 = min(l["x"] for l in hits); y1 = min(l["y"] for l in hits)
            x2 = max(l["x"] + l["w"] for l in hits); y2 = max(l["y"] + l["h"] for l in hits)
            X, Y = max(0, x1 - W * .08), max(0, y1 - H * .08)
            X2, Y2 = min(W, x2 + W * .08), min(H, y2 + H * .08)
            cw, ch = X2 - X, Y2 - Y
            if cw > 100 and ch > 100 and cw * ch < W * H * .8:
                z = max(1.0, min(2.5, 1600 / max(cw, ch)))
                c = im.crop((round(X), round(Y), round(X2), round(Y2)))
                if z > 1.001: c = c.resize((round(c.width * z), round(c.height * z)), Image.BILINEAR)
                b2 = self.detect(c)
                passes.append({"name": "paddle-t", "w": W, "h": H, "lines": self.lines(b2, self.recognize(c, b2), round(X), round(Y), z)})
        pi = [l for l in l1 if re.search(r"/\s*S|SC[UO0]", l["t"], re.I) and not re.search(r"[A-Za-z]{5,}", l["t"])]
        if pi:
            pb = [dict(b1[l["i"]], w=b1[l["i"]]["w"] + b1[l["i"]]["h"] * .6, h=b1[l["i"]]["h"] * .9) for l in pi]
            l3 = self.lines(pb, self.recognize(im, pb))
            repl = {id(pi[n["i"]]): n for n in l3}
            passes.append({"name": "paddle-p", "w": W, "h": H, "lines": [repl.get(id(l), l) for l in l1]})
        for p in passes:
            for l in p["lines"]: l.pop("i", None)
        return {"ok": True, "engine": "paddle", "passes": passes}

_paddle = None
_paddle_err = None
_paddle_lock = threading.Lock()
def paddle():
    """PaddleOCR einmal laden. None, wenn onnxruntime oder die Modelle fehlen, dann liest Tesseract."""
    global _paddle, _paddle_err
    with _paddle_lock:
        if _paddle is None and _paddle_err is None:
            try: _paddle = Paddle()
            except Exception as e: _paddle_err = str(e)
    return _paddle

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
FALLBACK_KEYS = ("<ctrl>+<f9>", "<ctrl>+<f10>")

def key_on_layout(combo):
    """Gibt es die Taste auf der aktuellen Tastaturbelegung? Dvorak oder US haben zum Beispiel kein Ö."""
    k = combo.split("+")[-1]
    if k.startswith("<") or len(k) != 1 or ord(k) < 128: return True
    try:
        from Xlib import display
        d = display.Display(); ok = d.keysym_to_keycode(ord(k)) != 0; d.close(); return ok
    except Exception:
        return True

class Hotkeys:
    """Globale Tastenkürzel über pynput (X11 und Spiele unter XWayland). Unter reinem Wayland über den Befehl mit --scan.
    Eigene Erkennung statt GlobalHotKeys, damit es auch mit Dvorak, Colemak und anderen Belegungen geht."""
    MODS = {"ctrl": "ctrl", "ctrl_l": "ctrl", "ctrl_r": "ctrl", "alt": "alt", "alt_l": "alt", "alt_r": "alt", "alt_gr": "alt",
            "shift": "shift", "shift_l": "shift", "shift_r": "shift", "cmd": "cmd", "cmd_l": "cmd", "cmd_r": "cmd"}
    def __init__(self, on_scan, on_auto):
        self.on_scan, self.on_auto, self.listener, self.ok = on_scan, on_auto, None, False
        self.held, self.combos = set(), []
    @staticmethod
    def parse(combo):
        parts = [p.strip().lower() for p in combo.split("+") if p.strip()]
        mods = {Hotkeys.MODS.get(p.strip("<>"), p.strip("<>")) for p in parts[:-1]}
        key = parts[-1].strip("<>") if parts[-1].startswith("<") else parts[-1]
        return mods, key
    def _name(self, key):
        from pynput import keyboard
        if isinstance(key, keyboard.Key): return key.name
        ch = getattr(key, "char", None)
        if ch and ch.isprintable(): return ch.lower()
        vk = getattr(key, "vk", None)
        # mit gedrückter Strg Taste kommt oft kein Zeichen, dann über den Tastencode
        if vk and 32 <= vk < 256: return chr(vk).lower()
        return None
    def start(self, scan_key, auto_key):
        self.stop()
        try:
            from pynput import keyboard
            if not os.environ.get("DISPLAY"): return False
            self.combos = [(self.parse(scan_key), self.on_scan), (self.parse(auto_key), self.on_auto)]
            def press(key):
                n = self._name(key)
                if n is None: return
                if n in self.MODS: self.held.add(self.MODS[n]); return
                for (mods, k), fn in self.combos:
                    if n == k and mods <= self.held and (self.held - mods) <= {"shift"}:
                        threading.Thread(target=fn, daemon=True).start()
            def release(key):
                n = self._name(key)
                if n in self.MODS: self.held.discard(self.MODS[n])
            self.listener = keyboard.Listener(on_press=press, on_release=release)
            self.listener.start(); self.ok = True
        except Exception:
            self.listener, self.ok = None, False
        return self.ok
    def stop(self):
        try:
            if self.listener: self.listener.stop()
        except Exception: pass
        self.listener, self.ok, self.held = None, False, set()

# ---------------------------------------------------------------- XDG Desktop Portal (Wayland: KDE Plasma, GNOME 48+, Hyprland)
APP_ID = "io.github.baneuncutted.CargoDeckScanner"
PORTAL_PATH = "/org/freedesktop/portal/desktop"

class Portal:
    """Eine D-Bus Verbindung zum Portal. Über jeepney (reines Python, keine Kompilierung nötig)."""
    def __init__(self):
        from jeepney.io.blocking import open_dbus_connection
        self.conn = open_dbus_connection(bus="SESSION")
        self.sender = self.conn.unique_name[1:].replace(".", "_")
        # Ohne App ID merkt sich GNOME keine Erlaubnis und KDE ordnet die Kürzel keiner App zu
        try: self.call("org.freedesktop.host.portal.Registry", "Register", "sa{sv}", (APP_ID, {}))
        except Exception: pass
    def addr(self, iface, path=PORTAL_PATH):
        from jeepney import DBusAddress
        return DBusAddress(path, bus_name="org.freedesktop.portal.Desktop", interface=iface)
    def call(self, iface, method, sig, body, path=PORTAL_PATH):
        from jeepney import new_method_call
        from jeepney.wrappers import unwrap_msg
        return unwrap_msg(self.conn.send_and_get_reply(new_method_call(self.addr(iface, path), method, sig, body), timeout=10))
    def version(self, iface):
        from jeepney import Properties
        from jeepney.wrappers import unwrap_msg
        try: return int(unwrap_msg(self.conn.send_and_get_reply(Properties(self.addr(iface)).get("version"), timeout=5))[0][1])
        except Exception: return 0
    def request(self, iface, method, sig, body, token, timeout=300):
        """Portal Aufruf mit Antwort über das Request Signal. Die Antwort kann dauern, wenn das System nachfragt."""
        from jeepney import MatchRule, message_bus
        from jeepney.wrappers import unwrap_msg
        path = f"{PORTAL_PATH}/request/{self.sender}/{token}"
        rule = MatchRule(type="signal", interface="org.freedesktop.portal.Request", member="Response", path=path)
        unwrap_msg(self.conn.send_and_get_reply(message_bus.AddMatch(rule), timeout=5))
        with self.conn.filter(rule) as q:
            self.call(iface, method, sig, body)
            msg = self.conn.recv_until_filtered(q, timeout=timeout)
        code, res = msg.body
        return code, {k: v[1] for k, v in res.items()}
    def close(self):
        try: self.conn.close()
        except Exception: pass

def portal_ok():
    if not os.environ.get("DBUS_SESSION_BUS_ADDRESS") and not os.path.exists(os.path.join(RUN_DIR, "bus")): return False
    try:
        import jeepney  # noqa
        return True
    except Exception: return False

def _token():
    return "cd" + os.urandom(6).hex()

# Tastenname aus der App (pynput Schreibweise) in die Schreibweise der Freedesktop Kürzel
_SYM = {"ö": "odiaeresis", "ä": "adiaeresis", "ü": "udiaeresis", "ß": "ssharp", "+": "plus", "-": "minus", "#": "numbersign",
        ".": "period", ",": "comma", "<": "less", "space": "space", "enter": "Return", "tab": "Tab", "home": "Home", "end": "End",
        "insert": "Insert", "delete": "Delete", "pause": "Pause", "scroll_lock": "Scroll_Lock", "print_screen": "Print",
        "page_up": "Prior", "page_down": "Next", "backspace": "BackSpace", "esc": "Escape",
        "up": "Up", "down": "Down", "left": "Left", "right": "Right"}
def spec_trigger(combo):
    try:
        mods, key = Hotkeys.parse(combo)
        m = [n for k, n in (("ctrl", "CTRL"), ("alt", "ALT"), ("shift", "SHIFT"), ("cmd", "LOGO")) if k in mods]
        if re.fullmatch(r"f\d{1,2}", key): k = key.upper()
        elif re.fullmatch(r"[a-z0-9]", key): k = key
        else: k = _SYM.get(key)
        return "+".join(m + [k]) if k else ""
    except Exception: return ""

class PortalHotkeys:
    """Globale Tastenkürzel über das Portal. Das System fragt einmal nach und merkt es sich dann."""
    def __init__(self, on_scan, on_auto, log):
        self.fn = {"scan": on_scan, "toggle": on_auto}
        self.log, self.p, self.stop_ev, self.thread, self.ok, self.bound = log, None, threading.Event(), None, False, {}
    def start(self, scan_key, auto_key):
        self.stop()
        if not portal_ok(): return False
        try:
            p = Portal()
            if p.version("org.freedesktop.portal.GlobalShortcuts") < 1: p.close(); return False
        except Exception: return False
        self.p, self.stop_ev, self.ok = p, threading.Event(), True
        self.thread = threading.Thread(target=self._run, args=(p, self.stop_ev, scan_key, auto_key), daemon=True); self.thread.start()
        return True
    def _run(self, p, stop_ev, scan_key, auto_key):
        from jeepney import MatchRule, message_bus
        from jeepney.wrappers import unwrap_msg
        try:
            t = _token()
            code, res = p.request("org.freedesktop.portal.GlobalShortcuts", "CreateSession", "a{sv}",
                                  ({"handle_token": ("s", t), "session_handle_token": ("s", _token())},), t, timeout=30)
            if code != 0: raise RuntimeError(f"CreateSession {code}")
            session = str(res.get("session_handle"))
            act = MatchRule(type="signal", interface="org.freedesktop.portal.GlobalShortcuts", member="Activated")
            unwrap_msg(p.conn.send_and_get_reply(message_bus.AddMatch(act), timeout=5))
            with p.conn.filter(act, bufsize=32) as q:
                sc = []
                for sid, desc, combo in (("scan", T("k_scan"), scan_key), ("toggle", T("k_auto"), auto_key)):
                    o = {"description": ("s", "Cargo Deck: " + desc)}
                    tr = spec_trigger(combo)
                    if tr: o["preferred_trigger"] = ("s", tr)
                    sc.append((sid, o))
                t = _token()
                code, res = p.request("org.freedesktop.portal.GlobalShortcuts", "BindShortcuts", "oa(sa{sv})sa{sv}",
                                      (session, sc, "", {"handle_token": ("s", t)}), t, timeout=600)
                if code != 0:
                    self.ok = False; self.log(T("hk_portal_no")); return
                self.bound = {sid: (o.get("trigger_description", ("s", ""))[1] or "") for sid, o in res.get("shortcuts", [])}
                shown = self.bound.get("scan") or T("hk_portal_unset")
                self.log(T("hk_portal", k=shown))
                last = {}
                while not stop_ev.is_set():
                    try: msg = p.conn.recv_until_filtered(q, timeout=1)
                    except TimeoutError: continue
                    if str(msg.body[0]) != session: continue
                    sid = msg.body[1]
                    # manche Desktops schicken das Signal doppelt
                    if time.time() - last.get(sid, 0) < .4: continue
                    last[sid] = time.time()
                    if sid in self.fn: threading.Thread(target=self.fn[sid], daemon=True).start()
        except Exception as e:
            if not stop_ev.is_set(): self.ok = False; self.log(T("hk_portal_err") + f" ({e})")
        finally:
            p.close()
    def stop(self):
        self.stop_ev.set()
        if self.p: self.p.close()
        self.p, self.ok, self.bound = None, False, {}

def portal_screenshot():
    """Screenshot über das Portal. GNOME fragt beim ersten Mal nach der Erlaubnis und merkt sich das."""
    from PIL import Image
    from urllib.parse import unquote, urlparse
    p = Portal()
    try:
        t = _token()
        code, res = p.request("org.freedesktop.portal.Screenshot", "Screenshot", "sa{sv}",
                              ("", {"handle_token": ("s", t), "interactive": ("b", False), "modal": ("b", False)}), t, timeout=120)
    finally: p.close()
    if code != 0 or not res.get("uri"): raise RuntimeError("portal " + str(code))
    f = unquote(urlparse(res["uri"]).path)
    try:
        im = Image.open(f); im.load(); return im
    finally:
        # nicht den Bilder Ordner mit Scans füllen
        try: os.remove(f)
        except Exception: pass

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
        # Scans, die warten, weil die Website nicht offen ist. Gehen raus, sobald sie offen ist.
        self.pending = []; self.flushing = False; self.next_web = 0
        self.hot = Hotkeys(lambda: self.trigger("scan"), lambda: self.trigger("toggle"))
        self.portal = PortalHotkeys(lambda: self.trigger("scan"), lambda: self.trigger("toggle"), lambda m: self.ui.log(m))
        self._last_trig = {}; self.portal_keys = None
        threading.Thread(target=self.loop, daemon=True).start()

    def trigger(self, what):
        # gleiches Kürzel kann über Portal und direkt kommen, nur einmal ausführen
        if time.time() - self._last_trig.get(what, 0) < .5: return
        self._last_trig[what] = time.time()
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
        # Taste gibt es auf dieser Tastatur nicht (z.B. Ö bei Dvorak), dann F9 und F10 nehmen
        if not key_on_layout(self.c["scan_key"]) or not key_on_layout(self.c["auto_key"]):
            self.c["scan_key"], self.c["auto_key"] = FALLBACK_KEYS
            self.ui.event("keys", None); self.ui.log(T("keys_swapped", k=pretty_key(FALLBACK_KEYS[0]), a=pretty_key(FALLBACK_KEYS[1])))
        wayland = bool(os.environ.get("WAYLAND_DISPLAY"))
        # Unter Wayland sieht pynput nur Tasten in X11 Fenstern, darum dort das Portal vom System
        pt = wayland and self.portal.start(self.c["scan_key"], self.c["auto_key"])
        self.portal_keys = (self.c["scan_key"], self.c["auto_key"]) if pt else None
        hk = self.hot.start(self.c["scan_key"], self.c["auto_key"])
        if pt:
            self.ui.log(T("started")); self.ui.log(T("hk_portal_wait"))
            if hk: self.ui.log(T("hk_game") + " " + pretty_key(self.c["scan_key"]))
        else:
            self.ui.log(T("started") + ("" if not hk else ", " + T("hk_x11") + " " + pretty_key(self.c["scan_key"])))
            if not hk or wayland: self.ui.log(T("hk_none") + f"  {APP} --scan")
        # Texterkennung im Hintergrund laden, das dauert beim ersten Mal ein paar Sekunden
        def load():
            p = paddle()
            self.ui.log(T("engine_paddle") if p else T("engine_tess") + (f" ({_paddle_err})" if _paddle_err else ""))
        threading.Thread(target=load, daemon=True).start()
        self.show_running()
        if self.c["sounds"]: play("on")
        return True

    def stop(self):
        self.running = False; self.hot.stop(); self.portal.stop(); self.portal_keys = None
        self.ui.event("running", False)
        self.ui.state(T("stopped"), "muted"); self.ui.log(T("stopped"))
        if self.c["sounds"]: play("off")

    def show_running(self):
        if self.pending: self.ui.state(T("q_title1") if len(self.pending) == 1 else T("q_title", n=len(self.pending)), "warn"); return
        self.ui.state(T("running_auto", n=self.c["interval"]) if self.c["mode"] == "auto" else T("running_hot", k=pretty_key(self.c["scan_key"])), "good")

    def loop(self):
        while True:
            time.sleep(.25)
            now = time.time()
            if self.pending and not self.flushing and now >= self.next_web:
                self.next_web = now + 4; self.flushing = True
                threading.Thread(target=self.flush, daemon=True).start()
            if not self.running: continue
            if now >= self.next_ping:
                self.next_ping = now + 60
                threading.Thread(target=self.ping, daemon=True).start()
            if self.c["mode"] == "auto" and not self.busy and now >= self.next_auto:
                self.next_auto = now + self.c["interval"]
                self.scan(True)

    def ping(self):
        """Meldet sich beim Server und sagt, ob die Website mit diesem Code gerade offen ist."""
        try:
            status, raw = post(self.c["url"] + "/api/pair/ping", {"pair": self.c["code"]}, 10)
            return status == 200 and bool(json.loads(raw).get("web"))
        except Exception: return False

    def enqueue(self, body):
        body["auto"] = False
        self.pending.append(body); del self.pending[:-40]
        n = len(self.pending)
        self.ui.log(T("q_log", n=n))
        if self.c["sounds"]: play("queued")
        if self.c["notify"]: notify(T("q_notify"))
        self.ui.event("queue", n); self.show_running(); self.ui.event("popup", None)

    def flush(self):
        try:
            if not self.pending or not self.ping(): return
            sent = 0
            while self.pending:
                try:
                    status, _ = post(self.c["url"] + "/api/pair/scan", self.pending[0])
                    if status == 429: break
                except Exception: break
                self.pending.pop(0); sent += 1
            if sent:
                self.ui.log(T("q_sent", n=sent))
                if self.c["sounds"]: play("ok")
                if self.c["notify"]: notify(T("q_sent", n=sent))
            self.ui.event("queue", len(self.pending))
            if self.running: self.show_running()
            elif not self.pending: self.ui.state(T("stopped"), "muted")
        finally: self.flushing = False

    def scan(self, auto):
        if self.busy:
            if not auto: self.ui.log(T("busy"))
            return
        if not self.running and not auto:
            if not self.start(): return
        self.busy = True
        try:
            try: im, how = screenshot(self.c.get("shot", "auto"), self.c.get("screen", "auto"))
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
                if not TERMINAL_WORDS.search(txt): forget_monitor(); return
            else:
                self.ui.state(T("reading"), "warn")
            shots = [im]
            for _ in range(1 if auto else 2):
                time.sleep(.35)
                try: shots.append(screenshot(self.c.get("shot", "auto"), self.c.get("screen", "auto"))[0])
                except Exception: break
            try:
                ocr = None
                p = paddle()
                if p:
                    try: ocr = p.read(shots[0])
                    except Exception as e: self.ui.log(T("paddle_fail") + f" {e}")
                if not ocr or not any(ps["lines"] for ps in ocr["passes"]): ocr = run_ocr(shots)
            except Exception as e:
                self.ui.log(T("ocr_fail") + f" {e}")
                if not auto: self.ui.state(T("ocr_fail"), "bad")
                return
            body = {"pair": self.c["code"], "auto": auto, "ocr": ocr, "image": jpeg64(im), "time": int(time.time() * 1000)}
            # Nur senden, wenn die Website offen ist, sonst in der App stapeln
            if self.pending or not self.ping():
                self.enqueue(body); return
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
                self.show_running(); self.ui.event("last", (rows, st))
                if self.c["sounds"]: play("ok")
                if self.c["notify"]: notify(T("sent_look", n=rows, st=st).replace("  ", " "))
            elif not auto:
                forget_monitor()
                n = r.get("error") or r.get("note") or T("no_term")
                self.ui.log(n); self.ui.state(n, "warn")
                if self.c["sounds"]: play("err")
        finally:
            self.busy = False
            if self.running and not auto: pass

# ---------------------------------------------------------------- Oberfläche
C = {"bg": "#0c1119", "panel": "#141c28", "panel2": "#1a2433", "line": "#243142", "line2": "#304056", "text": "#eef3f9", "muted": "#8f9db1", "dim": "#66748a",
     "acc": "#35d6cc", "good": "#4ade80", "warn": "#fbbf24", "bad": "#f87171"}

class App:
    """Oberfläche im Stil der Website: hochkant, Reiter Scanner, Einstellungen und Anleitung,
    kleines Fenster im Vordergrund wie beim Windows Rechner."""
    W, H, MW, MH = 400, 790, 300, 176

    def __init__(self, conf, minimized=False):
        import tkinter as tk
        from tkinter import ttk, font as tkfont
        self.tk, self.ttk, self.c = tk, ttk, conf
        self.q = queue.Queue()
        self.root = root = tk.Tk(className=APP)
        root.title(T("title")); root.configure(bg=C["bg"]); root.resizable(False, False)
        fams = set(tkfont.families(root))
        self.ff = next((f for f in ("Inter", "Noto Sans", "Cantarell", "DejaVu Sans", "Liberation Sans") if f in fams), "Sans")
        self.mono = next((f for f in ("JetBrains Mono", "Noto Sans Mono", "DejaVu Sans Mono", "Liberation Mono") if f in fams), "Monospace")
        self.icon_img = None
        try:
            icon = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cargodeck-scanner.png")
            if os.path.exists(icon):
                img = tk.PhotoImage(file=icon); root.iconphoto(True, img)
                small = os.path.join(os.path.dirname(icon), "cargodeck-scanner-36.png")
                if os.path.exists(small): self.icon_img = tk.PhotoImage(file=small)
                else: f = max(1, img.width() // 36); self.icon_img = img.subsample(f, f)
        except Exception: pass
        st = ttk.Style(root)
        try: st.theme_use("clam")
        except Exception: pass
        st.configure("TCombobox", fieldbackground=C["panel2"], background=C["panel2"], foreground=C["text"], arrowcolor=C["acc"], bordercolor=C["line2"], lightcolor=C["panel2"], darkcolor=C["panel2"], padding=5)
        st.map("TCombobox", fieldbackground=[("readonly", C["panel2"])], foreground=[("readonly", C["text"])], selectbackground=[("readonly", C["panel2"])], selectforeground=[("readonly", C["text"])])
        st.configure("Vertical.TScrollbar", background=C["panel2"], troughcolor=C["bg"], bordercolor=C["bg"], arrowcolor=C["muted"], lightcolor=C["panel2"], darkcolor=C["panel2"])
        root.option_add("*TCombobox*Listbox.background", C["panel"]); root.option_add("*TCombobox*Listbox.foreground", C["text"])
        root.option_add("*TCombobox*Listbox.selectBackground", C["acc"]); root.option_add("*TCombobox*Listbox.selectForeground", "#021715")
        root.option_add("*TCombobox*Listbox.font", (self.ff, 10))

        self.logs = []; self.cur_state = (T("ready"), "muted"); self.last = None; self.page = 0; self.body = None
        self.pinned = bool(conf.get("pinned", False))
        self.sc = Scanner(conf, self)
        self.build()
        serve_commands(lambda cmd: self.q.put(("cmd", cmd)))
        root.protocol("WM_DELETE_WINDOW", self.quit)
        root.bind("<Configure>", self._moved)
        root.after(100, self.pump)
        self.log(T("ready"))
        if not tesseract_ok() and not paddle(): self.state(T("no_tess"), "bad")
        threading.Thread(target=lambda: (paddle(), self.q.put(("engine", None))), daemon=True).start()
        if not CODE_RE.match(conf.get("code", "")): self.show_page(2)
        if os.environ.get("CD_PAGE"): self.show_page(int(os.environ["CD_PAGE"]))
        if minimized or conf.get("autostart") or "--was-running" in sys.argv:
            if CODE_RE.match(conf["code"]): root.after(400, self.toggle_run)
            if minimized and not self.pinned: root.after(200, root.iconify)

    # ------------------------------------------------ Bausteine
    def F(self, size=10, bold=False): return (self.ff, size, "bold") if bold else (self.ff, size)

    def card(self, parent, title=None, pady=(0, 10)):
        tk = self.tk
        outer = tk.Frame(parent, bg=C["line"], bd=0); outer.pack(fill="x", pady=pady)
        tk.Frame(outer, bg=C["acc"], height=1).pack(fill="x", padx=40)   # leuchtende Oberkante wie auf der Website
        inner = tk.Frame(outer, bg=C["panel"], bd=0, padx=16, pady=12); inner.pack(fill="both", expand=True, padx=1, pady=(0, 1))
        if title: tk.Label(inner, text=title.upper(), bg=C["panel"], fg=C["muted"], font=self.F(8, True), anchor="w").pack(fill="x", pady=(0, 8))
        return inner

    def lbl(self, parent, text, fg=None, size=10, bold=False, wrap=0, **kw):
        l = self.tk.Label(parent, text=text, bg=parent["bg"], fg=fg or C["text"], font=self.F(size, bold), anchor="w", justify="left", wraplength=wrap or 0, **kw)
        return l

    def entry(self, parent, value="", mono=False):
        e = self.tk.Entry(parent, bg=C["panel2"], fg=C["text"], insertbackground=C["text"], relief="flat", highlightthickness=1,
                          highlightbackground=C["line2"], highlightcolor=C["acc"], font=(self.mono, 13, "bold") if mono else self.F(11))
        e.insert(0, value)
        return e

    def button(self, parent, text, cmd, primary=False, w=360, h=44, size=11, icon=None):
        tk = self.tk
        cv = tk.Canvas(parent, width=w, height=h, bg=parent["bg"], highlightthickness=0, bd=0, cursor="hand2")
        cv.primary = primary; cv.hover = False; cv.text = text; cv.icon = icon
        def draw():
            cv.delete("all")
            if cv.primary: fill = "#5be4db" if cv.hover else C["acc"]; fg = "#0b0f14"; bd = fill
            else: fill = "#212d3e" if cv.hover else C["panel2"]; fg = C["acc"] if cv.hover else C["text"]; bd = C["acc"] if cv.hover else C["line2"]
            self.round_rect(cv, 1, 1, w - 2, h - 2, 10, fill=fill, outline=bd)
            label = (cv.icon + "  " if cv.icon else "") + cv.text
            cv.create_text(w / 2, h / 2, text=label, fill=fg, font=self.F(size, True))
        cv.redraw = draw
        cv.bind("<Enter>", lambda e: (setattr(cv, "hover", True), draw()))
        cv.bind("<Leave>", lambda e: (setattr(cv, "hover", False), draw()))
        cv.bind("<Button-1>", lambda e: cmd())
        draw(); return cv

    def set_btn(self, cv, text=None, primary=None, icon=None):
        if text is not None: cv.text = text
        if primary is not None: cv.primary = primary
        if icon is not None: cv.icon = icon
        cv.redraw()

    def toggle(self, parent, text, var, cmd=None):
        tk = self.tk
        f = tk.Frame(parent, bg=parent["bg"], cursor="hand2")
        cv = tk.Canvas(f, width=40, height=22, bg=parent["bg"], highlightthickness=0, bd=0, cursor="hand2"); cv.pack(side="left")
        l = tk.Label(f, text=text, bg=parent["bg"], fg=C["text"], font=self.F(10), cursor="hand2"); l.pack(side="left", padx=(10, 0))
        def draw():
            cv.delete("all"); on = var.get()
            self.round_rect(cv, 1, 1, 39, 21, 10, fill=C["acc"] if on else C["line2"], outline="")
            x = 21 if on else 4
            cv.create_oval(x, 4, x + 15, 19, fill="#0b0f14" if on else C["text"], outline="")
        def flip(e=None):
            var.set(not var.get()); draw()
            if cmd: cmd()
        for w in (f, cv, l): w.bind("<Button-1>", flip)
        var.trace_add("write", lambda *a: draw())
        draw(); return f

    def seg(self, parent, items, sel, cmd, w=360, h=40, size=10):
        tk = self.tk
        cv = tk.Canvas(parent, width=w, height=h, bg=parent["bg"], highlightthickness=0, bd=0, cursor="hand2")
        cv.sel = sel; cv.hov = -1
        n = len(items); iw = (w - 6) / n
        def draw():
            cv.delete("all")
            self.round_rect(cv, 1, 1, w - 2, h - 2, 10, fill=C["panel"], outline=C["line"])
            for i, it in enumerate(items):
                x0 = 3 + i * iw
                if i == cv.sel: self.round_rect(cv, x0 + 1, 4, x0 + iw - 1, h - 4, 8, fill="#153a3d", outline="#2a8c88")
                col = C["acc"] if i == cv.sel else C["text"] if i == cv.hov else C["muted"]
                cv.create_text(x0 + iw / 2, h / 2, text=it, fill=col, font=self.F(size, i == cv.sel))
        def at(x): return max(0, min(n - 1, int((x - 3) // iw)))
        cv.bind("<Motion>", lambda e: (setattr(cv, "hov", at(e.x)), draw()))
        cv.bind("<Leave>", lambda e: (setattr(cv, "hov", -1), draw()))
        def click(e):
            i = at(e.x)
            if i != cv.sel: cv.sel = i; draw(); cmd(i)
        cv.bind("<Button-1>", click)
        cv.redraw = draw; draw(); return cv

    def icon_btn(self, parent, kind, cmd):
        """Kleiner Knopf mit gezeichneter Nadel (festpinnen) oder Pfeil (zurück zum großen Fenster)."""
        tk = self.tk
        cv = tk.Canvas(parent, width=40, height=30, bg=parent["bg"], highlightthickness=0, bd=0, cursor="hand2"); cv.hover = False
        def draw():
            cv.delete("all")
            col = C["acc"] if cv.hover else C["text"]
            self.round_rect(cv, 1, 1, 38, 28, 8, fill="#212d3e" if cv.hover else C["panel2"], outline=C["acc"] if cv.hover else C["line2"])
            if kind == "pin":
                cv.create_polygon(16, 8, 24, 8, 23, 15, 26, 18, 14, 18, 17, 15, fill="", outline=col, width=1.6)
                cv.create_line(20, 18, 20, 24, fill=col, width=1.6)
            else:
                cv.create_rectangle(12, 9, 28, 21, outline=col, width=1.6)
                cv.create_line(20, 15, 27, 8, fill=col, width=1.6); cv.create_line(23, 8, 27, 8, 27, 12, fill=col, width=1.6)
        cv.bind("<Enter>", lambda e: (setattr(cv, "hover", True), draw()))
        cv.bind("<Leave>", lambda e: (setattr(cv, "hover", False), draw()))
        cv.bind("<Button-1>", lambda e: cmd())
        draw(); return cv

    @staticmethod
    def round_rect(cv, x1, y1, x2, y2, r, **kw):
        pts = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2, x2 - r, y2, x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
        return cv.create_polygon(pts, smooth=True, **kw)

    def dot(self, parent, size=22):
        cv = self.tk.Canvas(parent, width=size, height=size, bg=parent["bg"], highlightthickness=0, bd=0)
        return cv

    def draw_dot(self, cv, kind):
        if not cv or not cv.winfo_exists(): return
        cv.delete("all"); s = int(cv["width"]); col = C.get(kind, C["muted"]) if kind != "muted" else "#66748a"
        glow = {"good": "#1d4b35", "warn": "#4d4020", "bad": "#4d2a2e"}.get(kind, "#262f3c")
        cv.create_oval(1, 1, s - 1, s - 1, fill=glow, outline="")
        m = s * .25; cv.create_oval(m, m, s - m, s - m, fill=col, outline="")

    def scroll_page(self, parent):
        """Seite mit Scrollleiste, Mausrad geht auch."""
        tk, ttk = self.tk, self.ttk
        outer = tk.Frame(parent, bg=C["bg"])
        cv = tk.Canvas(outer, bg=C["bg"], highlightthickness=0, bd=0, width=self.W - 32 - 14)
        sb = ttk.Scrollbar(outer, orient="vertical", command=cv.yview)
        inner = tk.Frame(cv, bg=C["bg"])
        inner.bind("<Configure>", lambda e: cv.configure(scrollregion=cv.bbox("all")))
        win = cv.create_window((0, 0), window=inner, anchor="nw")
        cv.bind("<Configure>", lambda e: cv.itemconfigure(win, width=e.width))
        cv.configure(yscrollcommand=sb.set)
        cv.pack(side="left", fill="both", expand=True); sb.pack(side="right", fill="y")
        def wheel(e):
            d = -1 if (getattr(e, "num", 0) == 4 or getattr(e, "delta", 0) > 0) else 1
            cv.yview_scroll(d * 2, "units")
        for ev in ("<Button-4>", "<Button-5>", "<MouseWheel>"):
            outer.bind_all(ev, lambda e, c=cv: wheel(e) if self.page_canvas is c else None, add="+")
        outer.canvas = cv
        return outer, inner

    # ------------------------------------------------ Aufbau
    def build(self):
        tk = self.tk
        if self.body: self.body.destroy()
        self.body = body = tk.Frame(self.root, bg=C["bg"]); body.pack(fill="both", expand=True)
        self.full = full = tk.Frame(body, bg=C["bg"], padx=16, pady=14)
        self.mini = mini = tk.Frame(body, bg=C["bg"], padx=12, pady=10)
        self.page_canvas = None

        # Kopf
        top = tk.Frame(full, bg=C["bg"]); top.pack(fill="x")
        # rechte Seite zuerst, sonst drückt der lange Untertitel die Sprachwahl zusammen
        self.icon_btn(top, "pin", lambda: self.set_pin(True)).pack(side="right")
        self.seg(top, ["DE", "EN"], 1 if LANG == "en" else 0, lambda i: self.set_lang("en" if i else "de"), w=84, h=30, size=9).pack(side="right", padx=8)
        if self.icon_img: tk.Label(top, image=self.icon_img, bg=C["bg"]).pack(side="left", padx=(0, 10))
        tt = tk.Frame(top, bg=C["bg"]); tt.pack(side="left")
        tr = tk.Frame(tt, bg=C["bg"]); tr.pack(anchor="w")
        tk.Label(tr, text="CARGO", bg=C["bg"], fg=C["text"], font=self.F(15, True)).pack(side="left")
        tk.Label(tr, text="DECK", bg=C["bg"], fg=C["acc"], font=self.F(15, True)).pack(side="left", padx=(6, 0))
        tk.Label(tt, text=f"{T('subtitle')} · v{VERSION}", bg=C["bg"], fg=C["muted"], font=self.F(8)).pack(anchor="w")

        self.nav = self.seg(full, [T("nav_scan"), T("nav_set"), T("nav_help")], self.page, self.show_page, w=self.W - 32, h=40)
        self.nav.pack(fill="x", pady=(14, 12))
        self.pages = [self.build_scan(full), self.build_set(full), self.build_help(full)]
        self.build_mini(mini)
        self.show_page(self.page)
        self.apply_pin()
        self.render_state()

    def build_scan(self, full):
        tk = self.tk
        p = tk.Frame(full, bg=C["bg"])
        c = self.card(p)
        row = tk.Frame(c, bg=C["panel"]); row.pack(fill="x")
        self.dot_big = self.dot(row, 22); self.dot_big.pack(side="left", anchor="n", pady=(3, 0))
        tx = tk.Frame(row, bg=C["panel"]); tx.pack(side="left", fill="x", padx=(10, 0))
        self.st_title = self.lbl(tx, "", size=13, bold=True); self.st_title.pack(anchor="w")
        self.st_sub = self.lbl(tx, "", fg=C["muted"], size=9, wrap=290); self.st_sub.pack(anchor="w")
        self.startbtn = self.button(p, T("start"), self.toggle_run, primary=True, w=self.W - 32, h=54, size=12, icon="▶")
        self.startbtn.pack(pady=(0, 8))
        self.button(p, T("scan_now"), lambda: self.sc.trigger("scan"), w=self.W - 32, h=42, size=10).pack(pady=(0, 10))
        c = self.card(p)
        r = tk.Frame(c, bg=C["panel"]); r.pack(fill="x")
        self.autov = tk.BooleanVar(value=self.c["mode"] == "auto")
        self.toggle(r, T("auto"), self.autov, self.auto_changed).pack(side="left")
        self.lbl(r, T("sec"), fg=C["muted"], size=9).pack(side="right")
        self.interval = tk.IntVar(value=self.c["interval"])
        tk.Spinbox(r, from_=3, to=60, width=3, textvariable=self.interval, command=self.apply, bg=C["panel2"], fg=C["text"], buttonbackground=C["panel2"],
                   insertbackground=C["text"], relief="flat", highlightthickness=1, highlightbackground=C["line2"], font=self.F(10)).pack(side="right", padx=6)
        self.lbl(r, T("every"), fg=C["muted"], size=9).pack(side="right")
        c = self.card(p, T("last_title"))
        self.last_t = self.lbl(c, T("last_none"), size=12, bold=True); self.last_t.pack(anchor="w")
        self.last_s = self.lbl(c, "", fg=C["muted"], size=9, wrap=330); self.last_s.pack(anchor="w")
        c = self.card(p, T("log"), pady=(0, 0))
        self.logbox = tk.Text(c, height=9, bg=C["panel"], fg=C["muted"], relief="flat", font=(self.mono, 9), wrap="word", highlightthickness=0, bd=0)
        self.logbox.pack(fill="both", expand=True)
        for l in self.logs: self.logbox.insert("end", l + "\n")
        self.render_last()
        return p

    def build_set(self, full):
        tk, ttk = self.tk, self.ttk
        outer, p = self.scroll_page(full)
        c = self.card(p, T("conn_title"))
        self.lbl(c, T("site"), fg=C["muted"], size=9).pack(anchor="w")
        self.url = self.entry(c, self.c["url"]); self.url.pack(fill="x", pady=(2, 10), ipady=4)
        self.lbl(c, T("code_lbl"), fg=C["muted"], size=9).pack(anchor="w")
        self.code = self.entry(c, self.c["code"], mono=True); self.code.pack(fill="x", pady=(2, 4), ipady=4)
        self.lbl(c, T("code_hint"), fg=C["dim"], size=8, wrap=320).pack(anchor="w")
        self.qlbl = self.lbl(c, T("q_code", n=len(self.sc.pending)) if self.sc.pending else "", fg=C["warn"], size=9, bold=True); self.qlbl.pack(anchor="w")
        for e in (self.url, self.code): e.bind("<FocusOut>", lambda ev: self.apply())

        c = self.card(p, T("keys_title"))
        self.keys = {}
        for name, lbl in (("scan_key", T("k_scan")), ("auto_key", T("k_auto"))):
            r = tk.Frame(c, bg=C["panel"]); r.pack(fill="x", pady=3)
            self.lbl(r, lbl, size=10).pack(side="left")
            self.button(r, T("record"), lambda n=name: self.record(n), w=96, h=30, size=9).pack(side="right")
            v = tk.StringVar(value=pretty_key(self.c[name])); self.keys[name] = v
            tk.Label(r, textvariable=v, bg=C["panel2"], fg=C["acc"], font=(self.mono, 10, "bold"), padx=8, pady=4, width=10).pack(side="right", padx=8)
        self.lbl(c, T("keys_hint"), fg=C["dim"], size=8, wrap=320).pack(anchor="w", pady=(8, 0))
        tk.Label(c, text=f"{APP} --scan\n{APP} --toggle", bg=C["panel2"], fg=C["text"], font=(self.mono, 9), anchor="w", justify="left", padx=8, pady=4).pack(fill="x", pady=(4, 0))

        c = self.card(p, T("shot"))
        self.shot = tk.StringVar(value=self.c.get("shot", "auto"))
        opts = ["auto"] + [mm[0] for mm in SHOT_METHODS if not mm[1] or shutil.which(mm[1])]
        r = tk.Frame(c, bg=C["panel"]); r.pack(fill="x")
        cb = ttk.Combobox(r, values=opts, textvariable=self.shot, state="readonly", width=14, font=self.F(10)); cb.pack(side="left")
        cb.bind("<<ComboboxSelected>>", lambda e: self.apply())
        self.button(r, T("testshot"), self.test_shot, w=160, h=32, size=9).pack(side="right")
        mons = monitors(); self.screen = None
        if len(mons) > 1:
            self.lbl(c, T("screen"), fg=C["muted"], size=9).pack(anchor="w", pady=(10, 2))
            self.scr_names = {T("scr_auto"): "auto", T("scr_all"): "all"}
            for m in mons: self.scr_names[f"{m[0]}  ({m[3]} × {m[4]})"] = m[0]
            cur = next((k for k, v in self.scr_names.items() if v == self.c.get("screen", "auto")), T("scr_auto"))
            self.screen = tk.StringVar(value=cur)
            cb = ttk.Combobox(c, values=list(self.scr_names), textvariable=self.screen, state="readonly", font=self.F(10)); cb.pack(fill="x")
            cb.bind("<<ComboboxSelected>>", lambda e: self.apply())

        c = self.card(p, T("opt_title"))
        self.sounds = tk.BooleanVar(value=self.c["sounds"]); self.notif = tk.BooleanVar(value=self.c["notify"])
        self.autost = tk.BooleanVar(value=self.c["autostart"]); self.topm = tk.BooleanVar(value=self.c.get("topmost", False))
        for txt, var in ((T("sounds"), self.sounds), (T("notify"), self.notif), (T("autostart"), self.autost), (T("topmost"), self.topm)):
            self.toggle(c, txt, var, self.apply).pack(anchor="w", pady=4)

        c = self.card(p, T("engine_title"))
        self.engine_l = self.lbl(c, T("engine_load"), fg=C["muted"], size=9, wrap=320); self.engine_l.pack(anchor="w")
        self.show_engine()
        return outer

    def build_help(self, full):
        tk = self.tk
        outer, p = self.scroll_page(full)
        self.lbl(p, T("help_title"), size=13, bold=True).pack(anchor="w", pady=(0, 10))
        steps = [("h1_t", "h1"), ("h2_t", "h2"), ("h3_t", "h3"), ("h4_t", "h4"), ("h5_t", "h5")]
        for i, (t, d) in enumerate(steps):
            c = self.card(p)
            r = tk.Frame(c, bg=C["panel"]); r.pack(fill="x")
            n = tk.Canvas(r, width=28, height=28, bg=C["panel"], highlightthickness=0); n.pack(side="left", anchor="n")
            n.create_oval(1, 1, 27, 27, fill=C["acc"], outline=""); n.create_text(14, 14, text=str(i + 1), fill="#0b0f14", font=self.F(11, True))
            tx = tk.Frame(r, bg=C["panel"]); tx.pack(side="left", fill="x", padx=(12, 0))
            self.lbl(tx, T(t), size=10, bold=True).pack(anchor="w")
            self.lbl(tx, T(d, k=pretty_key(self.c["scan_key"])), fg=C["muted"], size=9, wrap=280).pack(anchor="w")
        c = self.card(p, T("tips_title"))
        for tk_ in ("tip1", "tip2", "tip3", "tip4"):
            r = tk.Frame(c, bg=C["panel"]); r.pack(fill="x", pady=3)
            tk.Label(r, text="•", bg=C["panel"], fg=C["acc"], font=self.F(11, True)).pack(side="left", anchor="n")
            self.lbl(r, T(tk_), fg=C["muted"], size=9, wrap=300).pack(side="left", padx=(6, 0))
        def site():
            try: subprocess.Popen(["xdg-open", self.c.get("url") or "https://cargodeck.onrender.com"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except Exception: pass
        self.button(p, T("open_site"), site, primary=True, w=self.W - 52, h=40, size=10).pack(pady=(4, 16))
        return outer

    def build_mini(self, m):
        tk = self.tk
        r = tk.Frame(m, bg=C["bg"]); r.pack(fill="x")
        self.dot_mini = self.dot(r, 20); self.dot_mini.pack(side="left", anchor="n", pady=(2, 0))
        tx = tk.Frame(r, bg=C["bg"]); tx.pack(side="left", fill="x", padx=(8, 0))
        self.mini_t = self.lbl(tx, "", size=11, bold=True); self.mini_t.pack(anchor="w")
        self.mini_s = self.lbl(tx, "", fg=C["muted"], size=8, wrap=210); self.mini_s.pack(anchor="w")
        self.icon_btn(r, "unpin", lambda: self.set_pin(False)).pack(side="right", anchor="n")
        b = tk.Frame(m, bg=C["bg"]); b.pack(fill="x", pady=(10, 6))
        self.button(b, T("k_scan"), lambda: self.sc.trigger("scan"), primary=True, w=134, h=42, size=10).pack(side="left")
        self.mini_auto = self.button(b, T("auto_short"), lambda: (self.autov.set(not self.autov.get()), self.auto_changed()), primary=self.c["mode"] == "auto", w=134, h=42, size=10)
        self.mini_auto.pack(side="right")
        self.mini_last = self.lbl(m, T("last_none"), fg=C["muted"], size=8, wrap=270); self.mini_last.pack(anchor="w")

    # ------------------------------------------------ Seiten und Fenster
    def show_page(self, i):
        self.page = i
        if getattr(self, "nav", None) and self.nav.sel != i: self.nav.sel = i; self.nav.redraw()
        for n, pg in enumerate(getattr(self, "pages", [])):
            if n == i: pg.pack(fill="both", expand=True)
            else: pg.pack_forget()
        self.page_canvas = getattr(self.pages[i], "canvas", None) if getattr(self, "pages", None) else None

    def apply_pin(self):
        r = self.root
        if self.pinned:
            self.full.pack_forget(); self.mini.pack(fill="both", expand=True)
            x, y = self.c.get("pin_x", -1), self.c.get("pin_y", -1)
            if x is None or x < 0: x = r.winfo_screenwidth() - self.MW - 24; y = r.winfo_screenheight() - self.MH - 80
            r.geometry(f"{self.MW}x{self.MH}+{x}+{y}")
            try: r.attributes("-topmost", True)
            except Exception: pass
        else:
            self.mini.pack_forget(); self.full.pack(fill="both", expand=True)
            r.geometry(f"{self.W}x{self.H}")
            try: r.attributes("-topmost", bool(self.c.get("topmost", False)))
            except Exception: pass

    def set_pin(self, on):
        self.pinned = on; self.c["pinned"] = on; self.save(); self.apply_pin()

    def _moved(self, e):
        if e.widget is self.root and self.pinned:
            self.c["pin_x"], self.c["pin_y"] = self.root.winfo_x(), self.root.winfo_y()

    # ------------------------------------------------ Zustand
    def log(self, t): self.q.put(("log", t))
    def state(self, t, kind): self.q.put(("state", (t, kind)))
    def event(self, what, val): self.q.put((what, val))

    def sub_text(self, kind):
        if self.sc.pending and kind == "warn": return T("q_sub")
        if self.sc.running and kind in ("good", "warn"):
            return T("sub_auto", n=self.c["interval"]) if self.c["mode"] == "auto" else T("sub_hot", k=pretty_key(self.c["scan_key"]))
        if not self.sc.running and kind == "muted": return T("sub_stopped")
        return ""

    def render_state(self):
        t, kind = self.cur_state; sub = self.sub_text(kind)
        for w, v in ((getattr(self, "st_title", None), t), (getattr(self, "mini_t", None), t), (getattr(self, "st_sub", None), sub), (getattr(self, "mini_s", None), sub)):
            if w and w.winfo_exists(): w.config(text=v)
        for w in (getattr(self, "st_title", None), getattr(self, "mini_t", None)):
            if w and w.winfo_exists(): w.config(fg=C["text"] if kind in ("muted", "good") else C.get(kind, C["text"]))
        self.draw_dot(getattr(self, "dot_big", None), kind); self.draw_dot(getattr(self, "dot_mini", None), kind)
        if getattr(self, "startbtn", None): self.set_btn(self.startbtn, T("stop") if self.sc.running else T("start"), primary=not self.sc.running, icon="■" if self.sc.running else "▶")

    def render_last(self):
        if not self.last: return
        n, st, t = self.last
        title = T("last_ok", n=n, t=t) + (f", {st}" if st else "")
        for w, v in ((getattr(self, "last_t", None), title), (getattr(self, "last_s", None), T("last_look")), (getattr(self, "mini_last", None), title)):
            if w and w.winfo_exists(): w.config(text=v)

    def show_engine(self):
        l = getattr(self, "engine_l", None)
        if not l or not l.winfo_exists(): return
        if _paddle: l.config(text=T("engine_paddle_s"), fg=C["good"])
        elif _paddle_err: l.config(text=T("engine_tess_s") + f" ({_paddle_err})", fg=C["warn"])
        else: l.config(text=T("engine_load"), fg=C["muted"])

    def pump(self):
        try:
            while True:
                kind, v = self.q.get_nowait()
                if kind == "log":
                    line = time.strftime("%H:%M:%S  ") + v
                    self.logs.insert(0, line); del self.logs[80:]
                    if self.logbox.winfo_exists(): self.logbox.insert("1.0", line + "\n"); self.logbox.delete("80.0", "end")
                elif kind == "state":
                    self.cur_state = v; self.render_state()
                elif kind == "last":
                    self.last = (v[0], v[1], time.strftime("%H:%M")); self.render_last()
                elif kind == "engine": self.show_engine()
                elif kind == "mode":
                    self.autov.set(v == "auto"); self.set_btn(self.mini_auto, primary=v == "auto"); self.save()
                    if self.sc.running: self.sc.show_running()
                elif kind == "keys":
                    for n in ("scan_key", "auto_key"): self.keys[n].set(pretty_key(self.c[n]))
                    self.save()
                elif kind == "running": self.render_state()
                elif kind == "queue":
                    l = getattr(self, "qlbl", None)
                    if l and l.winfo_exists(): l.config(text=T("q_code", n=v) if v else "")
                    ls = getattr(self, "last_s", None)
                    if v and ls and ls.winfo_exists(): ls.config(text=T("q_sub"))
                elif kind == "popup":
                    # Fenster zeigen und nach vorne holen, ohne es dauerhaft oben zu halten
                    self.root.deiconify(); self.root.lift()
                    try:
                        self.root.attributes("-topmost", True)
                        self.root.after(1500, lambda: self.root.attributes("-topmost", bool(self.c.get("topmost") or self.c.get("pinned"))))
                    except Exception: pass
                elif kind == "show":
                    self.root.deiconify(); self.root.lift()
                elif kind == "cmd":
                    if v in ("scan", "toggle"): self.sc.trigger(v)
                    elif v == "show": self.root.deiconify(); self.root.lift()
        except queue.Empty: pass
        self.root.after(80, self.pump)

    # ------------------------------------------------ Einstellungen
    def auto_changed(self):
        self.c["mode"] = "auto" if self.autov.get() else "hotkey"
        self.set_btn(self.mini_auto, primary=self.autov.get())
        self.apply()

    def read(self):
        self.c["url"] = self.url.get().strip().rstrip("/")
        self.c["code"] = self.code.get().strip().upper().replace(" ", "")
        self.c["mode"] = "auto" if self.autov.get() else "hotkey"
        try: self.c["interval"] = max(3, min(60, int(self.interval.get())))
        except Exception: pass
        self.c["sounds"] = self.sounds.get(); self.c["notify"] = self.notif.get(); self.c["autostart"] = self.autost.get()
        self.c["topmost"] = self.topm.get()
        if not self.pinned:
            try: self.root.attributes("-topmost", self.c["topmost"])
            except Exception: pass
        self.c["shot"] = self.shot.get() or "auto"; self.c["lang"] = LANG
        if self.screen is not None: self.c["screen"] = self.scr_names.get(self.screen.get(), "auto")

    def save(self):
        try: save_conf(self.c)
        except Exception as e: self.log(str(e))

    def apply(self):
        self.read(); self.save()
        if self.sc.running:
            self.sc.show_running()
            self.sc.hot.start(self.c["scan_key"], self.c["auto_key"])
            # Portal nur neu anmelden, wenn sich die Tasten geändert haben, sonst fragt das System jedes Mal
            keys = (self.c["scan_key"], self.c["auto_key"])
            if os.environ.get("WAYLAND_DISPLAY") and keys != self.sc.portal_keys:
                if self.sc.portal.start(*keys): self.sc.portal_keys = keys; self.log(T("hk_portal_wait"))
        else: self.render_state()

    def toggle_run(self):
        self.read(); self.save()
        if self.sc.running: self.sc.stop()
        else:
            if not self.sc.start(): self.show_page(1) if not self.pinned else None

    def test_shot(self):
        self.read()
        def go():
            try:
                forget_monitor()
                im, how = screenshot(self.c["shot"], self.c.get("screen", "auto")); self.log(T("shot_ok", m=how, w=im.width, h=im.height))
                out = os.path.join(os.path.expanduser("~"), "cargodeck-screenshot-test.png"); im.save(out); self.log(T("shot_saved", p=out))
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
            special = {"Return": "<enter>", "space": "<space>", "Tab": "<tab>", "Escape": "<esc>", "BackSpace": "<backspace>", "Insert": "<insert>", "Delete": "<delete>",
                       "Home": "<home>", "End": "<end>", "Prior": "<page_up>", "Next": "<page_down>", "Up": "<up>", "Down": "<down>", "Left": "<left>", "Right": "<right>"}
            if re.fullmatch(r"F\d+", e.keysym): key = "<" + e.keysym.lower() + ">"
            elif e.keysym in special: key = special[e.keysym]
            elif e.char and e.char.isprintable() and len(e.char) == 1 and e.char != " ": key = e.char.lower()
            # mit Strg liefert Tk ein Steuerzeichen, dann das Zeichen der Taste selbst nehmen
            elif 32 < e.keysym_num < 256: key = chr(e.keysym_num).lower()
            elif len(e.keysym) == 1: key = e.keysym.lower()
            else: return "break"
            if re.fullmatch(r"<f\d+>", key) or held:
                combo = "+".join(held + [key]); self.c[name] = combo; self.keys[name].set(pretty_key(combo))
                self.root.unbind("<KeyPress>"); self.apply()
            return "break"
        self.root.bind("<KeyPress>", down); self.root.focus_force()

    def set_lang(self, lang):
        """Sprache sofort umstellen, ohne Neustart. Einstellungen und Verlauf bleiben."""
        global LANG
        try: self.read()
        except Exception: pass
        LANG = lang; self.c["lang"] = lang; self.save()
        self.root.title(T("title"))
        if self.sc.running: self.sc.show_running()
        elif self.cur_state[1] == "muted": self.cur_state = (T("stopped") if self.cur_state[0] in (TEXT["stopped"][0], TEXT["stopped"][1]) else T("ready"), "muted")
        self.build()

    def quit(self):
        try: self.read(); self.save()
        except Exception: pass
        self.sc.hot.stop(); self.sc.portal.stop()
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
            if not send_command(cmd): print("Cargo Deck Price Capture läuft nicht / is not running"); sys.exit(1)
            return
    if args[:1] == ["--ocr-test"] and len(args) >= 3:
        from PIL import Image
        im = Image.open(args[1]).convert("RGB")
        p = paddle()
        t = time.time(); r = p.read(im) if p and "--tesseract" not in args else run_ocr([im]); r["seconds"] = round(time.time() - t, 1)
        if not p: print("PaddleOCR fehlt:", _paddle_err)
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
