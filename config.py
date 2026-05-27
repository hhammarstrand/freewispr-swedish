from pathlib import Path

from json_store import load_json, save_json_atomic

try:
    import keyring
except Exception:
    keyring = None

CONFIG_DIR = Path.home() / ".freewispr-swedish"
CONFIG_FILE = CONFIG_DIR / "config.json"
_KEYRING_SERVICE = "freewispr-swedish"

# Legacy single-key entry. Migreras till provider-specifika nycklar vid load().
_LEGACY_KEYRING_USERNAME = "llm_api_key"

# Provider-IDn som matchar PROVIDERS i llm_polish.py.
_LLM_PROVIDERS: tuple[str, ...] = ("github", "staik", "berget", "openai", "custom")


def _keyring_user(provider: str) -> str:
    """Per-provider entry: ``llm_api_key_github`` osv."""
    return f"{_LEGACY_KEYRING_USERNAME}_{provider}"


DEFAULTS = {
    "hotkey": "ctrl+space",
    "model_size": "small",      # tiny/base/small/medium/large
    "use_cuda": True,           # True = auto-detect GPU, False = force CPU
    "mic_device": None,         # None = auto-detect, or device name string

    # ---- LLM ----
    "llm_enabled": False,
    "llm_provider": "github",   # github | staik | berget | openai | custom
    # Per-provider sparade modellnamn. Gör att man kan växla utan att tappa val.
    "llm_model_github": "openai/gpt-4.1-nano",
    "llm_model_staik":  "gemma4:31b",
    "llm_model_berget": "gemma-4-31B-it",
    "llm_model_openai": "gpt-4.1-nano",
    "llm_model_custom": "",
    # Endast använd av custom-leverantören.
    "llm_custom_base_url": "",
    # API-nycklar (per provider) lagras i Credential Manager och dyker bara upp
    # i runtime-cfg, aldrig i config.json. Behåll tomma defaults så att
    # serialiseringen vet vilka fält som ska strippas.
    "llm_api_key_github": "",
    "llm_api_key_staik":  "",
    "llm_api_key_berget": "",
    "llm_api_key_openai": "",
    "llm_api_key_custom": "",
    "llm_privacy_accepted": False,

    # ---- Remote transcription (audio leaves the machine) ----
    # local | staik | berget | custom
    "transcription_provider": "local",
    # Modellnamn per leverantör (rimliga defaults — användaren kan ändra).
    "transcription_model_staik":  "kb-whisper-large",
    "transcription_model_berget": "KBLab/kb-whisper-large",
    "transcription_model_custom": "",
    # Custom-leverantörens base_url (delas inte med LLM-custom).
    "transcription_custom_base_url": "",
    # Explicit consent: ljudet skickas över nätet vid remote-transkribering.
    "transcription_privacy_accepted": False,

    "indicator_follow_mouse": True,
    # Lägsta RMS-nivå (0.0-1.0) som räknas som tal. Se DEFAULT_MIN_RMS i dictation.py.
    "min_rms": 0.003,
}

# Fältnamn som ALDRIG får sparas till disk (nycklar lagras separat i keyring).
_SECRET_FIELDS: tuple[str, ...] = tuple(f"llm_api_key_{p}" for p in _LLM_PROVIDERS)
# Plus legacy-fältet, för bakåtkompatibilitet.
_ALL_STRIPPED_FIELDS: tuple[str, ...] = (_LEGACY_KEYRING_USERNAME,) + _SECRET_FIELDS


def _get_secret(username: str) -> str:
    if not keyring:
        return ""
    try:
        return keyring.get_password(_KEYRING_SERVICE, username) or ""
    except Exception:
        return ""


def _set_secret(username: str, value: str) -> bool:
    if not keyring:
        return False
    try:
        if value:
            keyring.set_password(_KEYRING_SERVICE, username, value)
        else:
            keyring.delete_password(_KEYRING_SERVICE, username)
        return True
    except Exception:
        return False


def can_store_secret() -> bool:
    if not keyring:
        return False
    test_user = f"{_LEGACY_KEYRING_USERNAME}_probe"
    test_value = "probe"
    try:
        keyring.set_password(_KEYRING_SERVICE, test_user, test_value)
        ok = keyring.get_password(_KEYRING_SERVICE, test_user) == test_value
        try:
            keyring.delete_password(_KEYRING_SERVICE, test_user)
        except Exception:
            pass
        return ok
    except Exception:
        return False


