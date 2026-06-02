# TODO

Prioriterad förbättringslista baserad på repo-granskning 2026-05-20.
Kompletterad med pre-launch-granskning 2026-05-27.

## Hög prioritet

- [x] Stoppa loggning av dikterad text som standard.
  - Berör: `dictation.py`, `transcriber.py`, `llm_polish.py`, `auto_learn.py`.
  - Logga metadata i stället, t.ex. längd, latency, modell och status.
  - Lägg eventuell transcript-loggning bakom explicit debug/opt-in.

- [x] Förtydliga integritet och nätverksbeteende för LLM-granskning.
  - Berör: `README.md`, `ui.py`, `llm_polish.py`.
  - README säger i dag att appen är 100% lokal/offline, men LLM-läget skickar text till GitHub Models/Azure.
  - Lägg till tydlig opt-in-varning i UI och dokumentera exakt vad som skickas.

- [x] Flytta LLM API-nyckel från plaintext config till säker lagring.
  - Berör: `config.py`, `ui.py`, `main.py`.
  - Använd Windows Credential Manager via exempelvis `keyring`.
  - Spara endast flagga/referens i `config.json`, inte tokenvärdet.

- [x] Gör Windows-autostart opt-in.
  - Berör: `main.py`.
  - Ta bort automatisk aktivering vid första körning av fryst exe.
  - Låt användaren slå på funktionen själv via tray-menyn eller en första-körningsdialog.

- [x] Lägg till automatiska tester.
  - Lägg till `pytest` och börja med rena enhetstester.
  - Testa minst `transcriber._postprocess`, `corrections.apply`, `snippets.expand`, config-load/save och LLM-fallback.
  - Mocka Whisper, tangentbord, ljudenheter, clipboard och nätverk.

## Buggar (pre-launch-granskning 2026-05-27)

- [x] Fixa `_SYSTEM_PROMPT` i `llm_polish.py` — innehåller degraderad svenska utan å/ä/ö.
  - Berör: `llm_polish.py:226-233`.
  - "ar" → "är", "hora" → "höra", "Andra" → "Ändra", "innehall" → "innehåll" osv.
  - Kan försämra LLM:ens förmåga att följa svenskspråkiga instruktioner.

- [x] Fixa typo i `audio.py:228`: `"oppnas"` → `"öppnas"` (syns för användaren vid mikrofonfel).

- [x] Fixa typo i `audio.py:305`: `"naadde"` → `"nådde"` (syns i loggar).

- [x] Fixa TOCTOU dubbel-stat i `corrections.py:37` och `snippets.py:24`.
  - `_cache_mtime` sätts med ett andra `stat()`-anrop efter laddning.
  - Om filen skrivs igen mellan load och det andra stat()-anropet kan cachen
    registrera en nyare mtime än det som faktiskt laddades, vilket döljer
    nästa riktiga uppdatering.
  - Lösning: spara mtime från det första anropet, använd det genom hela load().

- [x] `save()` i `corrections.py:49` och `snippets.py:35` saknar try/except kring `_FILE.stat().st_mtime`.
  - Om stat() misslyckas direkt efter sparning (race, behörighetsändring)
    kastas ett ohanterat OSError.

- [x] `_enable_startup` i `main.py:513-519` är död kod — aldrig anropad.
  - `_toggle_startup` implementerar samma logik inline.
  - Ta bort den döda funktionen.

- [x] `_llm()` i `ui.py:26-29` är död kod — aldrig anropad.
  - Alla LLM-operationer använder `_llm_providers()` istället.

- [x] `_text_meta()` duplicerad i `dictation.py:34` och `transcriber.py:17`.
  - Behålls duplicerad medvetet: import från `transcriber` drar in `faster_whisper`
    som bryter tester i CI utan native deps.

- [x] `remote_transcribe.py:114-115` — `audio.reshape(-1)` plattar flerkanaligt ljud felaktigt.
  - Korrekt mono-mix borde vara `audio.mean(axis=1)`.
  - Ingen anropare skickar flerkanaligt just nu, men tyst korruptionsrisk.

- [x] `remote_transcribe.py:230-234` — JSON-fallback kan klistra in HTML i användarens dokument.
  - Om servern returnerar HTTP 200 med HTML-kropp (t.ex. Cloudflare-sida) behandlas
    allt som transkriptionstext.
  - Lägg till sanity-check: avvisa text som innehåller `<html` eller är orimligt lång.

- [x] Dubblett-entry i `_build_candidates` (`audio.py:257-259`).
  - `for ch in [1, d["max_input_channels"]]` lägger till samma tuple två gånger
    om `max_input_channels == 1`. Avduplicera.

- [x] `main.py:275` — Redundant `_reload_lock.locked()`-check.
  - Används innan `_config.update(new_cfg)` körs, men locken testas igen vid rad 377.
  - Mellan de två punkterna kan locken ha ändrats — den första checken är inte
    tillförlitlig och bör tas bort.

- [x] `corrections.py:67` — `_build_apply_cache` bör explicit använda `re.UNICODE`.
  - `\b` i regex matchar inte alltid korrekt vid svenska tecken (å/ä/ö) utan
    explicit `re.UNICODE`-flagga. Python 3 sätter detta som default för `\w` men
    inte alltid konsekvent för `\b`.

## Kodkvalitet och robusthet

- [x] Dela upp `ui.py` i mindre moduler.
  - Föreslagen struktur: `ui/indicator.py`, `ui/settings_window.py`, `ui/snippets_window.py`, `ui/dictionary_window.py`, `ui/hotkey_capture.py`, `ui/styles.py`.
  - Mål: lättare testning, mindre koppling och enklare ändringar.

- [x] Gör lazy startup konsekvent.
  - Berör: `main.py`, `ui.py`, `audio.py`.
  - `ui.py` importerar `audio`, som importerar SciPy; flytta `list_input_devices`-importen till när inställningsfönstret öppnas.

- [x] Fixa LLM-only settings så Whisper-modellen inte reloadas.
  - Berör: `main.py`.
  - När bara LLM-inställningar ändras ska befintlig `Transcriber` uppdateras i stället för att skapa ny modell.
  - Undvik synkron modellreload på UI-tråden.

- [x] Spara settings först efter lyckad modellvalidering.
  - Berör: `main.py`.
  - I dag sparas config innan ny modell/CUDA-konfiguration har laddats.
  - Validera först, spara efter lyckad reload eller rollbacka vid fel.

