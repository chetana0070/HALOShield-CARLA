from __future__ import annotations

import copy
from pathlib import Path
from typing import Any
import yaml


class ConfigError(ValueError):
    pass


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _deep_update(base: dict[str, Any], update: dict[str, Any]) -> dict[str, Any]:
    for key, value in update.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _deep_update(base[key], value)
        else:
            base[key] = value
    return base


def load_config(path: str | Path | None = None, overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg_path = Path(path) if path else repo_root() / "config" / "default.yaml"
    if not cfg_path.exists():
        raise ConfigError(f"Configuration file not found: {cfg_path}")
    with cfg_path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    if not isinstance(data, dict):
        raise ConfigError("Top-level configuration must be a mapping")
    cfg = copy.deepcopy(data)
    if overrides:
        _deep_update(cfg, overrides)
    validate_config(cfg)
    return cfg


def validate_config(cfg: dict[str, Any]) -> None:
    duration = float(cfg["experiment"]["duration_s"])
    delta = float(cfg["experiment"]["fixed_delta_s"])
    if duration <= 0:
        raise ConfigError("experiment.duration_s must be positive")
    if not (0.02 <= delta <= 0.1):
        raise ConfigError("experiment.fixed_delta_s must be within [0.02, 0.1]")
    if cfg["experiment"]["mode"] not in {"shield", "baseline"}:
        raise ConfigError("experiment.mode must be 'shield' or 'baseline'")
    horizons = cfg["safety"]["horizons_s"]
    if not horizons or any(float(h) <= 0 for h in horizons):
        raise ConfigError("safety.horizons_s must contain positive values")
    if int(cfg["camera"]["width"]) % 2 or int(cfg["camera"]["height"]) % 2:
        raise ConfigError("camera dimensions must be even for H.264 encoding")
