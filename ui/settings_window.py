"""
SettingsWindow — tabbed settings (hotkey, model, mic, GPU, LLM, transcription).
"""
import tkinter as tk
from tkinter import ttk, messagebox
import threading

import config as cfg_module

from ui.styles import BG, BG2, BG3, FG, FG2, ACC, ACC2, FONT, _style
from ui._ctk import ctk, _CTK_AVAILABLE
from ui.hotkey_capture import _HotkeyCapture


# -- lazy import helpers ---------------------------------------------------- #

def _llm_providers():
    """Lazy shim for the multi-provider LLM helpers (ctk Settings UI)."""
    from llm_polish import (
        PROVIDERS, provider_labels, provider_default_model,
        is_user_configurable_url, normalize_model, fetch_models, test_connection,
    )
    return {
        "PROVIDERS": PROVIDERS,
        "labels": provider_labels,
        "default_model": provider_default_model,
        "user_configurable_url": is_user_configurable_url,
        "normalize_model": normalize_model,
        "fetch_models": fetch_models,
        "test_connection": test_connection,
    }


def _tr_providers():
    """Lazy shim for remote-transcription provider helpers."""
    from remote_transcribe import (
        PROVIDERS, provider_labels, provider_default_model, test_connection,
    )
    return {
        "PROVIDERS": PROVIDERS,
        "labels": provider_labels,
        "default_model": provider_default_model,
        "test_connection": test_connection,
    }


# Model-size descriptions reused across both ctk and Tk fallback paths.
_MODEL_INFO = {
    "tiny":   "Snabbast, lägst kvalitet (~40 MB)",
    "base":   "Snabb, grundläggande kvalitet (~150 MB)",
    "small":  "Bra balans mellan hastighet och kvalitet (~500 MB)",
    "medium": "Hög kvalitet, långsammare (~1.5 GB)",
    "large":  "Bästa kvalitet, kräver mer minne (~3 GB)",
}


