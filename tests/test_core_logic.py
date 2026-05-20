import importlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


def reload_with_home(module_name: str, tmp_path: Path):
    module = importlib.import_module(module_name)
    module._FILE = tmp_path / f"{module_name}.json"
    module._cache = None
    module._cache_mtime = 0.0
    return module


@pytest.fixture
def fake_transcriber_deps(monkeypatch):
    monkeypatch.setitem(
        sys.modules,
        "faster_whisper",
        SimpleNamespace(WhisperModel=object),
    )


def test_transcriber_postprocess_cleans_common_artifacts(fake_transcriber_deps):
    transcriber = importlib.import_module("transcriber")

    result = transcriber._postprocess("  , hej  hej ,du!!!  ")

    assert result == "Hej, du!"


def test_corrections_apply_case_insensitive_whole_words(tmp_path):
    corrections = reload_with_home("corrections", tmp_path)
    corrections.save({"motte": "möte"})

    result = corrections.apply("Motte idag, men motteplats ska vara kvar")

    assert result == "möte idag, men motteplats ska vara kvar"


def test_snippets_expand_exact_trigger_only(tmp_path):
    snippets = reload_with_home("snippets", tmp_path)
    snippets.save({"mvb": "Med vänliga hälsningar"})

    assert snippets.expand(" MVB ") == "Med vänliga hälsningar"
    assert snippets.expand("mvb tack") == "mvb tack"


def test_auto_learn_extracts_same_length_word_diffs():
    auto_learn = importlib.import_module("auto_learn")

    diffs = auto_learn._extract_word_diffs(
        "Jag gar till motte.",
        "Jag går till möte.",
    )

    assert diffs == [("gar", "går"), ("motte", "möte")]


def test_config_save_uses_keyring_and_excludes_secret(tmp_path, monkeypatch):
    config = importlib.import_module("config")
    secrets = {}

    config.CONFIG_DIR = tmp_path
    config.CONFIG_FILE = tmp_path / "config.json"
    config.keyring = SimpleNamespace(
        get_password=lambda service, username: secrets.get((service, username)),
        set_password=lambda service, username, value: secrets.__setitem__((service, username), value),
        delete_password=lambda service, username: secrets.pop((service, username), None),
    )

    config.save({**config.DEFAULTS, "llm_api_key": "secret-token", "model_size": "tiny"})

    saved = json.loads(config.CONFIG_FILE.read_text(encoding="utf-8"))
    loaded = config.load()

    assert "llm_api_key" not in saved
    assert loaded["llm_api_key"] == "secret-token"
    assert loaded["model_size"] == "tiny"


def test_config_load_migrates_legacy_secret_off_disk(tmp_path):
    config = importlib.import_module("config")
    secrets = {}

    config.CONFIG_DIR = tmp_path
    config.CONFIG_FILE = tmp_path / "config.json"
    config.CONFIG_FILE.write_text(
        json.dumps({"model_size": "base", "llm_api_key": "legacy-secret"}),
        encoding="utf-8",
    )
    config.keyring = SimpleNamespace(
        get_password=lambda service, username: secrets.get((service, username)),
        set_password=lambda service, username, value: secrets.__setitem__((service, username), value),
        delete_password=lambda service, username: secrets.pop((service, username), None),
    )

    loaded = config.load()
    saved = json.loads(config.CONFIG_FILE.read_text(encoding="utf-8"))

    assert loaded["llm_api_key"] == "legacy-secret"
    assert "llm_api_key" not in saved
    assert saved["model_size"] == "base"


def test_llm_polish_falls_back_without_logging_body(monkeypatch, caplog):
    llm_polish = importlib.import_module("llm_polish")

    def raise_http_error(*args, **kwargs):
        raise llm_polish.urllib.error.HTTPError(
            url="https://example.test",
            code=400,
            msg="bad request",
            hdrs=None,
            fp=SimpleNamespace(read=lambda: b"echoed sensitive text"),
        )

    monkeypatch.setattr(llm_polish, "_call_api", raise_http_error)

    with caplog.at_level("WARNING"):
        result = llm_polish.polish("hemlig text", "token")

    assert result.text == "hemlig text"
    assert not result.changed
    assert "hemlig text" not in caplog.text
    assert "echoed sensitive text" not in caplog.text


# --------------------------------------------------------------------------- #
#  New regression tests for refactors landed in this round.
# --------------------------------------------------------------------------- #

def test_corrections_apply_cache_invalidates_on_mtime(tmp_path, monkeypatch):
    """Editing the corrections file should invalidate the compiled-regex cache."""
    corrections = reload_with_home("corrections", tmp_path)
    corrections.save({"motte": "möte"})
    assert corrections.apply("motte") == "möte"

    # Save a new mapping; mtime advances so the cache must be rebuilt.
    # Force a strictly newer mtime to defeat low filesystem resolution.
    corrections.save({"gar": "går"})
    new_mtime = corrections.mtime() + 1
    import os
    os.utime(corrections._FILE, (new_mtime, new_mtime))

    assert corrections.apply("gar") == "går"
    # Old mapping no longer applies after replacement.
    assert corrections.apply("motte") == "motte"


def test_auto_learn_extracts_single_word_replacements_only():
    """Multi-word edits (insertions, deletions) must not yield bogus pairs."""
    auto_learn = importlib.import_module("auto_learn")

    # Length differs — naive zip would invent garbage; SequenceMatcher should
    # only emit the genuine single-word replace.
    diffs = auto_learn._extract_word_diffs(
        "Jag gar till skolan idag",
        "Jag går till skolan",
    )
    assert ("gar", "går") in diffs
    # The trailing deletion of "idag" must not appear as a replacement.
    assert all(b != "" for _, b in diffs)


