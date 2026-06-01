# Konkurrent-roadmap — "secret sauce" från marknaden

Mål: kartlägga vad konkurrenterna (Wispr Flow, Superwhisper, MacWhisper, Aqua
Voice, Talon, Dragon, VoiceInk, Willow) gör bra, och implementera deras starkaste
idéer hos oss — **på svenska, lokal-först, och utan att tappa prestanda**.

## Designramar för detta arbete

- **Svenska only.** Vi lägger *inte* till flerspråkighet/auto-språkdetektering.
  Tvärtom utnyttjar vi att språket är låst till `sv` för prestanda (se nedan).
- **Lokal-först.** Inget nytt obligatoriskt nätberoende. Consent-grindar gäller.
- **Inga nya indikator-states.** Allt mappas till listen/transcribe/done/error.
- **Opt-in med säkra defaults**, bakåtkompatibel config, nycklar i keyring.

## Nuläge — vad vi redan matchar

| Konkurrent-"secret sauce" | Vår motsvarighet |
|---|---|
| Self-corrections ("nej, jag menar…") | AP1 polish |
| Ton/formalitet per kontext | AP3 app-profiler |
| Kommando vs diktering | AP5 command mode |
| Personlig ordbok / auto-inlärning | AP2 learning loop + hotwords |
| Kontext från aktivt fönster/skärm | AP3 UIA |
| Kontinuerligt flow-läge | AP6 |
| Fyllnadsord-borttagning | polish (delvis) |
| Snippets / textexpansion | AP7.6 |

## Svenska-only prestanda — redan på plats

De stora vinsterna av att vara enspråkig fanns redan i L5-koden:

- `language="sv"` är pinnat i både lokal (`transcriber.py`) och remote
  (`remote_transcribe.py`) → Whisper kör **ingen språkdetekterings-pass**.
- `without_timestamps=True` i lokal avkodning → decodern genererar bara
  text-tokens, inte tidsstämpel-tokens.

Polish-prompten är redan ren svenska utan flerspråkig hedging och ligger som
cachebart statiskt prefix (L3), så där finns ingen meningsfull trim kvar att
göra. Vi hittar alltså inte på en låtsas-optimering.

## Arbetspaket — implementerat

### KP2 — Användardefinierade lägen (Superwhisper "modes") ✅
`modes.py` + "modes.json". Namngivna lägen med egen ton/formaterings-beskrivning
och `polish`/`capitalize`-flaggor. Binds till appar via befintliga
`app_profiles` (process → lägesnyckel). Ett läge resolverar till en
`context_win.Profile`, så polish-pipelinen behövde **ingen** ändring.
Användarlägen skuggar inbyggda med samma namn; okända nycklar faller tillbaka
till `default`. `get_context()` konsulterar `modes.get_profile()` via lazy import.

### KP3 — Rösteditera markerad text (Wispr/Aqua Command Mode) ✅
Markera text → håll en egen hotkey → säg en instruktion → markeringen ersätts
med LLM-resultatet.
- `voice_edit.py` — ren, beroendeinjicerad orkestreringskärna.
- `paste.read_selection()` — läser markeringen via Ctrl+C, återställer urklipp.
- Återanvänder `llm_polish.instruct()` (redan saniterad + fail-safe).
- `DictationMode.run_voice_edit()` — routing + indikator-mappning.
- Egen hotkey (`voice_edit_hotkey`, tom = av) med separata press/release-handlers
  och en taggad jobb-tuple, så **dikteringens hot path är orörd**.
- Kräver att LLM är på (annars no-op).

> **Smoke-test krävs:** capture-vägen (hotkey → inspelning → `stop_fast`) kan
> inte köras headless. Worker-sidans routing är enhetstestad; kör en manuell
> Windows-smoke innan den förlitas på i produktion.

## Diskuterat men ej byggt (medvetet bortval)

- **Talon-stil kommandogrammatik / eye-tracking** — utanför push-to-talk-scope.
- **Live streaming-refinement (Aqua)** — krockar med stop→transcribe→paste-hot-pathen.
- **Flerspråkighet / code-switching** — explicit emot "svenska only".
- **Cross-device sync** — ingen molnbackend; lokal-först.

## Verifiering
`pytest` + `ruff check . --select E,F,W --ignore E501` gröna före varje commit.