- [x] Gör JSON-lagring atomisk och korruptionssäker.
  - Berör: `config.py`, `snippets.py`, `corrections.py`, `auto_learn.py`.
  - Skriv via tempfil + replace.
  - Logga och backa upp korrupt JSON i stället för att tyst ignorera eller krascha.
  - Överväg lås eller kopior för cacheade dicts.

- [x] Fixa indikatorns hide/show-race.
  - Berör: `ui.py`.
  - `hide(delay_ms)` kan dölja ett senare state; spåra `_hide_job` och avbryt pending hide i `show()`.

- [x] Logga audio callback-status.
  - Berör: `audio.py`.
  - Hantera `status` i callbacken för att upptäcka overflow/underflow.
  - Throttla loggning om det blir för mycket brus.

- [x] Spara mikrofonval mer stabilt än bara displaynamn.
  - Berör: `audio.py`, `ui.py`, `config.py`.
  - Spara exempelvis namn + host API + index/signatur för att undvika fel val när flera devices heter samma sak.

- [x] `json_store.py:19-21` — `config.json` korruption sväljs tyst utan backup.
  - Alla andra JSON-filer får en timestampad backup. `config.json` hoppar över det.
  - Användarens inställningar försvinner permanent utan varning. Lägg till backup.

- [x] `json_store.py:12-32` — `load_json` hanterar inte `UnicodeDecodeError` specifikt.
  - En binärkorrupt fil ger `UnicodeDecodeError` som faller in i det generella `except`.
  - Ingen timestampad backup skapas. Hantera som `JSONDecodeError` med backup.

- [x] `paste.py:73-74` — Obegränsad tråd-skapning i `_paste_and_keep_clipboard_async`.
  - Varje `paste_text` skapar en ny `Thread`. Om `keyboard.send` blockerar (terminal fryser)
    stackas trådar. Byt till en enda worker-tråd med kö.

- [x] `ui.py:1205-1207` — `list_input_devices()` anropas utan error handling i UI-bygget.
  - Om ljuduppräkning misslyckas (inget ljudsystem, PortAudio-fel) kraschar hela
    inställningsfönstret. Wrappa i try/except och visa degraderat UI.

- [x] `ui.py:1371-1380` — Asynk-trådar i Settings postar `self.root.after(0, ...)` efter
  att fönstret kan ha stängts → `TclError`. Kontrollera att widgeten lever.
  - Samma problem i `_test_llm` och `_test_tr`.

- [x] `auto_learn.py:93-135` — `record_correction()` saknar trådsäkerhet.
  - Ingen lock skyddar `_load_learned()` / `_save_learned()`. Samtida anrop kan
    orsaka lost-update. Lägg till en `threading.Lock`.

- [x] `auto_learn.py:149-155` — `_promote()` laddar corrections utan lock.
  - Två samtida promotions kan skriva över varandras ändringar.

- [x] Statusmeddelande-format inkonsekvent i `main.py`.
  - Fast path (rad 362): `"Inställningar sparade — håll {hotkey}"`
  - No-model path (rad 456): `"…håll {hotkey} för att prata"`
  - Model path (rad 436): `"Modell '{new_model}' klar — håll {hotkey}"`
  - Gör enhetligt.

- [x] `main.py:554-562` — `_quit` stänger inte `_transcriber.close()`.
  - Om modellen har GPU/VRAM kvar kan den läcka vid avslut.
  - Kosmetiskt (process avslutas direkt) men korrekt cleanup saknas.

- [x] `config.py` / `llm_polish.py` / `remote_transcribe.py` — Providerlistan hårdkodad på tre ställen.
  - `config.py:18` har `_LLM_PROVIDERS`, `llm_polish.py:48` har `PROVIDERS`, `remote_transcribe.py:46` har `PROVIDERS`.
  - En ny provider kräver ändring på alla tre ställen. Gör en enda sanning.

- [x] `remote_transcribe.py:61` — Custom-provider använder `"LLM_API_KEY"` som env-var.
  - Samma env-var som LLM-custom-providern i `llm_polish.py:138`.
  - Konflaterar LLM- och transkriberingscredentials. Byt till `TRANSCRIPTION_API_KEY`.

## Säkerhet och integritet

- [x] Dokumentera clipboard-baserad paste.
  - Berör: `paste.py`, `README.md`.
  - Appen kopierar dikterad text till globala clipboarden och återställer efter paste.
  - Dokumentera risken och överväg alternativ/direct text injection där möjligt.

- [x] Hantera clipboard-restore-fel bättre.
  - Berör: `paste.py`.
  - I dag ignoreras restore-fel tyst.
  - Överväg retry, clear clipboard eller diskret användarvarning.

- [x] Dokumentera lokala datafiler och privacy cleanup.
  - Berör: `README.md`, `config.py`, `corrections.py`, `snippets.py`, `auto_learn.py`.
  - Lista `config.json`, `corrections.json`, `snippets.json`, `learned.json`, `hotwords.txt`, loggfil och modellcache.
  - Lägg gärna till UI-funktion för "Rensa privat data".

- [x] Lägg till offline-only/fail-closed-läge.
  - Berör: `transcriber.py`, `README.md`.
  - Om modell saknas ska användaren kunna välja att inte kontakta Hugging Face automatiskt.

- [x] `modifiers.py` — Saknar `"altgr"`-alias.
  - AltGr (Right Alt) är vanligt på svenska tangentbord. Om användaren binder
    en hotkey med AltGr kan tangenten fastna efter paste.
  - Lägg till `"altgr": "alt"` (eller egen canonical `"altgr"`) i `_ALIASES`.

## Bygg, release och supply chain

- [x] Pin dependency-versioner för release.
  - Berör: `requirements.txt`, `build.bat`.
  - Ersätt breda `>=` med låsta versioner eller skapa separat lockfil.
  - Pin även `torch` och `pyinstaller` i buildflödet.

- [x] Lägg till dependency/security scanning i CI.
  - Exempel: pip-audit, safety eller GitHub Dependabot.
  - Kör även lint och tester i CI.

- [x] Pin modellrevisioner och verifiera checksums.
  - Berör: `transcriber.py`, `convert_model.py`, `README.md`.
  - Använd fasta Hugging Face revisions/commit-SHA och dokumentera nätverksendpoints.

- [x] Gör PyInstaller-spec reproducerbar.
  - Berör: `freewispr-swedish.spec`, `build.bat`.
  - Ta bort maskinspecifik absolut sökväg och generera assets-path dynamiskt.

