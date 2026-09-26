# Cargo Deck Scanner für Linux

Liest das Handelsterminal in Star Citizen und schickt Preise und Bestand an [Cargo Deck](https://cargodeck.onrender.com). Die Texterkennung läuft lokal mit Tesseract, an die Seite gehen nur der erkannte Text und ein verkleinertes Bild.

## Installieren

```
tar xzf CargoDeckScanner-linux.tar.gz
cd cargodeck-scanner-linux
./install.sh
```

Das Skript installiert Python mit Tk, Pillow, Tesseract und bei Bedarf ein Screenshot Werkzeug über deine Paketverwaltung (apt, dnf, pacman, zypper). Die App selbst landet nur in deinem Benutzerordner.

## Benutzen

1. Auf der Website unter Einstellungen den Code kopieren und in der App eintragen.
2. Start drücken.
3. Im Spiel am Terminal **Strg + Ö** drücken, oder Automatik einschalten.

**X11 und die meisten Spiele unter Proton oder Wine** nutzen die Tastenkürzel direkt.

**Wayland ohne X11 Fenster:** In den Systemeinstellungen ein eigenes Tastenkürzel anlegen mit dem Befehl `cargodeck-scanner --scan` (Automatik umschalten mit `--toggle`).

Screenshots gehen unter X11 direkt, unter Wayland über grim (Sway, Hyprland), spectacle (KDE) oder gnome-screenshot (GNOME). Mit "Screenshot testen" siehst du, was funktioniert.

## Entfernen

`./uninstall.sh`

---

# Cargo Deck Scanner for Linux

Reads the Star Citizen trade terminal and sends prices and stock to Cargo Deck. Text recognition runs locally with Tesseract.

Install with `./install.sh`, enter the code from the website settings, press Start, then press **Ctrl + Ö** at the terminal in game or turn on auto mode. On pure Wayland, create a system keyboard shortcut with the command `cargodeck-scanner --scan`.
