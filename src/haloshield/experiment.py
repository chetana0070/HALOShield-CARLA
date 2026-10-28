from __future__ import annotations

import csv
import json
import math
import random
import secrets
import signal
import subprocess
import threading
import time
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import yaml

from .autonomy import AdaptiveCruiseSupervisor, RoadFollower
from .carla_bridge import CarlaServerManager, import_carla
from .dashboard import Dashboard
from .logging_utils import configure_logging, log
from .metrics import MetricsCollector
from .recorder import VideoRecorder
from .reporting import write_safety_report
from .safety import PredictiveSafetyShield, SafetyConfig
from .scenario import ScenarioSpec, generate_scenario, scenario_from_dict
from .system import collect_system_info, disk_free_gb
from .types import ActorState, EgoState, NominalControl, Vec2
from .utils import write_json


class CameraBuffer:
    def __init__(self, width: int, height: int) -> None:
        self.width = width
        self.height = height
        self._lock = threading.Lock()
        self._frame: np.ndarray | None = None
        self._frame_number = -1

    def callback(self, image) -> None:
        array = np.frombuffer(image.raw_data, dtype=np.uint8).reshape((self.height, self.width, 4))
        rgb = array[:, :, :3][:, :, ::-1].copy()
        with self._lock:
            self._frame = rgb
            self._frame_number = int(image.frame)

    def latest(self) -> tuple[np.ndarray | None, int]:
        with self._lock:
            return (None if self._frame is None else self._frame.copy(), self._frame_number)


