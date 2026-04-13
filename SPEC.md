# FreeWispr-SV — Svensk speech-to-text för Windows

> **OBS: Detta dokument är den ursprungliga designspecifikationen från innan implementation.**
> **Den aktuella arkitekturen och funktionaliteten beskrivs i [README.md](README.md).**
> **Många detaljer nedan (t.ex. filler-ord, språkväljare, filstruktur) stämmer inte längre.**

> **Fork av:** [x26prakhar/freewispr](https://github.com/x26prakhar/freewispr)
> **Licens:** MIT
> **Mål:** Svensk speech-to-text med KB-Whisper, fortfarande Windows-only

---

## 1. Översikt

**Problemet:** Freewispr är utmärkt, men är optimerat för engelska. Svenska användare får sämre precision.

**Lösningen:** Fork med KBLab:s svenska Whisper-modeller (47% lägre WER på svenska).

**Målgrupp:** Svenska Windows-användare som vill ha lokal, privat, gratis speech-to-text.

---

## 2. Modeller

### Primär modell: `KBLab/kb-whisper-small`
- **Storlek:** ~500 MB
- **WER:** 7.3 (vs 20.6 för openai/whisper-small)
- **Format:** ctranslate2 (faster-whisper kompatibelt)

### Sekundära alternativ:
| Modell | WER | Storlek | Användning |
|--------|-----|---------|------------|
| `KBLab/kb-whisper-tiny` | 13.2 | ~40 MB | Låg latency, testning |
| `KBLab/kb-whisper-base` | 9.1 | ~150 MB | Balanserat |
| `KBLab/kb-whisper-small` | 7.3 | ~500 MB | **Default** |
| `KBLab/kb-whisper-medium` | 6.6 | ~1.5 GB | Hög precision |

---

## 3. Funktionalitet

### 3.1 Core Features (behåll från original)
- [ ] **Hold-to-talk hotkey** — Ctrl+Space (configurerbar)
- [ ] **Floating indicator** — Purple/Amber/Green states
- [ ] **Automatisk paste** — Text klistras vid cursor
- [ ] **System tray** — Bakgrundsläge, start med Windows
- [ ] **Multi-model stöd** — Växla mellan KB-modeller i Settings
- [ ] **Start with Windows** — Toggle i tray menu

### 3.2 Nya Features
- [ ] **KB-Whisper som default** — Svenska modeller förinstallerade
- [ ] **Språk: Svenska default** — ISO `sv`, ej `en`
- [ ] **Svenska filler-ord** — Ta bort "eh", "mm", "öh", "liksom", "typ", "ba" etc.
- [ ] **Svenska språkpaket** — Modellnedladdning från HuggingFace mirror (ev. svensk mirror)

### 3.3 Filler-ord att ta bort (svenska)
```
eh, em, öh, öhm, ah, ja, alltså, liksom, typ, ba, bara, 
大概, kanske, ju, nog, alltså, liksom, liknande
```

---

## 4. Teknisk Arkitektur

```
freewispr-sv/
├── main.py                 # Entry point (behåll struktur)
├── transcriber.py          # Byt till faster-whisper + KB-modell
├── hotkey.py              # Windows hotkey (behåll)
├── indicator.py           # Floating window (behåll)
├── settings.py            # Settings UI + model selection
├── lang/
│   └── sv.py              # Svenska filler-ord
├── assets/
│   └── icon.ico           # Uppdatera med "SV" badge
├── requirements.txt       # Lägg till faster-whisper, kb-whisper
├── SPEC.md                # Denna fil
└── README.md              # Svensk dokumentation
```

### Dependencies (nytt i requirements.txt):
```
faster-whisper>=1.0.0
torch
```

---

## 5. Konfiguration

### Inställningar (settings.json):
```json
{
  "model": "KBLab/kb-whisper-small",
  "language": "sv",
  "hotkey": "ctrl+space",
  "start_with_windows": false,
  "filler_removal": true,
  "filler_words": ["eh", "em", "öh", "öhm", "liksom", "typ", "ba", "bara"],
  "auto_download_model": true,
  "model_path": "~/.freewispr-sv/models/"
}
```

---

## 6. UI/UX

### 6.1 Tray Menu
- FreeWispr SV
- Settings → [KB-Whisper: Small ▼]
- Language: [Swedish ▼]
- Filler removal: [✓]
- ─────────────
- Start with Windows
- Quit

### 6.2 Indicator States
| State | Färg | Text |
|-------|------|------|
| Listening | 🔴 Lila | "Lyssnar..." |
| Transcribing | 🟡 Amber | "Transkriberar..." |
| Done | 🟢 Grön | "Klar ✓" |
| Error | 🔴 Röd | "Fel" |

### 6.3 Settings Window
- **Modell:** Dropdown (tiny/base/small/medium)
- **Språk:** Dropdown (sv, en, fi, no, da + 99 andra)
- **Hotkey:** Key recorder
- **Filler removal:** Checkbox + lista att redigera
- **Start with Windows:** Toggle
- **Model path:** Text input + Browse

---

## 7. Bygg & Release

### Byggprocess
```bash
pip install -r requirements.txt
python main.py              # Development
build.bat                   # PyInstaller → dist/freewispr-sv.exe
```

### Release-filer
- `dist/freewispr-sv.exe` — Single-file executable
- Modellfiler → laddas ner vid första körning (~500 MB)

### GitHub
```
Fork: x26prakhar/freewispr → hhammarstrand/freewispr-sv
License: MIT (behåll copyright notice)
```

---

## 8. Framtida Möjligheter

- [ ] Linux-port (pyaudio + pynput)
- [ ] macOS-version (objc-hotkeys)
- [ ] OpenAI Whisper compat-läge
- [ ] Team/enterprise features (central modell-hämtning)
- [ ] OBS-plugin integration

---

## 9. Att-göra (TODO)

### Phase 1: Setup
- [ ] Forka repo på GitHub
- [ ] Klona lokalt
- [ ] Skapa branch: `feature/kb-whisper`
- [ ] Updatera requirements.txt

### Phase 2: Core
- [ ] Byt modell till KBLab i transcriber.py
- [ ] Lägg till svenska som default-språk
- [ ] Testa med `kb-whisper-tiny` först (snabbare iteration)

### Phase 3: Svenska Features
- [ ] Implementera svenska filler-ord
- [ ] Updatera UI-text till svenska
- [ ] Lägg till "SV" badge på icon

### Phase 4: Build & Release
- [ ] Testa build.bat
- [ ] Release v1.0.0
- [ ] Uppdatera README.md

---

## 10. Kända Riskér

| Risk | Lösnning |
|------|----------|
| KB-modell storlek (~500MB) | Lazy-load, visa nedladdnings进度 |
| Svenska tecken (åäö) | Testa output encoding |
| Minnesanvändning | ctranslate2 med INT8 |
