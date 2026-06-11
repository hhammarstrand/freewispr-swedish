# Ändringslogg

Alla väsentliga ändringar i `freewispr-swedish` dokumenteras i denna fil.

Formatet följer [Keep a Changelog](https://keepachangelog.com/sv/1.1.0/) och
projektet använder [semantisk versionshantering](https://semver.org/lang/sv/).

## [1.1.0] — 2026-06-11

Säkerhets-, robusthets- och prestandarunda ovanpå 1.0.0, plus två nya
röstlägen för markerad text. Helt bakåtkompatibel — befintlig config
fungerar oförändrad.

### Tillagt

- **Uppdateringsnotis via GitHub Releases.** Vid varje start kontrollerar
  appen om en nyare stabil version finns publicerad på
  `github.com/hhammarstrand/freewispr-swedish/releases`. Om så är fallet
  visas en native Windows-toast och en menyrad i tray-ikonen som öppnar
  release-sidan i webbläsaren. Ingen automatisk nedladdning — användaren
  installerar själv. Pre-releases och drafts ignoreras. En manuell knapp
  "Sök efter uppdateringar" finns också i tray-menyn. Check skippas i
  utvecklarläge (icke-frozen) om inte miljövariabeln
  `FREEWISPR_FORCE_UPDATE_CHECK=1` är satt.
- **Live-transkribering under inspelning** (på som standard, endast lokal
  modell): färdiga fraser avkodas medan du fortfarande pratar, så vid
  släpp återstår bara svansen och texten klistras nästan direkt även efter
  långa dikteringar. Kan stängas av under Inställningar → Smart.
- **Fortsättningskontext:** texten som redan står före markören matas till
  Whisper som kontext, vilket ger konsekvent versalisering och terminologi
  vid diktering mitt i en mening. Skärmtext delas aldrig med en
  remote-tjänst utan uttryckligt medgivande.
- **Auto-rekommenderad modellstorlek vid första körning:** på en NVIDIA-GPU
  föreslås `large`/`medium` (efter VRAM) i stället för `small`, för bättre
  noggrannhet utan märkbar fördröjning.
- Experimentell `whisper_chunk_length` och `whisper_cpu_threads` i config
  för finjustering av lokal transkribering.
- **Röstredigering av markerad text (KP3):** markera text, håll en egen
  hotkey och säg en instruktion ("gör formellt", "översätt till engelska")
  — LLM:en skriver om markeringen på plats. Av som standard.
- **Svara på markerad text (KP4):** markera t.ex. ett mejl, håll en egen
  hotkey och säg vad du vill svara — LLM:en skriver svaret och lägger det i
  **urklipp** (klistras aldrig in, så markeringen är kvar). Klistra in det
  själv med Ctrl+V. Av som standard.

### Ändrat

- **Snabbare ljudberedning:** `soxr` följer nu med i bygget (~35 % snabbare
  downmix/resampling på den kritiska vägen; faller tillbaka till scipy).
- **Auto-dimensionerade CPU-trådar** för CTranslate2 (utnyttjar fler
  kärnor på CPU-maskiner; ingen effekt på CUDA).
- Live-lägets resampling är nu O(n) i stället för O(n²) via strömmande
  resampling.
- **Endast Tkinter-indikatorn kvar.** Den process-isolerade Qt-indikatorn
  (PySide6) och stilarna "modern"/"transparent" är borttagna — indikatorn
  är nu alltid den lätta Tkinter-varianten. Mindre bygge, färre beroenden.
- **LLM-uppvärmningen pollar inte längre.** Anslutningen värms en gång vid
  start (och vid provider-/nyckelbyte) i stället för ett 1-token-anrop var
  25:e sekund — inga billbara anrop till leverantören i viloläge.

### Säkerhet / integritet

- `sanitize_output()` strippar nu även "Trojan Source"-bidi-tecken;
  all provider-felrespons (LLM + remote-STT) saneras innan den når UI.
- Samtycke för LLM-granskning och remote-transkribering sparas oberoende
  av om funktionen är på; ett lokalt loopback-godkännande ärvs aldrig som
  remote-samtycke. Skärmnamn skickas till remote-tjänster endast med
  uttryckligt medgivande. Röstredigering avslöjar att markerad text skickas
  till leverantören.
- Custom-bas-URL:er avvisar nu querystring/fragment; `gh auth token`
  resolveras via absolut sökväg; transkriptionstext loggas aldrig.

### Fixat

- Korrekt nedstängning (ingen cross-thread Tk-teardown; single-instance-
  låset släpps sist), gammal Whisper-modell frigörs före omladdning (VRAM),
  atomisk config-/hotwords-skrivning, per-jobb-bunden kontext, remote-fel
  visas i stället för att maskeras som "Inget hördes", och misslyckad
  inklistring loggas i stället för att tystas.
- **Röstredigering/svara läser nu markeringen i fler appar.** Den
  syntetiska Ctrl+C:n skickas taktat (mänsklig timing) så Office-, Chromium-
  och WebView-appar (Word, Outlook, Teams, Electron) hinner skriva urklipp —
  tidigare fungerade det bara i enkla kontroller som Notepad++.
- **Markerings-hotkeys är nu modifierar-kombinationer** (t.ex. Ctrl+Alt /
  Ctrl+Shift) som drivs av en global hook, eftersom en bokstavstangent
  skrev över markeringen och vissa tangentbord inte skiljer höger/vänster
  Ctrl.

## [1.0.0] — 2026-05-28

Första publika releasen av den svenska forken. Stabil och produktionsklar
desktopapp för svensk diktering på Windows med valbar LLM-granskning och
remote-transkribering.

### Tillagt

- **Personlig kontext** — fritextfält i Inställningar som injiceras i
  LLM-system-prompten. Ersätter tidigare snippets och personlig ordlista
  med en enkel, transparent modell. Max 8000 tecken.
- **Vänta-läge för LLM-granskning** — när LLM är aktiverat klistras
  den polerade texten direkt i ett enda steg (ingen rå text → ny paste).
  Watchdog på 15 sekunder faller tillbaka till rå transkribering om
  LLM hänger.
- **Automatisk migration** vid första start efter uppgradering: tidigare
  `snippets.json`, `corrections.json` och `learned.json` slås ihop till
  `personal_context.json`. Explicit definierade rättningar vinner över
  auto-lärda observationer.
- **Remote-transkribering** via STAIK (Sveriges AI-kommun) och Berget AI
  med svenska KB-Whisper-modeller. Lokal Whisper kvar som standard.
- **Separata API-nycklar** för transkribering och LLM (säker lagring i
  Windows Credential Manager via `keyring`).
- **Första-körnings-dialog** som introducerar appen och tar explicit
  samtycke för LLM-granskning och remote-transkribering (båda av som
  standard).
- **Inställningar > Allmänt > "Starta med Windows"** synkad med
  tray-menyns motsvarande toggle.
- **Återhämtning** vid CUDA out-of-memory, korrupta modeller och hängande
  LLM-anrop — appen försöker degradera istället för att krascha.
- **Audio-feedback** vid start/stopp av diktering (kan stängas av).
- **GitHub Pages-landningssida** (`docs/index.html`) med funktionsöversikt,
  FAQ och nedladdningslänk.

### Ändrat

- **Modellrevisioner låsta** till specifika commit-SHA:n på Hugging Face
  för reproducerbara byggen.
- **Pinned dependencies** i `requirements.txt` med övre gränser för att
  undvika att numpy 2.x och liknande bryter bygget.
- **CTk-baserat UI** genomgående (Settings, FirstRun, Pair, Indicator).
- **Atomisk JSON-lagring** med tempfil + replace och backup av korrupt
  data istället för tyst förlust.
- **CI** kör tester, lint, pip-audit och Dependabot på varje PR.

### Borttaget

- `snippets.py`, `corrections.py`, `auto_learn.py` och tillhörande
  UI-fönster — ersatta av Personlig kontext. Data migreras automatiskt
  vid första start.
- `pyautogui` som runtime-beroende (paste sker via `keyboard.send`).

### Säkerhet

- API-nycklar lagras inte längre i `config.json` plaintext.
- Remote-transkribering har ingen lokal fallback (medvetet val för att
  inte tyst skicka ljud när användaren tror att lokalt används).
- HTML-sanity-check på JSON-fallback från remote-transkribering för att
  förhindra att HTML-felsidor klistras in i användarens dokument.
- Alla URL:er för custom-providers valideras innan anrop.

### Migration från tidigare interna versioner

- Inga åtgärder krävs. Vid första start efter uppgradering migreras
  `snippets.json`, `corrections.json` och `learned.json` automatiskt
  till `~/.freewispr-swedish/personal_context.json`. Originalfilerna
  lämnas orörda som backup och kan raderas manuellt.