- [x] Ta bort systemändringar från buildscript.
  - Berör: `build.bat`.
  - `HKLM` LongPaths-ändring bör vara dokumenterad prereq, inte köras automatiskt av bygget.

- [x] Säkerställ att buildartefakter inte följer med i repo eller release av misstag.
  - Berör: `.gitignore`, `build/`, `dist/`, `*.spec`, `__pycache__/`.
  - Granska releasepaket för lokala paths, pyc-filer, loggar, config och hemligheter.

- [x] `build.bat` saknar `--hidden-import=keyring.backends.Windows` och customtkinter-bundling.
  - CI-workflowen (`build-windows.yml`) har båda, men `build.bat` (lokal build) saknar dem.
  - Lokalt bygge kan krascha med `keyring` backend missing och sakna CTk-widgets.

- [x] `requirements.txt:11` — `pyautogui` anges som dependency trots att paste.py inte längre använder det.
  - Kommentaren säger "kept temporarily for legacy callers" men inga legacy-anropare finns.
  - Ta bort pyautogui helt — minskar installationen och angreppytan.

- [x] `NOTICE:19` — Listar `requests` som runtime-dependency, men ingenstans importeras requests.
  - Ta bort `requests` från NOTICE-filen.

## Dokumentation

- [x] Uppdatera `README.md` så den matchar aktuell funktionalitet.
  - `learned.json` saknas i datafiltabellen — lägg till.
  - Clipboard-beteendet (text stannar kvar, inget restore) bör nämnas tydligare.
  - Remote-transkribering (staik/berget/custom) nämns inte alls — nytt feature.
  - Privacy-sektionen nämner inte remote-transkribering.
  - `auto_learn.py` (auto-lärning) bör beskrivas kort i funktionslistan.

- [x] Arkivera eller uppdatera `SPEC.md`.
  - Dokumentet säger själv att flera detaljer är föråldrade.
  - Antingen flytta till historik/arkiv eller synka mot aktuell implementation.
  - Innehåller kinesiska tecken, stavfel, och föråldrad filstruktur.

- [x] Lägg till utvecklarguide.
  - Beskriv testkommandon, lint/format, build, release, modellkonvertering och felsökning.

- [x] `docs/index.html` — Webbsidan nämner inte remote-transkribering, auto-lärning, eller
  alla LLM-leverantörer (staik, berget, openai, custom).
  - Funktionslistan bör uppdateras så den matchar appens verkliga kapacitet.

- [x] `LICENSE` copyright anger bara "Prakhar Singh".
  - Forken har bidragande kod från en ny författare.
  - Överväg att lägga till "and contributors" eller forkens upphovsman.

- [x] `llm_polish.py:174-177` — Bakåtkompatibla module-level-aliases (`API_URL`, `AVAILABLE_MODELS`, etc.)
  bör markeras som deprecated eller tas bort om gammal UI-kod har uppdaterats.

## Prestanda och latens (granskning 2026-05-20)

### Kritiska latensvinster (~700 ms hot path)

- [x] Ersätt `pyautogui.hotkey` med `keyboard.send` i paste-flödet.
  - Berör: `paste.py:49-63`.
  - `pyautogui.hotkey` lägger ~200 ms via default `PAUSE=0.1` × 2, plus `time.sleep(0.02)` före och `time.sleep(0.1)` efter.
  - Droppa första sleep, flytta clipboard-restore till bakgrundstråd.
  - Förväntad vinst: **~300 ms per diktering**.

- [x] Byt `beam_size=5` till `beam_size=1` (greedy) för dictation.
  - Berör: `transcriber.py:329`.
  - Beam search ger försumbar WER-skillnad på korta utterances men är 2-4× långsammare.
  - Förväntad vinst: **~2× snabbare transkription**, särskilt på CPU.

- [x] Höj eller ta bort `min_silence_duration_ms=300` i VAD.
  - Berör: `transcriber.py:332`.
  - Default i faster-whisper är 2000 ms; 300 ms kapar legitima pauser och **tappar ord**.
  - Sätt ≥500 ms eller ta bort overriden helt.

- [x] Kör LLM polish i bakgrunden efter paste.
  - Berör: `transcriber.py:368`, `dictation.py:120-132`, `llm_polish.py:75`.
  - `polish()` körs synkront i dictation-tråden → blockerar paste upp till 8 s.
  - Paste lokalt resultat omedelbart, polera i bakgrunden, uppdatera clipboard/visa toast efteråt.
  - Förväntad vinst: **~1 s perceived latency** när LLM är på.

### Hög prioritet — arkitektur och minne

- [x] Släpp gammal `WhisperModel` explicit vid modellbyte.
  - Berör: `transcriber.py:304-309`, `main.py:170-171`.
  - Vid reload pinas två modeller i VRAM (2-3 GB) tills GC; kan OOM:a CUDA.
  - Lägg `close()`/`del self.model` + `gc.collect()` före rebind.

- [x] Serialisera settings-reloads med lock eller worker-queue.
  - Berör: `main.py:170-171`, `_apply_settings`.
  - Mutates globals från Tk callback-tråd utan lås; två snabba reload-klick racar.

- [x] Cacha kompilerad alternation-regex i `corrections.apply`.
  - Berör: `corrections.py:48-54`.
  - N regex-kompileringar + N full text-scans per transkription (5-15 ms för 50+ corrections).
  - Bygg en `re.compile(r'\b(' + '|'.join(re.escape(k) for k in corr) + r')\b', re.IGNORECASE)` cachad på mtime.
  - Verifiera case-bevarande för "Prak" vs "PRAK" → "Prakhar".

- [x] Pre-allokera audio ring-buffer i `MicRecorder`.
  - Berör: `audio.py:162-200`.
  - `indata.copy()` per callback allokerar småarrayer från realtidstråden → GC-thrashing.
  - Använd `np.empty((MAX_SECONDS * rate, channels))` och `memcpy` chunks in.

- [x] Cacha `sd.query_devices()`/`sd.query_hostapis()` vid app-start.
  - Berör: `audio.py:130-160`.
  - Anropas dubbelt per start (50-200 ms cold på Windows WASAPI).
  - Refresh endast vid device-change events eller explicit user action.

- [x] Track keyboard hook-handles, unhook selektivt.
  - Berör: `dictation.py:47-48`.
  - `keyboard.unhook_all()` dödar **alla** hooks i processen (snippets, etc).
  - Spara returvärden från `keyboard.hook(...)` och anropa `keyboard.unhook(handle)`.

