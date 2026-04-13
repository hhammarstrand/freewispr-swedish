import logging
import threading
import keyboard
import numpy as np

from audio import MicRecorder
from transcriber import Transcriber
from paste import paste_text
import snippets as snippet_module
import sounds

log = logging.getLogger("freewispr")

MIN_AUDIO_SAMPLES = 3200   # 0.2 s at 16 kHz — ignore accidental taps
MIN_RMS_THRESHOLD = 0.003  # Minimum RMS energy — reject near-silent recordings


class DictationMode:
    def __init__(self, transcriber: Transcriber, hotkey: str = "ctrl+space",
                 on_status=None, indicator=None, mic_device: str | None = None):
        self.transcriber = transcriber
        self.hotkey = hotkey
        self.recorder = MicRecorder(device_name=mic_device)
        self.on_status = on_status or (lambda msg: None)
        self.indicator = indicator
        self._active = False
        self._recording = False

        if "+" in self.hotkey:
            parts = self.hotkey.split("+")
            self._trigger_key = parts[-1]
            self._modifier = "+".join(parts[:-1])
        else:
            self._trigger_key = self.hotkey
            self._modifier = None

    # ------------------------------------------------------------------ public

    def start(self):
        self._active = True
        log.info("Hotkey: trigger='%s', modifier='%s'", self._trigger_key, self._modifier)
        keyboard.on_press_key(self._trigger_key, self._on_press, suppress=False)
        keyboard.on_release_key(self._trigger_key, self._on_release, suppress=False)
        self.on_status(f"Ready — hold {self.hotkey.upper()} to speak")

    def stop(self):
        self._active = False
        try:
            keyboard.unhook_all()
        except Exception:
            pass

    # ----------------------------------------------------------------- private

    def _modifier_held(self) -> bool:
        if not self._modifier:
            return True
        return keyboard.is_pressed(self._modifier)

    def _on_press(self, _):
        if self._active and not self._recording and self._modifier_held():
            try:
                self._recording = True
                self.recorder.start()
                sounds.play_start()
                self.on_status("Lyssnar…")
                if self.indicator:
                    self.indicator.show("Lyssnar…", state="listen")
            except Exception as e:
                self._recording = False
                log.error("Mic start error: %s", e, exc_info=True)
                sounds.play_error()
                if self.indicator:
                    self.indicator.show(f"Mikrofonfel: {e}", state="error")
                    self.indicator.hide(delay_ms=3000)

    def _on_release(self, _):
        if self._active and self._recording:
            self._recording = False
            sounds.play_stop()
            try:
                audio = self.recorder.stop()
            except Exception as e:
                log.error("Audio stop error: %s", e, exc_info=True)
                sounds.play_error()
                if self.indicator:
                    self.indicator.show("Mikrofonfel", state="error")
                    self.indicator.hide(delay_ms=2500)
                self.on_status(f"Klar — håll {self.hotkey.upper()}")
                return
            log.info("Audio samples: %d, peak: %.4f", len(audio), np.abs(audio).max())
            if len(audio) < MIN_AUDIO_SAMPLES:
                log.info("Inspelning för kort (%d samples), ignorerar", len(audio))
                self.on_status(f"Klar — håll {self.hotkey.upper()}")
                if self.indicator:
                    self.indicator.hide(delay_ms=0)
                return

            # Reject near-silent recordings (accidental taps, muted mic)
            rms = float(np.sqrt(np.mean(audio ** 2)))
            if rms < MIN_RMS_THRESHOLD:
                log.info("Inspelning för tyst (RMS=%.5f < %.5f), ignorerar", rms, MIN_RMS_THRESHOLD)
                self.on_status(f"Inget hördes — håll {self.hotkey.upper()}")
                if self.indicator:
                    self.indicator.show("Inget hördes", state="error")
                    self.indicator.hide(delay_ms=1500)
                return
            self.on_status("Transkriberar…")
            if self.indicator:
                self.indicator.show("Transkriberar…", state="transcribe")
            threading.Thread(target=self._transcribe, args=(audio,), daemon=True).start()

    def _transcribe(self, audio: np.ndarray):
        log.info("Transkriberar %d samples...", len(audio))
        try:
            text = self.transcriber.transcribe(audio)
            # Apply snippet expansion — if full text is a trigger, replace it
            text = snippet_module.expand(text)
            log.info("Resultat: '%s'", text)
            if text.strip():
                paste_text(text)
                self.on_status(f"Klistrad — håll {self.hotkey.upper()} igen")
                if self.indicator:
                    self.indicator.show("Klistrad", state="done")
                    self.indicator.hide(delay_ms=1800)
            else:
                self.on_status(f"Inget hördes — håll {self.hotkey.upper()}")
                if self.indicator:
                    self.indicator.show("Inget hördes", state="error")
                    self.indicator.hide(delay_ms=1500)
        except Exception as e:
            log.error("Transkribering misslyckades: %s", e, exc_info=True)
            self.on_status(f"Fel — håll {self.hotkey.upper()}")
            if self.indicator:
                self.indicator.show(f"Fel: {e}", state="error")
                self.indicator.hide(delay_ms=5000)
