"""KP3: voice-edit selection orchestration (pure core, injected deps)."""
import voice_edit


def _spy_paste():
    calls = []

    def paste(text, replace_len):
        calls.append((text, replace_len))

    return paste, calls


def test_happy_path_transforms_and_pastes():
    paste, calls = _spy_paste()
    res = voice_edit.run(
        "gör det formellt",
        read_selection=lambda: "tja läget",
        transform=lambda sel, ins: "God dag.",
        paste_replacement=paste,
    )
    assert res == voice_edit.OK
    assert calls == [("God dag.", 0)]


def test_no_instruction_is_noop():
    paste, calls = _spy_paste()
    res = voice_edit.run(
        "   ",
        read_selection=lambda: "något",
        transform=lambda sel, ins: "x",
        paste_replacement=paste,
    )
    assert res == voice_edit.NO_INSTRUCTION
    assert calls == []


def test_no_selection_does_not_paste():
    paste, calls = _spy_paste()
    res = voice_edit.run(
        "kortare",
        read_selection=lambda: "",
        transform=lambda sel, ins: "ignored",
        paste_replacement=paste,
    )
    assert res == voice_edit.NO_SELECTION
    assert calls == []


def test_unchanged_result_does_not_paste():
    # instruct() returns the input unchanged on failure / no-op.
    paste, calls = _spy_paste()
    res = voice_edit.run(
        "gör inget",
        read_selection=lambda: "samma text",
        transform=lambda sel, ins: "samma text",
        paste_replacement=paste,
    )
    assert res == voice_edit.UNCHANGED
    assert calls == []


def test_transform_exception_is_caught():
    paste, calls = _spy_paste()

    def boom(sel, ins):
        raise RuntimeError("provider down")

    res = voice_edit.run(
        "översätt",
        read_selection=lambda: "hej",
        transform=boom,
        paste_replacement=paste,
    )
    assert res == voice_edit.FAILED
    assert calls == []


def test_instruction_passed_through_to_transform():
    seen = {}

    def transform(sel, ins):
        seen["sel"] = sel
        seen["ins"] = ins
        return "RESULT"

    paste, _ = _spy_paste()
    voice_edit.run(
        "  översätt till engelska  ",
        read_selection=lambda: "  hej på dig  ",
        transform=transform,
        paste_replacement=paste,
    )
    # Both selection and instruction are trimmed before reaching transform.
    assert seen == {"sel": "hej på dig", "ins": "översätt till engelska"}
