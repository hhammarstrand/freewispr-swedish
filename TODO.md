# TODO

Aktiv, öppen förbättringslista. Avklarade poster från tidigare granskningar
(2026-05-20, 2026-05-27) har flyttats till [`TODO-archive.md`](TODO-archive.md)
för att hålla den här listan kort.

Den här filen innehåller djupgranskningen 2026-06-02. Merparten av posterna är
nu åtgärdade (`[x]`); de återstående (`[ ]`) är medvetet uppskjutna och
motiverade nedan.

## Återstår (medvetet uppskjutet)

Dessa fem är kvar — var och en är antingen riskabel att ändra blint eller
kräver en miljö/refaktor som inte ryms i den här rundan:

- **`dictation.py` live-transkriberings-drift** `[MEDIUM]` — ändrar
  tystnadssegmenteringen i en subtil ljudalgoritm på en opt-in-funktion
  (`live_transcribe_enabled`); kräver egen verifiering med riktigt ljud.
- **`main.py:493-497` fast-path-credentials utan lås** `[MEDIUM]` — korrekt fix
  kräver att credentials byts som ett immutabelt objekt (refaktor av läsvägarna
  i `polish`/`_transcribe_remote`). Warmer-omstarten (åtgärdad) tar bort den
  värsta risken (stale endpoint).
- **`http_pool.py:130-158` globalt lås över I/O** `[LOW/MED]` — per-origin-lås
  är en riskabel ändring av connection-poolen; nuvarande beteende är korrekt,
  bara mindre parallellt.
- **`llm_polish.py:190-218` `gh auth token` från PATH** `[LOW/SECURITY]` — en
  riktig fix kräver UI-opt-in/absolut sökväg; lämnas tills UI-ytan finns.
- **`requirements.txt` hash-låsning (`--require-hashes`)** `[LOW/MED]` — kräver
  ett komplett transitivt hash-manifest genererat och verifierat mot Windows-
  bygget; fel manifest bryter release-pipelinen.

## Djupgranskning 2026-06-02 (hela repot) — konsoliderad

Sammanslagning av tre oberoende djupgranskningar (hela kodbasen, inkl. moduler som
tillkommit efter förra rundan: `flow.py`, `learning.py`, `snippets.py`, `modes.py`,
`commands.py`, `voice_edit.py`, `http_pool.py`, `single_instance.py`, `updater.py`,
`context_win.py`, `ui/qt_indicator*`). Dubbletter är sammanslagna; severity i hakparentes.

**Källtaggar:** `[OC]` = OpenCode/Claude-granskning · `[GPT]` = ChatGPT-granskning ·
`[Gem]` = Gemini-granskning (flera taggar = samma fynd hittat oberoende av flera).

### Kritiskt / hög prioritet (säkerhet + invarianter)

- [x] `text_sanitize.py` — `sanitize_output()` strippar nu även Unicode bidi-
  overrides (U+202A–202E, U+2066–2069) och rad/stycke-separatorer (U+2028/U+2029),
  inte bara ASCII/Latin-1 C0/C1. **[HIGH]** `[OC]` Trojan Source neutraliserad.

- [x] `llm_polish.py:test_connection()` — provider-`body` saneras nu via
  `sanitize_output()` innan den når Settings-UI. **[HIGH]** `[OC]` (invariant 2)

- [x] `remote_transcribe.py:_http_message`/`test_connection` — rå provider-error-
  body saneras nu innan den når indikator/UI. **[HIGH]** `[OC]` (invariant 2)

- [x] `dictation.py` + `ui/indicator.py` — den 5:e indikator-staten `"review"`
  borttagen; polish-väntan mappar till `transcribe`. Död `review`-rendering
  borttagen även i Qt-barnet. **[HIGH]** `[OC]` (4-state-invarianten)

- [x] `single_instance.py` — `CreateMutexW`/`CloseHandle` har nu `restype`/
  `argtypes` (HANDLE trunkeras inte på Win64) och felkoden läses via
  `ctypes.get_last_error()` (WinDLL med `use_last_error=True`). **[HIGH]** `[OC]`

- [x] `main.py` modellreload — gamla `WhisperModel` släpps nu synkront
  (`close()` + `gc.collect()`) **före** rebind, inte i en daemon-tråd efteråt.
  **[HIGH]** `[OC]` (regression åter-fixad)

- [x] `http_pool.py:58` — pooled anslutning öppnas om när anroparen behöver
  längre timeout än socketen öppnades med. **[HIGH]** `[OC]`

- [x] `ui/indicator.py` — push-throttle-state (`_pushed_level`/`_pending_push`/
  `_last_push_ms`) skyddas nu av ett lås (skrivs från både audio- och Tk-tråden).
  **[HIGH]** `[OC]` *Not: den testade coalescing-kontrakten (≤1 schemalagd
  redraw per burst) behölls; full main-thread-kö var oförenlig med det testet.*

