# CLAUDE.md

Instruktioner för Claude (och Claude Code) när du arbetar i det här repot.

## Projektet i en mening

`freewispr-swedish` är en Windows-app för svensk push-to-talk-diktering byggd på KBLab:s Whisper-modeller, med valfri LLM-granskning via flera providers. Lokal-först, ingen registrering.

## Språkpolicy

- **Användarsynliga strängar** (status, fel, indikator, dialoger, README, webbsida) måste vara på **svenska med korrekta å/ä/ö**. Aldrig "oppnas", "modell" utan å/ä, eller "..." istället för "…".
- **Loggar, kommentarer, commit-meddelanden, docstrings** kan vara på engelska — det är internt.
- **Identifierare i kod** (variabelnamn, funktionsnamn) är engelska.

### Konsol/encoding (undvik falsklarm om mojibake)

- **`å/ä/ö` som visas som `H�g`/`Ã¥` i terminalutdata är ett konsol-avkodningsfel, INTE en filbugg.** Filerna är UTF-8; den här maskinens OEM-kodsida är 850 (IBM850), så konsolen avkodar UTF-8-bytes fel. **Ändra aldrig filinnehållet** (t.ex. byt `ö`→`o`) för att "fixa" sånt här — det förstör korrekt UTF-8. Verifiera alltid mot byte-innehållet (`Read`-verktyget eller `[System.Text.Encoding]::UTF8.GetString(...)`), inte mot rå konsoloutput, innan du tror att tecken är trasiga.
- **Fixa rätt encoding beroende på kontext:** interaktiva PowerShell-sessioner får UTF-8 via `~/Documents/PowerShell/profile.ps1`. Agent-/verktygsanrop kör `pwsh -NoProfile` och hoppar över profilen — sätt då UTF-8 i kommandot, och som **egen rad före** läsningen (inte med `;` i samma pipeline, då hinner strömmen kodas först):

  ```powershell
  [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
  Select-String -Path TODO.md -Pattern "^## "
  ```

## Hot path

Användaren håller en hotkey → spelar in → släpper → text klistras in. Allt mellan key-up och paste är på den kritiska latency-vägen:

```
audio.py:MicRecorder.stop_fast()  →  finalize_audio()  →
transcriber.py:transcribe()  →  paste.py:paste_text()
```

LLM-polish körs **asynkront efter paste** via `transcriber.py:polish_async()` med en `threading.Timer(15s)` watchdog så indikatorn aldrig hänger. Personlig kontext från `personal_context.py` injiceras i polish-system-prompten via `llm_polish.py:polish()`.

## Indikatorns 4 states

`ui/indicator.py:FloatingIndicator` accepterar exakt fyra `state`-värden — alla nya statusmeddelanden måste mappa till ett av dem:

| state | färg | när |
|---|---|---|
| `listen` | blå | inspelning pågår |
| `transcribe` | orange | transkribering / LLM-polish pågår |
| `done` | grön | text klistrad eller färdig |
| `error` | röd | fel inträffade |

Lägg inte till nya states — utöka `_COLORS`-mappningen om det absolut krävs.

## Filöversikt

