"""
Kommandoläge (AP5) — röststyrd redigering av senaste blocket.

När en diktering inleds med en känd kommandofras (t.ex. "gör det kortare",
"punktlista", "ta bort sista meningen") tolkas den som ett *kommando* på det
senast inklistrade blocket i stället för ny text: instruktionen + föregående
block skickas till LLM (eller en lokal operation körs) och resultatet ersätter
blocket — utan ny inspelning eller transkribering.

Fraslistan är konfigurerbar. Detektering och de lokala operationerna är rena
funktioner (inga sidoeffekter) så att de är enkla att testa.
"""
from __future__ import annotations

import re
from typing import Callable, NamedTuple


class Command(NamedTuple):
    phrase: str
    kind: str     # "llm" eller "local"
    payload: str  # LLM-instruktion, eller namnet på en lokal operation


# Fras → (kind, payload). Längre fraser matchas före kortare.
DEFAULT_COMMANDS: dict[str, tuple[str, str]] = {
    "gör det kortare": ("llm", "Gör texten kortare och mer koncis utan att ändra innebörden."),
    "fatta dig kortare": ("llm", "Gör texten kortare och mer koncis utan att ändra innebörden."),
    "gör en punktlista": ("llm", "Formatera texten som en punktlista."),
    "punktlista": ("llm", "Formatera texten som en punktlista."),
    "gör det formellt": ("llm", "Skriv om texten i en formell ton."),
    "gör det mer formellt": ("llm", "Skriv om texten i en mer formell ton."),
    "gör det ledigt": ("llm", "Skriv om texten i en ledig, vardaglig ton."),
    "rätta stavningen": ("llm", "Rätta stavning och grammatik i texten."),
    "översätt till engelska": ("llm", "Översätt texten till engelska."),
    "översätt till svenska": ("llm", "Översätt texten till svenska."),
    "ta bort sista meningen": ("local", "remove_last_sentence"),
}


def _remove_last_sentence(text: str) -> str:
    """Drop the final sentence (split on . ! ? boundaries)."""
    s = text.strip()
    if not s:
        return ""
    parts = re.split(r"(?<=[.!?])\s+", s)
    if len(parts) <= 1:
        return ""
    return " ".join(parts[:-1]).strip()


_LOCAL_OPS: dict[str, Callable[[str], str]] = {
    "remove_last_sentence": _remove_last_sentence,
}


def detect_command(text: str,
                   commands: dict[str, tuple[str, str]] | None = None
                   ) -> Command | None:
    """Return a :class:`Command` if ``text`` starts with a known phrase."""
    cmds = commands or DEFAULT_COMMANDS
    norm = (text or "").strip().lower().strip(".,!?;: ")
    if not norm:
        return None
    for phrase in sorted(cmds, key=len, reverse=True):
        if norm == phrase or norm.startswith(phrase + " ") or \
                norm.startswith(phrase + ","):
            kind, payload = cmds[phrase]
            return Command(phrase=phrase, kind=kind, payload=payload)
    return None


def execute(cmd: Command, previous_text: str,
            llm_transform: Callable[[str, str], str] | None = None
            ) -> str | None:
    """Run a command against the previous block.

    ``llm_transform(instruction, text) -> str`` performs LLM commands; pass
    ``None`` when LLM is unavailable (LLM commands then return ``None`` so the
    caller can fall back to treating the utterance as normal dictation).
    Returns the new text, or ``None`` when the command could not run.
    """
    prev = (previous_text or "").strip()
    if not prev:
        return None
    if cmd.kind == "local":
        op = _LOCAL_OPS.get(cmd.payload)
        return op(prev) if op else None
    if cmd.kind == "llm":
        if llm_transform is None:
            return None
        result = llm_transform(cmd.payload, prev)
        return result or None
    return None