class SettingsWindow:
    """Tabbed settings window.

    Public contract: ``SettingsWindow(config, on_save=callable)``. The callable
    receives the new config dict and may return ``False`` to veto the save
    (e.g. when the model reload pipeline is busy).
    """

    def __init__(self, config: dict, on_save=None):
        self.cfg = config.copy()
        self.on_save = on_save

        if _CTK_AVAILABLE:
            # Follow Windows light/dark mode and use the neutral blue ctk
            # palette (no Swedish-flag accent in the UI itself — colour is
            # reserved for the tray/exe icon).
            try:
                ctk.set_appearance_mode("system")
                ctk.set_default_color_theme("blue")
            except Exception:
                pass
            self.root = ctk.CTkToplevel()
        else:
            self.root = tk.Toplevel()

        self.root.title("freewispr-swedish — Inställningar")
        self.root.geometry("560x720")
        self.root.minsize(540, 600)

        if not _CTK_AVAILABLE:
            self.root.configure(bg=BG)
            _style(self.root)

        # Shared StringVars / BooleanVars used across tabs. Declared up front
        # so the build methods can wire them without forward references.
        self._init_vars()
        self._build()

    # -- helpers ------------------------------------------------------------- #

    def _init_vars(self):
        c = self.cfg
        self._hotkey_var = tk.StringVar(value=c.get("hotkey", "ctrl+space"))
        self._indicator_follow_var = tk.BooleanVar(
            value=c.get("indicator_follow_mouse", True)
        )
        self._model_var = tk.StringVar(value=c.get("model_size", "small"))
        self._cuda_var = tk.BooleanVar(value=c.get("use_cuda", True))
        self._mic_var = tk.StringVar()  # filled in _build_general

        # LLM
        self._llm_enabled_var = tk.BooleanVar(value=c.get("llm_enabled", False))
        self._llm_provider_var = tk.StringVar(value=c.get("llm_provider", "github"))
        self._llm_model_var = tk.StringVar()  # filled when provider chosen
        self._llm_key_var = tk.StringVar()    # filled when provider chosen
        self._llm_base_url_var = tk.StringVar(
            value=c.get("llm_custom_base_url", "")
        )

        # Transcription
        self._tr_provider_var = tk.StringVar(
            value=c.get("transcription_provider", "local")
        )
        self._tr_model_var = tk.StringVar()
        self._tr_key_var = tk.StringVar()
        self._tr_base_url_var = tk.StringVar(
            value=c.get("transcription_custom_base_url", "")
        )
        self._tr_consent_var = tk.BooleanVar(
            value=c.get("transcription_privacy_accepted", False)
        )

    def _stringvar(self, value: str = "") -> tk.StringVar:
        v = tk.StringVar()
        v.set(value)
        return v

    def _frame(self, parent):
        """Container that adapts to ctk or plain tk."""
        if _CTK_AVAILABLE:
            return ctk.CTkFrame(parent, fg_color="transparent")
        return tk.Frame(parent, bg=BG)

    def _label(self, parent, text, **kw):
        if _CTK_AVAILABLE:
            return ctk.CTkLabel(parent, text=text, anchor="w", **kw)
        return tk.Label(parent, text=text, bg=BG2, fg=FG,
                        font=("Segoe UI", 10), anchor="w")

    def _heading(self, parent, text):
        if _CTK_AVAILABLE:
            return ctk.CTkLabel(
                parent, text=text, anchor="w",
                font=ctk.CTkFont(size=13, weight="bold"),
            )
        return tk.Label(parent, text=text, bg=BG, fg=FG,
                        font=("Segoe UI", 12, "bold"), anchor="w")

    def _hint(self, parent, text):
        if _CTK_AVAILABLE:
            lbl = ctk.CTkLabel(
                parent, text=text, anchor="w",
                font=ctk.CTkFont(size=11),
                text_color=("gray40", "gray60"),
                wraplength=460, justify="left",
            )
        else:
            lbl = tk.Label(parent, text=text, bg=BG, fg=FG2,
                           font=("Segoe UI", 9), anchor="w",
                           wraplength=460, justify="left")
        return lbl

    def _entry(self, parent, var, show=None, width=400):
        if _CTK_AVAILABLE:
            kw = {"textvariable": var, "width": width}
            if show:
                kw["show"] = show
            return ctk.CTkEntry(parent, **kw)
        kw = {"textvariable": var, "bg": BG3, "fg": FG, "font": FONT,
              "insertbackground": FG, "relief": "flat",
              "highlightthickness": 1, "highlightbackground": FG2,
              "highlightcolor": ACC}
        if show:
            kw["show"] = show
        return tk.Entry(parent, **kw)

    def _combobox(self, parent, var, values, width=240, command=None):
        if _CTK_AVAILABLE:
            return ctk.CTkComboBox(
                parent, variable=var, values=list(values),
                width=width, state="readonly", command=command,
            )
        combo = ttk.Combobox(parent, textvariable=var, values=list(values),
                             state="readonly", width=max(10, width // 8))
        if command is not None:
            combo.bind("<<ComboboxSelected>>", lambda _e: command(var.get()))
        return combo

    def _switch(self, parent, text, var):
        if _CTK_AVAILABLE:
            return ctk.CTkSwitch(parent, text=text, variable=var,
                                 onvalue=True, offvalue=False)
        # Reuse the old custom toggle in fallback mode.
        row = tk.Frame(parent, bg=BG, cursor="hand2")
        ind = tk.Label(row, bg=BG, fg=FG2, font=("Segoe UI", 11), width=2)
        ind.pack(side="left")
        lbl = tk.Label(row, text=text, bg=BG, fg=FG, anchor="w",
                       font=("Segoe UI", 10))
        lbl.pack(side="left", fill="x", expand=True)

        def _upd(*_):
            ind.configure(text="◉" if var.get() else "○",
                          fg=ACC if var.get() else FG2)
        _upd()
        var.trace_add("write", _upd)
        for w in (row, ind, lbl):
            w.bind("<Button-1>", lambda _e: var.set(not var.get()))
        return row

    def _button(self, parent, text, command, *, primary=False, danger=False):
        if _CTK_AVAILABLE:
            kw = {"text": text, "command": command}
            if danger:
                kw["fg_color"] = ("#c0392b", "#96281b")
                kw["hover_color"] = "#7c1f15"
            elif not primary:
                kw["fg_color"] = "transparent"
                kw["border_width"] = 1
                kw["text_color"] = ("gray20", "gray80")
            return ctk.CTkButton(parent, **kw)
        bg = "#c0392b" if danger else (ACC if primary else BG3)
        fg_ = FG if (primary or danger) else FG2
        return tk.Button(parent, text=text, bg=bg, fg=fg_, relief="flat",
                         font=("Segoe UI Semibold", 10) if primary else FONT,
                         activebackground=ACC2 if primary else "#333",
                         activeforeground=FG, padx=18, pady=6, cursor="hand2",
                         command=command)

    # -- build --------------------------------------------------------------- #

    def _build(self):
        outer = self._frame(self.root)
        outer.pack(fill="both", expand=True, padx=18, pady=18)

        self._heading(outer, "Inställningar").pack(anchor="w", pady=(0, 12))

        if _CTK_AVAILABLE:
            self._tabs = ctk.CTkTabview(outer, anchor="nw")
            self._tabs.pack(fill="both", expand=True)
            tab_general = self._tabs.add("Allmänt")
            tab_llm = self._tabs.add("LLM-granskning")
            tab_tr = self._tabs.add("Transkribering")
        else:
            self._tabs = ttk.Notebook(outer)
            self._tabs.pack(fill="both", expand=True)
            tab_general = ttk.Frame(self._tabs)
            tab_llm = ttk.Frame(self._tabs)
            tab_tr = ttk.Frame(self._tabs)
            self._tabs.add(tab_general, text="Allmänt")
            self._tabs.add(tab_llm, text="LLM-granskning")
            self._tabs.add(tab_tr, text="Transkribering")

        self._build_general(tab_general)
        self._build_llm(tab_llm)
        self._build_transcription(tab_tr)

        # Bottom button row
        btn_row = self._frame(outer)
        btn_row.pack(fill="x", pady=(14, 0))
        self._button(btn_row, "Avbryt", self.root.destroy).pack(
            side="right", padx=(8, 0)
        )
        self._button(btn_row, "Spara", self._save, primary=True).pack(
            side="right"
        )

    # ------- Tab: Allmänt --------------------------------------------------- #

    def _build_general(self, parent):
        pad = {"padx": 6, "pady": (10, 0)}

        self._label(parent, "Dikteringstangent",
                    font=ctk.CTkFont(weight="bold") if _CTK_AVAILABLE else None
                    ).pack(anchor="w", **pad)
        hk = _HotkeyCapture(parent, self._hotkey_var)
        hk.pack(fill="x", padx=6, pady=(4, 0))
        self._hint(parent, "Klicka och tryck önskad tangentkombination.").pack(
            anchor="w", padx=6, pady=(4, 8)
        )

        # Lyssnarindikator
        self._label(parent, "Lyssnarindikator",
                    font=ctk.CTkFont(weight="bold") if _CTK_AVAILABLE else None
                    ).pack(anchor="w", **pad)
        self._switch(parent, "Följ muspekaren", self._indicator_follow_var).pack(
            anchor="w", padx=6, pady=(6, 0)
        )
        self._hint(parent, "Av = fast position överst på huvudskärmen.").pack(
            anchor="w", padx=6, pady=(2, 8)
        )

        # Mikrofon
        self._label(parent, "Mikrofon",
                    font=ctk.CTkFont(weight="bold") if _CTK_AVAILABLE else None
                    ).pack(anchor="w", **pad)

        try:
            from audio import list_input_devices
            self._mic_devices = list_input_devices()
        except Exception:
            self._mic_devices = []
        mic_names = ["Auto"] + [d["name"] for d in self._mic_devices]

        saved_mic_raw = self.cfg.get("mic_device")
        if isinstance(saved_mic_raw, dict):
            saved_mic = saved_mic_raw.get("name", "")
        else:
            saved_mic = saved_mic_raw or ""
        self._mic_var.set(saved_mic if saved_mic else "Auto")

        self._combobox(parent, self._mic_var, mic_names, width=480,
                       command=lambda _v: self._update_mic_info()).pack(
            anchor="w", padx=6, pady=(4, 0), fill="x"
        )
        self._mic_info = self._hint(parent, "")
        self._mic_info.pack(anchor="w", padx=6, pady=(2, 8))
        self._update_mic_info()

    def _update_mic_info(self):
        name = self._mic_var.get()
        if name == "Auto":
            self._mic_info.configure(
                text="Väljer bästa tillgängliga mikrofon automatiskt."
            )
            return
        for d in self._mic_devices:
            if d["name"] == name:
                self._mic_info.configure(
                    text=f"{d['api']}  •  {d['rate']} Hz  •  {d['channels']} ch"
                )
                return
        self._mic_info.configure(text="")

    def _update_model_desc(self):
        self._model_desc.configure(
            text=_MODEL_INFO.get(self._model_var.get(), "")
        )

    # ------- Tab: LLM ------------------------------------------------------- #

    def _build_llm(self, parent):
        pad = {"padx": 6, "pady": (10, 0)}

        self._switch(parent, "Aktivera LLM-granskning",
                     self._llm_enabled_var).pack(anchor="w", **pad)
        self._hint(parent,
                   "Transkriberad text skickas till vald leverantör för "
                   "lättviktig korrigering. Stäng av för helt lokal "
                   "diktering.").pack(anchor="w", padx=6, pady=(2, 8))

        # Provider selector
        self._label(parent, "Leverantör",
                    font=ctk.CTkFont(weight="bold") if _CTK_AVAILABLE else None
                    ).pack(anchor="w", **pad)

        llm = _llm_providers()
        labels = llm["labels"]()  # {provider_id: human_label}
        # Map label -> provider_id for the combobox; ctk's CTkComboBox can
        # only show one string, so we display labels and translate back.
        self._llm_label_to_id = {v: k for k, v in labels.items()}
        self._llm_id_to_label = labels
        cur_pid = self._llm_provider_var.get()
        cur_label = labels.get(cur_pid, next(iter(labels.values())))
        self._llm_provider_label_var = self._stringvar(cur_label)

        self._combobox(parent, self._llm_provider_label_var,
                       list(labels.values()), width=320,
                       command=lambda _v: self._on_llm_provider_change()
                       ).pack(anchor="w", padx=6, pady=(4, 0), fill="x")

        # Model picker
        self._label(parent, "Modell").pack(anchor="w", padx=6, pady=(10, 2))
        self._llm_model_combo = self._combobox(
            parent, self._llm_model_var, [], width=400,
        )
        self._llm_model_combo.pack(anchor="w", padx=6, pady=(0, 0), fill="x")
        self._llm_models_status = self._hint(parent, "")
        self._llm_models_status.pack(anchor="w", padx=6, pady=(2, 4))

        # API key
        self._label(parent, "API-nyckel").pack(anchor="w", padx=6, pady=(10, 2))
        self._llm_key_entry = self._entry(parent, self._llm_key_var, show="•")
        self._llm_key_entry.pack(anchor="w", padx=6, pady=(0, 4), fill="x")

        key_row = self._frame(parent)
        key_row.pack(fill="x", padx=6, pady=(0, 4))
        self._llm_show_key = False
        self._llm_show_btn = self._button(
            key_row, "Visa nyckel", self._toggle_llm_key_visibility,
        )
        self._llm_show_btn.pack(side="left")
        self._llm_test_btn = self._button(
            key_row, "Testa anslutning", self._test_llm, primary=True,
        )
        self._llm_test_btn.pack(side="left", padx=(8, 0))
        self._llm_test_result = self._hint(parent, "")
        self._llm_test_result.pack(anchor="w", padx=6, pady=(4, 8))

        # Custom base URL (visible only for custom provider)
        self._llm_base_label = self._label(parent, "Base URL (custom)")
        self._llm_base_entry = self._entry(parent, self._llm_base_url_var)
        self._llm_base_hint = self._hint(
            parent,
            "T.ex. http://localhost:11434/v1 (Ollama) eller http://localhost:1234/v1 (LM Studio)."
        )

        # Initialise dependent widgets (model list, key field, base URL row)
        self._on_llm_provider_change()

    def _on_llm_provider_change(self):
        pid = self._llm_label_to_id.get(
            self._llm_provider_label_var.get(),
            self._llm_provider_var.get(),
        )
        self._llm_provider_var.set(pid)

        # Load saved model + key for this provider.
        llm = _llm_providers()
        saved_model = self.cfg.get(f"llm_model_{pid}", "") or llm["default_model"](pid)
        self._llm_model_var.set(saved_model)
        self._llm_key_var.set(self.cfg.get(f"llm_api_key_{pid}", ""))

        # Populate the model dropdown from the provider's static fallback
        # list immediately, then try to refresh from the server in a thread.
        provider = llm["PROVIDERS"].get(pid)
        static_models = list(provider.fallback_models.keys()) if provider else []
        if saved_model and saved_model not in static_models:
            static_models = [saved_model] + static_models
        self._set_llm_model_choices(static_models)
        self._llm_models_status.configure(text="")

        # Toggle base_url row.
        show_base = llm["user_configurable_url"](pid)
        for w in (self._llm_base_label, self._llm_base_entry, self._llm_base_hint):
            w.pack_forget()
        if show_base:
            self._llm_base_label.pack(anchor="w", padx=6, pady=(10, 2))
            self._llm_base_entry.pack(anchor="w", padx=6, pady=(0, 2), fill="x")
            self._llm_base_hint.pack(anchor="w", padx=6, pady=(0, 8))

        # Async fetch updated models from the server. Best-effort.
        threading.Thread(
            target=self._fetch_llm_models_async,
            args=(pid, self._llm_key_var.get(), self._llm_base_url_var.get()),
            daemon=True,
        ).start()

    def _set_llm_model_choices(self, values: list[str]):
        if not values:
            return
        cur = self._llm_model_var.get()
        if _CTK_AVAILABLE and hasattr(self._llm_model_combo, "configure"):
            try:
                self._llm_model_combo.configure(values=values)
            except Exception:
                pass
        else:
            try:
                self._llm_model_combo["values"] = values
            except Exception:
                pass
        if cur not in values:
            self._llm_model_var.set(values[0])

    def _fetch_llm_models_async(self, pid: str, key: str, base_url: str):
        try:
            llm = _llm_providers()
            models = llm["fetch_models"](key, pid, base_url)
        except Exception:
            models = {}
        if not models:
            return
        names = list(models.keys())
        try:
            self.root.after(0, lambda: self._set_llm_model_choices(names))
            self.root.after(
                0,
                lambda: self._llm_models_status.configure(
                    text=f"{len(names)} modeller hittade hos leverantören."
                ),
            )
        except Exception:
            return

    def _toggle_llm_key_visibility(self):
        self._llm_show_key = not self._llm_show_key
        try:
            self._llm_key_entry.configure(show="" if self._llm_show_key else "•")
        except Exception:
            pass
        self._llm_show_btn.configure(
            text="Dölj nyckel" if self._llm_show_key else "Visa nyckel"
        )

    def _test_llm(self):
        llm = _llm_providers()
        pid = self._llm_provider_var.get()
        key = self._llm_key_var.get().strip()
        model = self._llm_model_var.get()
        base_url = self._llm_base_url_var.get().strip()

        try:
            self._llm_test_btn.configure(state="disabled", text="Testar...")
        except Exception:
            pass
        self._llm_test_result.configure(text="Ansluter...")

        def _run():
            try:
                ok, msg = llm["test_connection"](key, model, pid, base_url)
            except Exception as e:
                ok, msg = False, f"Fel: {e}"
            try:
                self.root.after(0, lambda: self._show_llm_test_result(ok, msg))
            except Exception:
                return

        threading.Thread(target=_run, daemon=True).start()

    def _show_llm_test_result(self, ok: bool, msg: str):
        self._render_test_result(self._llm_test_btn, self._llm_test_result,
                                 ok, msg)

    # ------- Tab: Transkribering ------------------------------------------- #

    def _build_transcription(self, parent):
        pad = {"padx": 6, "pady": (10, 0)}

        self._label(parent, "Transkriberingsleverantör",
                    font=ctk.CTkFont(weight="bold") if _CTK_AVAILABLE else None
                    ).pack(anchor="w", **pad)
        self._hint(parent,
                   "Lokal = Whisper körs på din dator (privat, snabb på GPU). "
                   "Remote = ljudet skickas till en svensk/EU-server med "
                   "KB-Whisper Large — bättre på svenska men kräver internet "
                   "och samtycke.").pack(anchor="w", padx=6, pady=(2, 8))

        tr = _tr_providers()
        # The radio shows "Lokal" + each remote provider's human label.
        self._tr_label_to_id = {"Lokal Whisper (på datorn)": "local"}
        for pid, label in tr["labels"]().items():
            self._tr_label_to_id[label] = pid
        self._tr_id_to_label = {v: k for k, v in self._tr_label_to_id.items()}
        cur_pid = self._tr_provider_var.get()
        cur_label = self._tr_id_to_label.get(cur_pid, "Lokal Whisper (på datorn)")
        self._tr_provider_label_var = self._stringvar(cur_label)

        self._combobox(parent, self._tr_provider_label_var,
                       list(self._tr_label_to_id.keys()), width=400,
                       command=lambda _v: self._on_tr_provider_change()
                       ).pack(anchor="w", padx=6, pady=(4, 8), fill="x")

        # Local-only fields (Whisper model + CUDA). Shown only in "local" mode.
        self._tr_local_frame = self._frame(parent)
        self._tr_local_frame.pack(fill="x", padx=0, pady=0)

        self._label(self._tr_local_frame, "Whisper-modell",
                    font=ctk.CTkFont(weight="bold") if _CTK_AVAILABLE else None
                    ).pack(anchor="w", padx=6, pady=(0, 2))
        self._combobox(self._tr_local_frame, self._model_var,
                       ["tiny", "base", "small", "medium", "large"],
                       width=180,
                       command=lambda _v: self._update_model_desc()).pack(
            anchor="w", padx=6, pady=(4, 0)
        )
        self._model_desc = self._hint(self._tr_local_frame, "")
        self._model_desc.pack(anchor="w", padx=6, pady=(2, 4))
        self._update_model_desc()

        self._switch(self._tr_local_frame,
                     "Använd GPU/CUDA (snabbare med NVIDIA)",
                     self._cuda_var).pack(anchor="w", padx=6, pady=(8, 4))
        self._hint(self._tr_local_frame,
                   "Kräver NVIDIA-GPU med CUDA. Saknas GPU används CPU "
                   "automatiskt.").pack(anchor="w", padx=6, pady=(0, 8))

        # Remote-only fields go in a sub-frame so we can hide them in "local" mode.
        self._tr_remote_frame = self._frame(parent)
        self._tr_remote_frame.pack(fill="x", padx=0, pady=0)

        self._label(self._tr_remote_frame, "Modell").pack(
            anchor="w", padx=6, pady=(0, 2)
        )
        self._tr_model_entry = self._entry(self._tr_remote_frame, self._tr_model_var)
        self._tr_model_entry.pack(anchor="w", padx=6, pady=(0, 2), fill="x")
        self._tr_model_hint = self._hint(self._tr_remote_frame, "")
        self._tr_model_hint.pack(anchor="w", padx=6, pady=(0, 8))

        self._label(self._tr_remote_frame, "API-nyckel").pack(
            anchor="w", padx=6, pady=(0, 2)
        )
        self._tr_key_entry = self._entry(self._tr_remote_frame, self._tr_key_var, show="•")
        self._tr_key_entry.pack(anchor="w", padx=6, pady=(0, 4), fill="x")

        tr_btn_row = self._frame(self._tr_remote_frame)
        tr_btn_row.pack(fill="x", padx=6, pady=(0, 4))
        self._tr_show_key = False
        self._tr_show_btn = self._button(
            tr_btn_row, "Visa nyckel", self._toggle_tr_key_visibility,
        )
        self._tr_show_btn.pack(side="left")
        self._tr_test_btn = self._button(
            tr_btn_row, "Testa anslutning", self._test_tr, primary=True,
        )
        self._tr_test_btn.pack(side="left", padx=(8, 0))
        self._tr_test_result = self._hint(self._tr_remote_frame, "")
        self._tr_test_result.pack(anchor="w", padx=6, pady=(4, 8))

        # Base URL (custom only)
        self._tr_base_label = self._label(self._tr_remote_frame, "Base URL (custom)")
        self._tr_base_entry = self._entry(self._tr_remote_frame, self._tr_base_url_var)
        self._tr_base_hint = self._hint(
            self._tr_remote_frame,
            "T.ex. https://api.example.com/v1 — måste exponera "
            "/v1/audio/transcriptions och /v1/models."
        )

        # Consent
        self._tr_consent_switch = self._switch(
            self._tr_remote_frame,
            "Jag samtycker till att ljudet skickas till vald server",
            self._tr_consent_var,
        )
        self._tr_consent_switch.pack(anchor="w", padx=6, pady=(8, 0))
        self._hint(self._tr_remote_frame,
                   "Krävs för att aktivera remote-transkribering. "
                   "Stäng av detta och leverantören återgår till lokal "
                   "Whisper.").pack(anchor="w", padx=6, pady=(2, 8))

        self._on_tr_provider_change()

    def _on_tr_provider_change(self):
        pid = self._tr_label_to_id.get(
            self._tr_provider_label_var.get(),
            self._tr_provider_var.get(),
        )
        self._tr_provider_var.set(pid)

        if pid == "local":
            try:
                self._tr_remote_frame.pack_forget()
            except Exception:
                pass
            try:
                self._tr_local_frame.pack(fill="x", padx=0, pady=0)
            except Exception:
                pass
            return

        # Remote provider selected — hide local-only fields, show remote.
        try:
            self._tr_local_frame.pack_forget()
        except Exception:
            pass

        # Show remote-only fields.
        try:
            self._tr_remote_frame.pack(fill="x", padx=0, pady=0)
        except Exception:
            pass

        tr = _tr_providers()
        default_model = tr["default_model"](pid)
        saved_model = self.cfg.get(f"transcription_model_{pid}", "") or default_model
        self._tr_model_var.set(saved_model)
        self._tr_key_var.set(self.cfg.get(f"transcription_api_key_{pid}", ""))
        self._tr_model_hint.configure(
            text=f"Standard: {default_model}" if default_model else
                 "Ange modellnamn enligt leverantörens dokumentation."
        )

        # Custom base_url row visibility.
        provider = tr["PROVIDERS"].get(pid)
        show_base = bool(provider and provider.user_configurable_url)
        for w in (self._tr_base_label, self._tr_base_entry, self._tr_base_hint):
            w.pack_forget()
        if show_base:
            self._tr_base_label.pack(anchor="w", padx=6, pady=(8, 2))
            self._tr_base_entry.pack(anchor="w", padx=6, pady=(0, 2), fill="x")
            self._tr_base_hint.pack(anchor="w", padx=6, pady=(0, 8))

    def _toggle_tr_key_visibility(self):
        self._tr_show_key = not self._tr_show_key
        try:
            self._tr_key_entry.configure(show="" if self._tr_show_key else "•")
        except Exception:
            pass
        self._tr_show_btn.configure(
            text="Dölj nyckel" if self._tr_show_key else "Visa nyckel"
        )

    def _test_tr(self):
        pid = self._tr_provider_var.get()
        if pid == "local":
            self._tr_test_result.configure(
                text="Lokal Whisper kräver inget anslutningstest."
            )
            return
        key = self._tr_key_var.get().strip()
        base_url = self._tr_base_url_var.get().strip()

        try:
            self._tr_test_btn.configure(state="disabled", text="Testar...")
        except Exception:
            pass
        self._tr_test_result.configure(text="Ansluter...")

        def _run():
            try:
                tr = _tr_providers()
                ok, msg = tr["test_connection"](pid, key, base_url)
            except Exception as e:
                ok, msg = False, f"Fel: {e}"
            try:
                self.root.after(0, lambda: self._show_tr_test_result(ok, msg))
            except Exception:
                return

        threading.Thread(target=_run, daemon=True).start()

    def _show_tr_test_result(self, ok: bool, msg: str):
        self._render_test_result(self._tr_test_btn, self._tr_test_result,
                                 ok, msg)

    def _render_test_result(self, button, label, ok: bool, msg: str) -> None:
        """Shared renderer for the LLM and transcription 'Testa anslutning' results.

        Both tabs need the same behaviour: re-enable the button, prefix the
        message with ✓/✗, and colour it green/red. Extracted from two
        verbatim copies so a future tweak (e.g. fading the colour, swapping
        symbols) only lives in one place.
        """
        try:
            button.configure(state="normal", text="Testa anslutning")
        except Exception:
            pass
        prefix = "✓ " if ok else "✗ "
        try:
            if _CTK_AVAILABLE:
                color = ("#27ae60", "#2ecc71") if ok else ("#c0392b", "#e74c3c")
                label.configure(text=prefix + msg, text_color=color)
            else:
                label.configure(
                    text=prefix + msg, fg="#27ae60" if ok else "#c0392b"
                )
        except Exception:
            label.configure(text=prefix + msg)

    # -- save ---------------------------------------------------------------- #

    def _save(self):
        # Resolve labels back to provider ids in case the combobox change
        # callbacks didn't fire (rare on keyboard navigation).
        llm_pid = self._llm_label_to_id.get(
            self._llm_provider_label_var.get(),
            self._llm_provider_var.get(),
        )
        tr_pid = self._tr_label_to_id.get(
            self._tr_provider_label_var.get(),
            self._tr_provider_var.get(),
        )

        llm_enabled = self._llm_enabled_var.get()
        llm_key = self._llm_key_var.get().strip()
        llm_was_enabled = self.cfg.get("llm_enabled", False)
        llm_privacy_accepted = self.cfg.get("llm_privacy_accepted", False)
        needs_llm_consent = llm_enabled and (
            not llm_was_enabled or not llm_privacy_accepted
        )

        # Sanity: can we store the secret?
        any_key_to_store = bool(llm_key) or bool(self._tr_key_var.get().strip())
        if any_key_to_store and not cfg_module.can_store_secret():
            messagebox.showerror(
                "Kan inte spara API-nyckel",
                "Saknar säker lagring för API-nyckeln. Installera/aktivera "
                "keyring med Windows Credential Manager och försök igen.",
            )
            return

        if needs_llm_consent:
            ok = messagebox.askokcancel(
                "Aktivera LLM-granskning?",
                "LLM-granskning skickar din transkriberade text till vald "
                "leverantör för korrigering.\n\nAktivera bara detta om du "
                "accepterar att texten lämnar datorn.",
            )
            if not ok:
                return

        # Transcription consent — only required when leaving "local".
        if tr_pid != "local" and not self._tr_consent_var.get():
            messagebox.showwarning(
                "Samtycke krävs",
                "Remote-transkribering skickar ditt ljud till en extern "
                "server. Bocka i samtyckesrutan på fliken Transkribering "
                "för att aktivera, eller välj Lokal Whisper.",
            )
            return

        # ---- Build new_cfg ----
        new_cfg = self.cfg.copy()
        new_cfg["hotkey"] = self._hotkey_var.get().strip()
        new_cfg["model_size"] = self._model_var.get()
        new_cfg["use_cuda"] = self._cuda_var.get()
        new_cfg["indicator_follow_mouse"] = self._indicator_follow_var.get()

        mic = self._mic_var.get()
        if mic == "Auto":
            new_cfg["mic_device"] = None
        else:
            picked = next(
                (d for d in getattr(self, "_mic_devices", []) if d["name"] == mic),
                None,
            )
            if picked:
                new_cfg["mic_device"] = {
                    "name": picked["name"],
                    "api": picked["api"],
                    "index": picked["index"],
                }
            else:
                new_cfg["mic_device"] = mic

        # LLM
        new_cfg["llm_enabled"] = llm_enabled
        new_cfg["llm_provider"] = llm_pid
        new_cfg[f"llm_model_{llm_pid}"] = self._llm_model_var.get().strip()
        new_cfg[f"llm_api_key_{llm_pid}"] = llm_key
        new_cfg["llm_custom_base_url"] = self._llm_base_url_var.get().strip()
        new_cfg["llm_privacy_accepted"] = bool(
            llm_enabled and (llm_privacy_accepted or needs_llm_consent)
        )

        # Transcription
        new_cfg["transcription_provider"] = tr_pid
        if tr_pid != "local":
            new_cfg[f"transcription_model_{tr_pid}"] = self._tr_model_var.get().strip()
            new_cfg[f"transcription_api_key_{tr_pid}"] = self._tr_key_var.get().strip()
            new_cfg["transcription_custom_base_url"] = self._tr_base_url_var.get().strip()
        new_cfg["transcription_privacy_accepted"] = bool(
            tr_pid != "local" and self._tr_consent_var.get()
        )

        # Strip removed legacy keys.
        for k in ("filter_fillers", "auto_punctuate", "language",
                  "llm_api_key", "llm_model"):
            new_cfg.pop(k, None)

        if self.on_save:
            if self.on_save(new_cfg) is False:
                return
        self.root.destroy()
