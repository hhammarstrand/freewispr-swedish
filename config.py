"""App configuration with keyring-backed secrets and migration."""
import copy
import logging
from pathlib import Path
from threading import Lock

from json_store import load_json, save_json_atomic

try:
    import keyring
except Exception:
    keyring = None

log = logging.getLogger("freewispr")

CONFIG_DIR = Path.home() / ".freewispr-swedish"
CONFIG_FILE = CONFIG_DIR / "config.json"
_KEYRING_SERVICE = "freewispr-swedish"

# Legacy single-key entry. Migreras till provider-specifika nycklar vid load().
_LEGACY_KEYRING_USERNAME = "llm_api_key"

# Serialise save() across threads. The function performs N keyring writes
# *and* an atomic JSON write; if two Settings-save calls land concurrently
# (e.g. user smashes Spara twice while the first run is still flushing),
# the keyring entries from save A and the JSON snapshot from save B can
# end up describing different worlds — keyring would hold A's keys while
# the file remembers B's provider id. Holding _save_lock for the full
# critical section makes the pair atomic from any caller's point of view.
_save_lock = Lock()

# Provider-IDn som matchar PROVIDERS i llm_polish.py och remote_transcribe.py.
# Hardkodade här eftersom dessa tupler används vid import-tid för att bygga
# _SECRET_FIELDS/_ALL_STRIPPED_FIELDS, och de tunga provider-modulerna inte
# kan importeras vid den tidpunkten.  _validate_providers() (anropas från
# load()) verifierar vid runtime att värdena stämmer.
_LLM_PROVIDERS: tuple[str, ...] = ("github", "staik", "berget", "openai", "custom")
# Remote-transkriberingsleverantörer (utan "local").
_TR_PROVIDERS: tuple[str, ...] = ("staik", "berget", "custom")


def _keyring_user(provider: str) -> str:
    """Per-provider LLM-entry: ``llm_api_key_github`` osv."""
    return f"{_LEGACY_KEYRING_USERNAME}_{provider}"