- [x] Single-slot lock på samtidiga transkriptioner.
  - Berör: `dictation.py:118`.
  - Mash-hotkey → flera CUDA-transkriptioner fightar om GPU.
  - Lägg `threading.Lock()` eller drop nya medan en pågår.

- [x] Kompilera regex i `_postprocess` vid modul-load.
  - Berör: `transcriber.py:118-167`.
  - `\b(\w+)(\s+\1){1,}\b` med IGNORECASE|UNICODE är O(n²) i värsta fall (5-20 ms på paragraf).
  - Slå ihop quote/dash-normaliseringar till en `str.translate()` (5-10× snabbare).

### Medel

- [x] Sluta tyst skriva över filer i HF-cachen.
  - Berör: `transcriber.py:57-79`, `_patch_vocabulary`.
  - Skriver patchad `vocabulary.json` direkt i HF cache → korrumperas vid re-download.
  - Hard-fail med "kör `convert_model.py large`" eller skriv till sibling-dir.

- [x] Lär från LLM-diff även vid olika ordantal.
  - Berör: `auto_learn.py:58-84`.
  - Kräver `len(before) == len(after)` → missar de flesta korrigeringar (interpunktion, splits).
  - Använd `difflib.SequenceMatcher` opcodes, begränsa till `replace` av 1-ords spans.

- [x] Fixa compound-modifier check i `_modifier_held`.
  - Berör: `dictation.py:60-63`.
  - `keyboard.is_pressed("ctrl+shift")` är inte API:t — split och `all(keyboard.is_pressed(m) for m in modifiers)`.

- [x] Räkna RMS på raw frames före resample.
  - Berör: `dictation.py:107`, `audio.py:169`.
  - Level beräknas redan per chunk i capture; återanvänd istället för full audio-pass efter resample.

- [x] Cacha polyphase-filter eller byt till `soxr` för resampling.
  - Berör: `audio.py:73-86`.
  - `resample_poly` rekomputerar FIR-filter varje anrop (~30-80 ms på 10s audio).

- [x] Exponera `corrections.mtime()` istället för privat `_FILE`.
  - Berör: `transcriber.py:262-263`, `corrections.py`.
  - Bryt koppling till private modulvariabler.

- [x] Hantera kanaldetektering vid stream-open, inte från första frame.
  - Berör: `audio.py:185-200`.
  - `_total_samples` räknar frames men buffer-alloc antar flat = mono.

- [x] Aggregera `auto_learn` log-spam.
  - Berör: `auto_learn.py:99`.
  - Loop loggar INFO per diff; byt till `log.debug` + summera vid end.

- [x] Pipeline-ordning i `transcribe` gör whitespace cleanup två gånger.
  - Berör: `transcriber.py:357-358`, `_postprocess`.
  - Kör `_postprocess` en gång sist.

- [x] Använd `np.max(np.abs(audio))` utan extra kopia i log path.
  - Berör: `transcriber.py:204`.

- [x] `llm_polish.py:281` — `max_tokens` beräknas från tecken (len) inte tokens.
  - `max(200, len(user_text) * 2)` överestimerar ~4-8× för svenska.
  - Slösar rate-limit-kvot och kan orsaka 400-fel på providers med hård max-gräns.
  - Byt till `max(200, len(user_text) // 2)` eller liknande.

- [x] `llm_polish.py:356-365` — HTTP-felsvar läses men loggas inte i `polish()`.
  - `e.read()` anropas för att dränera socketen men body kastas.
  - Jämför med `test_connection()` som inkluderar body i felmeddelandet.
  - Logga första 200 tecken av bodyn för lättare felsökning.

### Snabba vinster

- [x] Fixa hårdkodad sökväg i PyInstaller spec.
  - Berör: `freewispr-swedish.spec:8`.
  - `C:\Users\PSHUGHAM\...` bryter bygget på andra maskiner; använd `faster_whisper.__file__` dynamiskt.

- [x] Defer `from audio import list_input_devices` till settings window opens.
  - Berör: `ui.py`, `main.py:37`.
  - Laddar sounddevice + PortAudio DLL (50-200 ms) i tray startup.

- [x] Flytta `import random`/`import math` ur UI animation loops.
  - Berör: `ui.py:222, 252`.
  - Körs vid 20-30 Hz; flytta till modultopp.

- [x] Pin upper bounds i `requirements.txt`.
  - Berör: `requirements.txt`.
  - `numpy>=1.24` släpper in numpy 2.x som bryter faster-whisper <1.0.3.

- [x] Skicka faktisk modifier-set till paste, inte alla.
  - Berör: `paste.py:10-24`.
  - `pyautogui.keyUp("win")` när Win inte hålls kan öppna Start-menyn på Win10/11.

- [x] Använd `Image.open("assets/icon.ico")` istället för Pillow-redraw.
  - Berör: `main.py:339-356`.

- [x] DRY: extrahera `_make_transcriber(cfg)` / `_make_dictation(...)`.
  - Berör: `main.py:97-103, 197-203, 215-221`.
  - Tre kopior av samma konstruktion.

- [x] Förenkla `_KEY_NAMES`-dict.
  - Berör: `ui.py:559-563`.
  - Mest no-op identity-mappningar.

- [x] Dokumentera `MIN_RMS_THRESHOLD = 0.003`.
  - Berör: `dictation.py:14-15`.
  - Magisk konstant utan källa; gör user-konfigurerbar.
  - Konstanten är nu härledd i en kommentar (noise floor + tal-RMS) och
    exponerad via `config["min_rms"]` (UI-widget ej tillagd ännu).

- [x] Extrahera `JsonCache`-helper.
  - Berör: `corrections.py`, `snippets.py`, `auto_learn.py`.
  - Tre kopior av load/save/cache-mönster.

- [x] Förenkla `_check_cuda`.
  - Berör: `transcriber.py:170-180`.
  - `find_spec` + import är redundant; bara `try: import torch ... except`.

- [x] Lägg till `argparse` med `choices` i `convert_model.py`.
  - Exit-meddelande vid okänd storlek.

- [x] Konsolidera registry-kod för autostart.
  - Berör: `main.py:265-296`.
  - Tre olika öppningar av samma nyckel; `_enable_startup` används bara i `_toggle_startup`.

