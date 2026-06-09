# freewispr-swedish

Svensk diktering för Windows. Håll en tangent, prata, släpp – texten hamnar där markören står.

[![Windows build](https://github.com/hhammarstrand/freewispr-swedish/actions/workflows/build-windows.yml/badge.svg)](https://github.com/hhammarstrand/freewispr-swedish/actions/workflows/build-windows.yml)
[![GitHub Pages](https://github.com/hhammarstrand/freewispr-swedish/actions/workflows/pages.yml/badge.svg)](https://hhammarstrand.github.io/freewispr-swedish/)

![freewispr-swedish preview](docs/og-image.png?v=20260527)

Det här är en svensk fork av [x26prakhar/freewispr](https://github.com/x26prakhar/freewispr). Du kan köra KBLab:s svenska Whisper-modeller lokalt om du vill ha allt på datorn, eller välja providers som [staik.se](https://staik.se/) och [Berget AI](https://berget.ai/) för transkribering och LLM-granskning. Appen är trimmad för att fungera även i terminaler och CLI-verktyg där vanlig syntetisk paste brukar misslyckas.

## Vad som skiljer mot originalet

- Svenska Whisper-modeller från KBLab via `faster-whisper`. Standard är `KBLab/kb-whisper-small`.
- Vid lokal diktering skickas inget över nätet. Ljudet stannar på datorn och transkriberingen sker lokalt.
- Den dikterade texten lämnas kvar i urklipp efter pasteförsöket, så att den går att klistra in manuellt om en terminal eller ett CLI-verktyg blockerar syntetisk paste.
- Indikatorn kan följa muspekaren mellan skärmar, eller ligga still på huvudskärmen.
- Personlig kontext för LLM-granskning — fritextfält där du beskriver dig själv, fackord och vanliga feltolkningar. Skickas som referens vid varje LLM-pass.
- Valfri LLM-granskning via GitHub Models, staik.se, Berget AI, OpenAI eller egen OpenAI-kompatibel server. Avstängd som standard.
- Windows-byggen via GitHub Actions.

## Snabbstart

### Färdig build

Senaste lyckade bygge från `master` publiceras automatiskt som pre-release:

1. Öppna [Releases](https://github.com/hhammarstrand/freewispr-swedish/releases/tag/latest).
2. Ladda ner `freewispr-swedish-windows.zip`.
3. Packa upp zippen och kör `freewispr-swedish.exe`.
4. Första gången: välj Whisper-modell i välkomstdialogen (`small` är ~500 MB och tar några minuter att ladda ned).
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

Om modellen saknas visar appen en välkomstdialog där du kan ladda ned valfri KBLab-modell. Filerna sparas lokalt och behöver ingen extra konvertering.

Om du har en NVIDIA-GPU och vill använda CUDA:

```bash
pip install torch --index-url https://download.pytorch.org/whl/cu124
```

## Integritet

Normal diktering är lokal när en modell finns nedladdad och LLM/remote är avstängt. Nätverk används i dessa fall:

- När du laddar ned en KBLab-modell via välkomstdialogen eller `python convert_model.py` hämtas pre-konverterade CT2-filer från Hugging Face. Själva lokala transkriberingen laddar inte modeller i bakgrunden.
- Inställningar kan försöka hämta modellistan från vald LLM-leverantör om en API-nyckel finns sparad eller tillgänglig via miljövariabel/`gh auth token`.
- Om du slår på **LLM-granskning** skickas den transkriberade texten – inte ljudet – till vald leverantör. Leverantörer: GitHub Models, staik.se, Berget AI, OpenAI eller valfri OpenAI-kompatibel server.
- Om du slår på **remote-transkribering** skickas ljudet – inte bara text – till vald leverantör (staik.se, Berget AI eller custom). Det är valfritt; lokala KBLab-modeller fungerar utan provider.
- **Röstredigering** (egen hotkey, av som standard) läser den text du markerat via urklipp och skickar markeringen tillsammans med din röstinstruktion till vald LLM-leverantör. Markeringen kan innehålla känslig information och omfattas av samma LLM-samtycke.

### Samtycke

- Att slå på LLM-granskning eller remote-transkribering kräver ett uttryckligt samtycke (en synlig samtyckesruta på respektive flik, annars en bekräftelsedialog när du sparar). Samtycket sparas **oberoende** av om funktionen är på, så du behöver inte godkänna igen om du tillfälligt stänger av den.
- Byter du från en lokal `http://localhost`-uppsättning till en riktig remote-leverantör krävs ett **nytt** uttryckligt ja — ett lokalt (loopback) godkännande ärvs aldrig som remote-samtycke.
- Lokal LLM via **Custom + `http://localhost`** (Ollama, LM Studio, llama.cpp) lämnar aldrig datorn och kräver därför inget samtycke.
- **Kontextmedvetenhet** läser aktiv app och text nära markören **lokalt** för att stava egennamn rätt och anpassa ton/format. Egennamn från skärmen delas bara med en remote-tjänst (STT eller LLM) om du uttryckligen godkänt det; annars stannar de på datorn.

Om remote-transkribering misslyckas (t.ex. serverfel) visas felet i indikatorn — det maskeras inte längre som "Inget hördes", så du ser skillnad på tystnad och ett faktiskt fel.

API-nycklar för LLM och remote-transkribering lagras i Windows Credential Manager via `keyring`, aldrig i config-filen. Token loggas aldrig, och loggen innehåller aldrig full transkriptionstext — bara metadata (längd, latens, modell).

Den dikterade texten kopieras till urklipp och klistras in via syntetisk Ctrl+V (eller Shift+Insert i konsolterminaler). Texten stannar kvar i urklipp efteråt som fallback — ditt tidigare urklippsinnehåll återställs som standard inte (kan slås på via **Återställ urklipp efter diktering** i inställningarna).

## Funktioner

- Push-to-talk, standard `Ctrl+Space`. `Esc` avbryter en pågående inspelning.
- Systemfacksapp med inställningar för mikrofon, modell, CUDA och autostart.
- WASAPI/DirectSound/MME med automatisk prioritering.
- Flerkanalig inspelning och resampling till 16 kHz.
- Tystnadsdetektion som kastar för tysta inspelningar.
- Personlig kontext (fritext) som skickas till LLM-granskaren för bättre resultat med namn och fackord.
- Kontextmedvetenhet: anpassar ton/format per app och stavar egennamn nära markören rätt. All skärmtext används lokalt om du inte uttryckligen delar den med en remote-tjänst.
- Röstredigering av markerad text (KP3, egen hotkey): markera text, håll röstredigerings-tangenten och säg en instruktion ("gör formellt", "översätt till engelska") — LLM:en redigerar markeringen.
- Kommandoläge: rösta för att redigera det senast inklistrade blocket i stället för att diktera nytt.
- Hotwords från `~/.freewispr-swedish/hotwords.txt` för lokala Whisper-modeller.
- Live-transkribering under inspelning (lokal modell): färdiga fraser avkodas medan du fortfarande pratar, så vid släpp återstår bara svansen — texten klistras nästan direkt även efter långa dikteringar.
- Fortsättningskontext: texten som redan står före markören matas till Whisper som kontext, så fortsatt diktering mitt i en mening får konsekvent versalisering och terminologi. Skärmtext delas aldrig med en remote-tjänst utan uttryckligt medgivande.
- Valfri remote-transkribering via staik.se, Berget AI eller egen OpenAI-kompatibel endpoint, som alternativ till lokal modell.
- Vänta-läge för LLM: indikator visar "LLM-granskar…" och granskad/polerad text klistras i ett enda steg när LLM-svaret hinner klart.
- Statuslägen i indikatorn: rå, LLM-granskad eller LLM-polerad.

## Modeller

Appen använder [KBLab:s Whisper-modeller](https://huggingface.co/KBLab), tränade på svenskt tal.

| Modell | Storlek | Kommentar |
|--------|---------|-----------|
| `tiny` | ~40 MB | Snabbast, lägre precision |
| `base` | ~150 MB | Liten och snabb |
| `small` | ~500 MB | Standard |
| `medium` | ~1.5 GB | Bättre precision, tyngre |
| `large` | ~3 GB | Tyngst, kräver mest RAM/VRAM och disk |

Modellerna sparas i `~/.freewispr-swedish/models/`. Om vald lokal modell saknas visar appen en nedladdningsdialog; du kan också ladda ned i förväg med `convert_model.py`.

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
| LLM-granskning | Valfri eftergranskning av transkriberad text (kräver samtycke för remote-leverantör) |
| Remote-transkribering | Lokal Whisper eller remote-provider (`staik`, `berget`, `custom`); remote kräver samtycke |
| Personlig kontext | Fritext som används som referens vid LLM-granskning |
| Kontextmedvetenhet | Anpassa ton/format per app och stava egennamn nära markören rätt (lokalt) |
| Röstredigering | Egen hotkey för att redigera markerad text med en röstinstruktion |
| Live-transkribering | Avkoda färdiga fraser under inspelning (på som standard, endast lokal modell) |
| Rå direkt / Rå → ersätt | Klistra rå text direkt, eller klistra rått och byt mot polerat när det landar |
| Lär av mina rättelser | Lär `fel → rätt`-par när du rättar inklistrad text |
| Kommandoläge | Rösta för att redigera det senast inklistrade blocket |
| Snippets | Textexpansion: en ledande trigger-fras expanderas till längre text |
| Flow-läge | Kontinuerlig diktering över pauser (experimentellt, endast lokal) |
| Förvänta engelska facktermer | Bättre igenkänning av engelska facktermer i svensk diktering |
| Indikatorstil | Klassisk (Tk), modern (Qt-pill) eller transparent |
| Återställ urklipp | Lägg tillbaka ditt tidigare urklipp efter dikteringen |
| Autostart | Starta appen automatiskt med Windows |

`Esc` avbryter en pågående inspelning (byt via `cancel_hotkey` i config.json).

Konfiguration sparas i `~/.freewispr-swedish/config.json`. API-nycklar lagras i Windows Credential Manager via `keyring`, inte i config-filen.

Minimalt exempel — du behöver inte ange alla fält. Allt som saknas fylls i med sina standardvärden (de smarta funktionerna som live-transkribering, inlärning och kontextmedvetenhet är på som standard), så en delvis config slår aldrig av något:

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

LLM-granskning kan köras mot en lokal server istället för molnet om den exponerar en OpenAI-kompatibel `/v1/chat/completions`-endpoint — t.ex. [Ollama](https://ollama.com), [LM Studio](https://lmstudio.ai) eller [llama.cpp](https://github.com/ggml-org/llama.cpp).

### Exempel med Ollama

```bash
ollama serve
ollama pull gemma3:12b
```

I appen: Inställningar → LLM-granskning → Leverantör: **Custom** → Base URL: `http://localhost:11434/v1` → Modell: `gemma3:12b`.

Vilken modell som passar dig beror på din hårdvara och hur petig du vill vara på korrigeringen. Prova ett par och jämför.

> **Tips:** När LLM-granskning är aktiverad körs appen i vänta-läge — texten klistras inte in förrän polishen är klar. Om LLM-svaret dröjer mer än 15 s klistras rå text som fallback, annars får du den granskade/polerade texten i ett enda steg.

> **Rå → ersätt** (Inställningar → Smart): klistrar in den råa transkriberingen direkt så att text syns omedelbart, och byter sedan ut den mot den polerade versionen när den är klar (via backsteg + ny inklistring). Endast för redigerbara fält — aktiveras aldrig i terminal/kod-profiler. Avvägning: om du hinner trycka **Enter/Tab** innan polishen landar kan utbytet misslyckas och ge dubblerad text; lämna läget av om du ofta skickar iväg text direkt.

> **Lokal LLM-granskning** (lägre latens): har du GPU-headroom kan du köra granskningen lokalt i stället för mot en molnleverantör. Starta t.ex. [Ollama](https://ollama.com/) eller llama.cpp och välj **Custom**-leverantören med base-URL `http://localhost:11434/v1` (loopback kräver inget samtycke och lämnar aldrig maskinen). Det statiska system-/few-shot-prefixet återanvänds via modellens KV-cache, vilket sänker svarstiden ytterligare.

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
| `~/.freewispr-swedish/models/` | Nedladdade CT2-modellfiler |

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
+-- convert_model.py     # laddar ned pre-konverterade CT2-modellfiler
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
Inte stöttat just nu. När en inspelning ger text klistras den automatiskt in och ligger kvar i urklipp så du kan klistra in den manuellt om paste inte gick fram.

**Fungerar det utan internet?**
Ja, själva dikteringen fungerar offline så länge du redan har laddat ned en lokal modell (`python convert_model.py small`). LLM-granskning, remote-transkribering och modell-/providerhämtning kräver internet.

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
