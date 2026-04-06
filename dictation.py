import threading
import keyboard
import numpy as np

from audio import MicRecorder
from transcriber import Transcriber
from paste import paste_text

MIN_AUDIO_SAMPLES = 3200  # 0.2 s at 16 kHz — ignore accidental taps


class DictationMode:
    def __init__(self, transcriber: Transcriber, hotkey: str = "ctrl+space", on_status=None):
        self.transcriber = transcriber
        self.hotkey = hotkey
        self.recorder = MicRecorder()
        self.on_status = on_status or (lambda msg: None)
        self._active = False
        self._recording = False

        # Parse combo vs single key
        if "+" in self.hotkey:
            parts = self.hotkey.split("+")
            self._trigger_key = parts[-1]      # e.g. "space"
            self._modifier = "+".join(parts[:-1])  # e.g. "ctrl"
        else:
            self._trigger_key = self.hotkey
            self._modifier = None

    # ------------------------------------------------------------------ public

    def start(self):
        self._active = True
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
            self._recording = True
            self.recorder.start()
            self.on_status("Listening…")

    def _on_release(self, _):
        if self._active and self._recording:
            self._recording = False
            audio = self.recorder.stop()
            if len(audio) < MIN_AUDIO_SAMPLES:
                self.on_status(f"Ready — hold {self.hotkey.upper()} to speak")
                return
            self.on_status("Transcribing…")
            threading.Thread(target=self._transcribe, args=(audio,), daemon=True).start()

    def _transcribe(self, audio: np.ndarray):
        print("Transcribing...", flush=True)
        text = self.transcriber.transcribe(audio)
        print(f"Result: '{text}'", flush=True)
        if text.strip():
            paste_text(text)
            self.on_status(f"Pasted — hold {self.hotkey.upper()} to speak again")
        else:
            self.on_status(f"Nothing detected — hold {self.hotkey.upper()} to speak")