def test_dictation_parse_hotkey_splits_modifiers_and_trigger():
    """_parse_hotkey must return ("space", ("ctrl", "shift")) for chorded hotkeys."""
    import sys as _sys
    from types import SimpleNamespace as _NS
    # Stub out the `keyboard` module so dictation imports cleanly in CI envs
    # without the real C extension installed.
    _sys.modules.setdefault(
        "keyboard",
        _NS(
            parse_hotkey=lambda s: ((1,), (2,)),  # tuple shape only matters
            is_pressed=lambda key: False,
            add_hotkey=lambda *a, **kw: None,
            on_release_key=lambda *a, **kw: None,
            unhook=lambda h: None,
            send=lambda *a, **kw: None,
        ),
    )
    _sys.modules.setdefault("sounds", _NS(play_start=lambda: None, play_stop=lambda: None))
    dictation = importlib.import_module("dictation")

    trigger, modifiers = dictation._parse_hotkey("ctrl+shift+space")
    assert trigger == "space"
    assert set(modifiers) == {"ctrl", "shift"}

    trigger, modifiers = dictation._parse_hotkey("f9")
    assert trigger == "f9"
    assert modifiers == ()


# --------------------------------------------------------------------------- #
#  Fas 1: modifier normalisation + dictation off-hook pipeline regression.
# --------------------------------------------------------------------------- #

def test_modifiers_normalize_aliases():
    """All aliases for the Windows key must collapse to 'windows'."""
    modifiers = importlib.import_module("modifiers")
    assert modifiers.normalize("win") == "windows"
    assert modifiers.normalize("Cmd") == "windows"
    assert modifiers.normalize("SUPER") == "windows"
    assert modifiers.normalize("control") == "ctrl"
    assert modifiers.normalize("ctrl") == "ctrl"
    assert modifiers.normalize("nonsense") is None
    assert modifiers.normalize("") is None


def test_modifiers_normalize_all_dedupes_and_preserves_order():
    modifiers = importlib.import_module("modifiers")
    result = modifiers.normalize_all(["Ctrl", "shift", "control", "win", "cmd"])
    # ctrl/control collapse; win/cmd collapse to windows.
    assert result == ("ctrl", "shift", "windows")


def test_modifiers_is_modifier():
    modifiers = importlib.import_module("modifiers")
    assert modifiers.is_modifier("alt")
    assert modifiers.is_modifier("CMD")
    assert not modifiers.is_modifier("space")


def test_dictation_parse_hotkey_normalises_cmd_to_windows():
    """A hotkey with 'cmd' must yield canonical 'windows' so paste releases it."""
    import sys as _sys
    from types import SimpleNamespace as _NS
    _sys.modules.setdefault(
        "keyboard",
        _NS(
            parse_hotkey=lambda s: ((1,), (2,)),
            is_pressed=lambda key: False,
            add_hotkey=lambda *a, **kw: None,
            on_press_key=lambda *a, **kw: None,
            on_release_key=lambda *a, **kw: None,
            unhook=lambda h: None,
            send=lambda *a, **kw: None,
            release=lambda k: None,
        ),
    )
    _sys.modules.setdefault("sounds", _NS(play_start=lambda: None,
                                          play_stop=lambda: None,
                                          play_error=lambda: None))
    dictation = importlib.import_module("dictation")

    trigger, modifiers = dictation._parse_hotkey("cmd+shift+space")
    assert trigger == "space"
    # 'cmd' must be normalised to 'windows' so paste._release_modifiers
    # actually releases the held Win key after Ctrl+V.
    assert set(modifiers) == {"windows", "shift"}


def test_audio_finalize_handles_empty_input():
    """finalize_audio must gracefully return an empty array for zero input."""
    import numpy as np
    audio = importlib.import_module("audio")
    result = audio.finalize_audio(np.empty(0, dtype=np.float32), 1, 16000)
    assert result.shape == (0,)
    assert result.dtype.name == "float32"


def test_audio_finalize_downmixes_stereo_via_first_channel():
    """Multi-channel input must downmix to mono using the first channel."""
    import numpy as np
    audio = importlib.import_module("audio")
    # Stereo buffer: left channel = 1.0, right channel = 0.0
    stereo = np.array([[1.0, 0.0], [1.0, 0.0], [1.0, 0.0], [1.0, 0.0]],
                      dtype=np.float32)
    result = audio.finalize_audio(stereo, 2, audio.TARGET_RATE)
    assert result.shape == (4,)
    assert np.allclose(result, 1.0)


def test_corrections_apply_master_regex_handles_many_entries(tmp_path):
    """Master-regex path must apply all corrections in a single pass."""
    corrections = reload_with_home("corrections", tmp_path)
    mapping = {
        "motte": "möte",
        "gar": "går",
        "fika rasten": "fikarasten",
    }
    corrections.save(mapping)
    # Longest key first ensures multi-word "fika rasten" wins over individual
    # words that might overlap.
    result = corrections.apply("Jag gar pa motte under fika rasten idag")
    assert result == "Jag går pa möte under fikarasten idag"


def test_corrections_apply_empty_dictionary_is_noop(tmp_path):
    corrections = reload_with_home("corrections", tmp_path)
    corrections.save({})
    assert corrections.apply("oförändrad text") == "oförändrad text"

