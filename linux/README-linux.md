# Cargo Deck Price Capture für Linux

Liest das Handelsterminal in Star Citizen und schickt Preise und Bestand an [Cargo Deck](https://cargodeck.onrender.com). Die Texterkennung läuft lokal mit PaddleOCR, der gleichen Technik wie auf der Website. Fehlt die, liest Tesseract. An die Seite gehen nur der erkannte Text und ein verkleinertes Bild.

## Installieren

```
tar xzf CargoDeckPriceCapture-linux.tar.gz
cd cargodeck-price-capture-linux
./install.sh
```

Das Skript installiert Python mit Tk, Pillow, numpy, onnxruntime, Tesseract und bei Bedarf ein Screenshot Werkzeug über deine Paketverwaltung (apt, dnf, pacman, zypper). Die App selbst landet nur in deinem Benutzerordner.

## Benutzen

1. Auf der Website unter Einstellungen den Code kopieren und in der App eintragen.
2. Start drücken.
3. Im Spiel am Terminal **Strg + Ö** drücken, oder Automatik einschalten.

**X11 und die meisten Spiele unter Proton oder Wine** nutzen die Tastenkürzel direkt.

**Wayland (Fedora, KDE Plasma, GNOME 48 oder neuer, Hyprland):** Beim ersten Start fragt das System in einem Fenster nach den Tastenkürzeln, dort bestätigen. Ändern kannst du sie später in den Systemeinstellungen unter Tastenkürzel.

**Älteres GNOME oder wenn kein Fenster kommt:** In den Systemeinstellungen ein eigenes Tastenkürzel anlegen mit dem Befehl `cargodeck-scanner --scan` (Automatik umschalten mit `--toggle`).

Screenshots gehen unter X11 direkt, unter Wayland über grim (Sway, Hyprland), spectacle (KDE) oder das System Portal (GNOME, fragt einmal nach der Erlaubnis). Mit "Screenshot testen" siehst du, was funktioniert.

## Entfernen

`./uninstall.sh`

---

# Cargo Deck Price Capture for Linux

Reads the Star Citizen trade terminal and sends prices and stock to Cargo Deck. Text recognition runs locally with Tesseract.

Install with `./install.sh`, enter the code from the website settings, press Start, then press **Ctrl + Ö** at the terminal in game or turn on auto mode. On Wayland (KDE, GNOME 48+, Hyprland) the system asks once to confirm the shortcuts. On older GNOME, create a system keyboard shortcut with the command `cargodeck-scanner --scan`.
