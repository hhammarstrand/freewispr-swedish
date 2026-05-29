# FreeWispr-Swedish — Roadmap: närma sig Wispr Flow

> **Status: TODO / planerad.** Detta är en prioriterad att-göra-lista, inte
> implementerad kod. Arbetspaketen (AP1–AP6) plockas upp och implementeras i
> prioordning, ett i taget. Kodankarna (`fil:funktion`) pekar på var arbetet ska
> göras och stämde vid skrivande stund — verifiera radnummer innan du börjar.

## Syfte

Höja den **upplevda** dikteringskvaliteten mot Wispr Flow. Transkriberingsmotorn
(KBLab Whisper) är redan rätt val — gapet ligger i lagren ovanpå: en snabb,
icke-blockerande städ-/granskningspass, en inlärningsloop, kontextmedvetenhet och
kommandoläge.

## Vägledande princip

**Lägg intelligensen i provider-agnostiska lager.** Allt som höjer kvaliteten ska
fungera oavsett om transkriberingen körs lokalt (`faster-whisper`) eller mot en
provider (staik / Berget / custom OpenAI-kompatibel). Backend-specifik akustisk
tuning är en *villkorad* förbättring, inte grunden.

## Premisser (styr designen)

1. **KBLab rensar redan fyllnadsord.** Modellerna är finetunade på svenska
   TV-undertexter och riksdagsprotokoll — redan kondenserad text. Polish-promptens
   jobb är därför **inte** generisk filler-borttagning, utan: lösa
   självrättelser/omstarter, reda ut talspråk till läsbara meningar, tillämpa rätt
   ordförråd/egennamn, och lätt formatering efter måltext. KBLab har stilrevisions
   via `revision` (default/`strict`/`subtitle`) — **verifiera att CT2-byggen finns**
   innan de används i `faster-whisper`, annars fall tillbaka till default.
2. **Transkribering har två backends.** Akustiska/avkodningsparametrar
   (`vad_filter`, `beam_size`, `compute_type`, `hotwords`,
   `condition_on_previous_text` …) gäller **bara** lokal `faster-whisper`. Den remote
   OpenAI-kompatibla pathen stödjer som mest `language`, `prompt`, ibland
   `temperature` — allt övrigt är no-op. Applicera tuning villkorat bakom det
   gemensamma interfacet.
3. **LLM-modell/-provider ska förbli konfigurerbar.** Hårdkoda ingen modell.
   Referens idag: Qwen via staik, ~1.4 s latens. Optimera upplevd latens, inte
   modellvalet.
4. **Behåll integriteten.** Lokal modell + LLM av = helt offline, oförändrat.
   Nycklar i Windows Credential Manager via `keyring`. Logga aldrig nyckel eller
   textinnehåll. Skärmtext (AP3) används endast lokalt och skickas inte om
   LLM/remote är av.

---

## Arbetspaket

### AP1 — Snabb, icke-blockerande polish *(högst prio)*

**Mål:** behåll dagens wait-läge (terminalsäkert, en enda paste) men sänk både
faktisk och upplevd latens och höj promptkvaliteten.

- [x] Återanvänd en HTTP-session (keep-alive) per provider — undvik nytt
      TLS-handslag per diktering. *Idag: `llm_polish.py:_request_json()` /
      `_call_api()` använder rå `urllib.request` utan pooling.*
- [x] `temperature=0`, `max_tokens ≈ len(input)*1.3 + 32`, `stream=True`; börja
      paste-förberedelse så fort sista token kommit. *Idag:
      `llm_polish.py:polish()` (~rad 327), `max_tokens=max(100, len*1.5)`, ingen
      streaming.*
- [x] Ny stram svensk system-prompt (se **Polish-prompt** nedan) med few-shot på
      självrättelser. *Idag: `_SYSTEM_PROMPT` + `_build_system_prompt()`
      (`llm_polish.py` ~rad 225).*
- [x] Injektera referensblock: personlig kontext + inlärda rättelser (AP2) + ev.
      on-screen-kontext (AP3). *Idag injiceras endast `personal_context` via
      `transcriber.py:polish_async()` (~rad 484).*
- [x] Mät och logga per-steg-latens: `record → transcribe → llm → paste`. *Idag:
      spridda `log.info` i `dictation.py` (~rad 279/307/323) + `result.latency_ms`.*
- [x] Gör 15 s-fallbacken till konfigurerbar tröskel. *Idag: hårdkodad
      `threading.Timer(15.0, _watchdog_fallback)` i `dictation.py` (~rad 329–405).*
- [x] Lägg till global toggle "rå direkt" (ingen polish) + per app-profil (AP3).
      *Nytt fält i `config.py:DEFAULTS`; UI i `ui/settings_window.py`.*