- [x] Validera hotkey-parsning eller använd `keyboard.parse_hotkey`.
  - Berör: `dictation.py:34-40`.
  - Splittar på sista `+` → bryter på `ctrl++`.

- [x] Flytta logdir-creation från modul-import till `main()`.
  - Berör: `main.py:13`.
  - Side-effects at import; importer i tester rör disk.

- [x] Notera `pystray` LGPL-3.0 i NOTICE.
  - Dynamisk import OK för MIT-app men bör nämnas.

## Webbsida och visuellt (pre-launch-granskning 2026-05-27)

- [x] `docs/index.html` — Footer: `"svensk fork av freewispr"` bör lägga till `"av x26prakhar"` för
  tydlig attribution och copyright-compliance med MIT-licensen.

- [x] `docs/index.html` — Webbsidan saknar `lang`-attributets delsida `xml:lang`.
  - `lang="sv"` på `<html>` är korrekt men saknar `hreflang`-link för SEO (minor).

- [x] `docs/index.html` — Ingen `<meta name="author">` — tillägg kan hjälpa sökmotorer.

- [x] `docs/index.html` — Funktions-sektionen nämner 6 funktioner men appen har fler
  (remote-transkribering, auto-lärning, audio feedback, tystnadsdetektion).
  - Uppdatera eller lägg till fler feature-kort.

- [x] `docs/vercel.json` — Vercel-config finns men Pages deployar via GitHub Actions.
  - Om Vercel inte används bör filen tas bort för att undvika förvirring.

## Djupgranskning 2026-06-02 (hela repot) — konsoliderad

Sammanslagning av tre oberoende djupgranskningar (hela kodbasen, inkl. moduler som
tillkommit efter förra rundan: `flow.py`, `learning.py`, `snippets.py`, `modes.py`,
`commands.py`, `voice_edit.py`, `http_pool.py`, `single_instance.py`, `updater.py`,
`context_win.py`, `ui/qt_indicator*`). Dubbletter är sammanslagna; severity i hakparentes.
Alla rader är verifierade mot källkoden.

**Källtaggar:** `[OC]` = OpenCode/Claude-granskning · `[GPT]` = ChatGPT-granskning ·
`[Gem]` = Gemini-granskning (flera taggar = samma fynd hittat oberoende av flera).

### Kritiskt / hög prioritet (säkerhet + invarianter)

- [ ] `text_sanitize.py:46-50` — `sanitize_output()` strippar bara ASCII/Latin-1 C0/C1.
  Unicode bidi-overrides (U+202A–202E, U+2066–2069) och rad/stycke-separatorer
  (U+2028/U+2029) passerar igenom. **[HIGH]** `[OC]` En komprometterad provider kan injicera
  "Trojan Source"-sekvenser som visuellt kastar om inklistrad text (särskilt i kod).
  Lägg dessa codepoints i `_STRIP_TABLE`.

- [ ] `llm_polish.py:724-729` — `test_connection()` returnerar rå provider-`body`
  (`f"HTTP {e.code} ({latency}ms): {body}"`) **osanerad** till Settings-UI. **[HIGH]** `[OC]`
  Bryter invariant 2 (all provider-output till UI måste via `sanitize_output()`). Sanera bodyn.

- [ ] `remote_transcribe.py:437,446-464,235` — `_http_message`/`test_connection` returnerar
  rå provider-error-body osanerad till indikator/UI (`HTTP {code}: {snippet}`). **[HIGH]** `[OC]`
  Samma invariant-2-brott som ovan. Kör error-snippet genom `sanitize_output()`.

- [ ] `dictation.py:1214` + `ui/indicator.py:47-52` — `indicator.show(..., state="review")`
  är en **5:e** indikator-state. `_COLORS`/`_set_static_bars` känner bara till
  `listen/transcribe/done/error`. **[HIGH]** `[OC]` I "classic"/Tk-indikatorn faller "review"
  tillbaka till blå + min-höjd-staplar (ser trasigt/idle ut). Bryter 4-state-invarianten —
  mappa polish-väntan till `transcribe` i stället.

- [ ] `single_instance.py:52-56` — `CreateMutexW`/`CloseHandle` anropas utan `restype`/
  `argtypes` (HANDLE trunkeras till 32-bit på Win64) och använder `kernel32.GetLastError()`
  i stället för `ctypes.get_last_error()` (modulen är inte byggd med `use_last_error=True`).
  **[HIGH]** `[OC]` ctypes kan klottra last-error mellan anropen → falsk "kör redan" (blockerar
  legitim start) eller missad dubbelinstans → två Whisper-modeller i VRAM (just det OOM
  spärren ska förhindra). Sätt `argtypes/restype` till `wintypes.HANDLE`/`DWORD` och läs
  felkoden via `ctypes.get_last_error()`.

- [ ] `main.py:565-578` — modellreload binder `_transcriber = new_transcriber` **innan**
  den gamla modellen släpps (`old_transcriber.close()` körs i separat daemon-tråd *efter*
  rebind). **[HIGH]** `[OC]` Två `WhisperModel` lever samtidigt i VRAM → OOM på små CUDA-GPU:er.
  Regression av den tidigare fixade punkten "Släpp gammal WhisperModel före rebind".

- [ ] `http_pool.py:58` — `conn.timeout = timeout` på en **återanvänd** anslutning har ingen
  effekt: `http.client` låser socket-timeout vid `connect()`. **[HIGH]** `[OC]` Warmer öppnar
  socketen med 8 s timeout; en senare `transcribe(timeout_sec=60)` på samma varma anslutning
  timeoutar ändå efter 8 s → legitima långa fjärrtranskriptioner failar. Öppna ny anslutning
  vid längre timeout, eller stäng+återanslut när begärd timeout > anslutningens.

- [ ] `ui/indicator.py:118-137,146-149` — `hide()`/`push_level()` anropar `self._root.after()`/
  `after_cancel()` från keyboard-hook/worker/audio-trådar (ej Tk main-tråd). **[HIGH]** `[OC]` Kan ge
  `RuntimeError: main thread is not in main loop` eller event-loop-korruption på icke-fritrådad
  Tcl. `_pending_push`/`_last_push_ms` skrivs dessutom olåst från två trådar. Marshalla allt via
  en main-thread-kö (`after` schemalagt enbart från main-tråden).

