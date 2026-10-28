from __future__ import annotations

import math
import random
from dataclasses import dataclass

from .types import ActorState, EgoState, NominalControl
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



@dataclass(frozen=True)
class FollowingStatus:
    active: bool = False
    actor_id: int | None = None
    gap_m: float | None = None
    desired_gap_m: float | None = None
    closing_speed_mps: float | None = None


class AdaptiveCruiseSupervisor:
    """Nominal same-lane car-following controller.

    Ordinary traffic following belongs in the nominal autonomy stack.
    HALOShield should remain an emergency predictive override rather
    than becoming the everyday longitudinal controller.
    """

    def __init__(self, cfg: dict) -> None:
        self.enabled = bool(
            cfg.get("following_enabled", True)
        )

        self.time_gap_s = float(
            cfg.get("following_time_gap_s", 1.5)
        )

        self.min_gap_m = float(
            cfg.get("following_min_gap_m", 7.0)
        )

        self.buffer_m = float(
            cfg.get("following_buffer_m", 10.0)
        )

        self.k_gap = float(
            cfg.get("following_k_gap", 0.10)
        )

        self.k_closing = float(
            cfg.get("following_k_closing", 0.14)
        )

        self.max_brake = float(
            cfg.get("following_max_brake", 0.45)
        )

        self.corridor_half_width_m = float(
            cfg.get(
                "following_corridor_half_width_m",
                1.8,
            )
        )

    def apply(
        self,
        nominal: NominalControl,
        ego: EgoState,
        actors: list[ActorState],
    ) -> tuple[NominalControl, FollowingStatus]:

        if not self.enabled:
            return nominal, FollowingStatus()

        nearest = None

        for actor in actors:

            # ACC handles vehicles only.
            # Pedestrians remain part of the independent safety monitor.
            if not actor.kind.startswith("vehicle."):
                continue

            rel = actor.position - ego.position

            forward_dist = rel.dot(ego.forward)

            if forward_dist <= 0.0:
                continue

            lateral_dist = abs(
                rel.dot(ego.right)
            )

            lateral_limit = (
                self.corridor_half_width_m
                + actor.half_width
            )

            if lateral_dist > lateral_limit:
                continue

            gap_m = max(
                0.0,
                forward_dist
                - ego.half_length
                - actor.half_length,
            )

            actor_long_speed = (
                actor.velocity.dot(ego.forward)
            )

            ego_long_speed = (
                ego.velocity.dot(ego.forward)
            )

            closing_speed = (
                ego_long_speed
                - actor_long_speed
            )

            if (
                nearest is None
                or gap_m < nearest[0]
            ):
                nearest = (
                    gap_m,
                    closing_speed,
                    actor.actor_id,
                )

        if nearest is None:
            return nominal, FollowingStatus()

        gap_m, closing_speed, actor_id = nearest

        desired_gap_m = (
            self.min_gap_m
            + self.time_gap_s
            * max(ego.speed_mps, 0.0)
        )

        soft_limit_m = (
            desired_gap_m
            + self.buffer_m
        )

        if gap_m > soft_limit_m:
            return (
                nominal,
                FollowingStatus(
                    False,
                    actor_id,
                    gap_m,
                    desired_gap_m,
                    closing_speed,
                ),
            )

        status = FollowingStatus(
            True,
            actor_id,
            gap_m,
            desired_gap_m,
            closing_speed,
        )

        # Inside desired gap:
        # normal ACC applies moderate braking.
        if gap_m <= desired_gap_m:

            gap_error = (
                desired_gap_m
                - gap_m
            )

            brake = clamp(
                self.k_gap * gap_error
                + self.k_closing
                * max(closing_speed, 0.0),
                0.0,
                self.max_brake,
            )

            return (
                NominalControl(
                    throttle=0.0,
                    brake=max(
                        nominal.brake,
                        brake,
                    ),
                    steer=nominal.steer,
                ),
                status,
            )

        # Soft approach zone:
        # progressively remove throttle before braking
        # becomes necessary.
        throttle_scale = clamp(
            (
                gap_m
                - desired_gap_m
            )
            / max(
                self.buffer_m,
                0.1,
            ),
            0.0,
            1.0,
        )

        throttle = min(
            nominal.throttle,
            nominal.throttle
            * throttle_scale,
        )

        if closing_speed > 1.0:
            throttle = 0.0

        return (
            NominalControl(
                throttle=throttle,
                brake=nominal.brake,
                steer=nominal.steer,
            ),
            status,
        )
