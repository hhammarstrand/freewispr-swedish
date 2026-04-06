<div align="center">

<img src="assets/icon.ico" width="80" height="80" alt="freewispr icon" />

# freewispr

**Free, local, open-source speech-to-text for Windows.**  
Dictate anywhere. 100% on-device. No cloud. No subscription.

[![Platform](https://img.shields.io/badge/platform-Windows%2010%2F11-0078d4?style=flat-square)](https://github.com/x26prakhar/freewispr/releases)
[![License](https://img.shields.io/badge/license-MIT-22c55e?style=flat-square)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.10%2B-f59e0b?style=flat-square)](https://python.org)
[![Latest Release](https://img.shields.io/github/v/release/x26prakhar/freewispr?style=flat-square&color=7c5cfc)](https://github.com/x26prakhar/freewispr/releases/latest)

[Download](#install) · [Features](#features) · [Build from Source](#build-from-source)

</div>

---

## What is freewispr?

freewispr is a lightweight Windows tray app that brings speech-to-text to your entire computer — no account, no internet connection, no subscription.

Hold a hotkey, speak, release. The transcribed text is instantly pasted wherever your cursor is — browser, Word, Notepad, Slack, VS Code, anywhere.

All processing runs locally on your CPU using [faster-whisper](https://github.com/SYSTRAN/faster-whisper) with INT8 quantization. Your audio never leaves your device.

---

## Dictation

Hold `Ctrl+Space` (configurable) → speak → release. The transcribed text is instantly pasted wherever your cursor is.

A **floating indicator pill** appears at the top of your screen so you always know what's happening:

| State | Indicator |
|---|---|
| Listening | Purple dot — recording |
| Transcribing | Amber dot — processing |
| Done | Green dot — text pasted ✓ |

**Optional:** enable **filler word removal** in Settings to automatically strip "um", "uh", "you know", "basically" etc. from your output.

---

## Features

- **Dictation** — hold-to-talk hotkey, pastes at cursor, works in every app
- **Floating indicator** — always-on-top pill shows Listening / Transcribing / Pasted states
- **Filler word removal** — strips um/uh/you know/basically from output (toggle in Settings)
- **Configurable hotkey** — any combo: `ctrl+space`, `right ctrl`, `F9`, `alt+shift`, etc.
- **Multi-model support** — switch between `tiny`, `base`, `small` Whisper models in Settings
- **Multi-language** — 99 languages supported (set ISO code in Settings: `en`, `es`, `fr`, `de`, `hi`…)
- **Start with Windows** — one-click toggle in tray menu via Windows registry
- **System tray** — lives quietly in the background, zero UI until you need it
- **No install needed** — single `.exe`, just run it
- **Fully offline** — no telemetry, no analytics, no accounts

---

## Install

### Download (recommended)

Download the latest `freewispr.exe` from [**Releases**](https://github.com/x26prakhar/freewispr/releases/latest).

**Requirements:** Windows 10 or Windows 11

```
1. Download freewispr.exe
2. Double-click to run — no installer needed
3. A purple mic icon appears in your system tray
4. Hold Ctrl+Space and speak. Release to paste.
```

> On first launch, the Whisper `base` model (~150 MB) is downloaded automatically to `~/.freewispr/models/`. After that, the app works fully offline.

### Optional: Start with Windows

Right-click the tray icon → **Start with Windows** to register freewispr as a startup app. Toggle it again to remove.

---

## Build from Source

**Requirements:** Python 3.10+, Windows 10/11

```bash
# Clone the repo
git clone https://github.com/x26prakhar/freewispr.git
cd freewispr

# Install dependencies
pip install -r requirements.txt

# Run directly from source
python main.py

# Build a standalone .exe with PyInstaller
build.bat
```

The compiled executable lands at `dist/freewispr.exe`.

---

## Models

freewispr uses [faster-whisper](https://github.com/SYSTRAN/faster-whisper) — a reimplementation of Whisper using [CTranslate2](https://github.com/OpenNMT/CTranslate2) with INT8 quantization for fast CPU inference.

| Model | Size | Speed | Accuracy |
|---|---|---|---|
| `tiny` | ~40 MB | ~2–3s | Good |
| `base` | ~150 MB | ~3–5s | Better |
| `small` | ~500 MB | ~6–10s | Best on CPU |

**Default:** `base` — best balance of speed and accuracy for everyday dictation.

Models are downloaded from HuggingFace on first use for each model size. Switch between them in Settings without restarting.

> Latency figures are approximate for a typical mid-range CPU (Intel i5 / Ryzen 5). Dictation chunks are usually 3–10 seconds of audio, so real-world paste time is roughly 2–5 seconds after you release the hotkey.

---

## Permissions

| Permission | Why |
|---|---|
| **Microphone** | Dictation recording |
| **Keyboard (global)** | Hotkey detection works in any app, any window |
| **Clipboard** | Paste transcribed text via `Ctrl+V` simulation |
| **Registry** (optional) | Start with Windows — writes one key to `HKCU\...\Run` |
| **Network** (first launch only) | Downloads the Whisper model from HuggingFace |

---

## Architecture

```
Dictation path:
  keyboard ──► DictationMode ──► MicRecorder (sounddevice, 16kHz)
                    │                  │
                    │           audio array (numpy)
                    │                  │
                    └──► Transcriber (faster-whisper, VAD, INT8)
                                       │
                                  text string
                                       │
                              paste_text (pyperclip + pyautogui Ctrl+V)
```

---

## Tech Stack

| Component | Technology |
|---|---|
| App | Python 3.10+, Tkinter, pystray |
| ASR engine | [faster-whisper](https://github.com/SYSTRAN/faster-whisper) (CTranslate2, INT8 on CPU) |
| Whisper models | tiny / base / small — downloaded from HuggingFace |
| Mic audio | sounddevice (PortAudio) |
| Audio processing | numpy |
| Global hotkeys | keyboard library |
| Paste | pyperclip + pyautogui |
| Tray icon | pystray + Pillow (icon generated in code) |
| Packaging | PyInstaller `--onefile --windowed` |

---

## File Structure

```
freewispr/
├── main.py          # Entry point: tray icon, threading, app lifecycle
├── dictation.py     # DictationMode: hotkey → record → transcribe → paste
├── audio.py         # MicRecorder (sounddevice, 16kHz)
├── transcriber.py   # faster-whisper wrapper (VAD, filler filter)
├── paste.py         # Clipboard paste via pyperclip + pyautogui
├── ui.py            # Tkinter: FloatingIndicator, SettingsWindow
├── config.py        # JSON config loader/saver (~/.freewispr/config.json)
├── make_icon.py     # Generates assets/icon.ico programmatically with Pillow
├── build.bat        # PyInstaller build script (Windows)
└── requirements.txt # Python dependencies
```

---

## Data & Privacy

- **No telemetry.** No analytics. No usage tracking of any kind.
- Audio is **never saved** — processed in RAM and discarded immediately.
- The only network request is the one-time model download from HuggingFace on first launch.
- Config stored at `~/.freewispr/config.json`.

---

## Roadmap

- [ ] Word replacement — custom pairs e.g. "my address" → actual text
- [ ] Installer (NSIS or WiX Toolset)
- [ ] Dark/light theme toggle in UI
- [ ] Local LLM post-processing (grammar correction, punctuation)

---

## Contributing

Contributions welcome. Please open an issue first for larger changes.

```bash
git clone https://github.com/x26prakhar/freewispr.git
cd freewispr
pip install -r requirements.txt
python main.py   # run directly from source
```

---

## Acknowledgements

- [faster-whisper](https://github.com/SYSTRAN/faster-whisper) — efficient Whisper inference via CTranslate2
- [OpenAI Whisper](https://github.com/openai/whisper) — the original speech recognition model
- [sounddevice](https://python-sounddevice.readthedocs.io/) — PortAudio bindings for Python
- [pystray](https://github.com/moses-palmer/pystray) — system tray integration

---

## License

[MIT](LICENSE) — free and open source, forever.

---

<div align="center">
  Built by <a href="https://www.linkedin.com/in/prakharsingh96/">Prakhar Singh</a>
  &nbsp;·&nbsp;
  <a href="https://www.instagram.com/prakhar.vc/">@prakhar.vc</a>
  &nbsp;·&nbsp;
  <a href="https://github.com/x26prakhar/freewispr">GitHub</a>
</div>