- [ ] `main.py:836-858` — shutdown-/`_quit`-väg är trasig på två sätt: (a) `_quit` körs på
  pystray-tray-daemontråden men anropar `_tk_root.quit()` **och** `destroy()` cross-thread och
  `sys.exit(0)` i daemontråden (avslutar inte processen); (b) single-instance-låset släpps
  **först** innan Flow, hotkeys, indikator, transcriber och tray rivits ned. **[HIGH/RACE]**
  `[OC][GPT][Gem]` `destroy()` från fel tråd kan hänga/kasta Tcl-fel, och en ny process kan
  starta medan den gamla fortfarande äger hooks/VRAM → dubbel hotkey-hantering eller två
  Whisper-modeller. Signalera main-tråden att riva ner Tk och avsluta där, och släpp
  single-instance-låset **sist** i en final cleanup efter teardown.

- [ ] `ui/settings_window.py:1255-1268,1344-1347` — loopback/custom-LLM undantas korrekt från
  nätverkssamtycke vid save, men undantaget sparas som `llm_privacy_accepted=True`.
  **[HIGH/PRIVACY]** `[GPT]` Om användaren senare byter från lokal `http://localhost` till
  GitHub/OpenAI/Staik/Berget kan tidigare lokalacceptans undertrycka remote-samtycket och text
  skickas över nät utan ett nytt explicit ja. Spara inte loopback-undantaget som remote-samtycke;
  spåra lokal endpoint som runtime-undantag eller kräv nytt samtycke när provider/base_url blir remote.

- [ ] `context_win.py:231-235`, `dictation.py:1191-1194,1286-1289`, `llm_polish.py:295-299,498-500`,
  `ui/settings_window.py:1147-1152` — kontextmedvetenhet extraherar namn från fönstertitel/
  fokuserad text och skickar `onscreen_names` in i LLM-prompten när LLM-polish körs.
  **[HIGH/PRIVACY]** `[GPT]` UI-texten säger "All skärmtext används lokalt", men med remote-LLM
  lämnar dessa namn datorn. Lägg till separat samtycke/tydlig text för skärmnamn till remote-LLM,
  eller skicka inte `onscreen_names` till LLM när providern inte är lokal loopback.

- [ ] `transcriber.py:502-522`, `main.py:481-498` — LLM- och remote-STT-warmers startas med
  snapshots av provider/base_url men läser samtidigt levande `self.*`-credentials i loopen, och
  fast-path-inställningar stoppar inte befintliga warmer-trådar. **[HIGH/PRIVACY]** `[GPT]` Efter
  provider/key/base_url-byte eller disable kan bakgrundstrådar fortsätta pinga gamla eller blandade
  endpoints med fel nyckel. Stoppa/restarta warmers vid alla provider/key/base_url/model-ändringar
  och använd en immutabel settings-snapshot per tråd.

- [ ] `config.py:280-288,323-324` — migrationen `llm_model` -> `llm_model_github` uppdaterar bara
  runtime-`cfg`, men skriver sedan den modifierade `data`-dicten där legacy-nyckeln poppats och den
  nya nyckeln aldrig lagts in. **[HIGH/DATA-LOSS]** `[GPT]` En användares gamla modellval gäller bara
  för aktuell process och försvinner efter nästa start. Persistiera migrerade nycklar i `data` eller
  skriv en sanerad kopia av `cfg`.

- [ ] `remote_transcribe.py:343-353`, `transcriber.py:883-889` — HTTP 200 med HTML, malformed JSON
  eller JSON utan `text` returnerar `""` och blir i dikteringsflödet "Inget hördes". **[HIGH]** `[GPT]`
  Provider-/proxyfel maskeras som tystnad, vilket gör felsökning och integritetsstatus missvisande.
  Höj `RemoteTranscribeError` för 200-svar som inte innehåller användbar transkription.

### Medel (hot path-race + robusthet)

- [ ] `dictation.py:1027-1028` — voice-edit: `if len(audio) < MIN_AUDIO_SAMPLES: return`
  återställer/döljer **inte** indikatorn (till skillnad från grann-grenarna). **[MEDIUM]** `[OC]`
  Pillen fastnar i "Tolkar redigering…"/`transcribe`. Visa `error`/`done` + `hide()`.

- [ ] `dictation.py:907-910,930-934` — `self._ctx_result` och `_live_*` är **enstaka delade
  slots** som skrivs över vid nästa knapptryck (`_QUEUE_MAX=2`). **[MEDIUM]** `[OC]` Worker kan läsa
  press#2:s kontext/live-partials för press#1:s transkription → fel app-profil/biasing.
  Bind kontext/live-state till respektive jobb i stället för instans-attribut.

- [ ] `dictation.py:641-669` — live-transcribe: `_live_loop` räknar `consumed` mot
  `split_on_silence` av *växande* snapshots, men `_combine_live` re-splittar hela inspelningen
  och avkodar `chunks[consumed:]`. **[MEDIUM]** `[OC]` Tystnadssegmenteringen glider när ljudet växer
  → ord kan tappas/dubbleras; dessutom läses stale `_live_parts` om `t.join(timeout=5)` löper ut.

- [ ] `config.py:298,301` — `cfg = {**DEFAULTS, **data}` / `DEFAULTS.copy()` är **grunda**.
  Saknar `data` t.ex. `app_profiles` delas dict-objektet per referens med modulens `DEFAULTS`.
  **[MEDIUM]** `[OC]` En caller som muterar `cfg["app_profiles"]` korrumperar `DEFAULTS` för hela
  processen. Använd `copy.deepcopy(DEFAULTS)` (eller djup-merge).

- [ ] `config.py:308,323-324` — `load()`:s migrations-skrivning (`save_json_atomic(CONFIG_FILE,…)`)
  sker **utanför** `_save_lock`. **[MEDIUM]** `[OC]` En samtidig `save()` (Settings-flush) och en
  migrerande `load()` ger lost-update. `save()` låstes medvetet för detta — låt även load()-skriv
  ta `_save_lock`.

- [ ] `json_store.py:95,103` — `load()` returnerar den interna cache-dicten **per referens**;
  `save()` lagrar callerns dict per referens. **[MEDIUM]** `[OC]` Extern mutering desyncar cachen från
  disk för alla läsare. Returnera/lagra en kopia (eller djupkopia).

- [ ] `learning.py:119-145,161` — `add_hotwords()` gör icke-atomisk, **olåst** read-modify-write
  av `hotwords.txt` (`write_text` direkt, ej temp+replace) och anropas utanför `_lock` från
  `record_corrections`. **[MEDIUM]** `[OC]` Krasch mitt i skrivning korrumperar filen; samtidiga
  observationer tappar hotwords. Skriv atomiskt under `_lock`.

