## Sammanfattning

<!-- 1–3 punkter: vad ändrar denna PR och varför. -->

## Test

- [ ] `python -m pytest tests/ -q` grön
- [ ] `ruff check . --select E,F,W --ignore E501` grön
- [ ] Manuell smoke-test gjord om Windows-flödet ändrats (`python main.py` → diktera → verifiera paste)

## Risk

<!-- Vilka delar av appen kan påverkas? T.ex. "bara docs", "hot path",
"settings reload-koordinering", "consent-flöde". Hjälper review/rollback. -->

## Checklista (om relevant)

- [ ] Användarsynliga strängar på svenska med korrekta å/ä/ö
- [ ] Inga API-nycklar i config.json (allt via `keyring`)
- [ ] LLM/remote-text passerar `sanitize_output()` innan paste/UI
- [ ] Consent gates respekteras (`llm_privacy_accepted`, `transcription_privacy_accepted`)
- [ ] Indikator-state är `listen`/`transcribe`/`done`/`error`
- [ ] Nya provider-strängar uppdaterade på alla tre ställen (`config.py`, `llm_polish.py`, `remote_transcribe.py`)
