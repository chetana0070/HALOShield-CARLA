from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any


@dataclass(frozen=True)
class Vec2:
    x: float
    y: float

    def dot(self, other: "Vec2") -> float:
        return self.x * other.x + self.y * other.y

    def norm(self) -> float:
        return (self.x * self.x + self.y * self.y) ** 0.5

    def __add__(self, other: "Vec2") -> "Vec2":
        return Vec2(self.x + other.x, self.y + other.y)

    def __sub__(self, other: "Vec2") -> "Vec2":
        return Vec2(self.x - other.x, self.y - other.y)

    def __mul__(self, scale: float) -> "Vec2":
        return Vec2(self.x * scale, self.y * scale)


@dataclass(frozen=True)
class ActorState:
    actor_id: int
    kind: str
    position: Vec2
    velocity: Vec2
    half_length: float
    half_width: float


@dataclass(frozen=True)
class EgoState:
    position: Vec2
    velocity: Vec2
    forward: Vec2
    right: Vec2
    half_length: float
    half_width: float
    speed_mps: float


@dataclass
class NominalControl:
    throttle: float
    brake: float
    steer: float


@dataclass
class SafetyDecision:
    risk_level: str = "CLEAR"
    risk_score: float = 0.0
    min_ttc_s: float | None = None
    min_predicted_clearance_m: float | None = None
    threat_actor_id: int | None = None
    intervention: bool = False
    brake_override: float = 0.0
    throttle_cap: float = 1.0
    reason: str = "no threat"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
