<div align="center">

<img src="assets/icon.ico" width="80" height="80" alt="freewispr icon" />

# freewispr

**Free, local, open-source speech-to-text for Windows.**  
Dictate anywhere. Transcribe meetings. Search your transcripts. 100% on-device.

[![Platform](https://img.shields.io/badge/platform-Windows%2010%2F11-0078d4?style=flat-square)](https://github.com/x26prakhar/freewispr/releases)
[![License](https://img.shields.io/badge/license-MIT-22c55e?style=flat-square)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.10%2B-f59e0b?style=flat-square)](https://python.org)
[![Latest Release](https://img.shields.io/github/v/release/x26prakhar/freewispr?style=flat-square&color=7c5cfc)](https://github.com/x26prakhar/freewispr/releases/latest)

[Download](#install) · [Build from Source](#build-from-source) · [Features](#features) · [Architecture](#architecture)

</div>

---

## What is freewispr?

freewispr is a lightweight Windows tray app that brings speech-to-text to your entire computer — no account, no internet connection, no subscription. It combines:

- **Whisper-style dictation** — hold a hotkey, speak, release. Transcribed text pastes at your cursor in any app.
- **Meeting transcription** — records your mic and system audio simultaneously during calls, transcribes in real time with timestamps, and stores everything in a searchable local database.

All processing runs locally on your CPU using [faster-whisper](https://github.com/SYSTRAN/faster-whisper) with INT8 quantization. Your audio never leaves your device.

---

## Dictation

Hold `Ctrl+Space` (configurable) → speak → release. The transcribed text is instantly pasted wherever your cursor is — browser address bar, Word, Notepad, Slack, VS Code, anywhere.

A **floating indicator pill** appears at the top of your screen so you always know what's happening:

| State | Indicator |
|---|---|
| Listening | Purple dot — recording |
| Transcribing | Amber dot — processing |
| Done | Green dot — text pasted ✓ |

**Optional:** enable **filler word removal** in Settings to automatically strip "um", "uh", "you know", "basically" etc. from your output.

---

## Meeting Transcription

Open **Meeting Transcription** from the tray icon to record a session.

freewispr opens two audio streams simultaneously:
- **Mic** — captures your voice
- **System audio** (WASAPI loopback) — captures everything playing through your speakers, including remote participants on Zoom, Teams, or Google Meet

The streams are mixed, resampled, and sent to Whisper in chunks. Transcription happens **during the meeting** at natural speech boundaries, not after. When you stop, the full timestamped transcript is saved automatically.

```
[00:00] Let's get started — can everyone hear me?
[00:05] Yes, loud and clear.
[00:12] Great. Let me pull up the slides.
[00:18] Could you share your screen instead?
```

**Auto-detection:** freewispr watches for Zoom, Teams, Webex, Slack, and Skype. When detected, it notifies you via a tray balloon to start transcribing.

**AI Summary:** click **AI Summary** after a meeting to generate a concise summary, key decisions, and action items using GPT-4o-mini (requires an OpenAI API key in Settings).

---

## Meeting History

All transcripts are stored in a local SQLite database at `~/.freewispr/freewispr.db`. Open **Meeting History** from the tray to:

- Browse all past recordings with date, duration, and audio source
- **Full-text search** across every word ever transcribed — find any meeting instantly by keyword
- View the complete timestamped transcript for any session
- Export any recording to a `.txt` file
- Delete recordings you no longer need

AI summaries generated for a meeting are also saved and shown in the History view.

---

## Features

- **Dictation** — hold-to-talk hotkey, pastes at cursor, works in every app
- **Floating indicator** — always-on-top pill shows Listening / Transcribing / Pasted states
- **Filler word removal** — strips um/uh/you know/basically from output (toggle in Settings)
- **Meeting recording** — captures mic + system audio (WASAPI loopback) simultaneously
- **Silence-based chunking** — splits at natural speech pauses, not fixed intervals
- **Auto meeting detection** — detects Zoom, Teams, Webex, Slack, Skype and notifies you
- **AI meeting summary** — one-click GPT-4o-mini summary after any meeting
- **Meeting History** — SQLite database with full-text search across all past transcripts
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

| Model | Backend | Size | Speed | Accuracy | Languages |
|---|---|---|---|---|---|
| `tiny` | CTranslate2 / CPU | ~40 MB | ~2–3s | Good | 99 |
| `base` | CTranslate2 / CPU | ~150 MB | ~3–5s | Better | 99 |
| `small` | CTranslate2 / CPU | ~500 MB | ~6–10s | Best on CPU | 99 |

**Default:** `base` — best balance of speed and accuracy for everyday dictation and meetings.

Models are downloaded from HuggingFace on first use for each model size. Switch between them in Settings without restarting — freewispr reloads the model automatically.

> Latency figures are approximate for a typical mid-range CPU (Intel i5 / Ryzen 5). Dictation chunks are usually 3–10 seconds of audio, so real-world paste time is roughly 2–5 seconds after you release the hotkey.

---

## Permissions

| Permission | Why |
|---|---|
| **Microphone** | Dictation and meeting recording |
| **System Audio** | WASAPI loopback — captures speaker output (Zoom, Teams, etc.) |
| **Keyboard (global)** | Hotkey detection works in any app, any window |
| **Clipboard** | Paste transcribed text via `Ctrl+V` simulation |
| **Registry** (optional) | Start with Windows — writes one key to `HKCU\...\Run` |
| **Network** (first launch only) | Downloads the Whisper model from HuggingFace |

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  pystray (system tray)  ──►  Tray menu                      │
│                               ├── Meeting Transcription      │
│                               ├── Meeting History            │
│                               ├── Settings                   │
│                               └── Start with Windows         │
└───────────────────────────────────────┬─────────────────────┘
                                        │ Tkinter windows
                          ┌─────────────▼──────────────┐
                          │  MeetingWindow              │
                          │  HistoryWindow              │
                          │  SettingsWindow             │
                          │  FloatingIndicator (pill)   │
                          └─────────────────────────────┘

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

Meeting path:
  MeetingRecorder ──┬── MicStream    (sounddevice, 16kHz)  ──► numpy mix
                    └── SysStream    (WASAPI loopback)      ──►  + resample
                                                                     │
                                                              Transcriber (beam=2, VAD)
                                                                     │
                                                            ┌────────▼────────┐
                                                            │  SQLite DB       │  ~/.freewispr/freewispr.db
                                                            │  + .txt file     │  ~/.freewispr/transcripts/
                                                            └─────────────────┘
```

---

## Tech Stack

| Component | Technology |
|---|---|
| App | Python 3.10+, Tkinter, pystray |
| ASR engine | [faster-whisper](https://github.com/SYSTRAN/faster-whisper) (CTranslate2, INT8 on CPU) |
| Whisper models | tiny / base / small — downloaded from HuggingFace |
| Mic audio | sounddevice (PortAudio) |
| System audio | sounddevice WASAPI loopback (`WasapiSettings(loopback=True)`) |
| Audio processing | numpy (resampling, mixing, normalisation) |
| Global hotkeys | keyboard library |
| Paste | pyperclip + pyautogui |
| Storage | SQLite (`sqlite3` stdlib) with FTS5 full-text search |
| Tray icon | pystray + Pillow (icon generated in code) |
| Packaging | PyInstaller `--onefile --windowed` |
| Website | HTML/CSS/JS, deployed on Vercel |

---

## Data & Privacy

- **No telemetry.** No analytics. No usage tracking of any kind.
- Audio is **never saved** during dictation — processed in RAM and discarded immediately.
- Meeting transcripts are stored **locally only** at `~/.freewispr/`.
- The only network request is the one-time model download from HuggingFace on first launch.
- Config stored at `~/.freewispr/config.json`. Database at `~/.freewispr/freewispr.db`.

---

## File Structure

```
freewispr/
├── main.py          # Entry point: tray icon, threading, app lifecycle, meeting detection
├── dictation.py     # DictationMode: hotkey → record → transcribe → paste
├── meeting.py       # MeetingMode: continuous record → chunk → transcribe → DB + file
├── audio.py         # MicRecorder, MeetingRecorder (WASAPI loopback, silence VAD, mixing)
├── transcriber.py   # faster-whisper wrapper (VAD, filler filter, segment timestamps)
├── db.py            # SQLite layer (meetings, segments, FTS5 search)
├── paste.py         # Clipboard paste via pyperclip + pyautogui
├── ui.py            # Tkinter: FloatingIndicator, MeetingWindow, HistoryWindow, SettingsWindow
├── config.py        # JSON config loader/saver (~/.freewispr/config.json)
├── make_icon.py     # Generates assets/icon.ico programmatically with Pillow
├── build.bat        # PyInstaller build script (Windows)
├── requirements.txt # Python dependencies
└── docs/            # Website source (deployed on Vercel)
```

---

## Roadmap

- [ ] Speaker diarization — identify who said what (Speaker 1, Speaker 2…)
- [ ] Word replacement — custom pairs e.g. "my address" → actual text
- [ ] Installer (NSIS or WiX Toolset)
- [ ] Dark/light theme toggle in UI
- [ ] Local LLM summaries (no API key required)

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
- [CTranslate2](https://github.com/OpenNMT/CTranslate2) — fast CPU/GPU inference engine
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
