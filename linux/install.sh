#!/usr/bin/env bash
# Cargo Deck Scanner für Linux installieren / install Cargo Deck Scanner for Linux
# Installiert nur für deinen Benutzer, nach ~/.local. Pakete kommen aus deiner Distribution.
set -e
cd "$(dirname "$0")"
APP=cargodeck-scanner
DEST="$HOME/.local/share/$APP"
BIN="$HOME/.local/bin"

say(){ printf '\033[1;36m%s\033[0m\n' "$*"; }
warn(){ printf '\033[1;33m%s\033[0m\n' "$*"; }

say "Cargo Deck Scanner, Installation"

# ---- Pakete: Python mit Tk, Pillow, Tesseract mit Englisch, Meldungen
SUDO=""; [ "$(id -u)" -ne 0 ] && command -v sudo >/dev/null && SUDO=sudo
if command -v apt-get >/dev/null; then
  $SUDO apt-get update -qq || true
  $SUDO apt-get install -y python3 python3-tk python3-pil tesseract-ocr tesseract-ocr-eng libnotify-bin
  $SUDO apt-get install -y python3-pynput 2>/dev/null || true
elif command -v dnf >/dev/null; then
  $SUDO dnf install -y python3 python3-tkinter python3-pillow tesseract tesseract-langpack-eng libnotify
  $SUDO dnf install -y python3-pynput 2>/dev/null || true
elif command -v pacman >/dev/null; then
  $SUDO pacman -S --needed --noconfirm python tk python-pillow tesseract tesseract-data-eng libnotify
  $SUDO pacman -S --needed --noconfirm python-pynput 2>/dev/null || true
elif command -v zypper >/dev/null; then
  $SUDO zypper install -y python3 python3-tk python3-Pillow tesseract-ocr tesseract-ocr-traineddata-english libnotify-tools
  $SUDO zypper install -y python3-pynput 2>/dev/null || true
else
  warn "Paketverwaltung nicht erkannt. Bitte selbst installieren: python3, tkinter, Pillow, tesseract (mit Englisch), notify-send"
fi

# Tastenkürzel unter X11 brauchen pynput, notfalls für den Benutzer über pip
if ! python3 -c "import pynput" 2>/dev/null; then
  python3 -m pip install --user pynput 2>/dev/null || python3 -m pip install --user --break-system-packages pynput 2>/dev/null || \
    warn "pynput nicht installiert. Tastenkürzel dann über die Systemeinstellungen mit dem Befehl: $APP --scan"
fi

# Unter Wayland braucht es ein Screenshot Werkzeug des Desktops
if [ -n "$WAYLAND_DISPLAY" ]; then
  if ! command -v grim >/dev/null && ! command -v spectacle >/dev/null && ! command -v gnome-screenshot >/dev/null && ! command -v flameshot >/dev/null; then
    case "${XDG_CURRENT_DESKTOP,,}" in
      *kde*) PKG=spectacle ;;
      *gnome*) PKG=gnome-screenshot ;;
      *) PKG=grim ;;
    esac
    warn "Wayland erkannt, installiere $PKG für Screenshots"
    if command -v apt-get >/dev/null; then $SUDO apt-get install -y $PKG || true
    elif command -v dnf >/dev/null; then $SUDO dnf install -y $PKG || true
    elif command -v pacman >/dev/null; then $SUDO pacman -S --needed --noconfirm $PKG || true
    elif command -v zypper >/dev/null; then $SUDO zypper install -y $PKG || true; fi
  fi
fi

# ---- Dateien
mkdir -p "$DEST" "$BIN" "$HOME/.local/share/applications" "$HOME/.local/share/icons/hicolor/256x256/apps"
cp cargodeck-scanner.py cargodeck-scanner.png "$DEST/"
cp cargodeck-scanner.png "$HOME/.local/share/icons/hicolor/256x256/apps/$APP.png"
cat > "$BIN/$APP" <<EOF
#!/bin/sh
exec python3 "$DEST/cargodeck-scanner.py" "\$@"
EOF
chmod +x "$BIN/$APP" "$DEST/cargodeck-scanner.py"
cat > "$HOME/.local/share/applications/$APP.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Cargo Deck Scanner
Comment=Star Citizen Handelsterminal lesen und an Cargo Deck senden
Exec=$BIN/$APP
Icon=$APP
Terminal=false
Categories=Game;Utility;
EOF
update-desktop-database "$HOME/.local/share/applications" 2>/dev/null || true

say "Fertig. Starten über das Menü (Cargo Deck Scanner) oder mit: $APP"
case ":$PATH:" in *":$BIN:"*) ;; *) warn "Hinweis: $BIN ist nicht im PATH, sonst mit $BIN/$APP starten" ;; esac
if [ -n "$WAYLAND_DISPLAY" ]; then
  say "Wayland: Leg in den Systemeinstellungen ein Tastenkürzel an mit dem Befehl  $BIN/$APP --scan"
fi
