"""
Flow-läge (AP6, valfritt) — kontinuerlig diktering över pauser.

I stället för push-to-talk spelar Flow-läget in löpande och delar upp talet i
yttranden vid tystnadspauser; varje yttrande transkriberas och klistras in
(append) medan inspelningen fortsätter. **Endast lokal** transkribering stöds
initialt (ingen audio skickas till en remote-leverantör i en bakgrundsloop).

Tydlig start/stopp-toggle via :meth:`toggle` (tray-meny i ``main.py``).

Segmenteringslogiken (:func:`split_on_silence`) är en ren funktion och därför
enkel att testa; själva ljudloopen är best-effort runtime-kod.
"""
from __future__ import annotations

import logging
import threading
import time

import numpy as np

from audio import MicRecorder, finalize_audio
from paste import paste_text

log = logging.getLogger("freewispr")

_WIN_S = 0.05  # 50 ms analysis window for silence detection


def split_on_silence(audio: np.ndarray, rate: int,
                     min_rms: float = 0.003,
                     min_silence_s: float = 0.6,
                     min_chunk_s: float = 0.3) -> list[np.ndarray]:
    """Split a finalized mono float32 array into utterance chunks on silence.

    Pure function. Returns a list of audio slices, each a voiced utterance with
    short internal pauses kept but separated where silence exceeds
    ``min_silence_s``. Chunks shorter than ``min_chunk_s`` are dropped.
    """
    if audio is None or audio.size == 0:
        return []
    win = max(1, int(rate * _WIN_S))
    n = audio.size

    voiced: list[bool] = []
    for start in range(0, n, win):
        seg = audio[start:start + win]
        r = float(np.sqrt(np.mean(seg * seg))) if seg.size else 0.0
        voiced.append(r >= min_rms)

    silence_limit = max(1, int(min_silence_s / _WIN_S))
    segs: list[tuple[int, int]] = []
    cur_start: int | None = None
    gap = 0
    for i, v in enumerate(voiced):
        if v:
            if cur_start is None:
                cur_start = i
            gap = 0
        elif cur_start is not None:
            gap += 1
            if gap >= silence_limit:
                segs.append((cur_start, i - gap + 1))
                cur_start = None
                gap = 0
    if cur_start is not None:
        segs.append((cur_start, len(voiced)))

    min_win = max(1, int(min_chunk_s / _WIN_S))
    out: list[np.ndarray] = []
    for s, e in segs:
        if e - s < min_win:
            continue
        a = audio[s * win:min(e * win, n)]
        if a.size:
            out.append(a)
    return out


class FlowMode:
    def __init__(self, transcriber, mic_device=None, on_status=None,
                 indicator=None, min_rms: float = 0.003,
                 pause_ms: int = 700, max_chunk_s: float = 20.0):
        self.transcriber = transcriber
        self.recorder = MicRecorder(device=mic_device)
        self.on_status = on_status or (lambda msg: None)
        self.indicator = indicator
        self.min_rms = min_rms
        self.pause_s = pause_ms / 1000.0
        self.max_chunk_s = max_chunk_s
        self._active = False
        self._thread: threading.Thread | None = None

    @property
    def active(self) -> bool:
        return self._active

    def toggle(self) -> bool:
        """Start if stopped, stop if started. Returns the new active state."""
        if self._active:
            self.stop()
        else:
            self.start()
        return self._active

    def start(self) -> None:
        if self._active:
            return
        if getattr(self.transcriber, "transcription_provider", "local") != "local":
            # Never stream microphone audio to a remote provider in a loop.
            self.on_status("Flow-läge stöder bara lokal transkribering")
            log.warning("Flow-läge kräver lokal transkribering")
            return
        self._active = True
        self._thread = threading.Thread(target=self._loop, name="flow",
                                        daemon=True)
        self._thread.start()
        self.on_status("Flow-läge på — prata fritt")
        if self.indicator:
            self.indicator.show("Flow-läge på", state="listen")

    def stop(self, wait: bool = True) -> None:
        self._active = False
        try:
            self.recorder.shutdown()
        except Exception:
            log.debug("recorder.shutdown() i flow stop misslyckades", exc_info=True)
        t = self._thread
        if wait and t and t.is_alive():
            t.join(timeout=5.0)
        self._thread = None
        self.on_status("Flow-läge av")
        if self.indicator:
            self.indicator.show("Flow-läge av", state="done")
            self.indicator.hide(delay_ms=1200)

    # ----------------------------------------------------------------- private

    def _loop(self) -> None:
        while self._active:
            try:
                audio, channels, rate = self._record_chunk()
            except Exception as e:
                log.error("Flow-inspelning fel: %s", e, exc_info=True)
                break
            if audio is None or audio.size == 0:
                continue
            try:
                self._process_audio(audio, channels, rate)
            except Exception as e:
                log.error("Flow-transkribering fel: %s", e, exc_info=True)

    def _record_chunk(self) -> tuple[np.ndarray, int, int]:
        """Record until a trailing silence gap or the max chunk length."""
        self.recorder.start()
        t0 = time.monotonic()
        had_speech = False
        silence_start: float | None = None
        while self._active:
            time.sleep(_WIN_S)
            level = getattr(self.recorder, "level", 0.0)
            if level >= self.min_rms:
                had_speech = True
                silence_start = None
            elif had_speech:
                if silence_start is None:
                    silence_start = time.monotonic()
                elif time.monotonic() - silence_start >= self.pause_s:
                    break
            if had_speech and (time.monotonic() - t0) >= self.max_chunk_s:
                break
        return self.recorder.stop_fast()

    def _process_audio(self, audio: np.ndarray, channels: int, rate: int) -> None:
        """Finalize → transcribe (local) → paste-append each utterance chunk."""
        final = finalize_audio(audio, channels, rate)
        if final.size == 0:
            return
        for chunk in split_on_silence(final, 16000, self.min_rms) or [final]:
            if not self._active:
                # still flush the in-flight chunk on stop
                pass
            text = self.transcriber.transcribe(chunk)
            if text and text.strip():
                paste_text(text)
