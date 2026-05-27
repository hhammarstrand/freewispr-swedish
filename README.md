# freewispr-swedish

Svensk diktering för Windows. Håll en tangent, prata, släpp – texten hamnar där markören står.

[![Windows build](https://github.com/hhammarstrand/freewispr-swedish/actions/workflows/build-windows.yml/badge.svg)](https://github.com/hhammarstrand/freewispr-swedish/actions/workflows/build-windows.yml)
[![GitHub Pages](https://github.com/hhammarstrand/freewispr-swedish/actions/workflows/pages.yml/badge.svg)](https://hhammarstrand.github.io/freewispr-swedish/)

![freewispr-swedish preview](docs/og-image.png?v=20260527)

Det här är en svensk fork av [x26prakhar/freewispr](https://github.com/x26prakhar/freewispr). Den använder KBLab:s svenska Whisper-modeller och är trimmad för att fungera även i terminaler och CLI-verktyg där vanlig syntetisk paste brukar misslyckas.

## Vad som skiljer mot originalet

- Svenska Whisper-modeller från KBLab via `faster-whisper`. Standard är `KBLab/kb-whisper-small`.
- Inget skickas över nätet vid normal användning. Ljudet stannar på datorn och transkriberingen sker lokalt.
- Den dikterade texten lämnas kvar i urklipp efter pasteförsöket, så att den går att klistra in manuellt om en terminal eller ett CLI-verktyg blockerar syntetisk paste.
- Indikatorn kan följa muspekaren mellan skärmar, eller ligga still på huvudskärmen.
- Personlig ordlista, hotwords och snippets för namn, facktermer och fraser man skriver ofta.
- Valfri eftergranskning via GitHub Models. Avstängd som standard.
- Windows-byggen via GitHub Actions.

## Snabbstart

### Färdig build

Senaste lyckade bygge från `master` publiceras automatiskt som pre-release:

1. Öppna [Releases](https://github.com/hhammarstrand/freewispr-swedish/releases/tag/latest).
2. Ladda ner `freewispr-swedish-windows.zip`.
3. Packa upp zippen och kör `freewispr-swedish.exe`.
4. Håll `Ctrl+Space`, prata, släpp.

Vill du se loggarna från bygget, eller bygga själv? Se [Build Windows EXE](https://github.com/hhammarstrand/freewispr-swedish/actions/workflows/build-windows.yml).

### Från källkod

Kräver Windows 10/11 och Python 3.10+.

```bash
git clone https://github.com/hhammarstrand/freewispr-swedish.git
cd freewispr-swedish
pip install -r requirements.txt
python main.py
```

Om du har en NVIDIA-GPU och vill använda CUDA:

```bash
pip install torch --index-url https://download.pytorch.org/whl/cu124
```

## Integritet

Appen pratar bara med nätverket i två fall:

- Första gången du använder en modell laddas den ner från Hugging Face om den inte redan finns lokalt.
- Om du själv slår på LLM-granskning skickas den transkriberade texten – inte ljudet – till GitHub Models.

GitHub-token för LLM hämtas i tur och ordning från sparad nyckel, `GITHUB_TOKEN`, `GH_TOKEN` eller `gh auth token`. Token loggas aldrig.

- Om du slår på remote-transkribering skickas ljudet – inte bara text – till vald leverantör (staik.se eller Berget AI).

Den dikterade texten ligger kvar i urklipp efter att appen har försökt klistra in. Det är ett medvetet val: gamla urklippets innehåll återställs inte, men du kan alltid klistra in manuellt om paste-försöket inte gick fram.

## Funktioner

- Push-to-talk, standard `Ctrl+Space`.
- Systemfacksapp med inställningar för mikrofon, modell, CUDA och autostart.
- WASAPI/DirectSound/MME med automatisk prioritering.
- Flerkanalig inspelning och resampling till 16 kHz.
- Tystnadsdetektion som kastar för tysta inspelningar.
- Personliga ordkorrigeringar.
- Hotwords från ordlista och `~/.freewispr-swedish/hotwords.txt`.
- Snippets och textmallar.
- Valfri remote-transkribering via staik.se eller Berget AI.
- Statuslägen i indikatorn: lokal, LLM-granskad eller LLM-polerad.

## Modeller

Appen använder [KBLab:s Whisper-modeller](https://huggingface.co/KBLab), tränade på svenskt tal.

| Modell | Storlek | Kommentar |
|--------|---------|-----------|
| `tiny` | ~40 MB | Snabbast, lägre precision |
| `base` | ~150 MB | Liten och snabb |
| `small` | ~500 MB | Standard |
| `medium` | ~1.5 GB | Bättre precision, tyngre |
| `large` | ~3 GB | Tyngst, kan behöva konverteras |

Modellerna sparas i `~/.freewispr-swedish/models/` och hämtas automatiskt första gången de används.

Medium och large kan behöva konverteras till CTranslate2-format:

```bash
pip install ctranslate2 transformers
python convert_model.py medium
python convert_model.py large
```

## Inställningar

Högerklicka på systemfacksikonen och välj **Inställningar**.

| Inställning | Beskrivning |
|-------------|-------------|
| Snabbtangent | Tangentkombination för diktering |
| Mikrofon | Specifik mikrofon eller auto |
| Modell | `tiny`, `base`, `small`, `medium` eller `large` |
| GPU/CUDA | Använd NVIDIA-GPU när tillgänglig |
| Lyssnarindikator | Följ muspekaren eller ligg still på huvudskärmen |
| LLM-granskning | Valfri eftergranskning av transkriberad text |

Konfiguration sparas i `~/.freewispr-swedish/config.json`. API-nyckeln för LLM lagras i Windows Credential Manager via `keyring`, inte i config-filen.

Exempel:

```json
{
  "hotkey": "ctrl+space",
  "model_size": "small",
  "use_cuda": true,
  "mic_device": null,
  "indicator_follow_mouse": true,
  "llm_enabled": false,
  "llm_model": "openai/gpt-4.1-nano"
}
```

## Datafiler

| Fil | Beskrivning |
|-----|-------------|
| `~/.freewispr-swedish/corrections.json` | Personliga ordkorrigeringar |
| `~/.freewispr-swedish/snippets.json` | Snippets och expansioner |
| `~/.freewispr-swedish/hotwords.txt` | Egna termer för Whisper |
| `~/.freewispr-swedish/learned.json` | Auto-lärda korrigeringar från LLM |
| `~/.freewispr-swedish/freewispr.log` | Logg för felsökning |
| `~/.freewispr-swedish/models/` | Nedladdade och konverterade modeller |

## Bygga exe

```bash
build.bat
```

Resultatet hamnar i `dist/freewispr-swedish/freewispr-swedish.exe`.

Ikoner och webbgrafik genereras med:

```bash
python make_icon.py
```

## Testa

```bash
python -m pytest tests/ -q
```

## Projektstruktur

```text
freewispr-swedish/
+-- main.py          # systemfack, inställningar, applifecycle
+-- dictation.py     # push-to-talk, pipeline och paste-status
+-- transcriber.py   # KBLab Whisper, CUDA och LLM-granskning
+-- audio.py         # mikrofoninspelning, resampling och kanalhantering
+-- paste.py         # urklipp och terminalvänlig paste
+-- ui.py            # Tkinter UI och flytande indikator
+-- config.py        # config och nyckelhantering
+-- corrections.py   # personlig ordlista
+-- snippets.py      # snippets/textmallar
+-- llm_polish.py    # GitHub Models-integration
+-- make_icon.py     # genererar appikon, favicon och OG-bild
+-- docs/            # GitHub Pages-site
```

## Synka med originalet

```bash
git remote add upstream https://github.com/x26prakhar/freewispr.git
git fetch upstream
git merge upstream/master
```

## Licens

[MIT](LICENSE)

## Tack

[KBLab](https://huggingface.co/KBLab), [faster-whisper](https://github.com/SYSTRAN/faster-whisper), [OpenAI Whisper](https://github.com/openai/whisper) och [freewispr](https://github.com/x26prakhar/freewispr).