- [ ] `main.py:438,456-457 + olåsta läsare` — `_config` muteras under `_config_lock`
  (`update()`, och `_rollback()` gör `clear()`+`update()`) men läses **olåst** i `_build_menu`,
  `_set_tray_status`, `_make_dictation/_make_transcriber` och bakgrunds-`_reload`. **[MEDIUM]** `[OC]`
  En läsare i gapet mellan `clear()` och `update()` ser tom dict → tysta default-fallbacks.
  Snapshotta config eller läs under lås.

- [ ] `main.py:493-497` — LLM-/remote-only-fast-path skriver `_transcriber.llm_*`/
  `transcription_*` direkt utan `_model_lock`. **[MEDIUM]** `[OC]` En pågående `polish_async`/
  `transcribe` kan göra torn read av provider+nyckel mitt i bytet → fel credentials mot fel
  provider.

- [ ] `ui/qt_indicator.py:151-176` — `_ensure_started()` saknar lås; `push_level` (audiotråd)
  och `show` (worker) kan båda nå spawn-grenen → två Qt-barnprocesser, en läcker. **[MEDIUM]** `[OC]`
  Lägg lås runt `self._process is None`-checken.

- [ ] `ui/qt_indicator.py:178-188` — `_send()` skriver JSON-rader till barnets stdin från flera
  trådar utan lås och utan non-blocking write. **[MEDIUM]** `[OC]` Om barnet stallar fylls pipe-bufferten
  och `push_level`/`show`-tråden (hot path) blockerar. Serialisera writes + använd watchdog/
  non-blocking.

- [ ] `ui/settings_window.py:719-737,696-700,527-546` — async-trådars `root.after(0, lambda: …
  .configure(...))` saknar widget-liveness-guard → `TclError` om Settings stängts; snabb
  provider-växling racar resultat (äldre tråds resultat skriver över nyare). **[MEDIUM]** `[OC]` Lägg
  `winfo_exists()`-guard + generation-token/cancellation.

- [ ] `convert_model.py:71` — completeness-checken testar bara `model.bin`. **[MEDIUM]** `[OC]` Om
  `model.bin` hämtas men en senare fil (`tokenizer.json`/`vocabulary.json`/…) failar lämnas en
  "klar men trasig" modell; nästa körning hoppar över nedladdning och faster-whisper failar vid
  load. Verifiera alla `_REQUIRED_FILES` (eller ladda till temp-dir + atomisk rename).

- [ ] `transcriber.py:121-125` — `_patch_vocabulary` gör `vocab_path.replace(backup)` (flyttar
  bort originalet) **före** att den trimmade filen skrivs. **[MEDIUM]** `[OC]` Om `json.dump` kraschar
  (full disk/behörighet) lämnas snapshot:en med bara `vocabulary.json.orig` och inget
  `vocabulary.json` → modellen går inte att ladda. Skriv ny fil först, byt sedan atomiskt.

- [ ] `ui/settings_window.py:1355-1357` — `transcription_privacy_accepted` skrivs som `False` när
  provider är `local`. **[MEDIUM/CONSENT]** `[GPT]` Det bryter designinvarianten att consent ska sparas
  oberoende av om funktionen är aktiv; användaren tappar tidigare remote-STT-samtycke bara genom att
  tillfälligt byta till lokal Whisper. Bevara befintligt consent vid local och ändra bara vid explicit
  accept/revoke.

- [ ] `ui/settings_window.py:1366-1378,1393-1406,1429-1431` — snippets, rättelser och personlig
  kontext sparas innan `on_save(new_cfg)` validerar modell/config och innan huvudconfig persistieras.
  **[MEDIUM/DATA-LOSS]** `[GPT]` Om modellreload eller config-save nekas blir settings-fönstret kvar med
  rollbackad huvudconfig men sidofilerna är redan överskrivna. Stage:a sidofilsändringar tills `on_save`
  lyckats, eller snapshotta och rollbacka dem vid fel.

- [ ] `url_security.py:78-108`, `llm_polish.py:436`, `remote_transcribe.py:336,425` — custom `base_url`
  tillåter querystring och fragment, t.ex. `https://host/v1?api_key=...`. **[MEDIUM/SECURITY]** `[GPT]`
  API-nycklar eller routingdata i URL kan hamna i proxy-/serverloggar och path-konkateneringen blir
  otydlig. Avvisa `?query` och `#fragment`; tillåt bara scheme, host, port och path-prefix och bygg
  endpoints strukturerat.

- [ ] `llm_polish.py:617-633,662-674` — `instruct()` och `test_connection()` anropar `_resolve_base_url()`
  utanför fail-safe-`try`. **[MEDIUM]** `[GPT]` En ogiltig custom-URL kan kasta `ValueError` istället för
  att kommandoläget returnerar originaltexten eller testet returnerar `(False, meddelande)`. Flytta
  provider/base/model-resolution in i try-block eller fånga `ValueError` explicit.

- [ ] `paste.py:82-118` — clipboard-restore-trådar saknar generation/token. **[MEDIUM/RACE]** `[GPT]`
  Två snabba paste-operationer med `restore_clipboard=True` kan återställa urklippet i fel ordning så att
  gammal clipboard eller föregående diktering vinner över den senaste. Ge varje paste en generation och
  låt bara senaste restore köra.

- [ ] `paste.py:178-221`, `dictation.py:425-453`, `voice_edit.py:34-76` — voice-edit läser markerad text
  via globalt urklipp och skickar markerad text + instruktion till vald LLM. **[MEDIUM/PRIVACY]** `[GPT]`
  Det är mer känsligt än vanlig diktering eftersom användaren kan ha markerat hemligheter/PII i en annan
  app, och informationen kan exponeras både för clipboard-observers och remote-LLM. Lägg till explicit
  voice-edit-disclosure/samtycke och överväg att kräva lokal LLM eller separat remote-acceptans.

- [ ] `config.py:140-143`, `main.py:213-214`, `dictation.py:1132-1138`, `ui/settings_window.py:1240-1357`
  — `context_to_remote_accepted` finns som config-gate för att skicka skärmnamn till remote-STT, men
  Settings har ingen synlig kontroll och `_save()` persistierar inte fältet. **[MEDIUM/UX]** `[GPT]`
  Funktionen kan i praktiken aldrig aktiveras via UI, så remote-STT får aldrig kontextnamn trots att kod
  och tester stödjer det. Lägg till separat samtyckesruta eller ta bort död config-yta.