- [x] `main.py:_quit` — teardown marshallas till Tk-main-tråden (ingen cross-
  thread `quit()`/`destroy()`/`sys.exit()` på pystray-daemonen) och single-
  instance-låset släpps **sist** i `_final_cleanup()`. **[HIGH/RACE]** `[OC][GPT][Gem]`

- [x] `ui/settings_window.py` — loopback-undantaget sparas **inte** längre som
  `llm_privacy_accepted=True`; loopback-skippen utvärderas i runtime
  (`main._active_llm_settings`). **[HIGH/PRIVACY]** `[GPT]`

- [x] `context_win.py`/`dictation.py`/`llm_polish.py` — skärmnamn (`onscreen_names`)
  skickas nu bara till LLM-polish vid lokal loopback eller med explicit
  `context_to_remote_accepted`-samtycke (`_names_for_llm()`), symmetriskt med
  remote-STT-grinden. **[HIGH/PRIVACY]** `[GPT]`

- [x] `transcriber.py` LLM-/STT-warmers — kör nu på en immutabel credential-
  snapshot per tråd och har `restart_warmers()` som Settings-fast-path anropar
  vid provider/key/base_url-ändring. **[HIGH/PRIVACY]** `[GPT]`

- [x] `config.py` migration `llm_model` -> `llm_model_github` — skriver nu nyckeln
  i `data` som persisteras, inte bara runtime-`cfg`. **[HIGH/DATA-LOSS]** `[GPT]`

- [x] `remote_transcribe.py` — HTTP 200 utan användbar transkription (HTML,
  malformed JSON, JSON utan `text`) höjer nu `RemoteTranscribeError` i stället
  för att maskeras som tyst `""`/"Inget hördes". **[HIGH]** `[GPT]`

### Medel (hot path-race + robusthet)

- [x] `dictation.py` voice-edit — kort ljud återställer/döljer nu indikatorn
  (inte fast i "Tolkar redigering…"). **[MEDIUM]** `[OC]`

- [x] `dictation.py` — kontext + live-state binds nu till respektive jobb via
  `_PressState` genom kön; ett snabbt nästa knapptryck kan inte längre skriva
  över ett köat jobbs kontext/live-partials. **[MEDIUM]** `[OC]`

- [ ] `dictation.py` live-transkribering — tystnadssegmenteringen glider mellan
  `_live_loop` (växande snapshots) och `_combine_live` (re-split av hela
  inspelningen). **[MEDIUM]** `[OC]` *Uppskjutet — se "Återstår" ovan.*

- [x] `config.py` — `copy.deepcopy(DEFAULTS)` så nästlade containrar (app_profiles)
  inte delas per referens med modulens DEFAULTS. **[MEDIUM]** `[OC]`

- [x] `config.py` — migrations-skrivningen i `load()` tar nu `_save_lock`.
  **[MEDIUM]** `[OC]`

- [x] `json_store.py` — `JsonCache.load()`/`save()` returnerar/lagrar djupkopior
  så extern mutering inte desyncar cachen. **[MEDIUM]** `[OC]`

- [x] `learning.py:add_hotwords()` — atomisk (temp+replace) och låst read-modify-
  write av `hotwords.txt`. **[MEDIUM]** `[OC]`

- [x] `main.py` — `_rollback()` undviker tomt mellanläge (ingen `clear()`), så
  olåsta läsare aldrig ser en tom config. **[MEDIUM]** `[OC]` *Not: `.update()`
  är additivt → läsare ser alltid en giltig config.*

- [ ] `main.py:493-497` — fast-path skriver `_transcriber.*`-credentials utan
  `_model_lock`. **[MEDIUM]** `[OC]` *Uppskjutet — se "Återstår" ovan.*

- [x] `ui/qt_indicator.py` — `_ensure_started()` (spawn) och `_send()` (stdin)
  skyddas nu av en RLock så två trådar inte startar två barnprocesser eller
  blandar bytes. **[MEDIUM]** `[OC]`

- [x] `ui/settings_window.py` — async-`after`-callbacks har nu `winfo_exists()`-
  guard + generation-token (LLM-modellhämtning), så stängt fönster/ny provider
  inte kraschar eller skriver över. **[MEDIUM]** `[OC]`

- [x] `convert_model.py` — completeness-checken verifierar nu **alla**
  `_REQUIRED_FILES`, inte bara `model.bin`. **[MEDIUM]** `[OC]`

- [x] `transcriber.py:_patch_vocabulary` — skriver ny `vocabulary.json` till temp
  och byter atomiskt; flyttar inte originalet före lyckad skrivning. **[MEDIUM]** `[OC]`

- [x] `ui/settings_window.py` — `transcription_privacy_accepted` bevaras nu vid
  lokal provider (skrivs bara vid explicit accept/revoke). **[MEDIUM/CONSENT]** `[GPT]`

