"""
Personal context — fri text som injiceras i LLM-polishens system-prompt.

Ersätter de tidigare separata snippets- och korrigeringsfunktionerna
med en enda kontext-ruta där användaren naturligt beskriver vem de är,
vad de jobbar med, vanliga egennamn / facktermer, ton och stil. LLM:n
använder kontexten för smartare korrigeringar än vad statiska regex-
substitutioner kunde åstadkomma.

Lagras i ``~/.freewispr-swedish/personal_context.json`` som
``{"text": "..."}`` så att framtida fält (t.ex. per-domän kontexter)
kan läggas till utan migration.

Skriven defensivt: tom/whitespace-bara text räknas som "ingen kontext"
och utelämnas helt från prompten — vi vill aldrig skicka ett tomt
"Användarens kontext:"-block som LLM:n kan tolka som en instruktion.
"""
from __future__ import annotations

from pathlib import Path

from json_store import JsonCache

_PATH = Path.home() / ".freewispr-swedish" / "personal_context.json"

# Hård gräns så att en användare som råkar klistra in en hel bok inte
# blåser upp varje LLM-anrop. 8000 tecken ≈ ~2000 tokens — rikligt med
# kontext utan att äta hela budget.
MAX_LENGTH = 8000

_store = JsonCache(_PATH, default={"text": ""})


def mtime() -> float:
    """Filens mtime (0.0 om saknas) — för cache-invalidering hos konsumenter."""
    return _store.mtime()


def load() -> str:
    """Returnera den lagrade kontexten, eller tom sträng."""
    data = _store.load()
    if not isinstance(data, dict):
        return ""
    text = data.get("text", "")
    return text if isinstance(text, str) else ""


def save(text: str) -> None:
    """Spara kontext atomärt. Trunkerar tyst till MAX_LENGTH för säkerhets skull."""
    if not isinstance(text, str):
        text = ""
    if len(text) > MAX_LENGTH:
        text = text[:MAX_LENGTH]
    _store.save({"text": text})


def exists_and_nonempty() -> bool:
    """True om filen finns och innehåller faktisk text (efter strip)."""
    return bool(load().strip())
