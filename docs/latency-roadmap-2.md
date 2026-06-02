# FreeWispr-Swedish — L5: latens, omgång 2

> **Status: implementerad.** Fortsättning efter L0–L4 (#26). Två angreppssätt:
> *skala ner golvet* (snabbare inferens) och *gå under golvet* (sluta vänta på
> inferensen) — vilket L0–L4 medvetet inte rörde. Plockas i prioordning (1–3 är
> bästa lågt hängande). Kodankare (`fil:funktion`) verifierade mot nuvarande
> `master`.

## Förutsättning: mät allt mot befintlig harness

Alla acceptanskriterier verifieras via `tests/bench_latency.py` + L0-telemetrin
(`transcribe_ms`, `llm_ms`, `conn_ms`, `conn_reused`, `first_token_ms`,
`context_hotpath_ms`). Lägg till nya loggfält där det behövs (`resample_ms`,
`upload_bytes`, `decode_passes`).

## Invarianter (behåll)

Trådning/hooks <10 ms, terminalsäker single-paste, provider-agnostik,
lokal-först/integritet, bakåtkompatibel `config.json`, `keyring`, tester + `ruff`.
Inga regressioner i L0–L4-vinsterna eller i VAD-/OOM-robustheten. Nya beteenden
opt-in med säkra defaults.

**Ingår inte:** `max_tokens`-städningen (AP7.8) — kodhygien, inte latens (för stort
`max_tokens` saktar inte generering, den stannar vid EOS).

---

## L5.1 — Pinna `temperature=0` *(billigast, tar bort svans-latens)*

**Problem (verifierat):** `transcriber.py:_transcribe_local` sätter ingen
`temperature` i `model.transcribe(...)` (~rad 718), så faster-whisper använder
default-fallbacken `(0.0, 0.2, …, 1.0)` och kör om avkodningen upp till 6 gånger
när `compression_ratio`/`log_prob`-trösklarna fallerar.

- [x] Sätt `temperature=0.0` (skalär) i transcribe-anropet → max ett
      avkodningspass. Behåll övriga rattar (beam_size, no_repeat_ngram,
      repetition_penalty).
- [x] Logga `decode_passes` (1 i normalfallet).

**Acceptanskriterier**
- Brusigt testklipp: `decode_passes == 1`; `transcribe_ms` p95 på brusig indata
  sjunker mot baseline i `bench_latency`.
- Enhetstest: transcribe-anropet får en skalär temperatur.

---

## L5.2 — Komprimera ljudet på remote-pathen

**Problem (verifierat):** `remote_transcribe.py:_float_to_wav_bytes` (~rad 120)
skickar okomprimerad 16-bitars WAV (~32 KB/s). Ljudet är redan 16k mono här
(`finalize_audio` i `dictation._process_job`).

- [x] Config `remote_audio_format`: `wav` (default) | `flac` (~hälften) | `opus`
      (~10× mindre för tal). Koda till valt format före multipart-bygget; sätt
      rätt `Content-Type` + filändelse. FLAC via `soundfile`/`libsndfile`, Opus
      via `soundfile`/`opuslib`/`ffmpeg`; falla tillbaka till WAV om kodaren
      saknas.
- [x] Logga `upload_bytes`.

**Acceptanskriterier**
- `flac`/`opus`: `upload_bytes` ned ≥40 % (FLAC) / ≥85 % (Opus) på 5 s-klipp;
  leverantören returnerar korrekt text (Opus sänker inte kvaliteten märkbart).
- WAV-fallback fungerar när kodaren saknas (test).

---

## L5.3 — Värm transkriberings-anslutningen vid start

**Problem (verifierat):** `llm_polish.py:warm` (~rad 558) värmer bara
LLM-endpointen; remote-transkriberingen får ingen pre-warm, så L2:s keep-alive
hjälper först från diktering nr 2.

- [x] Lägg en `warm`-motsvarighet för transkriberings-poolen (öppna/håll
      `http_pool`-anslutningen mot transkriberings-base_url vid start, ev. en
      pytteliten request). Anropas bara när `transcription_provider != "local"`.

**Acceptanskriterier**
- Första remote-dikteringen efter start loggar `conn_ms` ≈ 0 och
  `conn_reused=true`.

---

## L5.4 — Fånga ljudet direkt i 16 kHz mono

**Problem (verifierat):** strömmen öppnas i enhetens nativa rate
(`audio.py:_try_start` ~rad 168, `samplerate=default_samplerate`, oftast 48k) och
resamplas i `finalize_audio` (~rad 468, soxr HQ / scipy).

- [x] Försök öppna `sd.InputStream` med `samplerate=16000, channels=1`. Lyckas →
      `finalize_audio` blir no-op (hoppa resampling/downmix). Misslyckas → falla
      tillbaka till nativa-rate + resample.
- [x] Logga `resample_ms` (0 när hoppad).

**Acceptanskriterier**
- Enhet som stödjer 16k mono: `resample_ms` ≈ 0, steget loggas som överhoppat.
- Enhet som inte stödjer det: oförändrat beteende, ingen krasch.

---

## L5.5 — Billig RMS-trim av tystnad före decode

**Problem (verifierat):** VAD är default på och `_transcribe_local` kör ett
*andra* no-VAD-pass när VAD-passet ger tomt (`vad_attempts = (True, False)`
~rad 713).

- [x] Trimma ledande/avslutande tystnad med befintlig RMS (`min_rms`) före
      transcribe — billigt, RMS finns redan i recordern.
- [x] Säkerställ att no-VAD-fallbacken bara körs när VAD-passet faktiskt gav
      tomt (inte rutinmässigt).

**Acceptanskriterier**
- Klipp med tystnad i kanterna: färre samples till Whisper och lägre
  `transcribe_ms`; inga ord kapas (gränsfallstest).

---

## L5.6 — Hoppa över polish för triviala transkript

- [x] Billig lokal heuristik i polish-pathen (`dictation`/`transcriber`): hoppa
      polish när transkriptet är trivialt — ≤ N ord **och** inga
      disfluens-/självrättelse-spår ("öh/eh/nej förresten" …). Konservativt, så
      självrättelser aldrig missas. Config-tröskel, default på.

**Acceptanskriterier**
- Trivialt yttrande: `llm_ms == 0` (polish hoppad), text klistras direkt.
- Icke-trivialt yttrande: polish körs som vanligt.
- Enhetstest på predikatet (trivial vs ej).

---

## L5.7 — Transkribera *under* inspelningen *(störst vinst, fasad)*

- [x] **Fas 1 (lokal):** låna chunkningen från `flow.py:split_on_silence` /
      `FlowMode` till push-to-talk: transkribera bufferten i bitar *medan*
      användaren pratar; vid släpp återstår bara sista chunken. Sätt ihop
      delresultaten (polish körs på helheten som idag). Robust mot mycket korta
      yttranden (degraderar till nuvarande beteende).
- [x] **Fas 2 (remote, valfritt):** om `staik`/`berget` exponerar
      streaming-/realtids-ASR, strömma ljud under inspelning; annars no-op
      (behåll batch).

**Acceptanskriterier**
- Långt yttrande: post-release `transcribe_ms` sjunker väsentligt mot
  batch-baseline; endast sista chunken avkodas efter släpp.
- Slutlig text motsvarar batch-resultatet (regressionståls).
- Korta yttranden: ingen regression.

---

## L5.8 — Valfritt / utforskande

- [x] **`BatchedInferencePipeline`** (faster-whisper) för *längre* klipp →
      parallell chunk-avkodning. Mät innan default.
- [x] **Prefix/KV-cache för polish-prompten:** lokal Ollama (KV-återanvändning av
      det statiska prefixet); staik om prompt-caching stöds. Mål: lägre
      `first_token_ms`.
- [x] **Lokal polish-modell** som config-alternativ (LAN-rundtur) ovanpå
      befintlig custom-provider. Ren config/dokumentation.

---

## Tvärgående krav

- Bakåtkompatibel `config.json`; nya fält (`remote_audio_format`,
  trim/skip-trösklar, streaming-toggle) med säkra defaults.
- Integritet: ingen ny obligatorisk nätverkstrafik; Fas 2 i L5.7 får aldrig
  strömma ljud till remote i bakgrunden utan uttryckligt val (samma princip som
  `flow.py`).
- `pytest` per arbetspaket (mocka modell/HTTP/ljud); `ruff` ska passera.
- Allt verifierbart via `bench_latency` + telemetrin. Kör harness före/efter
  varje paket och jämför p50/p95.
