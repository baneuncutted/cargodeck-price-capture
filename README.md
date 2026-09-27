# Cargo Deck Price Capture

App für Windows und Linux für [Cargo Deck](https://cargodeck.onrender.com). Sie liest Preise und Bestand vom Handelsterminal in Star Citizen und schickt sie an deine Cargo Deck Seite.

## Herunterladen

Rechts unter **Releases** die neueste Version öffnen.

**Windows** `CargoDeckPriceCapture.exe` laden. Keine Installation nötig, einfach starten.

**Linux** `CargoDeckPriceCapture-linux.tar.gz` laden, entpacken und `./install.sh` ausführen. Mehr dazu in `linux/README-linux.md`.

Windows zeigt beim ersten Start eventuell "Der Computer wurde durch Windows geschützt", weil die App nicht signiert ist. Dann auf **Weitere Informationen** und **Trotzdem ausführen**.

## So gehts

1. Auf Cargo Deck unter **Einstellungen, Price Capture** den Kopplungscode kopieren
2. In der App einfügen und **Starten** drücken
3. Im Spiel am Terminal **Linke Strg + ö** drücken, oder die Automatik einschalten

Mit der Nadel oben rechts wird die App zu einem kleinen Fenster, das immer im Vordergrund bleibt. Oben rechts lässt sich auch die Sprache umstellen, Deutsch oder Englisch.

Die Automatik schaut alle paar Sekunden aufs Bild und sendet nur, wenn wirklich ein Handelsterminal zu sehen ist. Mit **Linke Strg + ä** schaltest du sie im Spiel an und aus.

Star Citizen am besten im Modus **Rahmenloses Fenster** spielen, im echten Vollbild bleibt der Screenshot schwarz.

## Was die App macht und was nicht

- Macht einen Screenshot vom aktiven Fenster, nur wenn du die Taste drückst oder die Automatik läuft
- Liest den Text mit PaddleOCR, der gleichen Texterkennung wie auf der Website, alles auf deinem PC. Die Modelle liegen im Ordner `ocr`
- Geht das mal nicht, liest unter Windows die eingebaute Texterkennung und unter Linux Tesseract
- Schickt den erkannten Text und ein verkleinertes Bild an die Adresse, die du einträgst
- Liest keine Spieldateien, greift nicht ins Spiel ein und drückt keine Tasten
- Speichert ihre Einstellungen in `%APPDATA%\CargoDeck\scanner.json`

Der ganze Quellcode liegt hier im Repo. Die exe wird von GitHub selbst aus genau diesem Code gebaut, siehe `.github/workflows/build.yml`, das Linux Paket mit `.github/workflows/linux.yml`. Die Prüfsumme steht beim Release in `SHA256.txt`.

## Selbst bauen

.NET 8 SDK installieren, dann

```
dotnet publish CargoDeckScanner.csproj -c Release -o out
```

## Hinweis

Inoffizielles Fanprojekt, nicht mit Cloud Imperium Games verbunden.
