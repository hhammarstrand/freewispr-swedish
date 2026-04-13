import json
from pathlib import Path

CONFIG_DIR = Path.home() / ".freewispr-swedish"
CONFIG_FILE = CONFIG_DIR / "config.json"

DEFAULTS = {
    "hotkey": "ctrl+space",
    "model_size": "small",     # tiny/base/small/medium/large
    "use_cuda": True,         # True = auto-detect GPU, False = force CPU
    "mic_device": None,       # None = auto-detect, or device name string
}


def load():
    CONFIG_DIR.mkdir(exist_ok=True)
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE, encoding="utf-8") as f:
            data = json.load(f)
        return {**DEFAULTS, **data}
    return DEFAULTS.copy()


def save(cfg):
    CONFIG_DIR.mkdir(exist_ok=True)
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)