**Acceptanskriterier**
- Per-steg-latens syns i loggen.
- Ingen modell hårdkodad; nuvarande provider-val styr.
- Lokalt offline-läge (LLM av) fungerar exakt som idag.

---

### AP2 — Inlärningsloop (auto-ordlista + rättelser)

**Bakgrund:** `corrections.json`/`learned.json` migrerades tidigare till en
*statisk* kontext-blob (`8ed9942`), vilket tog bort den dynamiska loopen. Återinför
den — men **bygg INTE tillbaka** `snippets.py`/`corrections.py`/`auto_learn.py`. Bygg
en fristående dynamisk loop bredvid `personal_context`.

**Mål:** när användaren rättar inklistrad text ska systemet lära sig till nästa gång.

- [x] Ny modul `learning.py`.
- [x] Efter paste: läs målfältets värde via UIA (infra från AP3) eller urklippsdiff;
      jämför mot det som klistrades. *OBS: `paste.py` har idag ingen clipboard-diff —
      bygg det eller använd UIA.*
- [x] Heuristik: ordbyte (t.ex. Levenshtein-tröskel + ordpar) → spara term-paret.
- [x] Lokal backend: append unika rättade termer till
      `~/.freewispr-swedish/hotwords.txt`.
- [x] Alla backends: append `"X" → "Y"`-par till
      `~/.freewispr-swedish/corrections.json` (strukturerat, dedupliceras, atomiskt
      via `json_store.py:JsonCache` — samma mönster som `personal_context.py`).
- [x] Injicera rättelserna i polish-prompten (AP1) som "kända rättelser".
- [x] Inställning: av/på (default på) + knapp "rensa inlärt". *UI:
      `ui/settings_window.py`; config-fält i `config.py:DEFAULTS`.*

**Acceptanskriterier**
- En manuell rättelse i t.ex. Anteckningar reflekteras i `corrections.json` och i
  nästa polish.
- Fungerar även med LLM av (då uppdateras bara `hotwords.txt`).
- Allt lokalt; ingen PII loggas.

---

### AP3 — Kontextmedvetenhet (aktiv app + text nära markör)

**Mål:** rätt egennamn/versalisering, och rätt ton/format per app.

- [x] Ny modul `context_win.py` (kräver `from __future__ import annotations`).
- [x] Aktiv app: `win32gui.GetForegroundWindow` +
      `win32process.GetWindowThreadProcessId` + `psutil` → processnamn +
      fönstertitel.
- [x] Fokuserat fält / omgivande text: UIA via `uiautomation` (eller `pywinauto`
      uia-backend) — fokuserat elements värde + ev. "Till"-fält. **Best-effort:**
      returnera tom sträng om inget går att läsa, krascha aldrig.
- [x] Konfigurerbar app→profil-mappning, t.ex.:
  - `teams`, `slack`, `discord` → "ledig ton"
  - `outlook`, `mail` → "formell e-post"
  - `code`, `cursor`, `windowsterminal`, `cmd`, `powershell` → "kod / ingen
    formatering / ingen versalisering"
- [x] Polish-prompt (AP1): skicka app-profil + on-screen-namn som **referens**
      (uttryckligen "använd som referens, klistra inte in").
- [x] Lokal transkribering (AP4): lägg on-screen-namn i `hotwords`/`initial_prompt`.
- [x] Integritet: skärmtext används endast lokalt; skickas inte om LLM/remote är av.
      Respektera "kontextmedvetenhet av"-toggle (default på).

**Acceptanskriterier**
- I en e-postklient blir mottagarens namn oftare rätt stavat/versaliserat.
- I terminal/editor klistras text enligt profil (ingen oönskad
  versalisering/skiljetecken).
- Saknad UIA-data → tom kontext, ingen krasch.

---

### AP4 — Transkriberings-biasing (backend-medveten)

**Mål:** höj råprecisionen där det går, utan att anta lokal körning.

- [x] `transcriber.py:_transcribe_local()` (~rad 593) — gör konfigurerbart:
      `hotwords` (från `hotwords.txt` + AP3-namn), `initial_prompt` (kort mening med
      fackord/namn), `vad_filter=True` (Silero), `beam_size`,
      `condition_on_previous_text=False`, `no_speech_threshold`. *Flera av dessa
      sätts redan men är hårdkodade.*
- [x] `compute_type` vid laddning (t.ex. `int8_float16` på CUDA). *Idag: i
      `Transcriber.__init__`/modell-laddning.*
- [x] Val av KBLab `revision` (default/strict/subtitle) med CT2-fallback enligt
      premiss 1. *Idag: `transcriber.py:KBLAB_REVISIONS` (~rad 119) allt `None`.*
