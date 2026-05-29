# FreeWispr-Swedish — Latens-roadmap (uppföljning på AP1–AP6)

> **Status: implementerad.** Ren latenspass ovanpå AP1–AP6 (landade i PR #25).
> Jaga all latens i hot-pathen som **inte** är modellinferens — inferensen (lokal
> Whisper-decode resp. remote transkriberings-/LLM-inferens) är det irreducibla
> golvet. Arbetspaketen plockas i ordning L0→L4. Kodankare (`fil:funktion`) är
> verifierade mot nuvarande `master`.

## Vägledande princip

Hot-pathen är: `tangent ned → spela in → tangent upp → finalisera → transkribera
→ (polish) → klistra`. Allt som inte är inferens ska antingen **bort**,
**överlappas** med inspelningen, eller **poolas/värmas**. Behåll alla invarianter:
trådning (hooks <10 ms), terminalsäker single-paste som default, provider-agnostik,
lokal-först/integritet, bakåtkompatibel config, tester + ruff.

---

## L0 — Mätbarhet *(förutsättning, gör först)*

Utan mätning är ms-kriterierna nedan inte verifierbara. Bygg ut den befintliga
latensloggen (`dictation.py:_log_latency`, ~rad 311).

- [x] Lägg till fält i `_log_latency` så raden blir komplett:
  - `context_hotpath_ms` — hur mycket kontext/UIA-läsning bidrog till kritiska
    vägen (≈0 om överlappad/cachad enligt L1).
  - `uia_ms` — faktisk tid för UIA-läsningen (oavsett var den körs).
  - `conn_ms` + `conn_reused` (bool) — anslutningssetup för remote-anrop
    (transkribering och polish).
  - `first_token_ms` — TTFT för polish (även om paste sker vid full text).
- [x] Rullande sammanställning i loggen (p50/p95 över senaste N dikteringar).
- [x] Benchmark-läge `python -m tests.bench_latency <wav>` — kör pipelinen K
      gånger på en fast WAV och skriver percentiler per steg. Får mocka
      paste/UIA så det körs i CI utan Windows-GUI.

**Acceptanskriterier**
- Varje diktering loggar samtliga fält ovan.
- `bench_latency` kör i CI och skriver p50/p95 för `transcribe_ms`, `llm_ms`,
  `paste_ms`, `context_hotpath_ms`, `conn_ms`.

---

## L1 — Få UIA av kritiska vägen *(störst)*

**Problem (verifierat):** efter `_on_release` kör `_process_job` först
`_observe_corrections()` → en UIA-läsning (`context_win.get_focused_text`), och
sedan `_transcribe` → `_resolve_context()` → `get_context()` (~`context_win.py:144`)
→ **ännu en** UIA-läsning + `get_active_app`. Båda synkrona och seriella *före*
transkribering. I Electron/Chromium kan varje
`GetFocusedControl().GetValuePattern()` ta 100–500 ms och ibland hänga.

- [x] **Flytta kontextupplösningen till `_on_press`, på en daemon-tråd.** Aktiv
      app + fokuserat fält är kända vid nedtryck och ändras inte medan tangenten
      hålls. Spara i t.ex. `self._ctx_future`; `_transcribe` läser cachat med kort
      hård `join(timeout)`. UIA-kostnaden överlappar hela inspelningen.
- [x] **Slå ihop de två UIA-läsningarna till en.** Snapshotet vid nedtryck ger
      både (a) fältets nuvarande innehåll = förra (ev. redigerade) inklistringen
      → underlag för AP2-inlärningen, och (b) egennamn för AP3-biasing.
      `_observe_corrections` konsumerar (a) från samma snapshot. Ingen synkron
      `get_focused_text` kvar i `_process_job`/`_transcribe`.
- [x] **Tidsbegränsa UIA hårt.** `uiautomation.SetGlobalSearchTimeout(...)` lågt
      vid init, och kör läsningen i tråd med `join(timeout≈150 ms)` → returnera
      `""` annars.
- [x] **Hoppa över textläsningen när den inte behövs.** `get_context(read_text=…)`
      finns redan men anropas alltid med `True`. Anropa med `read_text=False` när
      profilen är polish-av (t.ex. `code`) **och** `_last_pasted` är tomt — då
      räcker billiga `get_active_app`.

**Acceptanskriterier**
- `context_hotpath_ms` ≤ 5 ms (mätt) när tangenten hållits ≥ UIA-tiden.
- Strukturtest: varken `_process_job` eller `_transcribe` anropar
  `get_focused_text` synkront (mock som höjer om den anropas på worker-tråden).
- Endast **en** UIA-läsning per diktering (räknare i test).
- Patologisk app (mocka UIA att sova 2 s): dikteringen blockeras aldrig mer än
  `timeout` (~150 ms) och faller tillbaka till tom kontext.

---

## L2 — Keep-alive för remote-transkribering

**Problem (verifierat):** `remote_transcribe.transcribe()` (~rad 172) bygger en
färsk `urllib.request.Request` per diktering (~rad 229) → ny TCP + TLS varje gång
(~100–300 ms). `llm_polish.py` har redan keep-alive-poolad transport
(`_http_request` ~rad 423, `_read_sse` ~rad 391, `reset_sessions` ~rad 384,
stale-reopen+retry); transkriberingen saknar den.

- [x] Bryt ut keep-alive-poolen ur `llm_polish.py` till delad modul
      `http_pool.py` (persistent anslutning per host, stale-detektion → reopen +
      retry-en-gång, timeouts). Behåll `reset_sessions()`-motsvarighet.
- [x] Använd poolen i **både** `llm_polish.py` och `remote_transcribe.py`.
- [x] Multipart-bygget kan vara kvar; bara transporten ska poolas.

**Acceptanskriterier**
- Diktering N>1 mot samma host loggar `conn_reused=true` och `conn_ms` ≈ 0 (mot
  ~100–300 ms på N=1).
- Test: poolen återanvänder samma anslutningsobjekt över ≥2 anrop till samma
  host; byte av host/base_url öppnar ny.
- Polish oförändrad (regression i `tests/test_polish_transport.py`).

---

## L3 — Polish: värm, prefix-cacha, valfri "rå → ersätt"

**Problem (verifierat):** streamingen assemblas helt innan paste, så TTFT ger
ingen vinst i nuläget. Whisper värms (`transcriber.py:_warmup` ~rad 456, 1 s
tystnad på egen tråd) men **inget värmer LLM-endpointen** → första polishen betalar
handskakning + ev. provider-cold-start.

- [x] **Värm LLM-anslutningen vid start + periodiskt.** Minimal throwaway-polish
      (~1 token) på egen tråd när LLM är på, och håll den poolade anslutningen
      (L2) varm med intervall under keep-alive-timeouten.
- [x] **Valfritt "rå → ersätt"-läge** (config-flagga, default av). Klistra rå
      transkribering direkt och ersätt med polerad text när den landar, via
      **befintlig** `paste.py:_paste_and_keep_clipboard(replace_len=…)` (~rad 56).
      **Grinda på app-profil:** aldrig i `code`/terminal (paste-twice-risk),
      endast i redigerbara fält (casual/email). Hoppa över ersättning om
      användaren redan tryckt Enter/Tab (best-effort; dokumentera tradeoffen i
      README).
- [x] **Prefix-caching:** strukturera polish-anropet så ett statiskt
      system-/few-shot-prefix kan cachas där providern stödjer det
      (capability-flagga per provider; lokal Ollama/llama.cpp via KV-cache). Håll
      annars few-shot stramt.

**Acceptanskriterier**
- Efter warm: gapet mellan **första** polish-`llm_ms` i en session och medianen
  < ~150 ms (mätt).
- I "rå → ersätt"-läge: tid till **första synliga text** ≈ `transcribe_ms +
  paste_ms` (mätt); i `code`-profil sker ingen ersättning (test).
- Default-läget (single paste) oförändrat och fortsatt terminalsäkert.

---

## L4 — Lokala avkodningsrattar

**Problem (verifierat):** `beam_size` är redan 1 (greedy — bra). Kvar:
`whisper_vad_filter=True` som default kör Silero-VAD-inferens före decode (kan
kosta mer än den sparar på korta klipp; RMS-grinden fångar redan tystnad), och
CUDA-`compute_type` bör vara `int8_float16`.

- [x] Sätt CUDA-default-`compute_type` till `int8_float16` i
      `transcriber.py:_get_device_and_compute` (~rad 258) (behåll override).
- [x] Behåll `whisper_vad_filter` som dokumenterad latensratt; logga `vad`-on/off
      så deltat syns.
- [x] Säkerställ att den **live** transkriberingspathen (inte bara `_warmup`)
      sätter `condition_on_previous_text=False` för single-shot (~rad 702 — redan
      satt; verifiera och täck med test).

**Acceptanskriterier**
- På CUDA: `transcribe_ms` med `int8_float16` ≤ `float16`-baseline på samma fasta
  klipp (båda via `bench_latency`).
- VAD on/off-delta loggas och syns i `bench_latency`.

---

## Tvärgående krav

- **Integritet oförändrad:** ingen ny obligatorisk nätverkstrafik i grundläget
  (lokal modell + LLM av = offline). Kontext/UIA stannar lokalt; skickas till LLM
  endast när polish körs.
- Bakåtkompatibel `config.json`; nya fält med säkra defaults.
- Nycklar i Windows Credential Manager via `keyring`; logga aldrig nyckel eller
  textinnehåll (latensloggen loggar bara tider + metadata).
- `pytest` för varje WP (mocka UIA och HTTP); `ruff` ska passera.
- Inga regressioner i terminalsäker paste eller i lokal offline-diktering.
- Allt verifierbart från latensloggen / `bench_latency`.

## Förväntad nettoeffekt

På remote-pathen: ~2 borttagna handskakningar (L2 + polish-warm) + ~2 borttagna
UIA-läsningar av kritiska vägen (L1) ≈ storleksordning **300–800 ms** lägre
upplevd latens, utan att röra själva inferensen.
