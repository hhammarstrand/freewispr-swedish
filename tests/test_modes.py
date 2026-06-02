"""KP2: user-defined modes (Superwhisper-style), resolving to Profiles."""
import modes


def _isolate(tmp_path, monkeypatch):
    # Point the module's store at a throwaway file.
    from json_store import JsonCache
    monkeypatch.setattr(modes, "_store", JsonCache(tmp_path / "modes.json",
                                                   default={}))


def test_add_load_roundtrip(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    modes.add("Juridik", "formell juridisk ton", polish=True, capitalize=True)
    data = modes.load()
    assert data["Juridik"]["description"] == "formell juridisk ton"
    assert data["Juridik"]["polish"] is True


def test_get_profile_returns_user_mode(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    modes.add("Anteckning", "kort och koncis", polish=True, capitalize=False)
    prof = modes.get_profile("Anteckning")
    assert prof.description == "kort och koncis"
    assert prof.capitalize is False
    assert prof.polish is True


def test_unknown_key_falls_back_to_default(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    from context_win import PROFILES
    assert modes.get_profile("nonexistent") == PROFILES["default"]


def test_builtin_key_resolves_without_user_mode(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    from context_win import PROFILES
    assert modes.get_profile("code") == PROFILES["code"]


def test_user_mode_shadows_builtin(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    modes.add("email", "min egen mejl-ton", polish=True, capitalize=True)
    assert modes.get_profile("email").description == "min egen mejl-ton"


def test_remove(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    modes.add("Tillfälligt", "x")
    modes.remove("Tillfälligt")
    assert "Tillfälligt" not in modes.load()


def test_malformed_record_ignored(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    # Write junk straight through the store; load() must not crash.
    modes._store.save({"bad": "not-a-dict", "ok": {"description": "fin ton"}})
    data = modes.load()
    assert "bad" not in data
    assert data["ok"]["description"] == "fin ton"


def test_all_mode_keys_includes_builtins_and_user(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    modes.add("Egen", "x")
    keys = modes.all_mode_keys()
    assert "default" in keys and "code" in keys and "Egen" in keys
