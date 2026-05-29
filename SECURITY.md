# Säkerhetspolicy

## Rapportera en sårbarhet

Hittade du en sårbarhet i freewispr-swedish? Rapportera **privat** via GitHub:s
[Security Advisory](https://github.com/hhammarstrand/freewispr-swedish/security/advisories/new)
— inte som en vanlig issue. Initialt svar inom 7 dagar.

## Inom scope

Sårbarheter som påverkar appens säkerhetsmodell:

- **Hantering av API-nycklar** — läckage från `keyring`, eller nycklar som
  hamnar i `config.json` / loggar trots `_SECRET_FIELDS`-strippningen.
- **Sanering av LLM/remote-text** — ANSI/control-sekvenser eller liknande
  som passerar `text_sanitize.sanitize_output()` och hamnar i urklipp/UI.
- **URL-validering** — kringgående av `url_security`-kontroller så att en
  custom-provider kan användas för SSRF eller exfiltration.
- **Consent gates** — paths där audio/text skickas över nät utan att
  `llm_privacy_accepted` eller `transcription_privacy_accepted` är `True`.
- **PyInstaller-bygget** — supply chain-risker via beroenden eller
  modellfiler från Hugging Face.

## Utanför scope

- **Funktionella buggar** ("mikrofonen hittas inte", "indikatorn fastnar") —
  öppna en vanlig issue.
- **Kända CVE:er i beroenden som inte påverkar appen praktiskt** —
  `pip-audit` körs i CI och vi följer Dependabot.
- **Att Windows SmartScreen flaggar exe:n** — den är inte kodsignerad,
  vilket är dokumenterat i README.

## Hotmodell i korthet

- **Lokal-först:** standardläget skickar ingen text eller ljud över nät.
- **Opt-in remote:** LLM-granskning och remote-transkribering kräver
  uttryckligt samtycke i Inställningar.
- **Provider-misstro:** alla LLM-svar och remote-transkriptioner behandlas
  som potentiellt fientliga och saneras innan paste/UI.
- **Modeller laddas med `local_files_only=True`** under normalt bruk —
  endast `convert_model.py` och first-run-dialogen får ladda ned.
