"""
Tkinter-based windows for freewispr.
- MeetingWindow  : transcript view + start/stop controls
- SettingsWindow : hotkey, model, language, API key
"""
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox, filedialog
from pathlib import Path
import subprocess
import sys


BG = "#0f0f0f"
BG2 = "#1a1a1a"
ACC = "#7c5cfc"          # purple accent
ACC2 = "#5a3fd4"
FG = "#e8e8e8"
FG2 = "#888"
FONT = ("Segoe UI", 10)
FONT_MONO = ("Consolas", 10)


def _style(root):
    s = ttk.Style(root)
    s.theme_use("clam")
    s.configure("TButton", background=ACC, foreground=FG, font=FONT, relief="flat", padding=6)
    s.map("TButton", background=[("active", ACC2)])
    s.configure("Stop.TButton", background="#c0392b", foreground=FG, font=FONT, relief="flat", padding=6)
    s.map("Stop.TButton", background=[("active", "#96281b")])
    s.configure("TLabel", background=BG, foreground=FG, font=FONT)
    s.configure("Sub.TLabel", background=BG, foreground=FG2, font=("Segoe UI", 9))
    s.configure("TFrame", background=BG)
    s.configure("TEntry", fieldbackground=BG2, foreground=FG, font=FONT)
    s.configure("TCombobox", fieldbackground=BG2, foreground=FG, font=FONT)


# --------------------------------------------------------------------------- #
#  Meeting window                                                              #
# --------------------------------------------------------------------------- #

class MeetingWindow:
    def __init__(self, meeting_mode, on_close=None):
        self.meeting = meeting_mode
        self.on_close = on_close
        self._running = False

        self.root = tk.Toplevel()
        self.root.title("freewispr — Meeting")
        self.root.geometry("680x520")
        self.root.configure(bg=BG)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        _style(self.root)

        self._build()

    def _build(self):
        # Header
        hdr = ttk.Frame(self.root)
        hdr.pack(fill="x", padx=16, pady=(16, 4))
        ttk.Label(hdr, text="Meeting Transcription", font=("Segoe UI", 13, "bold")).pack(side="left")
        self._status_var = tk.StringVar(value="Ready to record")
        ttk.Label(hdr, textvariable=self._status_var, style="Sub.TLabel").pack(side="right")

        # Transcript area
        self._text = scrolledtext.ScrolledText(
            self.root, bg=BG2, fg=FG, font=FONT_MONO,
            relief="flat", borderwidth=0, wrap="word",
            insertbackground=FG,
        )
        self._text.pack(fill="both", expand=True, padx=16, pady=8)
        self._text.configure(state="disabled")

        # Controls
        ctrl = ttk.Frame(self.root)
        ctrl.pack(fill="x", padx=16, pady=(0, 16))
        self._start_btn = ttk.Button(ctrl, text="Start Recording", command=self._toggle)
        self._start_btn.pack(side="left", padx=(0, 8))
        ttk.Button(ctrl, text="Save Transcript", command=self._save).pack(side="left", padx=(0, 8))
        ttk.Button(ctrl, text="Clear", command=self._clear).pack(side="left")
        self._open_btn = ttk.Button(ctrl, text="Open Folder", command=self._open_folder)
        self._open_btn.pack(side="right")

    # ------------------------------------------------------------------ actions

    def _toggle(self):
        if not self._running:
            self._running = True
            self._start_btn.configure(text="Stop Recording", style="Stop.TButton")
            self.meeting.on_line = self._add_line
            self.meeting.on_status = self._set_status
            self.meeting.start()
        else:
            self._running = False
            self._start_btn.configure(text="Start Recording", style="TButton")
            path = self.meeting.stop()
            self._set_status(f"Saved → {path}" if path else "Stopped")

    def _add_line(self, line: str):
        self.root.after(0, self._insert_line, line)

    def _insert_line(self, line: str):
        self._text.configure(state="normal")
        self._text.insert("end", line + "\n")
        self._text.see("end")
        self._text.configure(state="disabled")

    def _set_status(self, msg: str):
        self.root.after(0, lambda: self._status_var.set(msg))

    def _save(self):
        transcript = self.meeting.get_transcript()
        if not transcript.strip():
            messagebox.showinfo("freewispr", "No transcript yet.")
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".txt",
            filetypes=[("Text files", "*.txt")],
            initialfile="meeting_transcript.txt",
        )
        if path:
            with open(path, "w", encoding="utf-8") as f:
                f.write(transcript)
            messagebox.showinfo("freewispr", f"Saved to {path}")

    def _clear(self):
        self._text.configure(state="normal")
        self._text.delete("1.0", "end")
        self._text.configure(state="disabled")

    def _open_folder(self):
        folder = Path.home() / ".freewispr" / "transcripts"
        folder.mkdir(parents=True, exist_ok=True)
        subprocess.Popen(f'explorer "{folder}"')

    def _on_close(self):
        if self._running:
            self._running = False
            self.meeting.stop()
        self.root.destroy()
        if self.on_close:
            self.on_close()