class ExperimentRunner:
    def __init__(self, cfg: dict[str, Any], seed: int | None = None, headless: bool = False, mode: str | None = None, output_root: Path | None = None, replay_scenario: dict[str, Any] | None = None) -> None:
        self.cfg = cfg
        self.seed = int(seed if seed is not None else secrets.randbits(32))
        self.headless = headless
        self.mode = mode or str(cfg["experiment"]["mode"])
        self.replay_scenario = replay_scenario
        if replay_scenario is not None:
            self.seed = int(replay_scenario["seed"])
        self.output_root = output_root or Path(cfg["storage"]["output_root"])
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        self.run_dir = self.output_root / f"{timestamp}_seed-{self.seed}_{self.mode}"
        self.run_dir.mkdir(parents=True, exist_ok=False)
        self.logger = configure_logging(self.run_dir / "run.log")
        self.stop_requested = False
        self.actors: list[Any] = []
        self.walker_controllers: list[Any] = []
        self.sensors: list[Any] = []
        self.events: list[dict[str, Any]] = []
        self.original_world_settings = None
        self.tm = None
        self.world = None
        self.server = CarlaServerManager(cfg["server"], self.run_dir / "carla_server.log")
        self._old_signal_handlers: dict[int, Any] = {}

    def run(self) -> dict[str, Any]:
        carla = import_carla()
        self._install_signal_handlers()
        video: VideoRecorder | None = None
        dashboard: Dashboard | None = None
        metrics = MetricsCollector()
        start_wall = time.monotonic()
        termination_reason = "completed"
        scenario: ScenarioSpec | None = None
        try:
            self._preflight()
            info = collect_system_info(Path.cwd())
            info.update({
                "selected_carla_version": "0.9.16",
                "selected_quality": self.cfg["server"]["quality"],
                "camera_resolution": [self.cfg["camera"]["width"], self.cfg["camera"]["height"]],
                "experiment_mode": self.mode,
            })
            write_json(self.run_dir / "system_info.json", info)
            log(self.logger, "SETUP", f"GPU: {info.get('gpu', {}).get('name', 'unknown')} / VRAM {info.get('gpu', {}).get('memory_total_mib', 'unknown')} MiB")
            log(self.logger, "SETUP", f"RAM: {info.get('ram_total_gib')} GiB / disk free: {info.get('disk_free_gib')} GiB")
            started = self.server.start_if_needed()
            log(self.logger, "CARLA", "Launching packaged CARLA 0.9.16" if started else "Using CARLA server already listening on port 2000")
            self.server.wait_until_ready()

            client = carla.Client(str(self.cfg["server"]["host"]), int(self.cfg["server"]["port"]))
            client.set_timeout(120.0)
            available_maps = client.get_available_maps()
            scenario = scenario_from_dict(self.replay_scenario) if self.replay_scenario is not None else generate_scenario(self.seed, self.cfg, available_maps)
            write_json(self.run_dir / "scenario.json", scenario.to_dict())
            with (self.run_dir / "config_snapshot.yaml").open("w", encoding="utf-8") as handle:
                yaml.safe_dump(self.cfg, handle, sort_keys=False)
            log(self.logger, "SCENARIO", f"seed={self.seed} map={scenario.map_name.split('/')[-1]} weather={scenario.weather}")

            self.world = client.load_world(scenario.map_name)
            self._configure_world(carla, scenario)
            self.tm = client.get_trafficmanager(int(self.cfg["traffic"]["tm_port"]))
            self._configure_traffic_manager()
            ego, lead = self._spawn_core_actors(carla, scenario)
            self._spawn_background_traffic(carla, scenario, ego, lead)
            camera_buffer = self._spawn_sensors(carla, ego, metrics)

            controller = RoadFollower(self.world.get_map(), self.cfg["controller"], self.seed)
            controller.reset(ego)
            lead_controller = RoadFollower(self.world.get_map(), self.cfg["controller"], self.seed ^ 0x1155AA77)
            lead_controller.reset(lead)
            shield = PredictiveSafetyShield(SafetyConfig.from_mapping(self.cfg["safety"]))
            following_supervisor = AdaptiveCruiseSupervisor(
                self.cfg["controller"]
            )

            camera_cfg = self.cfg["camera"]
            rec_cfg = self.cfg["recording"]
            dashboard = Dashboard(int(camera_cfg["width"]), int(camera_cfg["height"]), self.headless)
            video = VideoRecorder(
                self.run_dir / "demo.mp4",
                int(camera_cfg["width"]), int(camera_cfg["height"]), int(rec_cfg["fps"]),
                bool(rec_cfg["prefer_nvenc"]), int(rec_cfg["crf"]),
            )
            log(self.logger, "VIDEO", f"Recording via {video.encoder} to {self.run_dir / 'demo.mp4'}")

            duration_s = float(self.cfg["experiment"]["duration_s"])
            dt = float(self.cfg["experiment"]["fixed_delta_s"])
            target_speed = float(self.cfg["experiment"]["target_speed_mps"])
            warmup_s = float(self.cfg["experiment"].get("warmup_s", 0.0))
            last_recorded_camera_frame = -1
            sim_time = 0.0
            event_state: dict[int, bool] = {}
            event_done: dict[int, bool] = {}
            event_started_at: dict[int, float] = {}
            next_status = 0.0

            # Prime synchronous sensors and physics.
            for _ in range(max(2, int(warmup_s / dt))):
                self.world.tick(120.0)
                if self.stop_requested:
                    break
            warm_frame, _ = camera_buffer.latest()
            if warm_frame is None:
                raise RuntimeError("RGB camera produced no frames during warmup; cannot create the required demo video.")

            while sim_time < duration_s and not self.stop_requested:
                loop_start = time.perf_counter()

                # Service the Pygame/desktop event queue every simulation tick.
                # Without this, GNOME may label the visualization window
                # "not responding" even though CARLA is still running.
                try:
                    import pygame

                    for event in pygame.event.get():
                        if event.type == pygame.QUIT:
                            self.stop_requested = True
                except Exception:
                    pass

                if self.stop_requested:
                    break
                # ------------------------------------------------------------
                # Scenario supervisor
                #
                # Hazard trigger_s is now the EARLIEST eligible time, rather
                # than an unconditional wall-clock trigger. A hard-braking
                # event is only activated when the ego is actually moving and
                # the scripted lead is within a scientifically useful gap.
                # ------------------------------------------------------------

                ego_speed_before = self._speed(ego)
                ego_red_light = self._must_stop_for_red_light(
                    ego,
                    carla,
                )

                gap_m = float(
                    ego.get_location().distance(
                        lead.get_location()
                    )
                )

                desired_gap_m = float(scenario.lead_distance_m)

                # Pace the scripted lead so red lights and other delays do not
                # make it disappear far ahead of the ego vehicle.
                lead_target_speed = target_speed * 0.88

                if gap_m > desired_gap_m + 8.0:
                    lead_target_speed = target_speed * 0.55
                elif gap_m < max(12.0, desired_gap_m - 8.0):
                    lead_target_speed = target_speed

                lead_nominal = lead_controller.control(
                    lead,
                    dt,
                    lead_target_speed,
                )

                # Keep the scripted lead coupled to the experiment when the
                # ego is legitimately stopped at a signal.
                if ego_red_light or self._must_stop_for_red_light(
                    lead,
                    carla,
                ):
                    lead_nominal = NominalControl(
                        0.0,
                        max(lead_nominal.brake, 0.75),
                        lead_nominal.steer,
                    )

                phase = "nominal"
                active_hazard = False

                min_hazard_speed = float(
                    self.cfg["scenario"].get(
                        "hazard_min_ego_speed_mps",
                        4.0,
                    )
                )

                valid_gap = self.cfg["scenario"].get(
                    "hazard_valid_gap_m",
                    [10.0, 45.0],
                )

                min_gap_m = float(valid_gap[0])
                max_gap_m = float(valid_gap[1])

                for idx, event in enumerate(
                    scenario.hazard_events
                ):
                    started_at = event_started_at.get(idx)

                    # trigger_s means "not before this simulation time".
                    # Actual activation waits until the physical state makes
                    # the experiment meaningful.
                    if started_at is None:
                        eligible = (
                            sim_time >= float(event.trigger_s)
                            and ego_speed_before >= min_hazard_speed
                            and not ego_red_light
                            and min_gap_m <= gap_m <= max_gap_m
                        )

                        if eligible:
                            started_at = sim_time
                            event_started_at[idx] = sim_time
                            event_state[idx] = True

                            phase = (
                                f"lead-hard-brake-{idx + 1}"
                            )

                            self.events.append(
                                {
                                    "sim_time_s": sim_time,
                                    "type": "hazard_start",
                                    "detail": (
                                        f"{phase}; "
                                        f"scheduled_not_before="
                                        f"{event.trigger_s:.2f}; "
                                        f"ego_speed_mps="
                                        f"{ego_speed_before:.2f}; "
                                        f"gap_m={gap_m:.2f}"
                                    ),
                                }
                            )

                            log(
                                self.logger,
                                "SCENARIO",
                                f"Hazard {idx + 1} started "
                                f"at t={sim_time:.1f}s "
                                f"(eligible after "
                                f"{event.trigger_s:.1f}s, "
                                f"speed={ego_speed_before:.1f}m/s, "
                                f"gap={gap_m:.1f}m)",
                            )

                    started_at = event_started_at.get(idx)

                    active = (
                        started_at is not None
                        and started_at
                        <= sim_time
                        < started_at + float(event.duration_s)
                    )

                    if active:
                        active_hazard = True
                        phase = f"lead-hard-brake-{idx + 1}"

                        lead.apply_control(
                            carla.VehicleControl(
                                throttle=0.0,
                                brake=float(event.brake),
                                steer=lead_nominal.steer,
                            )
                        )

                    elif (
                        started_at is not None
                        and not event_done.get(idx)
                        and sim_time
                        >= started_at + float(event.duration_s)
                    ):
                        event_done[idx] = True

                        self.events.append(
                            {
                                "sim_time_s": sim_time,
                                "type": "hazard_end",
                                "detail": (
                                    f"lead-hard-brake-{idx + 1}"
                                ),
                            }
                        )

                        log(
                            self.logger,
                            "SCENARIO",
                            f"Hazard {idx + 1} ended "
                            f"at t={sim_time:.1f}s",
                        )

                if not active_hazard:
                    lead.apply_control(
                        carla.VehicleControl(
                            throttle=lead_nominal.throttle,
                            brake=lead_nominal.brake,
                            steer=lead_nominal.steer,
                        )
                    )

                nominal = controller.control(ego, dt, target_speed)
                if self._must_stop_for_red_light(ego, carla):
                    nominal = NominalControl(0.0, max(nominal.brake, 0.75), nominal.steer)
                    phase = "red-light-compliance"

                ego_state = self._ego_state(ego)
                nearby = self._nearby_actor_states(ego)

                following_status = None

                if phase != "red-light-compliance":
                    nominal, following_status = (
                        following_supervisor.apply(
                            nominal,
                            ego_state,
                            nearby,
                        )
                    )

                    if (
                        following_status.active
                        and phase == "nominal"
                    ):
                        phase = "car-following"

                safety_start = time.perf_counter()
                decision = shield.evaluate(ego_state, nearby, sim_time)
                safety_latency_ms = (time.perf_counter() - safety_start) * 1000.0
                final = shield.apply(
                    nominal,
                    decision,
                    enabled=self.mode == "shield",
                )

                shield_changed_control = (
                    self.mode == "shield"
                    and (
                        final.brake
                        > nominal.brake + 1e-4
                        or final.throttle
                        < nominal.throttle - 1e-4
                    )
                )

                ego.apply_control(carla.VehicleControl(throttle=final.throttle, brake=final.brake, steer=final.steer))

                self.world.tick(45.0)
                snapshot = self.world.get_snapshot()
                sim_time += dt
                speed = self._speed(ego)
                transform = ego.get_transform()
                loc = transform.location
                row = {
                    "sim_time_s": round(sim_time, 3),
                    "speed_mps": round(speed, 4),
                    "throttle_nominal": round(nominal.throttle, 4),
                    "brake_nominal": round(nominal.brake, 4),
                    "throttle_applied": round(final.throttle, 4),
                    "brake_applied": round(final.brake, 4),
                    "steer": round(final.steer, 4),
                    "risk_level": decision.risk_level,
                    "risk_score": round(decision.risk_score, 4),
                    "min_ttc_s": None if decision.min_ttc_s is None else round(decision.min_ttc_s, 4),
                    "min_predicted_clearance_m": None if decision.min_predicted_clearance_m is None else round(decision.min_predicted_clearance_m, 4),
                    "threat_actor_id": decision.threat_actor_id,
                    "intervention": bool(shield_changed_control),
                    "shield_requested_intervention": bool(
                        decision.intervention
                    ),
                    "following_actor_id": (
                        None
                        if following_status is None
                        else following_status.actor_id
                    ),
                    "following_gap_m": (
                        None
                        if following_status is None
                        or following_status.gap_m is None
                        else round(
                            following_status.gap_m,
                            3,
                        )
                    ),
                    "following_desired_gap_m": (
                        None
                        if following_status is None
                        or following_status.desired_gap_m is None
                        else round(
                            following_status.desired_gap_m,
                            3,
                        )
                    ),
                    "following_closing_speed_mps": (
                        None
                        if following_status is None
                        or following_status.closing_speed_mps is None
                        else round(
                            following_status.closing_speed_mps,
                            3,
                        )
                    ),
                    "safety_latency_ms": round(safety_latency_ms, 5),
                    "scenario_phase": phase,
                    "frame": int(snapshot.frame),
                }
                metrics.record_tick(row, (loc.x, loc.y, loc.z))

                frame, frame_no = camera_buffer.latest()
                if frame is not None and frame_no != last_recorded_camera_frame:
                    hud = {
                        **row,
                        "mode": self.mode,
                        "elapsed_s": sim_time,
                        "duration_s": duration_s,
                        "seed": self.seed,
                    }
                    rendered, keep_running = dashboard.render(frame, hud)
                    video.write(rendered)
                    last_recorded_camera_frame = frame_no
                    if not keep_running:
                        self.stop_requested = True
                        termination_reason = "dashboard_closed"

                if sim_time >= next_status:
                    log(
                        self.logger,
                        "METRICS",
                        f"t={sim_time:5.1f}s "
                        f"speed={speed*3.6:4.1f}km/h "
                        f"phase={phase} "
                        f"nominal=T{nominal.throttle:.2f}/B{nominal.brake:.2f} "
                        f"applied=T{final.throttle:.2f}/B{final.brake:.2f} "
                        f"risk={decision.risk_level} "
                        f"interventions={metrics.interventions}",
                    )
                    next_status += 10.0

                # Catch runaway loop stalls without changing simulator determinism.
                if time.perf_counter() - loop_start > 2.0:
                    self.events.append({"sim_time_s": sim_time, "type": "high_loop_latency", "detail": "control loop exceeded 2 wall-clock seconds"})

            if self.stop_requested and termination_reason == "completed":
                termination_reason = "interrupt_requested"

            elapsed = min(sim_time, duration_s)
            summary = metrics.summary(elapsed, termination_reason)
            summary.update({
                "seed": self.seed,
                "mode": self.mode,
                "video_encoder": video.encoder,
                "video_frames": video.frames_written,
                "wall_clock_s": round(time.monotonic() - start_wall, 2),
                "project_version": self.cfg["project"]["version"],
                "git_commit": self._git_commit(),
                "carla_version": "0.9.16",
            })
            metrics.write_csv(self.run_dir / "telemetry.csv")
            with (self.run_dir / "metrics.csv").open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=list(summary.keys()))
                writer.writeheader()
                writer.writerow(summary)
            write_json(self.run_dir / "summary.json", summary)
            self._write_events()
            write_safety_report(self.run_dir / "safety_report.md", scenario.to_dict(), summary, info, self.mode, self.events)
            log(self.logger, "REPORT", f"Run complete: {self.run_dir}")
            return summary
        except KeyboardInterrupt:
            termination_reason = "keyboard_interrupt"
            raise
        except Exception as exc:
            self.events.append({"sim_time_s": 0.0, "type": "exception", "detail": repr(exc)})
            self._write_events()
            log(self.logger, "RUN", f"ERROR: {exc}", level=40)
            raise
        finally:
            if video:
                try:
                    video.close()
                except Exception as exc:
                    log(self.logger, "VIDEO", f"Video finalization warning: {exc}", level=30)
            if dashboard:
                dashboard.close()
            self._cleanup()
            self.server.stop()
            self._restore_signal_handlers()

    def _preflight(self) -> None:
        free = disk_free_gb(Path.cwd())
        minimum = float(self.cfg["storage"]["min_free_before_run_gb"])
        if free < minimum:
            raise RuntimeError(f"Only {free:.1f} GiB free; at least {minimum:.1f} GiB is required before a run.")
        if not subprocess.run(["bash", "-lc", "command -v ffmpeg >/dev/null"], check=False).returncode == 0:
            raise RuntimeError("ffmpeg is required for automatic demo recording. Install it with: sudo apt install ffmpeg")
        if self.mode not in {"shield", "baseline"}:
            raise RuntimeError("Mode must be 'shield' or 'baseline'")

    def _configure_world(self, carla, scenario: ScenarioSpec) -> None:
        self.original_world_settings = self.world.get_settings()
        settings = self.world.get_settings()
        settings.synchronous_mode = True
        settings.fixed_delta_seconds = float(self.cfg["experiment"]["fixed_delta_s"])
        settings.no_rendering_mode = False
        self.world.apply_settings(settings)
        weather = getattr(carla.WeatherParameters, scenario.weather, carla.WeatherParameters.ClearNoon)
        self.world.set_weather(weather)

    def _configure_traffic_manager(self) -> None:
        self.tm.set_synchronous_mode(True)
        self.tm.set_random_device_seed(self.seed)
        self.tm.set_global_distance_to_leading_vehicle(float(self.cfg["traffic"]["global_distance_m"]))
        if bool(self.cfg["traffic"].get("hybrid_physics", True)):
            self.tm.set_hybrid_physics_mode(True)
            self.tm.set_hybrid_physics_radius(float(self.cfg["traffic"].get("hybrid_radius_m", 60.0)))

    def _tick_world(self, timeout_s: float, context: str):
        """Advance synchronous CARLA simulation with a descriptive timeout."""
        if self.world is None:
            raise RuntimeError(
                f"{context}: CARLA world is not initialized"
            )

        try:
            return self.world.tick(float(timeout_s))
        except RuntimeError as exc:
            raise RuntimeError(
                f"{context}: CARLA tick failed after "
                f"{timeout_s:.0f}s timeout: {exc}"
            ) from exc

    def _spawn_core_actors(self, carla, scenario: ScenarioSpec):
        """
        Spawn the research ego + scripted lead pair.

        A candidate is rejected if either vehicle initially sits inside an
        active red/yellow traffic-light trigger. Starting there can make an
        otherwise valid experiment spend its opening seconds stationary,
        which is undesirable for the hazard-response study.
        """
        blueprints = self.world.get_blueprint_library()

        ego_bp = blueprints.find("vehicle.tesla.model3")
        if ego_bp is None:
            ego_candidates = [
                bp for bp in blueprints.filter("vehicle.*")
                if int(bp.get_attribute("number_of_wheels")) == 4
            ]
            if not ego_candidates:
                raise RuntimeError("No four-wheel vehicle blueprints are available")
            ego_bp = ego_candidates[0]

        if ego_bp.has_attribute("role_name"):
            ego_bp.set_attribute("role_name", "ego")

        lead_candidates = [
            bp for bp in blueprints.filter("vehicle.*")
            if int(bp.get_attribute("number_of_wheels")) == 4
        ]
        if not lead_candidates:
            raise RuntimeError("No valid lead-vehicle blueprints are available")

        rng = random.Random(self.seed ^ 0xC0FFEE)
        spawn_points = self.world.get_map().get_spawn_points()
        rng.shuffle(spawn_points)

        validation_timeout = float(
            self.cfg["server"].get("warmup_tick_timeout_s", 120.0)
        )

        for spawn in spawn_points[:min(40, len(spawn_points))]:
            ego = self.world.try_spawn_actor(ego_bp, spawn)
            if not ego:
                continue

            wp = self.world.get_map().get_waypoint(
                spawn.location,
                project_to_road=True,
            )

            lead_wp = wp
            remaining = scenario.lead_distance_m

            while remaining > 0 and lead_wp:
                options = lead_wp.next(min(3.0, remaining))

                if not options:
                    lead_wp = None
                    break

                current_yaw = lead_wp.transform.rotation.yaw

                lead_wp = min(
                    options,
                    key=lambda w: self._yaw_delta_deg(
                        current_yaw,
                        w.transform.rotation.yaw,
                    ),
                )

                remaining -= 3.0

            if lead_wp is None:
                try:
                    ego.destroy()
                except Exception:
                    pass
                continue

            lead_bp = rng.choice(lead_candidates)

            if lead_bp.has_attribute("role_name"):
                lead_bp.set_attribute(
                    "role_name",
                    "scripted_hazard",
                )

            lead_transform = lead_wp.transform
            lead_transform.location.z += 0.35

            lead = self.world.try_spawn_actor(
                lead_bp,
                lead_transform,
            )

            if not lead:
                try:
                    ego.destroy()
                except Exception:
                    pass
                continue

            # Explicitly ensure neither manually controlled vehicle inherits
            # an unintended parking state.
            ego.apply_control(
                carla.VehicleControl(
                    throttle=0.0,
                    brake=0.0,
                    hand_brake=False,
                )
            )

            lead.apply_control(
                carla.VehicleControl(
                    throttle=0.0,
                    brake=0.0,
                    hand_brake=False,
                )
            )

            # CARLA traffic-light association is based on the most recent
            # simulation tick, so tick once before validating the spawn.
            self._tick_world(
                validation_timeout,
                "core actor spawn validation",
            )

            ego_blocked = self._must_stop_for_red_light(
                ego,
                carla,
            )

            lead_blocked = self._must_stop_for_red_light(
                lead,
                carla,
            )

            if ego_blocked or lead_blocked:
                log(
                    self.logger,
                    "SCENARIO",
                    "Rejecting core spawn because it begins inside "
                    "an active red/yellow traffic-light trigger",
                    level=30,
                )

                try:
                    if lead.is_alive:
                        lead.destroy()
                except Exception:
                    pass

                try:
                    if ego.is_alive:
                        ego.destroy()
                except Exception:
                    pass

                # Commit the destruction before trying the next spawn.
                self._tick_world(
                    validation_timeout,
                    "rejected spawn cleanup",
                )

                continue

            self.actors.extend([ego, lead])

            log(
                self.logger,
                "SCENARIO",
                f"Spawned ego and scripted lead at "
                f"{scenario.lead_distance_m:.1f} m nominal separation",
            )

            return ego, lead

        raise RuntimeError(
            "Could not find a valid ego + lead spawn pair after "
            "rejecting occupied and traffic-light-blocked starts"
        )

    def _spawn_background_traffic(self, carla, scenario: ScenarioSpec, ego, lead) -> None:
        rng = random.Random(self.seed ^ 0xBADC0DE)
        blueprints = [bp for bp in self.world.get_blueprint_library().filter("vehicle.*") if int(bp.get_attribute("number_of_wheels")) == 4]
        spawn_points = self.world.get_map().get_spawn_points()
        rng.shuffle(spawn_points)
        spawned = 0
        for transform in spawn_points:
            if spawned >= scenario.npc_vehicles:
                break
            if transform.location.distance(ego.get_location()) < 18 or transform.location.distance(lead.get_location()) < 12:
                continue
            bp = rng.choice(blueprints)
            if bp.has_attribute("role_name"):
                bp.set_attribute("role_name", "background")
            actor = self.world.try_spawn_actor(bp, transform)
            if actor:
                actor.set_autopilot(True, int(self.cfg["traffic"]["tm_port"]))
                self.tm.vehicle_percentage_speed_difference(actor, rng.uniform(-5.0, 25.0))
                self.actors.append(actor)
                spawned += 1
        log(self.logger, "SCENARIO", f"Spawned {spawned}/{scenario.npc_vehicles} background vehicles")
        self._spawn_walkers(carla, scenario.pedestrians, rng)

    def _spawn_walkers(self, carla, count: int, rng: random.Random) -> None:
        walker_bps = self.world.get_blueprint_library().filter("walker.pedestrian.*")
        controller_bp = self.world.get_blueprint_library().find("controller.ai.walker")
        spawned = 0
        for _ in range(count * 3):
            if spawned >= count:
                break
            location = self.world.get_random_location_from_navigation()
            if location is None:
                continue
            transform = carla.Transform(location)
            walker = self.world.try_spawn_actor(rng.choice(walker_bps), transform)
            if not walker:
                continue
            controller = self.world.try_spawn_actor(controller_bp, carla.Transform(), attach_to=walker)
            if not controller:
                walker.destroy()
                continue
            self.actors.append(walker)
            self.walker_controllers.append(controller)
            controller.start()
            destination = self.world.get_random_location_from_navigation()
            if destination:
                controller.go_to_location(destination)
            controller.set_max_speed(rng.uniform(0.9, 1.7))
            spawned += 1
        log(self.logger, "SCENARIO", f"Spawned {spawned}/{count} pedestrians")

    def _spawn_sensors(self, carla, ego, metrics: MetricsCollector) -> CameraBuffer:
        bp_lib = self.world.get_blueprint_library()
        cam_cfg = self.cfg["camera"]
        camera_bp = bp_lib.find("sensor.camera.rgb")
        camera_bp.set_attribute("image_size_x", str(cam_cfg["width"]))
        camera_bp.set_attribute("image_size_y", str(cam_cfg["height"]))
        camera_bp.set_attribute("fov", str(cam_cfg["fov"]))
        camera_bp.set_attribute("sensor_tick", str(1.0 / float(cam_cfg["fps"])))
        transform = carla.Transform(
            carla.Location(x=float(cam_cfg["x"]), z=float(cam_cfg["z"])),
            carla.Rotation(pitch=float(cam_cfg["pitch"])),
        )
        buffer = CameraBuffer(int(cam_cfg["width"]), int(cam_cfg["height"]))
        camera = self.world.spawn_actor(camera_bp, transform, attach_to=ego, attachment_type=carla.AttachmentType.SpringArmGhost)
        camera.listen(buffer.callback)
        self.sensors.append(camera)

        collision_bp = bp_lib.find("sensor.other.collision")
        collision = self.world.spawn_actor(collision_bp, carla.Transform(), attach_to=ego)
        def on_collision(event) -> None:
            record = {
                "frame": int(event.frame),
                "other_actor_id": int(event.other_actor.id),
                "other_actor_type": str(event.other_actor.type_id),
                "impulse": [float(event.normal_impulse.x), float(event.normal_impulse.y), float(event.normal_impulse.z)],
            }
            metrics.record_collision(record)
            self.events.append({"sim_time_s": len(metrics.rows) * float(self.cfg["experiment"]["fixed_delta_s"]), "type": "collision", "detail": json.dumps(record)})
        collision.listen(on_collision)
        self.sensors.append(collision)
        return buffer

    def _ego_state(self, ego) -> EgoState:
        transform = ego.get_transform()
        velocity = ego.get_velocity()
        forward3 = transform.get_forward_vector()
        right3 = transform.get_right_vector()
        extent = ego.bounding_box.extent
        speed = self._speed(ego)
        return EgoState(
            position=Vec2(transform.location.x, transform.location.y),
            velocity=Vec2(velocity.x, velocity.y),
            forward=Vec2(forward3.x, forward3.y),
            right=Vec2(right3.x, right3.y),
            half_length=float(extent.x),
            half_width=float(extent.y),
            speed_mps=speed,
        )

    def _nearby_actor_states(self, ego) -> list[ActorState]:
        states: list[ActorState] = []
        ego_loc = ego.get_location()
        actors = list(self.world.get_actors().filter("vehicle.*")) + list(self.world.get_actors().filter("walker.pedestrian.*"))
        for actor in actors:
            if actor.id == ego.id:
                continue
            loc = actor.get_location()
            if loc.distance(ego_loc) > float(self.cfg["safety"]["monitor_range_m"]) + 8.0:
                continue
            vel = actor.get_velocity()
            extent = actor.bounding_box.extent
            states.append(ActorState(
                actor_id=int(actor.id),
                kind=str(actor.type_id),
                position=Vec2(loc.x, loc.y),
                velocity=Vec2(vel.x, vel.y),
                half_length=float(extent.x),
                half_width=float(extent.y),
            ))
        return states

    @staticmethod
    def _speed(actor) -> float:
        velocity = actor.get_velocity()
        return math.sqrt(velocity.x ** 2 + velocity.y ** 2 + velocity.z ** 2)

    @staticmethod
    def _yaw_delta_deg(a: float, b: float) -> float:
        delta = (b - a + 180.0) % 360.0 - 180.0
        return abs(delta)

    @staticmethod
    def _must_stop_for_red_light(ego, carla) -> bool:
        """Return True only when CARLA says the vehicle is at an active signal."""
        try:
            if not ego.is_at_traffic_light():
                return False

            state = ego.get_traffic_light_state()

            return state in {
                carla.TrafficLightState.Red,
                carla.TrafficLightState.Yellow,
            }

        except Exception:
            # Traffic-light telemetry must never crash the control loop.
            return False

    def _write_events(self) -> None:
        path = self.run_dir / "events.jsonl"
        with path.open("w", encoding="utf-8") as handle:
            for event in self.events:
                handle.write(json.dumps(event, sort_keys=True) + "\n")

    def _cleanup(self) -> None:
        """
        Cleanly release CARLA resources without double-destroy races.

        Sensors are explicitly stopped and destroyed because their Python
        wrappers otherwise warn when leaving scope. When HALOShield owns
        the CARLA server, vehicles and walkers are left to Unreal process
        shutdown, which destroys the complete world atomically.
        """
        log(
            self.logger,
            "CARLA",
            "Cleaning up simulation resources",
        )

        # Sensors need explicit shutdown because their callbacks have their
        # own lifecycle.
        for sensor in reversed(self.sensors):
            try:
                if getattr(sensor, "is_listening", False):
                    sensor.stop()
            except Exception:
                pass

            try:
                if getattr(sensor, "is_alive", False):
                    sensor.destroy()
            except Exception:
                pass

        self.sensors.clear()

        if getattr(self.server, "_owns_server", False):
            log(
                self.logger,
                "CARLA",
                "Managed server detected; vehicles/walkers delegated "
                "to CARLA process shutdown",
            )

            # Do not issue individual destroy RPCs for attached walker
            # controllers and their parents. Killing the managed CARLA
            # process immediately afterwards destroys the world atomically.
            self.tm = None
            self.world = None
            return

        # External CARLA server: preserve the server, so clean actors
        # individually where possible.
        for controller in reversed(self.walker_controllers):
            try:
                if getattr(controller, "is_alive", False):
                    controller.stop()
                    controller.destroy()
            except Exception:
                pass

        for actor in reversed(self.actors):
            try:
                if getattr(actor, "is_alive", False):
                    actor.destroy()
            except Exception:
                pass

        if self.tm:
            try:
                self.tm.set_synchronous_mode(False)
            except Exception:
                pass

        if self.world and self.original_world_settings:
            try:
                self.world.apply_settings(
                    self.original_world_settings
                )
            except Exception:
                pass

    def _install_signal_handlers(self) -> None:
        def handler(signum, _frame):
            self.stop_requested = True
            log(self.logger, "RUN", f"Signal {signum} received; finishing current tick and cleaning up", level=30)
        for sig in (signal.SIGINT, signal.SIGTERM):
            self._old_signal_handlers[sig] = signal.getsignal(sig)
            signal.signal(sig, handler)

    def _restore_signal_handlers(self) -> None:
        for sig, handler in self._old_signal_handlers.items():
            signal.signal(sig, handler)

    @staticmethod
    def _git_commit() -> str | None:
        try:
            return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True, stderr=subprocess.DEVNULL, timeout=2).strip()
        except Exception:
            return None
