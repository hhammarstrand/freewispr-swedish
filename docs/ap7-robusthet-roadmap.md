# FreeWispr-Swedish — AP7: robusthet & saknade funktioner

> **Status: implementerad.** Nästa pass efter AP1–AP6 (PR #25) och latens-passet
> L0–L4 (PR #26). Robusthet + funktioner som saknas mot ett komplett
> dikteringsverktyg. Plockas i prioordning (7.1, 7.4, 7.8 först — hög nytta/låg
> risk). Kodankare (`fil:funktion`) verifierade mot nuvarande `master`.

## Vägledande princip

Behåll alla invarianter: trådning (tangent-hooks <10 ms), terminalsäker
single-paste som default, provider-agnostik, lokal-först/integritet,
bakåtkompatibel `config.json`, nycklar i `keyring`, tester + `ruff`. Nya
funktioner är **opt-in** där de ändrar nuvarande beteende.

## Redan på plats — bygg INTE om detta

- Inspelningstak: `audio.py:MAX_RECORD_SECONDS = 120` (buffertkapacitet
  `rate * 120`, ~rad 300). Rör inte.
- Säkerhet: `url_security.py` (SSRF/klartext-skydd) och `text_sanitize.py`
  (kontrollteckeninjektion). Återanvänd, duplicera inte.
- Profiler: `context_win.py:PROFILES` (`code` stänger av polish + versalisering).
  Återanvänd för grindning nedan.
- Replace-primitiv: `paste.py:_paste_and_keep_clipboard(replace_len=…)` (~rad 56).
  Återanvänd för ångra/snippets.

---

## AP7.1 — Single-instance-spärr *(högst prio)*

**Mål:** förhindra två samtidiga instanser (dubbla hotkeys, *två* Whisper-modeller
i VRAM → OOM, urklippskonflikt).

- [x] I `main.py:main()` (~rad 723, före tray/dictation-init): ta ett
      single-instance-lås. Windows: namngiven mutex via
      `ctypes.windll.kernel32.CreateMutexW(None, False, "freewispr-swedish")` +
      kontrollera `GetLastError() == 183` (`ERROR_ALREADY_EXISTS`); alternativt
      bind en socket till en fast loopback-port. Är appen redan igång: visa kort
      notis (tray-balloon/messagebox) och avsluta rent **utan** att registrera
      hotkey eller ladda modell. Släpp låset vid avslut.

**Acceptanskriterier**
- Andra instansen avslutas inom ~1 s utan hotkey/modell-laddning; första
  instansen opåverkad.
- Test mockar låset och verifierar att guard-pathen avslutar tidigt.

---

## AP7.4 — Urklippsåterställning

**Mål:** sluta skriva över användarens urklipp permanent (nuvarande beteende
lämnar dikterad text kvar — bekräftat avsiktligt som CLI-fallback).

- [x] `paste.py:_paste_and_keep_clipboard` (~rad 56): ny config
      `restore_clipboard` (bool). På: spara tidigare urklipp före
      `pyperclip.copy(...)` och återställ efter kort delay (~300–500 ms, så
      syntetisk Ctrl+V hinner landa). Av: nuvarande beteende oförändrat.
- [x] Hantera icke-text-urklipp (bilder) elegant: `pyperclip` är textbaserat — om
      tidigare innehåll inte var text, hoppa över återställning (eller använd
      `win32clipboard` för full fidelitet). Best-effort, krascha aldrig.
- [x] Dokumentera att `restore_clipboard=on` tar bort "klistra manuellt"-fallbacken
      i terminaler.

**Acceptanskriterier**
- `restore_clipboard=on`: efter diktering innehåller urklipp användarens tidigare
  text efter delayen.
- Av: dikterad text ligger kvar (oförändrat).
- Test mockar urklipp och verifierar spara→klistra→återställ-ordningen.

---

## AP7.8 — `max_tokens`-städning *(kodnivå)*

**Mål:** rätta tecken-vs-token-överbudget i `llm_polish.py`
(`polish` ~rad 418 `int(len(user_text)*1.3)+32` och `instruct` ~rad 624
`int(len(text)*1.6)+64`). `len` är tecken men `max_tokens` är tokens → ~4–5× för
stort för svenska.

- [x] Byt till token-uppskattning (t.ex. `tecken/3 * 1.3 + headroom`) eller ett
      vettigt absolut tak (`min(generöst_tak, uppskattning)`). Behåll marginal så
      legitim output aldrig trunkeras. Lämna `warm()`-anropets `max_tokens: 1`
      (~rad 568) orört.

**Acceptanskriterier**
- `max_tokens` för ett typiskt svenskt yttrande hamnar i ett rimligt
  token-intervall (inte 4–5× för stort).
- Test med representativa indata: polish-output trunkeras inte.

---

## AP7.2 — Avbryt pågående diktering

**Mål:** låt användaren slänga en diktering så inget transkriberas/klistras.

- [x] `dictation.py`: registrera en Esc-hanterare som bara är aktiv medan
      `_recording` (no-op annars, så normal Esc inte störs). Vid Esc: sätt
      `_cancel`-flagga, kasta ljudbufferten (`recorder.abort()`), köa **inget** jobb.
- [x] Avbryt under LLM-vänteläget avbryter watchdog + hoppar paste.
- [x] Indikator visar "Avbruten". Avbryt-tangenten konfigurerbar (default Esc).

**Acceptanskriterier**
- Esc under inspelning → ingen paste och inget jobb köat; Esc utan inspelning →
  ingen effekt.
- Test verifierar att inget jobb köas vid avbrott.

---

## AP7.3 — Paus/mute från tray

**Mål:** stäng av diktering tillfälligt utan att avsluta (lösenord, spel,
skärmdelning).

- [x] `main.py:_build_menu` (~rad 686): ny post "Pausa diktering" / "Återuppta".
      Togglar `paused`-tillstånd på `DictationMode` (t.ex. `set_paused(bool)` som
      gör `_on_press` till no-op, eller av-/på-registrerar hotkeyen). Spegla i
      tray-etikett + indikator. Session-tillstånd, default igång (persistas inte).

**Acceptanskriterier**
- Pausad: hotkeyen gör inget; tray-etiketten speglar tillståndet; återuppta
  återställer normalt.
- Test verifierar att `_on_press` no-op:ar när pausad.

---

## AP7.5 — Kodväxling sv/en *(mitigering, inte fix)*

**Mål:** bättre hantering av engelska facktermer i svensk diktering. KBLab är
svensktränad → akustisk mangling av engelska kan inte elimineras helt; dokumentera
det ärligt.

- [x] Ny config `expect_english_terms` (bool). På:
  - förstärk `transcriber.py`-bias (`initial_prompt`/hotwords) med vanliga
    engelska facktermer,
  - utöka polish-prompten i `llm_polish.py` med instruktion att behålla engelska
    facktermer i korrekt form.
- [x] Valfritt: tillåt `language=None`/auto på *remote*-pathen för providers som
      stödjer autodetektering (skopa till remote/custom; lokal KBLab gynnas inte).

**Acceptanskriterier**
- `expect_english_terms=on`: engelska termer i svensk diktering ("vi måste deploya
  till staging") stavas rätt oftare (kvalitativt); polish-prompten innehåller
  instruktionen; ingen regression för ren svenska.

---

## AP7.6 — Snippets / textexpansion *(återinför)*

**Mål:** dynamisk trigger→expansion (t.ex. "min signatur" → mejlfot), borttaget i
commit `8ed9942`.

- [x] Ny `snippets.py`: trigger→expansion-par i
      `~/.freewispr-swedish/snippets.json` (atomärt via `json_store`). Applicera i
      pipelinen på **slutlig** text, exakt-/normaliserad matchning på ledande fras
      (förutsägbart, likt kommandoläget). Håll åtskilt från inlärningsloopen
      (rättelser) och `personal_context` (referenstext).
- [x] UI i Inställningar för att lägga till/redigera/ta bort.

**Acceptanskriterier**
- Konfigurerad snippet expanderar vid diktering; redigera/ta bort i Inställningar
  fungerar; ingen expansion när trigger saknas.
- Test på den rena expansionsfunktionen.

---

## AP7.7 — UI för inlärda rättelser + ångra

**Mål:** (a) se/redigera/ta bort inlärda rättelser; (b) ångra senaste diktering.

- [x] Inställningar: flik som listar `learning.load_corrections()` (~rad 110) med
      radvis ta-bort + "rensa alla" (`learning.clear_learned()` ~rad 173) +
      lägg till/redigera. Mest UI-koppling till befintlig `learning.py`.
- [x] Ångra: spåra senaste blocket + dess längd; hotkey/tray-post "Ångra senaste"
      som backspacar senaste inklistrade blocket via `paste.py:replace_len` med tom
      ersättning. Best-effort (antar att markören står kvar efter pastet).

**Acceptanskriterier**
- Rättelselistan visar inlärda par; ta-bort tar bort ur `corrections.json`.
- Ångra tar bort senaste blocket när markören står kvar efter det.
- Test för rättelselistans datapath.

---

## Tvärgående krav

- **Integritet:** ingen ny obligatorisk nätverkstrafik; snippets/rättelser/urklipp
  hanteras lokalt.
- Bakåtkompatibel `config.json`; nya fält med säkra defaults (nya beteenden opt-in).
- Nycklar i Windows Credential Manager via `keyring`; logga aldrig nyckel eller
  textinnehåll.
- `pytest` per arbetspaket (mocka UIA/HTTP/urklipp/keyboard); `ruff` ska passera.
- Inga regressioner i terminalsäker paste, offline-diktering, eller
  hook-latensen (<10 ms).

## Verifiering (manuellt, efter bygge)

Kör `bench_latency` på riktig maskin och bekräfta att inget i AP7 lagt latens på
hot-pathen: `context_hotpath` ska fortsatt vara ≈0 och paste-vägen oförändrad.