# --------------------------------------------------------------------------- #
#  Settings window                                                             #
# --------------------------------------------------------------------------- #

class SettingsWindow:
    def __init__(self, config: dict, on_save=None):
        self.cfg = config.copy()
        self.on_save = on_save

        self.root = tk.Toplevel()
        self.root.title("freewispr — Settings")
        self.root.geometry("420x360")
        self.root.resizable(False, False)
        self.root.configure(bg=BG)
        _style(self.root)

        self._build()

    def _build(self):
        pad = {"padx": 20, "pady": 6}

        ttk.Label(self.root, text="Settings", font=("Segoe UI", 13, "bold")).pack(anchor="w", **pad)

        # Hotkey
        ttk.Label(self.root, text="Dictation hotkey").pack(anchor="w", padx=20, pady=(12, 0))
        self._hotkey_var = tk.StringVar(value=self.cfg.get("hotkey", "right ctrl"))
        ttk.Entry(self.root, textvariable=self._hotkey_var, width=30).pack(anchor="w", **pad)
        ttk.Label(self.root, text="e.g. right ctrl, F9, alt+shift", style="Sub.TLabel").pack(anchor="w", padx=20, pady=(0, 4))

        # Model size
        ttk.Label(self.root, text="Whisper model").pack(anchor="w", padx=20, pady=(8, 0))
        self._model_var = tk.StringVar(value=self.cfg.get("model_size", "base"))
        model_cb = ttk.Combobox(self.root, textvariable=self._model_var,
                                values=["tiny", "base", "small"], state="readonly", width=20)
        model_cb.pack(anchor="w", **pad)
        ttk.Label(self.root, text="tiny = fastest, small = most accurate (slow on CPU)",
                  style="Sub.TLabel").pack(anchor="w", padx=20, pady=(0, 4))

        # Language
        ttk.Label(self.root, text="Language").pack(anchor="w", padx=20, pady=(8, 0))
        self._lang_var = tk.StringVar(value=self.cfg.get("language", "en"))
        ttk.Entry(self.root, textvariable=self._lang_var, width=10).pack(anchor="w", **pad)
        ttk.Label(self.root, text="ISO 639-1 code: en, es, fr, de, hi…",
                  style="Sub.TLabel").pack(anchor="w", padx=20, pady=(0, 4))

        # API key (for optional summaries)
        ttk.Label(self.root, text="OpenAI API key (optional, for summaries)").pack(anchor="w", padx=20, pady=(8, 0))
        self._api_var = tk.StringVar(value=self.cfg.get("api_key", ""))
        ttk.Entry(self.root, textvariable=self._api_var, show="*", width=40).pack(anchor="w", **pad)

        # Save
        ttk.Button(self.root, text="Save", command=self._save).pack(anchor="e", padx=20, pady=16)

    def _save(self):
        self.cfg["hotkey"] = self._hotkey_var.get().strip()
        self.cfg["model_size"] = self._model_var.get()
        self.cfg["language"] = self._lang_var.get().strip()
        self.cfg["api_key"] = self._api_var.get().strip()
        if self.on_save:
            self.on_save(self.cfg)
        self.root.destroy()