- [x] `remote_transcribe.py:transcribe()` (~rad 172) — skicka `language="sv"`,
      `prompt` (samma biasing-sträng), och `temperature` om providern stödjer det;
      annars no-op. Logga om providern uppenbart ignorerar `prompt`. *Idag skickas
      bara `model` + `language`.*
- [x] Gemensamt transkriberingsinterface så resten av appen är backend-agnostisk.

**Acceptanskriterier**
- Lokal path: parametrar appliceras; VAD minskar hallucinering på tyst/brusigt ljud.
- Remote path: kör utan fel även om providern struntar i `prompt`.

---

### AP5 — Kommandoläge

**Mål:** röststyrd redigering av senaste blocket (motsvarar Wispr Command Mode).

- [x] Ny modul `commands.py`: detektera ledande kommandofraser ("gör det kortare",
      "punktlista", "ta bort sista meningen", "gör det formellt", "översätt till
      engelska" …).
- [x] Vid träff: skicka senaste polerade block + instruktion till LLM och
      ersätt/append enligt app-profil — utan ny inspelning/transkribering.
- [x] Konfigurerbar fraslista; av/på.

**Acceptanskriterier**
- "gör det kortare" efter en diktering förkortar föregående text.

---

### AP6 — Flow-läge *(valfritt, lägst prio)*

- [x] Kontinuerlig inspelning över pauser med chunkad transkribering och append.
      Endast lokal path initialt. Tydlig start/stopp-toggle.

---

## Polish-prompt (spec)

System-prompt på **svenska**. Krav:

- **Roll:** språkstädare, inte författare. Ändra ALDRIG innebörd. Lägg ALDRIG till
  fakta, hälsningar eller signaturer som inte sagts.
- **Uppgifter, i ordning:**
  1. Lös självrättelser/omstarter — behåll den slutliga avsikten.
  2. Bryt rörig talspråksföljd till läsbara meningar.
  3. Tillämpa kända rättelser och fackord/egennamn från referensblocket.
  4. Lätt formatering enligt app-profil.
- **Gör INTE:** generisk filler-jakt utöver det uppenbara (KBLab har redan rensat det
  mesta), ompolering av redan korrekt text, utfyllnad.
- **Output:** returnera ENBART den färdiga texten, inget annat (ingen förklaring,
  inga markdown-fences).
- **Referensblock** (utelämnas helt om tomt, så modellen inte får tomma block):
  personlig kontext · kända rättelser (`X → Y`) · app-profil · on-screen-namn.

**Few-shot (skapa 4–6 svenska exempel som täcker):**
- självrättelse ("…klockan fem, nej förresten sex" → "…klockan sex"),
- omstrukturering av en run-on,
- namn-/fackordsrättelse via referens,
- ett kod/terminal-fall där ingen versalisering/skiljetecken ska läggas till.

---

## Tvärgående krav

- [x] Bakåtkompatibel `config.json`: nya fält med säkra defaults i
      `config.py:DEFAULTS`.
- [x] Nycklar i Windows Credential Manager via `keyring` som idag; logga aldrig
      nyckel eller textinnehåll.
- [x] `pytest`-tester för nya moduler (mocka UIA och HTTP); `ruff`-CI ska passera.
- [x] Ingen ny obligatorisk nätverksberoende i grundläget (lokal modell + LLM av =
      helt offline).
- [x] Per-steg-latens i loggen för felsökning.

### Test- och stub-noteringar

- `tests/conftest.py` stubbar native deps genom `sys.modules`-injektion (se
  `sounddevice`, `keyboard`, `pyperclip`, `pystray`, `winsound`). Nya moduler kräver
  stubbar för `win32gui`, `win32process`, `psutil`, `uiautomation` enligt samma
  mönster.
- HTTP mockas via `monkeypatch.setattr(..., "urlopen", fake)` — se
  `tests/test_providers.py` för LLM- och remote-transcribe-exempel.
- Alla nya moduler med type hints mot stubbade typer kräver
  `from __future__ import annotations` (se CLAUDE.md-invariant).
- Lägg providers på alla tre ställen (`config.py`, `llm_polish.py`,
  `remote_transcribe.py`) om en ny provider införs.

---

## Underlag (faktakoll och referens)

- KBLab träningsdata + stilrevisions: `kb-labb.github.io`,
  `huggingface.co/KBLab/kb-whisper-*` (revision `strict`/`subtitle`).
- `faster-whisper`-parametrar: `SYSTRAN/faster-whisper` README.
- OpenAI-kompatibelt audio-API (`prompt`/`language`/`temperature`): OpenAI
  API-referens för transcriptions.
- Målbild (context awareness, auto-dictionary, command mode): Wispr Flow Help Center.