def _tr_keyring_user(provider: str) -> str:
    """Per-provider transkriberings-entry: ``transcription_api_key_staik`` osv.

    Separat från LLM-nyckeln så att användaren kan ha t.ex. ett gratiskonto för
    transkribering och ett betalkonto för LLM hos samma leverantör.
    """
    return f"transcription_api_key_{provider}"


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
    "llm_model_berget": "mistralai/Mistral-Small-3.2-24B-Instruct-2506",
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
    # "Rå direkt": paste the raw transcript and skip LLM polish even when LLM
    # is enabled (useful per-app via profiles, or as a global fast toggle).
    "llm_raw_mode": False,
    # "Rå → ersätt" (L3): paste the raw transcript immediately for instant
    # visible text, then replace it with the polished version when it lands.
    # Editable fields only (code/terminal profiles disable polish). Default off.
    "llm_replace_mode": False,
    # Watchdog threshold (seconds): if polish hasn't returned by now, the raw
    # transcript is pasted as a fallback so the indicator never hangs.
    "llm_timeout_sec": 15.0,

    # ---- Remote transcription (audio leaves the machine) ----
    # local | staik | berget | custom
    "transcription_provider": "local",
    # Modellnamn per leverantör (rimliga defaults — användaren kan ändra).
    "transcription_model_staik":  "kb-whisper-large",
    "transcription_model_berget": "KBLab/kb-whisper-large",
    "transcription_model_custom": "",
    # Custom-leverantörens base_url (delas inte med LLM-custom).
    "transcription_custom_base_url": "",
    # Egen API-nyckel per remote-leverantör (delas inte med LLM-nyckeln).
    "transcription_api_key_staik":  "",
    "transcription_api_key_berget": "",
    "transcription_api_key_custom": "",
    # Explicit consent: ljudet skickas över nätet vid remote-transkribering.
    "transcription_privacy_accepted": False,

    # ---- Transkriberings-biasing (AP4) ----
    # Lokal faster-whisper: avkodnings-/biaseringsparametrar.
    "whisper_beam_size": 1,            # 1 = greedy (snabbast); 5 = noggrannare
    "whisper_vad_filter": True,        # Silero VAD klipper tystnad/hallucination
    "whisper_no_speech_threshold": 0.6,
    "whisper_compute_type": "",        # "" = auto (float16 CUDA / int8 CPU)
    # CPU-trådar för CTranslate2-inferens. 0 = auto (≈ fysiska kärnor, minst 4
    # = CT2:s egen default så auto aldrig blir långsammare än tidigare).
    "whisper_cpu_threads": 0,
    # EXPERIMENTELLT: Whisper-enkoderns fönsterlängd i sekunder. 0 = modellens
    # default (30 s). Whisper paddar alltid ljudet till fönsterlängden, så en
    # 4 s-diktering betalar nästan full enkoderkostnad — ett lägre värde
    # (t.ex. 15) kapar den kostnaden för korta yttranden. Modellen är dock
    # tränad på 30 s-fönster: verifiera WER på egen diktering innan du ändrar.
    # Påverkar endast lokal transkribering.
    "whisper_chunk_length": 0,
    "kblab_revision": "default",       # default | strict | subtitle (CT2-fallback)
    # Remote OpenAI-kompatibel path: temperatur (prompt byggs automatiskt).
    "transcription_temperature": 0.0,
    # L5.2: uppladdningsformat för remote audio: wav (default) | flac | opus.
    # flac/opus kräver soundfile; faller annars tillbaka till wav.
    "remote_audio_format": "wav",

    # ---- Kommandoläge (AP5) ----
    # Tolka inledande kommandofraser ("gör det kortare" m.fl.) som redigering
    # av senaste blocket i stället för ny diktering.
    "command_mode_enabled": True,

    # ---- Inlärningsloop (AP2) ----
    # Lär dig term-par när användaren rättar inklistrad text. Påverkar bara
    # *inspelning* av nya rättelser; redan inlärda injiceras alltid i polish.
    "learning_enabled": True,

    # ---- Kontextmedvetenhet (AP3) ----
    # Läs aktiv app + text nära markör för bättre egennamn/ton. Best-effort.
    "context_awareness_enabled": True,
    # Egna app→profil-overrides (processnamn utan .exe → "casual"/"email"/
    # "code"). Slås ihop ovanpå context_win.DEFAULT_APP_PROFILES. Tomt = inbyggda.
    "app_profiles": {},
    # Uttryckligt medgivande: namn som skrapas från skärmen (nära markören /
    # fönstertitel) får skickas som biasing-prompt till en *remote*-
    # transkriberingsleverantör. Detta är en EGEN datakategori, skild från
    # ljudet som transcription_privacy_accepted täcker — skärmtext kan innehålla
    # uppgifter från andra appar. Av som default; lokal transkribering påverkas
    # aldrig (namnen lämnar då aldrig maskinen).
    "context_to_remote_accepted": False,

    # ---- Flow-läge (AP6, valfritt) ----
    # Kontinuerlig diktering över pauser (endast lokal transkribering). Av som
    # default; togglas via tray-menyn när påslaget.
    "flow_mode_enabled": False,

    # ---- Robusthet & saknade funktioner (AP7) ----
    # Återställ användarens urklipp efter diktering (opt-in; av = dikterad text
    # ligger kvar som CLI-fallback).
    "restore_clipboard": False,
    # Avbryt pågående inspelning (AP7.2). Aktiv endast medan inspelning pågår.
    "cancel_hotkey": "esc",
    # Behåll engelska facktermer bättre i svensk diktering (AP7.5, mitigering).
    "expect_english_terms": False,
    # Snippets / textexpansion (AP7.6) — par lagras i snippets.json.
    "snippets_enabled": True,
    # KP2: användardefinierade lägen (Superwhisper-stil) — definitioner lagras i
    # modes.json, bindningar app→läge i app_profiles. Inget eget på/av-fält
    # behövs (ett läge är aktivt bara om en app pekar på det).
    # KP3: rösteditera markerad text. Egen hotkey: spela in instruktion, läs
    # markeringen, kör LLM-omskrivning, ersätt. Tom = av. Kräver att LLM är på.
    "voice_edit_hotkey": "",
    # L5.5: trimma ledande/avslutande tystnad (RMS) före decode.
    "silence_trim_enabled": True,
    # L5.6: hoppa LLM-polish för triviala (korta, disfluensfria) yttranden.
    "polish_skip_trivial": True,
    "polish_skip_max_words": 6,
    # L5.7: transkribera färdiga chunkar redan under inspelning (endast lokal).
    # På som default — vid key-up återstår bara svansen att avkoda, vilket är
    # samma streaming-knep som de kommersiella apparna använder för "instant"
    # paste på längre dikteringar. Inkrementell resampling via soxr (O(n) i
    # stället för O(n²)); avkodade partials matas som kontext till nästa chunk.
    "live_transcribe_enabled": True,
    # L5.8: BatchedInferencePipeline för längre klipp (faster-whisper). Av som
    # default — mät innan du slår på. Faller tillbaka om klassen saknas.
    "whisper_batched": False,

    "indicator_follow_mouse": True,
    # Lägsta RMS-nivå (0.0-1.0) som räknas som tal. Se DEFAULT_MIN_RMS i dictation.py.
    "min_rms": 0.003,
}

# Fältnamn som ALDRIG får sparas till disk (nycklar lagras separat i keyring).
_LLM_SECRET_FIELDS: tuple[str, ...] = tuple(f"llm_api_key_{p}" for p in _LLM_PROVIDERS)
_TR_SECRET_FIELDS: tuple[str, ...] = tuple(f"transcription_api_key_{p}" for p in _TR_PROVIDERS)
_SECRET_FIELDS: tuple[str, ...] = _LLM_SECRET_FIELDS + _TR_SECRET_FIELDS
# Plus legacy-fältet, för bakåtkompatibilitet.
_ALL_STRIPPED_FIELDS: tuple[str, ...] = (_LEGACY_KEYRING_USERNAME,) + _SECRET_FIELDS


