# freewispr-swedish

Svensk diktering för Windows. Håll en tangent, prata, släpp – texten hamnar där markören står.

[![Windows build](https://github.com/hhammarstrand/freewispr-swedish/actions/workflows/build-windows.yml/badge.svg)](https://github.com/hhammarstrand/freewispr-swedish/actions/workflows/build-windows.yml)
[![GitHub Pages](https://github.com/hhammarstrand/freewispr-swedish/actions/workflows/pages.yml/badge.svg)](https://hhammarstrand.github.io/freewispr-swedish/)

![freewispr-swedish preview](docs/og-image.png?v=20260527)

Det här är en svensk fork av [x26prakhar/freewispr](https://github.com/x26prakhar/freewispr). Du kan köra KBLab:s svenska Whisper-modeller lokalt om du vill ha allt på datorn, eller välja providers som staik.se och Berget AI för transkribering och LLM-granskning. Appen är trimmad för att fungera även i terminaler och CLI-verktyg där vanlig syntetisk paste brukar misslyckas.

## Vad som skiljer mot originalet

- Svenska Whisper-modeller från KBLab via `faster-whisper`. Standard är `KBLab/kb-whisper-small`.
- Inget skickas över nätet vid normal användning. Ljudet stannar på datorn och transkriberingen sker lokalt.
- Den dikterade texten lämnas kvar i urklipp efter pasteförsöket, så att den går att klistra in manuellt om en terminal eller ett CLI-verktyg blockerar syntetisk paste.
- Indikatorn kan följa muspekaren mellan skärmar, eller ligga still på huvudskärmen.
- Personlig kontext för LLM-granskning — fritextfält där du beskriver dig själv, fackord och vanliga feltolkningar. Skickas som referens vid varje LLM-pass.
- Valfri eftergranskning via GitHub Models. Avstängd som standard.
- Windows-byggen via GitHub Actions.

## Snabbstart

### Färdig build

Senaste lyckade bygge från `master` publiceras automatiskt som pre-release:

1. Öppna [Releases](https://github.com/hhammarstrand/freewispr-swedish/releases/tag/latest).
2. Ladda ner `freewispr-swedish-windows.zip`.
3. Packa upp zippen och kör `freewispr-swedish.exe`.
4. Första gången: välj Whisper-modell i välkomstdialogen (~500 MB nedladdning, tar några minuter).
5. Håll `Ctrl+Space`, prata, släpp.

> **Windows SmartScreen-varning?** Eftersom appen inte är kodsignerad ($300/år i certifikat) flaggar Windows den som "okänd utgivare". Klicka **Mer information** → **Kör ändå**. All källkod finns på GitHub och bygget sker via GitHub Actions så du kan verifiera vad som finns i exe:n.

Vill du se loggarna från bygget, eller bygga själv? Se [Build Windows EXE](https://github.com/hhammarstrand/freewispr-swedish/actions/workflows/build-windows.yml).

### Från källkod

Kräver Windows 10/11 och Python 3.10+.

```bash
git clone https://github.com/hhammarstrand/freewispr-swedish.git
cd freewispr-swedish
pip install -r requirements.txt
python convert_model.py small
python main.py
```

Modellen (~500 MB) laddas ner och konverteras första gången.

Om du har en NVIDIA-GPU och vill använda CUDA:

```bash
pip install torch --index-url https://download.pytorch.org/whl/cu124
```

## Integritet

Appen pratar bara med nätverket när du uttryckligen slår på det:

- Modeller laddas ner via `python convert_model.py` — appen kontaktar inte Hugging Face automatiskt.
- Om du slår på **LLM-granskning** skickas den transkriberade texten – inte ljudet – till vald leverantör. Leverantörer: GitHub Models, staik.se, Berget AI, OpenAI eller valfri OpenAI-kompatibel server.
- Om du slår på **remote-transkribering** skickas ljudet – inte bara text – till vald leverantör (staik.se, Berget AI eller custom). Det är valfritt; lokala KBLab-modeller fungerar utan provider.

API-nycklar lagras i Windows Credential Manager via `keyring`, aldrig i config-filen. Token loggas aldrig.

Den dikterade texten kopieras till urklipp och klistras in via syntetisk Ctrl+V (eller Shift+Insert i konsolterminaler). Texten stannar kvar i urklipp efteråt som fallback — gammalt urklippsinnehåll återställs inte.

## Funktioner

- Push-to-talk, standard `Ctrl+Space`.
- Systemfacksapp med inställningar för mikrofon, modell, CUDA och autostart.
- WASAPI/DirectSound/MME med automatisk prioritering.
- Flerkanalig inspelning och resampling till 16 kHz.
- Tystnadsdetektion som kastar för tysta inspelningar.
- Personlig kontext (fritext) som skickas till LLM-granskaren för bättre resultat med namn och fackord.
- Hotwords från `~/.freewispr-swedish/hotwords.txt` för lokala Whisper-modeller.
- Valfri remote-transkribering via staik.se eller Berget AI, som alternativ till lokal modell.
- Vänta-läge för LLM: indikator visar "LLM-granskar…" och polerad text klistras i ett enda steg.
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

Du kan ladda ner ytterligare modeller manuellt:

```bash
python convert_model.py medium
python convert_model.py large
```

KBLab publicerar pre-konverterade modeller, så ingen extra konvertering behövs.

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
  "llm_provider": "github",
  "llm_model_github": "openai/gpt-4.1-nano",
  "llm_privacy_accepted": false,
  "transcription_provider": "local",
  "min_rms": 0.003
}
```

## Lokal LLM (valfritt)

LLM-granskning kan köras mot en lokal server istället för molnet. Alla OpenAI-kompatibla servrar fungerar — t.ex. [Ollama](https://ollama.com), [LM Studio](https://lmstudio.ai) eller [llama.cpp](https://github.com/ggml-org/llama.cpp).

### Exempel med Ollama

```bash
ollama serve
ollama pull gemma3:12b
```

I appen: Inställningar → LLM-granskning → Leverantör: **Custom** → Base URL: `http://localhost:11434/v1` → Modell: `gemma3:12b`.

### Rekommenderade modeller

| Modell | VRAM | Kommentar |
|--------|------|-----------|
| `gemma3:4b` | ~3 GB | Snabbast, enklare korrigeringar |
| `gemma3:12b` | ~8 GB | Bra balans, ryms i de flesta GPU:er |
| `qwen3:14b` | ~9 GB | Stark på korrigering, kräver offload till RAM |
| `mistral-small:24b` | ~16 GB | Bäst kvalitet, kräver mycket RAM |

> **Tips:** När LLM-granskning är aktiverad körs appen i vänta-läge — texten klistras inte in förrän polishen är klar (eller 15 s timeout). Du får alltid polerad text i ett enda steg, så du slipper trycka Ctrl+V två gånger eller skicka rå text av misstag.

## Personlig kontext

LLM-granskaren får en kort beskrivning av dig som referens vid varje pass — namn, fackord, vanliga feltolkningar. Du redigerar texten under **Inställningar → Kontext**.

Texten skickas som en del av system-prompten med tydlig instruktion att använda den som referens, inte som innehåll att klistra in. Max 8000 tecken. Tom kontext utelämnas helt så modellen inte får en tom referensblock.

Vid första start migreras eventuella tidigare `snippets.json`, `corrections.json` och `learned.json` automatiskt till en initial kontext-text. Originalfilerna lämnas på disk som backup.

## Datafiler

| Fil | Beskrivning |
|-----|-------------|
| `~/.freewispr-swedish/personal_context.json` | Personlig kontext för LLM-granskning |
| `~/.freewispr-swedish/hotwords.txt` | Egna termer för lokala Whisper-modeller |
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

## Utveckling

### Testa

```bash
python -m pytest tests/ -q
```

Tester som behöver `sounddevice`, `keyboard` eller `pyperclip` kräver att dessa paket är installerade (de skippas annars).

### Lint och format

CI kör `ruff check . --select E,F,W --ignore E501` vid varje push.

### Modellnedladdning

```bash
python convert_model.py medium
python convert_model.py large
```

Filerna hämtas via `huggingface_hub` som redan ingår i `requirements.txt`. Ingen extra konvertering behövs — KBLab publicerar pre-konverterade ct2-modeller.

### Release-flöde

1. Push till `master` triggar GitHub Actions som bygger `.exe` och publicerar en rolling pre-release.
2. Webbsidan deployar automatiskt via GitHub Pages vid ändringar i `docs/`.
3. Ikoner och OG-bild genereras med `python make_icon.py` (kräver Windows-fonter för bästa resultat).

## Projektstruktur

```text
freewispr-swedish/
+-- main.py              # systemfack, inställningar, applifecycle
+-- dictation.py         # push-to-talk, pipeline och paste-status
+-- transcriber.py       # KBLab Whisper, CUDA och LLM-granskning
+-- audio.py             # mikrofoninspelning, resampling och kanalhantering
+-- paste.py             # urklipp och terminalvänlig paste
+-- ui/                  # Tkinter/CustomTkinter UI (paket)
|   +-- __init__.py
|   +-- _ctk.py          #   lazy-import av customtkinter
|   +-- indicator.py     #   flytande indikator
|   +-- settings_window.py # inställningsfönster med tabs
|   +-- hotkey_capture.py #  tangentfångst-dialog
|   +-- pair_dialog.py   #   nyckel-värde-dialog
|   +-- styles.py        #   färger och ttk-tema
+-- config.py            # config, nyckelhantering och keyring-integration
+-- personal_context.py  # personlig kontext-text för LLM-granskning
+-- migrate_context.py   # en-gångs migration från snippets/corrections/learned
+-- llm_polish.py        # LLM-leverantörer (GitHub, staik, Berget, OpenAI, custom)
+-- remote_transcribe.py # remote-transkribering via OpenAI-kompatibelt API
+-- json_store.py        # atomisk JSON-lagring med backup vid korruption
+-- modifiers.py         # kanoniska modifier-namn för tangentbord
+-- sounds.py            # syntetiserade ljudeffekter
+-- make_icon.py         # genererar appikon, favicon och OG-bild
+-- convert_model.py     # konverterar Whisper-modeller till CTranslate2
+-- run.bat              # startar appen utan konsolfönster
+-- NOTICE               # tredjepartslicenser
+-- docs/                # GitHub Pages-site
+-- tests/               # pytest-tester
```

## Synka med originalet

```bash
git remote add upstream https://github.com/x26prakhar/freewispr.git
git fetch upstream
git merge upstream/master
```

## Vanliga frågor

**Varför varnar Windows att appen kommer från okänd utgivare?**
Appen är inte kodsignerad. Klicka *Mer information → Kör ändå*. Du kan verifiera bygget i [Actions](https://github.com/hhammarstrand/freewispr-swedish/actions).

**Hur stänger jag av automatisk paste?**
Inte stöttat just nu — texten klistras alltid in. Den ligger kvar i urklipp så du kan klistra in den manuellt om paste inte gick fram.

**Fungerar det utan internet?**
Ja, helt — så länge du har laddat ned en modell (`python convert_model.py small`). LLM-granskning och remote-transkribering kräver internet, men är avstängda som standard.

**Min mikrofon hittas inte.**
Öppna *Inställningar → Mikrofon* och välj din mikrofon manuellt. Om listan är tom: kolla att Windows har gett appen åtkomst i *Inställningar → Sekretess → Mikrofon*.

**Texten innehåller fel ord.**
Slå på LLM-granskning och beskriv namnen, fackorden eller felmönstren under *Inställningar → Kontext*. För lokala Whisper-modeller kan du även lägga till termer i `~/.freewispr-swedish/hotwords.txt`.

**Kan jag använda en lokal LLM istället för GitHub Models?**
Ja, se [Lokal LLM](#lokal-llm-valfritt) — funkar med Ollama, LM Studio och llama.cpp.

**Vilken hotkey ska jag välja?**
`Ctrl+Space` fungerar för de flesta men krockar med en del editorer (autocompletion). `Alt+Space` är vanligt på Mac-vana användare. `F9`/`F10` om du vill ha en dedikerad tangent.

**Texten blir bättre om jag pratar tydligt?**
Whisper är trimmat på naturligt svenskt tal — det fungerar bra med vanligt tempo och uttal. Långsamt och övertydligt tal kan faktiskt bli sämre eftersom modellen tränades på naturligt språk.

## Ändringslogg

Se [Releases](https://github.com/hhammarstrand/freewispr-swedish/releases) för detaljerade release notes.

## Licens

[MIT](LICENSE)

## Tack

[KBLab](https://huggingface.co/KBLab), [faster-whisper](https://github.com/SYSTRAN/faster-whisper), [OpenAI Whisper](https://github.com/openai/whisper) och [freewispr](https://github.com/x26prakhar/freewispr).
