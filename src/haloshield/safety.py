from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable

from .types import ActorState, EgoState, NominalControl, SafetyDecision, Vec2
from .utils import clamp


@dataclass(frozen=True)
class SafetyConfig:
    monitor_range_m: float
    corridor_half_width_m: float
    horizons_s: tuple[float, ...]
    base_margin_m: float
    uncertainty_initial_m: float
    uncertainty_growth_mps: float
    caution_ttc_s: float
    warning_ttc_s: float
    critical_ttc_s: float
    warning_clearance_m: float
    critical_clearance_m: float
    warning_brake: float
    critical_brake: float
    hold_s: float

    @classmethod
    def from_mapping(cls, cfg: dict) -> "SafetyConfig":
        return cls(
            monitor_range_m=float(cfg["monitor_range_m"]),
            corridor_half_width_m=float(cfg["corridor_half_width_m"]),
            horizons_s=tuple(float(v) for v in cfg["horizons_s"]),
            base_margin_m=float(cfg["base_margin_m"]),
            uncertainty_initial_m=float(cfg["uncertainty_initial_m"]),
            uncertainty_growth_mps=float(cfg["uncertainty_growth_mps"]),
            caution_ttc_s=float(cfg["caution_ttc_s"]),
            warning_ttc_s=float(cfg["warning_ttc_s"]),
            critical_ttc_s=float(cfg["critical_ttc_s"]),
            warning_clearance_m=float(cfg["warning_clearance_m"]),
            critical_clearance_m=float(cfg["critical_clearance_m"]),
            warning_brake=float(cfg["warning_brake"]),
            critical_brake=float(cfg["critical_brake"]),
            hold_s=float(cfg["hold_s"]),
        )


class PredictiveSafetyShield:
    """Independent short-horizon safety monitor.

    It assumes constant velocity over a small horizon and inflates actor safety
    envelopes as prediction horizon grows. The uncertainty growth is deliberately
    simple and inspectable: this project studies the safety-system architecture,
    not a black-box trajectory predictor.
    """

    def __init__(self, cfg: SafetyConfig) -> None:
        self.cfg = cfg
        self._hold_until_s = -1.0
        self._held_brake = 0.0

    def evaluate(self, ego: EgoState, actors: Iterable[ActorState], sim_time_s: float) -> SafetyDecision:
        best = SafetyDecision()
        for actor in actors:
            rel = actor.position - ego.position
            forward_dist = rel.dot(ego.forward)
            lateral_dist = abs(rel.dot(ego.right))
            if forward_dist <= -2.0 or forward_dist > self.cfg.monitor_range_m:
                continue
            lateral_limit = self.cfg.corridor_half_width_m + actor.half_width
            if lateral_dist > lateral_limit:
                continue

            relative_velocity = ego.velocity - actor.velocity
            closing_speed = relative_velocity.dot(ego.forward)
            safe_long = ego.half_length + actor.half_length + self.cfg.base_margin_m
            ttc = None
            if closing_speed > 0.15 and forward_dist > safe_long:
                ttc = max(0.0, (forward_dist - safe_long) / closing_speed)

            min_clearance = math.inf
            for horizon in self.cfg.horizons_s:
                ego_future = ego.position + ego.velocity * horizon
                actor_future = actor.position + actor.velocity * horizon
                separation = (actor_future - ego_future).norm()
                uncertainty = self.cfg.uncertainty_initial_m + self.cfg.uncertainty_growth_mps * horizon
                envelope = (
                    max(ego.half_length, ego.half_width)
                    + max(actor.half_length, actor.half_width)
                    + self.cfg.base_margin_m
                    + uncertainty
                )
                min_clearance = min(min_clearance, separation - envelope)

            risk_ttc = 0.0 if ttc is None else clamp((self.cfg.caution_ttc_s - ttc) / self.cfg.caution_ttc_s, 0.0, 1.0)
            risk_clearance = clamp((self.cfg.warning_clearance_m - min_clearance) / max(self.cfg.warning_clearance_m, 0.1), 0.0, 1.0)
            score = max(risk_ttc, risk_clearance)

            candidate = self._decision(actor.actor_id, ttc, min_clearance, score)
            if candidate.risk_score > best.risk_score or (
                candidate.risk_score == best.risk_score and candidate.brake_override > best.brake_override
            ):
                best = candidate

        if best.intervention:
            self._hold_until_s = sim_time_s + self.cfg.hold_s
            self._held_brake = max(self._held_brake, best.brake_override)
        elif sim_time_s < self._hold_until_s:
            best = SafetyDecision(
                risk_level="HOLD",
                risk_score=0.35,
                intervention=True,
                brake_override=self._held_brake,
                throttle_cap=0.0,
                reason="intervention hysteresis",
            )
        else:
            self._held_brake = 0.0
        return best

    def _decision(self, actor_id: int, ttc: float | None, clearance: float, score: float) -> SafetyDecision:
        critical = (ttc is not None and ttc <= self.cfg.critical_ttc_s) or clearance <= self.cfg.critical_clearance_m
        warning = (ttc is not None and ttc <= self.cfg.warning_ttc_s) or clearance <= self.cfg.warning_clearance_m
        caution = ttc is not None and ttc <= self.cfg.caution_ttc_s
        if critical:
            return SafetyDecision("CRITICAL", score, ttc, clearance, actor_id, True, self.cfg.critical_brake, 0.0, "predicted collision envelope")
        if warning:
            return SafetyDecision("WARNING", score, ttc, clearance, actor_id, True, self.cfg.warning_brake, 0.0, "short TTC / low predicted clearance")
        if caution:
            return SafetyDecision("CAUTION", score, ttc, clearance, actor_id, False, 0.0, 0.35, "closing actor ahead")
        return SafetyDecision("CLEAR", score, ttc, clearance, actor_id, False, 0.0, 1.0, "monitored actor remains outside intervention thresholds")

    def apply(self, nominal: NominalControl, decision: SafetyDecision, enabled: bool = True) -> NominalControl:
        if not enabled:
            return nominal
        throttle = min(nominal.throttle, decision.throttle_cap)
        brake = max(nominal.brake, decision.brake_override)
        if brake > 0.05:
            throttle = 0.0
        return NominalControl(throttle=clamp(throttle, 0.0, 1.0), brake=clamp(brake, 0.0, 1.0), steer=clamp(nominal.steer, -1.0, 1.0))
