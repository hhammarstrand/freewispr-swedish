# CLAUDE.md

Instruktioner för Claude (och Claude Code) när du arbetar i det här repot.

## Projektet i en mening

`freewispr-swedish` är en Windows-app för svensk push-to-talk-diktering byggd på KBLab:s Whisper-modeller, med valfri LLM-granskning via flera providers. Lokal-först, ingen registrering.

## Språkpolicy

- **Användarsynliga strängar** (status, fel, indikator, dialoger, README, webbsida) måste vara på **svenska med korrekta å/ä/ö**. Aldrig "oppnas", "modell" utan å/ä, eller "..." istället för "…".
- **Loggar, kommentarer, commit-meddelanden, docstrings** kan vara på engelska — det är internt.
- **Identifierare i kod** (variabelnamn, funktionsnamn) är engelska.

## Hot path

Användaren håller en hotkey → spelar in → släpper → text klistras in. Allt mellan key-up och paste är på den kritiska latency-vägen:

```
audio.py:MicRecorder.stop_fast()  →  finalize_audio()  →
transcriber.py:transcribe()  →  paste.py:paste_text()
```

LLM-polish körs **asynkront efter paste** via `transcriber.py:polish_async()` med en `threading.Timer(15s)` watchdog så indikatorn aldrig hänger.

## Filöversikt

| Fil | Roll |
|---|---|
| `main.py` | Tray icon, tk root, app lifecycle, settings reload-koordinering |
| `dictation.py` | Hotkey hooks, recording state machine, transcribe → paste pipeline |
| `transcriber.py` | Whisper-anrop (lokal eller remote), LLM polish_async |
| `audio.py` | MicRecorder, finalize (downmix + resample till 16 kHz) |
| `paste.py` | Clipboard + syntetisk Ctrl+V / Shift+Insert i konsoler |
| `llm_polish.py` | 5 providers (github/staik/berget/openai/custom), polish() + test_connection() |
| `remote_transcribe.py` | 3 remote-providers (staik/berget/custom) för audio-API |
| `config.py` | JSON-config + keyring-backed secrets, migration, save_lock |
| `personal_context.py` | Ersatte snippets/corrections/auto_learn: fritextkontext för LLM |
| `text_sanitize.py` | `sanitize_output()` — strippa ANSI/control-bytes från LLM-svar |
| `url_security.py` | `is_plaintext_loopback()`, base URL-validering |
| `ui/` | Tkinter/CustomTkinter — `indicator`, `settings_window`, `first_run`, m.fl. |

## Designinvarianter (bryt inte)

1. **API-nycklar lagras i Windows Credential Manager via `keyring`**, aldrig i `config.json`. Se `config.py:_SECRET_FIELDS`. När du läser/skriver hemligheter — gå via `config.save()` / `config.load()`.
2. **All LLM-respons och remote-transkribering måste passera `sanitize_output()`** innan den når urklipp eller UI. Hotmodell: komprometterad provider injicerar ANSI-escape-sekvenser. Båda `polish()` och `test_connection()` gör detta.
3. **Consent gates får inte kringgås.** `llm_privacy_accepted` och `transcription_privacy_accepted` styr när audio/text får skickas över nät. Persistas i config oberoende av om respektive feature är på.
4. **Audio-status måste reflektera vad som faktiskt händer**: om `transcription_provider != "local"` ska användaren se "Transkriberar via X…" så de vet att audio lämnar maskinen — även om LLM-polish är av.
5. **Lokal Whisper laddas med `local_files_only=True`**. Appen kontaktar aldrig HuggingFace automatiskt under normalt bruk. Endast `convert_model.py` och `ui/first_run.py` får ladda ned.
6. **Loggar får aldrig innehålla API-nycklar eller full transkriptionstext.** Logga metadata: `chars`, `words`, `latency_ms`, `model`. Se `_text_meta()` i `transcriber.py`.

## Testkörning

```bash
python -m pytest tests/ -q
ruff check . --select E,F,W --ignore E501
```

Båda måste vara gröna innan en PR mergas. CI kör samma kommandon plus `pip-audit`.

Native deps (`sounddevice`, `keyboard`, `pyperclip`, `pystray`, `winsound`) stubas via `tests/conftest.py` så testerna fungerar headless.

## Konventioner

- **Hotkey/keyboard:** `dictation.py:_parse_hotkey()` normaliserar via `modifiers.py`. Lägg inte till nya alias direkt — utöka `modifiers._ALIASES` med kanonisk form.
- **Config-fält:** lägg till i `config.py:DEFAULTS` + uppdatera consent-villkor om nytt nätbeteende införs. Per-provider-fält följer mönstret `{feature}_{kind}_{provider}` (`llm_api_key_github`, `transcription_model_staik`).
- **Felmeddelanden** för användaren går via `_friendly_mic_error()` / `_friendly_transcribe_error()` i `dictation.py`. Lägg till nya nyckelord där istället för att läcka råa exceptions.
- **GitHub Actions** pinas till SHA + version-kommentar. Se `build-windows.yml` för stilen: `uses: actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd  # v6.0.2`.
- **Modellrevisioner** pinas i `transcriber.py:KBLAB_REVISIONS` för reproducerbara nedladdningar.

## Vad du *inte* bör göra

- **Lägg inte tillbaka snippets/corrections/auto_learn.** Det är borttaget och ersatt av `personal_context.py` (fritextfält). Återanvändbar tunn UI för listor av nyckel-värde-par finns inte längre.
- **Inför ingen lazy-import-cykel** mellan `config.py` och `llm_polish.py`/`remote_transcribe.py`. `config.py` validerar provider-listor lazy via `_validate_providers()` — efterlikna det mönstret.
- **Bygg ingen ny UI-stack** ovanpå Tkinter/CTk om det inte är absolut nödvändigt. Att byta till Qt/Electron är diskuterat och avvisat — alla UI-bidrag måste fungera inom den befintliga `ui/`-paketstrukturen.
- **Modifiera inte mic prewarm-logiken.** Den togs bort i `d238086` efter att den krockade med andra ljudströmmar (t.ex. Spotify). Återinför inte utan att hantera exclusivitet/duplex.

## Verifiering före PR

1. `python -m pytest tests/ -q` → alla gröna
2. `ruff check . --select E,F,W --ignore E501` → All checks passed
3. Manuell smoke-test om Windows-flödet ändrats: kör `python main.py`, diktera, kolla att text klistras in
4. Granska commit-meddelanden — på engelska, beskrivande, `type: kort beskrivning` (`fix:`, `feat:`, `refactor:`, `docs:`)
5. PR-titel + body på svenska om det är användarrelevant; engelska om det är internt

## Resurser

- Webbsidan: <https://hhammarstrand.github.io/freewispr-swedish/>
- KBLab-modeller: <https://huggingface.co/KBLab>
- faster-whisper: <https://github.com/SYSTRAN/faster-whisper>
