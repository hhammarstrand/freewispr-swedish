# Ändringslogg

Alla väsentliga ändringar i `freewispr-swedish` dokumenteras i denna fil.

Formatet följer [Keep a Changelog](https://keepachangelog.com/sv/1.1.0/) och
projektet använder [semantisk versionshantering](https://semver.org/lang/sv/).

## [Ej släppt]

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
