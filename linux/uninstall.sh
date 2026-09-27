#!/usr/bin/env bash
# Cargo Deck Price Capture entfernen / remove. Pakete wie tesseract bleiben installiert.
APP=cargodeck-scanner
"$HOME/.local/bin/$APP" --version >/dev/null 2>&1 && pkill -f "$APP.py" 2>/dev/null
rm -rf "$HOME/.local/share/$APP" "$HOME/.local/bin/$APP" "$HOME/.local/share/applications/$APP.desktop" "$HOME/.local/share/applications/io.github.baneuncutted.CargoDeckScanner.desktop" \
       "$HOME/.local/share/icons/hicolor/256x256/apps/$APP.png" "$HOME/.config/autostart/$APP.desktop"
echo "Entfernt. Deine Einstellungen liegen noch in ~/.config/cargodeck (einfach löschen, wenn du sie nicht mehr brauchst)."
