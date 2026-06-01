"""
Voice-edit selection (KP3) — Wispr/Aqua "Command Mode" på godtycklig markering.

Konkurrenterna låter dig markera text, hålla en hotkey, *säga* en instruktion
("gör det här mer formellt", "översätt till engelska", "kortare") och ersätta
markeringen med resultatet. Vårt befintliga kommandoläge (AP5) jobbar bara på
*föregående dikterade block*; detta generaliserar det till vilken markering som
helst i vilken app som helst.

Återanvänder:
- ``paste.read_selection()`` för att läsa markeringen (Ctrl+C + återställ urklipp),
- ``llm_polish.instruct()`` för transformationen (redan saniterad + fail-safe),
- ``paste.paste_text()`` för att ersätta markeringen.

Designinvarianter: LLM-respons går genom ``sanitize_output()`` (i ``instruct``),
consent-grinden gäller (anropas inte om LLM är av), och allt är fail-safe — en
miss får aldrig krascha eller radera användarens markering.

Kärnan (:func:`run`) är ren och beroendeinjicerad så tester slipper native-deps.
"""
from __future__ import annotations

from typing import Callable

# Result codes so the caller can map to the 4 indicator states without this
# module importing any UI.
OK = "ok"            # selection transformed + pasted  → done
NO_SELECTION = "no_selection"   # nothing was selected   → error/info
NO_INSTRUCTION = "no_instruction"  # nothing was said    → error/info
UNCHANGED = "unchanged"  # LLM returned the input as-is → done (no-op)
FAILED = "failed"        # transform errored            → error


def run(
    instruction: str,
    *,
    read_selection: Callable[[], str],
    transform: Callable[[str, str], str],
    paste_replacement: Callable[[str, int], None],
) -> str:
    """Drive one voice-edit: read selection → transform by instruction → paste.

    Pure orchestration; every side-effecting dependency is injected:

    - ``read_selection() -> str``: the currently selected text ("" if none).
    - ``transform(selection, instruction) -> str``: LLM rewrite (already
      sanitized + fail-safe; returns the input unchanged on any error).
    - ``paste_replacement(text, replace_len) -> None``: replace the selection
      with ``text``. ``replace_len`` is the selected length so the caller can
      backspace it before pasting (mirrors AP5 command-mode replace).

    Returns one of the module result codes.
    """
    instruction = (instruction or "").strip()
    if not instruction:
        return NO_INSTRUCTION

    selection = (read_selection() or "").strip()
    if not selection:
        return NO_SELECTION

    try:
        new_text = (transform(selection, instruction) or "").strip()
    except Exception:
        return FAILED

    if not new_text or new_text == selection:
        # instruct() returns the input unchanged on failure or genuine no-op;
        # either way there's nothing to paste. Don't disturb the selection.
        return UNCHANGED

    # Replace the selection: with text selected, a paste overwrites it, so no
    # backspacing is needed — replace_len=0. (The selection is still active
    # because read_selection() only issued Ctrl+C, never collapsed it.)
    paste_replacement(new_text, 0)
    return OK
