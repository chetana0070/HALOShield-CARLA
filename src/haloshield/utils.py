from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def wrap_angle_rad(angle: float) -> float:
    while angle > math.pi:
        angle -= 2 * math.pi
    while angle < -math.pi:
        angle += 2 * math.pi
    return angle


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
