from __future__ import annotations

import csv
import math
from dataclasses import dataclass, field
from pathlib import Path
from statistics import mean
from typing import Any


@dataclass
class MetricsCollector:
    rows: list[dict[str, Any]] = field(default_factory=list)
    collision_events: list[dict[str, Any]] = field(default_factory=list)
    interventions: int = 0
    near_miss_ticks: int = 0
    min_ttc_s: float | None = None
    min_clearance_m: float | None = None
    distance_m: float = 0.0
    previous_location: tuple[float, float, float] | None = None

    def record_collision(self, event: dict[str, Any]) -> None:
        self.collision_events.append(event)

    def record_tick(self, row: dict[str, Any], location_xyz: tuple[float, float, float]) -> None:
        if self.previous_location is not None:
            dx = location_xyz[0] - self.previous_location[0]
            dy = location_xyz[1] - self.previous_location[1]
            dz = location_xyz[2] - self.previous_location[2]
            self.distance_m += math.sqrt(dx * dx + dy * dy + dz * dz)
        self.previous_location = location_xyz
        if row.get("intervention"):
            self.interventions += 1
        ttc = row.get("min_ttc_s")
        if ttc is not None:
            self.min_ttc_s = ttc if self.min_ttc_s is None else min(self.min_ttc_s, ttc)
            if ttc < 1.5:
                self.near_miss_ticks += 1
        clearance = row.get("min_predicted_clearance_m")
        if clearance is not None:
            self.min_clearance_m = clearance if self.min_clearance_m is None else min(self.min_clearance_m, clearance)
        self.rows.append(row)

    def summary(self, duration_s: float, termination_reason: str) -> dict[str, Any]:
        speeds = [float(row["speed_mps"]) for row in self.rows] if self.rows else []
        shield_latency = [float(row["safety_latency_ms"]) for row in self.rows if row.get("safety_latency_ms") is not None]
        unique_intervention_events = 0
        was_active = False
        for row in self.rows:
            active = bool(row.get("intervention"))
            if active and not was_active:
                unique_intervention_events += 1
            was_active = active
        return {
            "duration_s": round(duration_s, 3),
            "termination_reason": termination_reason,
            "collisions": len(self.collision_events),
            "intervention_ticks": self.interventions,
            "intervention_events": unique_intervention_events,
            "near_miss_ticks_ttc_lt_1_5": self.near_miss_ticks,
            "min_ttc_s": None if self.min_ttc_s is None else round(self.min_ttc_s, 3),
            "min_predicted_clearance_m": None if self.min_clearance_m is None else round(self.min_clearance_m, 3),
            "distance_m": round(self.distance_m, 2),
            "mean_speed_mps": round(mean(speeds), 3) if speeds else 0.0,
            "mean_safety_latency_ms": round(mean(shield_latency), 4) if shield_latency else 0.0,
            "max_safety_latency_ms": round(max(shield_latency), 4) if shield_latency else 0.0,
        }

    def write_csv(self, path: Path) -> None:
        if not self.rows:
            path.write_text("", encoding="utf-8")
            return
        keys = list(self.rows[0].keys())
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=keys)
            writer.writeheader()
            writer.writerows(self.rows)