def _migrate_legacy_field_names(cfg: dict, data: dict) -> bool:
    """Översätt gamla config-fält till nya. Returnerar True om något migrerades."""
    changed = False

    # llm_model -> llm_model_github (det var alltid github förut).
    legacy_model = data.pop("llm_model", None)
    if legacy_model and "llm_model_github" not in data:
        cfg["llm_model_github"] = legacy_model
        changed = True

    return changed


def load():
    CONFIG_DIR.mkdir(exist_ok=True)
    if CONFIG_FILE.exists():
        data = load_json(CONFIG_FILE, {})
        cfg = {**DEFAULTS, **data}
    else:
        data = {}
        cfg = DEFAULTS.copy()

    # Strip hemligheter ur runtime-cfg så att vi inte råkar skriva dem.
    for field in _ALL_STRIPPED_FIELDS:
        cfg.pop(field, None)
        data.pop(field, None)

    migrated = _migrate_legacy_field_names(cfg, data)

    # Migrera legacy single-key till per-provider entries första gången.
    legacy_secret = _get_secret(_LEGACY_KEYRING_USERNAME)
    if legacy_secret:
        github_user = _keyring_user("github")
        if not _get_secret(github_user):
            if _set_secret(github_user, legacy_secret):
                _set_secret(_LEGACY_KEYRING_USERNAME, "")
                migrated = True

    # Lös in en hemlighet per provider till runtime-cfg.
    for provider in _LLM_PROVIDERS:
        cfg[f"llm_api_key_{provider}"] = _get_secret(_keyring_user(provider))

    if migrated:
        save_json_atomic(CONFIG_FILE, data)

    return cfg


def _read_existing_secrets() -> dict[str, str]:
    return {p: _get_secret(_keyring_user(p)) for p in _LLM_PROVIDERS}


def save(cfg):
    CONFIG_DIR.mkdir(exist_ok=True)
    data = cfg.copy()

    # Bakåtkompatibilitet: UI:t kan fortfarande skicka in legacy-fält
    # (``llm_api_key``, ``llm_model``) tills Settings-UI:t skrivits om.
    # Översätt dessa till den aktiva provider-slotten *före* hemligheter
    # plockas ut, så att nyckeln hamnar i rätt keyring-entry.
    active_provider = data.get("llm_provider", "github")
    legacy_key = data.pop(_LEGACY_KEYRING_USERNAME, None)
    if legacy_key is not None:
        data.setdefault(f"llm_api_key_{active_provider}", legacy_key)
    legacy_model = data.pop("llm_model", None)
    if legacy_model:
        data.setdefault(f"llm_model_{active_provider}", legacy_model)

    # Plocka bort alla hemligheter — de hör hemma i Credential Manager.
    new_secrets = {p: (data.pop(f"llm_api_key_{p}", "") or "") for p in _LLM_PROVIDERS}
    data.pop(_LEGACY_KEYRING_USERNAME, None)

    old_secrets = _read_existing_secrets()

    written_secrets: list[str] = []
    try:
        for provider, value in new_secrets.items():
            user = _keyring_user(provider)
            if value:
                if not _set_secret(user, value):
                    raise RuntimeError(
                        f"Kunde inte spara API-nyckeln för {provider} i "
                        "Windows Credential Manager"
                    )
                written_secrets.append(provider)
            elif old_secrets.get(provider) and not _set_secret(user, ""):
                raise RuntimeError(
                    f"Kunde inte ta bort API-nyckeln för {provider} från "
                    "Windows Credential Manager"
                )
            else:
                written_secrets.append(provider)

        save_json_atomic(CONFIG_FILE, data)

    except Exception:
        # Återställ Credential Manager till samma tillstånd som JSON-filen.
        for provider in _LLM_PROVIDERS:
            old = old_secrets.get(provider, "")
            user = _keyring_user(provider)
            try:
                if old:
                    _set_secret(user, old)
                elif provider in written_secrets and new_secrets[provider]:
                    _set_secret(user, "")
            except Exception:
                pass
        raise
