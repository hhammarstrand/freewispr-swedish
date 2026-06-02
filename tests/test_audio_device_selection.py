"""Teams-like input-device selection for MicRecorder.

Verifies the auto-select path: skips loopback/phantom endpoints, follows the
Windows default input device, and re-probes when that default changes between
recordings so swapping mics (laptop ↔ Yealink ↔ AirPods) just works.
"""
from __future__ import annotations

import audio


# Fake PortAudio tables. hostapi indices map into HOSTAPIS.
HOSTAPIS = [
    {"name": "MME"},
    {"name": "Windows DirectSound"},
    {"name": "Windows WASAPI"},
    {"name": "Windows WDM-KS"},
]
DEVICES = [
    # 0: built-in Intel mic via WASAPI (best API rank)
    {"name": "Mikrofonuppsättning (Intel Smart Sound)",
     "max_input_channels": 4, "hostapi": 2, "default_samplerate": 48000},
    # 1: real dock mic, WDM-KS only
    {"name": "Mikrofon (ThinkPad Dock USB Audio)",
     "max_input_channels": 1, "hostapi": 3, "default_samplerate": 44100},
    # 2: loopback — must be skipped in auto
    {"name": "Stereo mix (Realtek HD Audio Stereo input)",
     "max_input_channels": 2, "hostapi": 3, "default_samplerate": 48000},
    # 3: phantom endpoint — must be skipped
    {"name": "Mikrofonuppsättning 1 ()",
     "max_input_channels": 2, "hostapi": 3, "default_samplerate": 48000},
    # 4: phantom endpoint — must be skipped
    {"name": "Input ()",
     "max_input_channels": 2, "hostapi": 3, "default_samplerate": 44100},
    # 5: real Realtek mic, WDM-KS
    {"name": "Mikrofon (Realtek HD Audio Mic input)",
     "max_input_channels": 2, "hostapi": 3, "default_samplerate": 44100},
]


def _patch_tables(monkeypatch, default_name=None):
    monkeypatch.setattr(audio, "_devices", lambda: DEVICES)
    monkeypatch.setattr(audio, "_hostapis", lambda: HOSTAPIS)
    monkeypatch.setattr(audio, "_default_input_name", lambda: default_name)


def _names_for(candidates):
    return [DEVICES[c[0]]["name"] for c in candidates]


# --- blacklist helper ----------------------------------------------------

def test_is_blacklisted_input_flags_loopback_and_phantoms():
    bl = audio._is_blacklisted_input
    assert bl("Stereo mix (Realtek HD Audio Stereo input)")
    assert bl("Mikrofonuppsättning 1 ()")
    assert bl("Input ()")
    assert bl("")
    assert bl("   ")


def test_is_blacklisted_input_allows_real_mics():
    bl = audio._is_blacklisted_input
    assert not bl("Mikrofon (ThinkPad Dock USB Audio)")
    assert not bl("Mikrofonuppsättning (Intel Smart Sound)")
    assert not bl("Mikrofon (Realtek HD Audio Mic input)")


# --- candidate building --------------------------------------------------

def test_build_candidates_skips_loopback_and_phantoms(monkeypatch):
    _patch_tables(monkeypatch, default_name=None)
    rec = audio.MicRecorder(device=None)
    names = _names_for(rec._build_candidates())
    assert "Stereo mix (Realtek HD Audio Stereo input)" not in names
    assert "Mikrofonuppsättning 1 ()" not in names
    assert "Input ()" not in names
    # Real mics survive.
    assert "Mikrofon (ThinkPad Dock USB Audio)" in names
    assert "Mikrofonuppsättning (Intel Smart Sound)" in names


def test_build_candidates_without_default_prefers_best_api(monkeypatch):
    _patch_tables(monkeypatch, default_name=None)
    rec = audio.MicRecorder(device=None)
    cands = rec._build_candidates()
    # No default set → WASAPI (best rank) Intel mic comes first.
    assert cands[0][0] == 0


def test_build_candidates_follows_windows_default(monkeypatch):
    # Default = the dock mic, even though Intel/WASAPI has a better API rank.
    _patch_tables(monkeypatch,
                  default_name="Mikrofon (ThinkPad Dock USB Audio)")
    rec = audio.MicRecorder(device=None)
    cands = rec._build_candidates()
    assert cands[0][0] == 1  # default device tried first


def test_explicit_device_not_filtered_by_blacklist(monkeypatch):
    # A user who deliberately selects "Stereo Mix" still gets it.
    _patch_tables(monkeypatch, default_name=None)
    rec = audio.MicRecorder(device={"name": "Stereo mix", "api": None,
                                     "index": None})
    monkeypatch.setattr(audio, "_find_device_by_name",
                        lambda name: [{"index": 2, "rate": 48000,
                                       "channels": 2, "api": "Windows WDM-KS",
                                       "_rank": 99}])
    names = _names_for(rec._build_candidates())
    assert "Stereo mix (Realtek HD Audio Stereo input)" in names


# --- start() re-probe on default change ---------------------------------

def _patch_start_io(monkeypatch, opened):
    """Make _try_start succeed and record the device index it opened."""
    class _FakeStream:
        def start(self):
            pass

    def fake_try_start(device, rate, channels, callback):
        opened.append(device)
        return _FakeStream()

    monkeypatch.setattr(audio, "_try_start", fake_try_start)
    monkeypatch.setattr(audio, "_reinit_portaudio", lambda: None)
    monkeypatch.setattr(audio, "invalidate_device_cache", lambda: None)


def test_start_uses_cached_spec_when_default_unchanged(monkeypatch):
    _patch_tables(monkeypatch, default_name=None)
    monkeypatch.setattr(audio, "_default_input_index", lambda: 1)
    opened = []
    _patch_start_io(monkeypatch, opened)

    rec = audio.MicRecorder(device=None)
    rec._cached_spec = (5, 44100, 1, "cached Realtek")
    rec._auto_default_index = 1  # same as current default

    probed = {"called": False}
    orig = rec._build_candidates
    monkeypatch.setattr(rec, "_build_candidates",
                        lambda: (probed.__setitem__("called", True) or orig()))

    rec.start()
    assert opened == [5]          # opened the cached device
    assert probed["called"] is False  # fast path, no re-probe


def test_start_reprobes_when_default_changed(monkeypatch):
    _patch_tables(monkeypatch,
                  default_name="Mikrofon (ThinkPad Dock USB Audio)")
    monkeypatch.setattr(audio, "_default_input_index", lambda: 1)
    opened = []
    _patch_start_io(monkeypatch, opened)

    rec = audio.MicRecorder(device=None)
    rec._cached_spec = (5, 44100, 1, "stale Realtek")
    rec._auto_default_index = 5   # default *was* device 5, now it's 1

    rec.start()
    # Cache dropped → fresh probe → opens the new default (dock mic, idx 1).
    assert opened == [1]
    assert rec._auto_default_index == 1
