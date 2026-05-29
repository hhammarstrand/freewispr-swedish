"""
Latensbenchmark (L0) — kör hot-path-stegen K gånger och skriv percentiler.

Körs som ``python -m tests.bench_latency <wav>`` på en fast WAV för att mäta
p50/p95 per steg (transcribe/llm/paste/context/conn) utan att röra inferensvalet.

Designad för att vara CI-vänlig: ``run_bench`` tar injicerbara callables så att
testet kan mocka transkribering/polish/paste/UIA och köra helt headless.
``main`` bygger en riktig Transcriber och används manuellt på Windows.
"""
from __future__ import annotations

import sys
import time
from typing import Callable

import numpy as np

_KEYS = ("context_hotpath_ms", "transcribe_ms", "llm_ms", "paste_ms", "conn_ms")


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    if len(s) == 1:
        return s[0]
    k = (len(s) - 1) * (pct / 100.0)
    f = int(k)
    c = min(f + 1, len(s) - 1)
    if f == c:
        return s[f]
    return s[f] + (s[c] - s[f]) * (k - f)


def run_bench(audio: np.ndarray, iterations: int = 20, *,
              transcribe: Callable[[np.ndarray], str],
              polish: Callable[[str], str] | None = None,
              paste: Callable[[str], None] | None = None,
              context: Callable[[], object] | None = None,
              conn_provider: Callable[[], float] | None = None
              ) -> dict[str, dict[str, float]]:
    """Time each hot-path step over ``iterations`` and return p50/p95 per step.

    Each step is optional (pass ``None`` to skip). Pure timing harness — the
    callables decide what real/mock work happens, so this runs in CI.
    """
    samples: dict[str, list[float]] = {k: [] for k in _KEYS}
    for _ in range(max(1, iterations)):
        if context is not None:
            t = time.monotonic()
            context()
            samples["context_hotpath_ms"].append((time.monotonic() - t) * 1000)

        t = time.monotonic()
        text = transcribe(audio)
        samples["transcribe_ms"].append((time.monotonic() - t) * 1000)

        if polish is not None:
            t = time.monotonic()
            text = polish(text) or text
            samples["llm_ms"].append((time.monotonic() - t) * 1000)

        if paste is not None:
            t = time.monotonic()
            paste(text)
            samples["paste_ms"].append((time.monotonic() - t) * 1000)

        if conn_provider is not None:
            samples["conn_ms"].append(float(conn_provider()))

    return {
        k: {"p50": _percentile(v, 50), "p95": _percentile(v, 95)}
        for k, v in samples.items() if v
    }


def load_wav(path: str) -> tuple[np.ndarray, int]:
    """Load a WAV file as mono float32 in [-1, 1]."""
    import wave
    with wave.open(path, "rb") as w:
        rate = w.getframerate()
        n = w.getnframes()
        ch = w.getnchannels()
        raw = w.readframes(n)
    data = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    if ch > 1:
        data = data.reshape(-1, ch).mean(axis=1)
    return data, rate


def _format(results: dict[str, dict[str, float]]) -> str:
    lines = ["steg                  p50(ms)   p95(ms)"]
    for k in _KEYS:
        if k in results:
            r = results[k]
            lines.append(f"{k:<20} {r['p50']:>8.0f}  {r['p95']:>8.0f}")
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    if not argv:
        print("Användning: python -m tests.bench_latency <wav> [iterationer]")
        return 2
    wav_path = argv[0]
    iterations = int(argv[1]) if len(argv) > 1 else 20

    import config
    from transcriber import Transcriber

    audio, _rate = load_wav(wav_path)
    cfg = config.load()
    tr = Transcriber(
        model_size=cfg.get("model_size", "small"),
        use_cuda=cfg.get("use_cuda", True),
        llm_enabled=cfg.get("llm_enabled", False),
        llm_api_key=cfg.get(f"llm_api_key_{cfg.get('llm_provider', 'github')}", ""),
        llm_model=cfg.get(f"llm_model_{cfg.get('llm_provider', 'github')}", ""),
        llm_provider=cfg.get("llm_provider", "github"),
    )

    def _polish(text: str) -> str:
        from llm_polish import polish
        return polish(text, tr.llm_api_key, model=tr.llm_model,
                      provider=tr.llm_provider).text

    polish_fn = _polish if cfg.get("llm_enabled") else None
    results = run_bench(
        audio, iterations,
        transcribe=tr.transcribe,
        polish=polish_fn,
        paste=lambda _t: None,
        conn_provider=lambda: getattr(tr, "last_polish_conn_ms", 0.0),
    )
    print(_format(results))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