# Mappning från config-fältnamn → keyring-username. En enda sanning som både
# load() och save() konsulterar; håller koden ifrån att glömma bort att lägga
# till nya hemligheter på fel ställen.
def _secret_field_map() -> dict[str, str]:
    mapping: dict[str, str] = {}
    for p in _LLM_PROVIDERS:
        mapping[f"llm_api_key_{p}"] = _keyring_user(p)
    for p in _TR_PROVIDERS:
        mapping[f"transcription_api_key_{p}"] = _tr_keyring_user(p)
    return mapping


_providers_validated = False
_validate_lock = Lock()


def _validate_providers() -> None:
    """Check that hardcoded _LLM_PROVIDERS/_TR_PROVIDERS match the actual modules.

    Called once from load(). Logs a warning if they diverge — this catches the
    case where someone adds a new provider to llm_polish.py or
    remote_transcribe.py but forgets to update the tuples here.
    """
    global _providers_validated
    with _validate_lock:
        if _providers_validated:
            return
        _providers_validated = True
    try:
        from llm_polish import PROVIDERS as llm_providers
        actual_llm = tuple(llm_providers.keys())
        if set(_LLM_PROVIDERS) != set(actual_llm):
            log.warning(
                "config._LLM_PROVIDERS %s != llm_polish.PROVIDERS keys %s — "
                "update config.py to match!",
                _LLM_PROVIDERS, actual_llm,
            )
    except Exception as e:
        log.debug("Kunde inte validera LLM-providers: %s", e)
    try:
        from remote_transcribe import PROVIDERS as tr_providers
        actual_tr = tuple(tr_providers.keys())
        if set(_TR_PROVIDERS) != set(actual_tr):
            log.warning(
                "config._TR_PROVIDERS %s != remote_transcribe.PROVIDERS keys %s — "
                "update config.py to match!",
                _TR_PROVIDERS, actual_tr,
            )
    except Exception as e:
        log.debug("Kunde inte validera TR-providers: %s", e)


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
        # Persist into `data` too — otherwise the migrated value only lives in
        # the runtime cfg and the on-disk file (written from `data` below) is
        # missing the new key, so the migration silently re-runs/loses the
        # user's old model choice on the next launch.
        data["llm_model_github"] = legacy_model
        changed = True

    return changed


def load():
    _validate_providers()
    CONFIG_DIR.mkdir(exist_ok=True)
    if CONFIG_FILE.exists():
        data = load_json(CONFIG_FILE, {})
        # Deep-copy DEFAULTS: a shallow {**DEFAULTS, **data} shares nested
        # containers (e.g. app_profiles) by reference with the module-level
        # DEFAULTS, so a caller mutating cfg["app_profiles"] would corrupt
        # DEFAULTS for the whole process.
        cfg = {**copy.deepcopy(DEFAULTS), **data}
    else:
        data = {}
        cfg = copy.deepcopy(DEFAULTS)

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

    # Lös in en hemlighet per provider till runtime-cfg (LLM + transkribering).
    for field, user in _secret_field_map().items():
        cfg[field] = _get_secret(user)

    if migrated:
        # Take the same lock as save(): a concurrent Settings flush and this
        # migrating write must not interleave (lost update / divergent file).
        with _save_lock:
            save_json_atomic(CONFIG_FILE, data)

    return cfg


def _read_existing_secrets() -> dict[str, str]:
    """Nuvarande värde i keyring per config-fält. Används för rollback i save()."""
    return {field: _get_secret(user) for field, user in _secret_field_map().items()}


def save(cfg):
    with _save_lock:
        _save_locked(cfg)


def _save_locked(cfg):
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
    field_map = _secret_field_map()
    new_secrets = {field: (data.pop(field, "") or "") for field in field_map}
    data.pop(_LEGACY_KEYRING_USERNAME, None)

    old_secrets = _read_existing_secrets()

    written_fields: list[str] = []
    try:
        for field, value in new_secrets.items():
            user = field_map[field]
            if value:
                if not _set_secret(user, value):
                    raise RuntimeError(
                        f"Kunde inte spara {field} i Windows Credential Manager"
                    )
                written_fields.append(field)
            elif old_secrets.get(field) and not _set_secret(user, ""):
                raise RuntimeError(
                    f"Kunde inte ta bort {field} från Windows Credential Manager"
                )
            else:
                written_fields.append(field)

        save_json_atomic(CONFIG_FILE, data)

    except Exception:
        # Återställ Credential Manager till samma tillstånd som JSON-filen.
        for field, user in field_map.items():
            old = old_secrets.get(field, "")
            try:
                if old:
                    _set_secret(user, old)
                elif field in written_fields and new_secrets[field]:
                    _set_secret(user, "")
            except Exception:
                pass
        raise