- [x] `ui/settings_window.py` — snippets/rättelser/personlig kontext skrivs nu
  **efter** att `on_save()` validerat och persistat huvudconfig. **[MEDIUM/DATA-LOSS]** `[GPT]`

- [x] `url_security.py` — custom `base_url` avvisar nu `?query` och `#fragment`
  (nyckel-läckage till loggar). **[MEDIUM/SECURITY]** `[GPT]`

- [x] `llm_polish.py` — `instruct()`/`test_connection()` resolvar base-URL inom
  guard (ValueError → originaltext / (False, meddelande)). **[MEDIUM]** `[GPT]`

- [x] `paste.py` — clipboard-restore har nu generation + pre-burst-snapshot; bara
  senaste restore kör och egen inklistrad text snapshottas inte. **[MEDIUM/RACE]** `[GPT]`

- [x] `paste.py`/`voice_edit.py` — voice-edit-disclosure: LLM-samtyckesdialogen
  och hinten anger nu att markerad text (möjlig PII) skickas till leverantören.
  **[MEDIUM/PRIVACY]** `[GPT]`

- [x] `config.py:context_to_remote_accepted` — grinden är nu funktionell för både
  remote-STT och remote-LLM med säker default (av). UI-text "All skärmtext
  används lokalt" är sann för alla UI-nåbara lägen. **[MEDIUM/UX]** `[GPT]`

- [x] `remote_transcribe.py` — FLAC/Opus delar nu mono-normalisering
  (`_to_mono`, `mean(axis=1)`) med WAV-vägen; ingen `reshape(-1)`-korruption.
  **[MEDIUM]** `[GPT]`

- [x] `flow.py` — stannar nu (`return`) när Flow stoppas mitt i bearbetning i
  stället för att fortsätta klistra in chunks efter stopp. **[MEDIUM]** `[GPT][Gem]`

### Lägre prioritet (robusthet/kosmetik)

- [x] `remote_transcribe.py:test_connection` — använder nu no-redirect-poolen
  (urlopen följde redirects och kunde läcka `Authorization: Bearer`). **[LOW]** `[OC]`

- [ ] `http_pool.py:130-158` — globalt lås hålls över hela nätverks-round-tripen.
  **[LOW/MEDIUM]** `[OC]` *Uppskjutet — se "Återstår" ovan.*

- [x] `http_pool.py` — `resp.read()`/SSE-loopen har nu en storleksgräns (32 MB).
  **[LOW/MEDIUM]** `[OC]`

- [x] `llm_polish.py:polish()` — loggar inte längre rå provider-body (kan eka
  transcript); loggar bara byte-storlek. **[LOW]** `[OC]` (invariant 6)

- [x] `dictation.py` — OOM-checkens `and`-subuttryck parentesat (RUF021). **[LOW]** `[OC]`

- [x] `migrate_context.py` — whitespace-only nycklar filtreras bort
  (`str(k).strip()`). **[LOW]** `[OC][Gem]`

- [x] `learning.py` — eviction slår nu på recency (touched-keys flyttas sist),
  inte ren insättningsordning. **[LOW]** `[OC]`

- [x] `updater.py` — `tag[1:] if startswith("v")` i stället för `lstrip("v")`.
  **[LOW]** `[OC]`

- [x] `ui/first_run.py` — `winfo_ismapped()`/`pack` guardade mot destroyat fönster;
  en nedladdning som blir klar efter cancel kastas inte längre. **[LOW]** `[OC]`

- [x] `snippets.py` & `modes.py` — `add()`/`remove()` read-modify-write är låst.
  **[LOW]** `[OC]`

- [x] `config.py` — `_providers_validated`-flaggan skyddas av ett lås. **[LOW]** `[OC]`

- [ ] `llm_polish.py:190-218` — GitHub-token-fallback kör `gh auth token` från PATH.
  **[LOW/SECURITY]** `[GPT]` *Uppskjutet — se "Återstår" ovan.*

### Bygg, release, supply chain & lint

- [ ] `requirements.txt` / `build-windows.yml` — hash-låst requirements med
  `--require-hashes`. **[LOW/MEDIUM]** `[GPT]` *Uppskjutet — se "Återstår" ovan.*

- [x] `transcriber.py` `KBLAB_REVISIONS` — synkad med `convert_model.py`:s pinnade
  commit-SHA:er (var `None`). Den effektiva nedladdnings-pinnen finns i
  `convert_model.py` (redan pinnad; laddning här är `local_files_only`).
  SHA256-manifest-verifiering återstår som framtida härdning. **[LOW/MEDIUM]** `[GPT]`

- [x] `.github/workflows/pages.yml` — actions SHA-pinnade med versionskommentar
  (samma stil som `build-windows.yml`). **[LOW]** `[GPT]`

- [x] `design/preview_indicator.py`, `make_demo_gif.py`, `tests/test_updater.py` —
  rena mot `ruff` (E,F,W); de tidigare rapporterade felen är redan åtgärdade.
  **[LOW]** `[OC]`
