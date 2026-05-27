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

- [ ] Dela upp `ui.py` i mindre moduler.
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

- [ ] Lägg till dependency/security scanning i CI.
  - Exempel: pip-audit, safety eller GitHub Dependabot.
  - Kör även lint och tester i CI.

- [ ] Pin modellrevisioner och verifiera checksums.
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

- [ ] Lägg till utvecklarguide.
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

- [ ] Pre-allokera audio ring-buffer i `MicRecorder`.
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

- [ ] Cacha polyphase-filter eller byt till `soxr` för resampling.
  - Berör: `audio.py:73-86`.
  - `resample_poly` rekomputerar FIR-filter varje anrop (~30-80 ms på 10s audio).

- [x] Exponera `corrections.mtime()` istället för privat `_FILE`.
  - Berör: `transcriber.py:262-263`, `corrections.py`.
  - Bryt koppling till private modulvariabler.

- [ ] Hantera kanaldetektering vid stream-open, inte från första frame.
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

- [ ] `docs/index.html` — Webbsidan saknar `lang`-attributets delsida `xml:lang`.
  - `lang="sv"` på `<html>` är korrekt men saknar `hreflang`-link för SEO (minor).

- [x] `docs/index.html` — Ingen `<meta name="author">` — tillägg kan hjälpa sökmotorer.

- [x] `docs/index.html` — Funktions-sektionen nämner 6 funktioner men appen har fler
  (remote-transkribering, auto-lärning, audio feedback, tystnadsdetektion).
  - Uppdatera eller lägg till fler feature-kort.

- [x] `docs/vercel.json` — Vercel-config finns men Pages deployar via GitHub Actions.
  - Om Vercel inte används bör filen tas bort för att undvika förvirring.