| Fil | Roll |
|---|---|
| `main.py` | Tray icon, tk root, app lifecycle, settings reload-koordinering |
| `dictation.py` | Hotkey hooks, recording state machine, transcribe → paste pipeline |
| `transcriber.py` | Whisper-anrop (lokal eller remote), LLM polish_async + 15s watchdog |
| `audio.py` | MicRecorder, finalize (downmix + resample till 16 kHz) |
| `paste.py` | Clipboard + syntetisk Ctrl+V / Shift+Insert i konsoler |
| `llm_polish.py` | 5 providers, polish() + test_connection(), läser personal_context |
| `remote_transcribe.py` | 3 remote-providers (staik/berget/custom) för audio-API |
| `config.py` | JSON-config + keyring-backed secrets, migration, save_lock |
| `personal_context.py` | Fritextkontext för LLM (ersatte gamla auto_learn-arkitekturen) |
| `migrate_context.py` | One-shot migration vid app-start — idempotent |
| `context_win.py` | Kontextmedvetenhet (AP3): aktiv app + text nära markören, app-profiler |
| `learning.py` | Inlärningsloop (AP2): lär `fel → rätt`-par från användarens manuella rättelser |
| `snippets.py` | Textexpansion (AP7.6): ledande trigger-fras → expansion |
| `modes.py` | Användardefinierade lägen (KP2): namngivna ton-/formatprofiler |
| `commands.py` | Kommandoläge (AP5): röststyrd redigering av senaste blocket |
| `voice_edit.py` | Röstredigering (KP3): LLM-redigera markerad text via egen hotkey |
| `flow.py` | Flow-läge (AP6, opt-in): kontinuerlig diktering över pauser, endast lokal |
| `http_pool.py` | Delad keep-alive HTTP-transport (L2), per-origin-lås, storleksgräns |
| `single_instance.py` | Single-instance-spärr (mutex på Windows, loopback-port annars) |
| `updater.py` | Notis-only uppdateringskoll mot GitHub Releases (hårdkodad URL) |
| `text_sanitize.py` | `sanitize_output()` — strippa ANSI/control-bytes + Trojan Source-bidi |
| `url_security.py` | `is_plaintext_loopback()`, base URL-validering |
| `json_store.py` | `JsonCache` med mtime-invalidering, atomic save |
| `modifiers.py` | Kanoniska modifier-tangentnamn + alias-mapping |
| `sounds.py` | In-process WAV-syntes för start/stop/error |
| `convert_model.py` | Lättviktig modellnedladdning via `huggingface_hub` (pinnade revisioner) |
| `hardware.py` | GPU-VRAM-detektering + modellstorleksrekommendation (first-run) |
| `make_icon.py` | Genererar tray/window-ikoner |
| `ui/` | Tkinter/CustomTkinter — `indicator`, `settings_window`, `first_run`, m.fl. |

## Providers (fullständig enumeration)

Hårdkodade på tre ställen (`config.py`, `llm_polish.py`, `remote_transcribe.py`). När du lägger till en provider — uppdatera **alla tre** och kör `_validate_providers()`-flödet.

- **LLM-providers** (`llm_polish.py:PROVIDERS`): `github`, `staik`, `berget`, `openai`, `custom`
- **Transkriberings-providers** (`remote_transcribe.py:PROVIDERS`): `staik`, `berget`, `custom` — plus den implicita `local` som hanteras i `transcriber.py`

## Designinvarianter (bryt inte)

1. **API-nycklar lagras i Windows Credential Manager via `keyring`**, aldrig i `config.json`. Se `config.py:_SECRET_FIELDS`. När du läser/skriver hemligheter — gå via `config.save()` / `config.load()`.
2. **All LLM-respons och remote-transkribering måste passera `sanitize_output()`** innan den når urklipp eller UI. Hotmodell: komprometterad provider injicerar ANSI-escape-sekvenser. Båda `polish()` och `test_connection()` gör detta.
3. **Consent gates får inte kringgås.** `llm_privacy_accepted` och `transcription_privacy_accepted` styr när audio/text får skickas över nät. Persistas i config **oberoende** av om respektive feature är på (annars förlorar användaren consent när hen tillfälligt stänger av LLM).
4. **Audio-status måste reflektera vad som faktiskt händer**: om `transcription_provider != "local"` ska användaren se "Transkriberar via X…" så de vet att audio lämnar maskinen — även om LLM-polish är av.
5. **Lokal Whisper laddas med `local_files_only=True`**. Appen kontaktar aldrig HuggingFace automatiskt under normalt bruk. Endast `convert_model.py` och `ui/first_run.py` får ladda ned.
6. **Loggar får aldrig innehålla API-nycklar eller full transkriptionstext.** Logga metadata: `chars`, `words`, `latency_ms`, `model`. Se `_text_meta()` i `transcriber.py`.

## Testkörning

```bash
python -m pytest tests/ -q
ruff check . --select E,F,W --ignore E501
```

Båda måste vara gröna innan en PR mergas. CI kör samma kommandon plus `pip-audit`.

Native deps (`sounddevice`, `keyboard`, `pyperclip`, `pystray`, `winsound`) stubbas via `tests/conftest.py` så testerna fungerar headless. `faster_whisper` stubbas centralt i conftest **endast när paketet saknas** — i CI/Windows (där det är installerat) används den riktiga importen. Tester som behöver `PIL`/`tkinter` skippas när de saknas lokalt men körs i CI; installera `pillow` + `python3-tk` lokalt för full CI-paritet. Detta kräver:

- **`from __future__ import annotations`** i alla nya moduler som har type hints med stubbade typer (t.ex. `pystray.Icon | None`). Utan det evalueras annotationerna vid import och kraschar mot stubbarna. Befintliga moduler som följer mönstret: `main.py`, `transcriber.py`, `llm_polish.py`, `remote_transcribe.py`, `personal_context.py`, `text_sanitize.py`, `url_security.py`, `migrate_context.py`, `make_icon.py`.

## Konventioner

- **Hotkey/keyboard:** `dictation.py:_parse_hotkey()` normaliserar via `modifiers.py`. Lägg inte till nya alias direkt — utöka `modifiers._ALIASES` med kanonisk form.
- **Config-fält:** lägg till i `config.py:DEFAULTS` + uppdatera consent-villkor om nytt nätbeteende införs. Per-provider-fält följer mönstret `{feature}_{kind}_{provider}` (`llm_api_key_github`, `transcription_model_staik`).
- **Felmeddelanden** för användaren går via `_friendly_mic_error()` / `_friendly_transcribe_error()` i `dictation.py`. Lägg till nya nyckelord där istället för att läcka råa exceptions.
- **GitHub Actions** pinas till SHA + version-kommentar. Se `build-windows.yml` för stilen: `uses: actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd  # v6.0.2`.
- **Modellrevisioner** pinas i `transcriber.py:KBLAB_REVISIONS` för reproducerbara nedladdningar.
- **PyInstaller** kräver `--collect-submodules=ui` så hela `ui/`-paketet bundlas. Glömmer du det bryter alla fönster i den frysta exe:n.

## Git-flow

- **Branch-namn:** `claude/<kort-beskrivning>` för Claude-genererat arbete; `fix/`, `feat/`, `docs/` för manuellt arbete.
- **Commit-meddelanden:** Conventional commits på engelska — `fix:`, `feat:`, `refactor:`, `docs:`, `ci:`, `security:`, `robust:`. En rad sammanfattning + brödtext som förklarar *varför*.
- **PR-titel:** svenska om användarrelevant, engelska om internt (refactor, lint).
- **PR-merge:** squash är default. Pre-mergerebase bara om det behövs för konflikter.
- **Aldrig** `--no-verify` eller skip-hooks. Om CI failar — fixa root cause.

## Vad du *inte* bör göra

- **Återinför inte den gamla auto_learn-arkitekturen** (`auto_learn.py`/`corrections.py`-modulerna som togs bort i `8ed9942`). Observera att snippets och rättelser har *återinförts i ny form* — `snippets.py` (AP7.6, trigger→expansion) och `learning.py` (AP2, diff-baserad inlärning) är aktiva moduler och ska inte "städas bort". Det som inte ska tillbaka är den gamla designen: mtime-cachade modulglobaler, auto-promotion utan diff-tröskel och den tunna key-value-list-UI:n.
- **Inför ingen lazy-import-cykel** mellan `config.py` och `llm_polish.py`/`remote_transcribe.py`. `config.py` validerar provider-listor lazy via `_validate_providers()` — efterlikna det mönstret.
- **Bygg ingen ny UI-stack** ovanpå Tkinter/CTk om det inte är absolut nödvändigt. Att byta till Qt/Electron är diskuterat och avvisat — alla UI-bidrag måste fungera inom den befintliga `ui/`-paketstrukturen.
- **Återinför inte mic prewarm.** Den togs bort i `d238086` efter att den krockade med andra ljudströmmar (t.ex. Spotify körandes parallellt). Ersattes av device-spec cache + low-latency open.

## Verifiering före PR

1. `python -m pytest tests/ -q` → alla gröna
2. `ruff check . --select E,F,W --ignore E501` → All checks passed
3. Manuell smoke-test om Windows-flödet ändrats: kör `python main.py`, diktera, kolla att text klistras in
4. Granska commit-meddelanden — på engelska, beskrivande, `type: kort beskrivning`
5. PR-titel + body på svenska om det är användarrelevant; engelska om det är internt

## Resurser

- Webbsidan: <https://hhammarstrand.github.io/freewispr-swedish/>
- KBLab-modeller: <https://huggingface.co/KBLab>
- faster-whisper: <https://github.com/SYSTRAN/faster-whisper>
