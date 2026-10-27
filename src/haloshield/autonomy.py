from __future__ import annotations

import math
import random
from dataclasses import dataclass

from .types import NominalControl
from .utils import clamp, wrap_angle_rad


@dataclass
class PIDState:
    integral: float = 0.0
    previous_error: float = 0.0


class RoadFollower:
    """Readable lane-center waypoint follower with deterministic seeded branching."""

    def __init__(self, world_map, cfg: dict, seed: int) -> None:
        self.map = world_map
        self.cfg = cfg
        self.rng = random.Random(seed ^ 0xA17E5AFE)
        self.target_waypoint = None
        self.speed_pid = PIDState()
        self.previous_heading_error = 0.0

    def reset(self, ego) -> None:
        self.target_waypoint = self.map.get_waypoint(ego.get_location(), project_to_road=True)
        self.speed_pid = PIDState()
        self.previous_heading_error = 0.0
        self._advance_target(float(self.cfg["lookahead_m"]))

    def _choose_next(self, candidates):
        if len(candidates) == 1:
            return candidates[0]
        current_yaw = float(self.target_waypoint.transform.rotation.yaw)
        def yaw_delta(candidate):
            delta = (float(candidate.transform.rotation.yaw) - current_yaw + 180.0) % 360.0 - 180.0
            return abs(delta)
        ranked = sorted(candidates, key=yaw_delta)
        # Prefer the straightest continuation so the ego and scripted lead remain
        # in the same traffic corridor. Seeded tie-breaking preserves reproducibility.
        best_delta = yaw_delta(ranked[0])
        tied = [c for c in ranked if abs(yaw_delta(c) - best_delta) < 2.0]
        return tied[self.rng.randrange(len(tied))]

    def _advance_target(self, distance_m: float) -> None:
        if self.target_waypoint is None:
            return
        remaining = distance_m
        step = float(self.cfg["waypoint_step_m"])
        while remaining > 0:
            candidates = self.target_waypoint.next(min(step, remaining))
            if not candidates:
                break
            self.target_waypoint = self._choose_next(candidates)
            remaining -= step

    def control(self, ego, dt: float, target_speed_mps: float) -> NominalControl:
        if self.target_waypoint is None:
            self.reset(ego)
        location = ego.get_location()
        target_loc = self.target_waypoint.transform.location
        if location.distance(target_loc) < max(2.5, float(self.cfg["lookahead_m"]) * 0.55):
            self._advance_target(float(self.cfg["lookahead_m"]))
            target_loc = self.target_waypoint.transform.location

        transform = ego.get_transform()
        yaw = math.radians(transform.rotation.yaw)
        desired = math.atan2(target_loc.y - location.y, target_loc.x - location.x)
        heading_error = wrap_angle_rad(desired - yaw)
        derivative = (heading_error - self.previous_heading_error) / max(dt, 1e-3)
        self.previous_heading_error = heading_error
        steer = clamp(float(self.cfg["steer_kp"]) * heading_error + float(self.cfg["steer_kd"]) * derivative, -1.0, 1.0)

        velocity = ego.get_velocity()
        speed = math.sqrt(velocity.x ** 2 + velocity.y ** 2 + velocity.z ** 2)
        error = target_speed_mps - speed
        self.speed_pid.integral = clamp(self.speed_pid.integral + error * dt, -10.0, 10.0)
        derivative_v = (error - self.speed_pid.previous_error) / max(dt, 1e-3)
        self.speed_pid.previous_error = error
        effort = (
            float(self.cfg["speed_kp"]) * error
            + float(self.cfg["speed_ki"]) * self.speed_pid.integral
            + float(self.cfg["speed_kd"]) * derivative_v
        )
        if effort >= 0:
            throttle = clamp(effort, 0.0, float(self.cfg["max_throttle"]))
            brake = 0.0
        else:
            throttle = 0.0
            brake = clamp(-effort, 0.0, float(self.cfg["max_brake"]))
        return NominalControl(throttle, brake, steer)