- [ ] `remote_transcribe.py:151-174` — FLAC/Opus-kodningen flattenar flerkanaligt ljud med `reshape(-1)`
  medan WAV-vägen mixar mono med `mean(axis=1)`. **[MEDIUM]** `[GPT]` Om någon anropar remote-encodern med
  stereo/interleaved input korruptas tidsaxeln. Dela mono-normalisering mellan WAV/FLAC/Opus och testa
  2D-audio.

- [ ] `flow.py:179-185` (+ shutdown-väg ~122-136) — när Flow stoppas under `_process_audio()` gör
  `if not self._active: pass` och fortsätter sedan transkribera/klistra chunks. **[MEDIUM]** `[GPT][Gem]`
  Användaren kan få text inklistrad efter att Flow stängts av, och en stream-/worker-leak vid shutdown.
  Om bara in-flight chunk ska flushas, gör det explicit en gång; annars `break`/`return` vid stopp och
  städa strömmen.

### Lägre prioritet (robusthet/kosmetik)

- [ ] `remote_transcribe.py:426-429` — `test_connection` använder `urllib.request.urlopen` som
  **följer redirects** och kan skicka `Authorization: Bearer` till redirect-målet. **[LOW]** `[OC]`
  Använd no-redirect-vägen (som pool:en).

- [ ] `http_pool.py:130-158` — globalt `_lock` hålls över hela nätverks-round-tripen → en 60 s
  `transcribe()` blockerar `polish()`/warmers även mot annan origin. **[LOW/MEDIUM]** `[OC]` Lås per
  origin/connection, inte globalt över I/O.

- [ ] `http_pool.py:87,145,155` — `resp.read()`/SSE-loopen saknar storleksgräns. **[LOW/MEDIUM]** `[OC]`
  Hostile/buggy provider kan strömma godtyckligt stor body → minnesutmattning på hot path. Inför
  max-storlek.

- [ ] `llm_polish.py:550-554` — provider-error-body loggas (`body[:200]`); vissa providers ekar
  request-payload (transcript) i felsvar → kan läcka transcript till logg. **[LOW]** `[OC]` Brushar mot
  invariant 6. Logga inte rå body, eller redigera.

- [ ] `dictation.py:218` — `if "out of memory" in msg or "cuda" in msg and "memory" in msg:`
  är funktionellt OK men oparentesterad precedens (RUF021). **[LOW]** `[OC]` Parentesera för tydlighet.

- [ ] `migrate_context.py:46` — `if isinstance(v, str) and k` behåller whitespace-only nycklar
  (`"   "` är truthy) → skräprad i genererad kontext. **[LOW]** `[OC][Gem]` Använd `k.strip()`.

- [ ] `learning.py:153-159` — eviction vid `len > MAX_CORRECTIONS` slår på insättningsordning,
  inte recency; ett ofta återkorrigerat gammalt ord kan vräkas före en engångs-ny post. **[LOW]** `[OC]`

- [ ] `updater.py:194` — `tag.lstrip("v")` strippar en *teckenmängd*, inte prefixet. **[LOW]** `[OC]`
  Använd `tag[1:] if tag.startswith("v") else tag`.

- [ ] `ui/first_run.py:265-273,323,360-366` — `winfo_ismapped()`/`pack` körs oguardat efter
  möjlig destroy → `TclError`; en nedladdning som blir klar *efter* cancel kastar resultatet
  (`result` förblir `None`, behandlas som "avbruten"). **[LOW]** `[OC]`

- [ ] `snippets.py:47-57` & `modes.py:73-89` — olåst read-modify-write (`dict(load()); …; save()`)
  över delad `JsonCache`; två nära-samtidiga ändringar kan tappa en uppdatering. **[LOW]** `[OC]`

- [ ] `config.py:213-216` — `_providers_validated`-flaggan läses/sätts utan lås (två samtidiga
  `load()` kan validera två gånger). **[LOW]** `[OC]` Idempotent men osynkroniserat.

- [ ] `llm_polish.py:190-218` — GitHub-token fallback kör `gh auth token` från `PATH` när explicit
  LLM-nyckel saknas. **[LOW/SECURITY]** `[GPT]` En oväntad eller skadlig `gh.exe` tidigare i PATH kan
  köras, och användaren får inte tydlig kontroll över att en bred GitHub CLI-token återanvänds för LLM.
  Föredra explicit lagrad token eller resolvera `gh` via betrodd absolut sökväg och visa tydlig opt-in.

### Bygg, release, supply chain & lint

- [ ] `requirements.txt:4-16`, `.github/workflows/build-windows.yml:95-98` — releasebygget installerar
  dependency-ranges från PyPI och opinnad `pyinstaller`, trots att äldre TODO-punkt om pinnade
  dependency-versioner är markerad klar. **[LOW/MEDIUM SUPPLY-CHAIN]** `[GPT]` En ny package-release inom
  intervallet kan hamna i EXE-bygget utan review. Skapa hash-låst requirements/constraints för release
  och installera med `--require-hashes`.

- [ ] `transcriber.py:140-149`, `convert_model.py:87-98`, `TODO.md:210-212` — TODO säger att
  modellrevisioner/checksums är pinnade, men `KBLAB_REVISIONS` är fortfarande `None` för alla storlekar
  och ingen SHA256-manifest verifieras. **[LOW/MEDIUM SUPPLY-CHAIN]** `[GPT]` Nedladdade modellartefakter
  är inte reproducerbart låsta eller app-verifierade innan de laddas av ML-runtime. Pin:a revisions till
  commit-SHA och verifiera förväntade filhashar.

- [ ] `.github/workflows/pages.yml:48,51,54,60` — Pages-workflowen använder rörliga action-tags
  (`@v4`, `@v5`, `@v3`) trots projektkonventionen att GitHub Actions ska SHA-pinnas med versionskommentar.
  **[LOW SUPPLY-CHAIN]** `[GPT]` Pin:a actions på samma sätt som `build-windows.yml`.

- [ ] `design/preview_indicator.py` (~79 fel: W293 trailing whitespace, F401, F841),
  `make_demo_gif.py` (F401, RUF046), `tests/test_updater.py` (F401 `os`/`io.BytesIO`).
  **[LOW]** `[OC]` Dessa ligger kvar och skulle fälla `ruff`-steget i CI. Städa eller exkludera dem.
