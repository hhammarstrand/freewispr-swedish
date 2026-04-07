# FreeWispr SV

**Svensk speech-to-text för Windows.**  
Diktera var som helst. 100% lokalt. Ingen molnanslutning. Ingen prenumeration.

> **Fork av:** [x26prakhar/freewispr](https://github.com/x26prakhar/freewispr)  
> **Licens:** MIT  
> **Mål:** Svensk speech-to-text med KB-Whisper-modeller

---

## Vad är FreeWispr SV?

FreeWispr SV är en modifierad version av freewispr optimerad för **svenska**. Istället för OpenAI:s Whisper-modeller använder vi **KBLab:s svenska Whisper-modeller** som ger upp till **47% lägre WER** (Word Error Rate) på svenska.

Standardmodellen är `KBLab/kb-whisper-small` — mindre än OpenAI:s `whisper-small` men med **bättre precision på svenska**.

---

## Funktionalitet

- **Diktering** — håll tangent nedtryckt, prata, släpp. Texten klistras in direkt
- **Flytande indikator** — visar Lyssnar / Transkriberar / Klar
- **Svenska filler-ord** — tar bort "eh", "mm", "liksom", "typ", "ba" etc.
- **Flerspråkig** — byt språk i inställningar (sv, en, och 97 andra)
- **Flermodell-stöd** — tiny, base, small, medium, large (alla KBLab)
- **Starta med Windows** — enkel toggle i menyn
- **Systemfack** — lever diskret i bakgrunden
- **Helt offline** — efter första nedladdningen av modellen

---

## Installation

### Ladda ner (rekommenderas)

Ladda ner senaste `freewispr-sv.exe` från [**Releases**](https://github.com/hhammarstrand/freewispr/releases).

**Krav:** Windows 10 eller Windows 11

```
1. Ladda ner freewispr-sv.exe
2. Dubbelklicka för att köra — ingen installation behövs
3. En lila mikrofon-ikon visas i systemfacket
4. Håll Ctrl+Space och prata. Släpp för att klistra in.
```

> Vid första starten laddas KB-Whisper-small (~500 MB) ner automatiskt. Därefter fungerar appen helt offline.

---

## Bygga från källkod

**Krav:** Python 3.10+, Windows 10/11

```bash
# Klona repot
git clone https://github.com/hhammarstrand/freewispr.git
cd freewispr

# Installera dependencies
pip install -r requirements.txt

# Kör direkt från källkod
python main.py

# Bygg .exe med PyInstaller
build.bat
```

---

## Modeller

FreeWispr SV använder [KBLab:s Whisper-modeller](https://huggingface.co/KBLab) tränade på över 50 000 timmar svenskt tal.

| Modell | WER (svenska) | Storlek | Jämförelse OpenAI |
|--------|---------------|---------|-------------------|
| `tiny` | 13.2 | ~40 MB | 59.2 |
| `base` | 9.1 | ~150 MB | 39.6 |
| **`small`** | **7.3** | **~500 MB** | **20.6** |
| `medium` | 6.6 | ~1.5 GB | 15.8 |

**Standard:** `small` — bästa balansen mellan hastighet och precision för svenska.

---

## Teknisk arkitektur

```
freewispr/
├── main.py          # Entry point: systemfack, threading, applifecycle
├── transcriber.py   # KB-Whisper + filler-filtrering
├── dictation.py     # Dikteringslogik: tangent → spela in → transkribera → klistra
├── audio.py         # Mikrofoninspelning (sounddevice, 16kHz)
├── paste.py         # Urklipp via pyperclip + pyautogui
├── ui.py            # Tkinter: flytande indikator, inställningar
├── config.py        # JSON konfiguration (~/.freewispr/config.json)
├── lang/
│   └── sv.py       # Svenska filler-ord
├── build.bat        # PyInstaller bygge (Windows)
└── requirements.txt # Python dependencies
```

---

## Svenska filler-ord

Vid aktivering i inställningar tas följande svenska utfyllnadsord bort:

```
eh, em, öh, öhm, äh, ahm, liksom, typ, ba, bara, alltså,
liknande, sådär, kanske, ju, nog, väl, mm, mhm, aa, såhär
```

---

## Licens

[MIT](LICENSE) — fri och open source, för alltid.

---

## Tack till

- [KBLab](https://huggingface.co/KBLab) — Nationella biblioteket Sveriges Whisper-modeller
- [faster-whisper](https://github.com/SYSTRAN/faster-whisper) — effektiv Whisper-inферен via CTranslate2
- [OpenAI Whisper](https://github.com/openai/whisper) — den ursprungliga speech recognition-modellen
- [freewispr](https://github.com/x26prakhar/freewispr) — originalprojektet
