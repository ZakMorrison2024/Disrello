from __future__ import annotations

# HARD RULES
DEFAULT_RAM_GB = 4
MAX_RAM_GB = 8
ALLOWED_RAM_GB = (2, 4, 8)

# Your installed models (approx RAM use; conservative)
# Note: actual usage varies by quant/context, but these estimates are good for gating.
MODEL_RAM_ESTIMATES_GB = {
    "phi3.5": 3.0,
    "tinyllama": 1.5,
    "tinydolphin": 2.0,

    "gemma3": 6.5,
    "mistral": 7.5,
    "nous-hermes2": 7.8,
    "wizard-vicuna": 7.8,

    # Mixtral-class MoE: far above 8GB in practice
    "dolphin-mixtral": 14.0,
}


def normalize_ram_gb(v) -> int:
    try:
        n = int(v)
    except Exception:
        n = DEFAULT_RAM_GB
    if n not in ALLOWED_RAM_GB:
        n = DEFAULT_RAM_GB
    return n


def estimate_ram_gb(model_name: str) -> float | None:
    m = (model_name or "").strip()
    if not m:
        return None
    # exact match first
    if m in MODEL_RAM_ESTIMATES_GB:
        return MODEL_RAM_ESTIMATES_GB[m]
    # allow tag variants e.g. "mistral:latest"
    base = m.split(":", 1)[0]
    return MODEL_RAM_ESTIMATES_GB.get(base)


def model_fits_ram(model_name: str, ram_gb: int) -> bool:
    est = estimate_ram_gb(model_name)
    if est is None:
        # Unknown model -> treat as NOT allowed (safe default)
        return False
    return float(est) <= float(ram_gb)

