from __future__ import annotations

import random
from dataclasses import dataclass, asdict
from typing import Any


@dataclass
class HazardEvent:
    trigger_s: float
    duration_s: float
    brake: float


@dataclass
class ScenarioSpec:
    seed: int
    map_name: str
    weather: str
    npc_vehicles: int
    pedestrians: int
    lead_distance_m: float
    hazard_events: list[HazardEvent]

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        return data


def generate_scenario(seed: int, cfg: dict, available_maps: list[str]) -> ScenarioSpec:
    rng = random.Random(seed)
    preferred = cfg["experiment"]["preferred_maps"]
    normalized = {name.split("/")[-1]: name for name in available_maps}
    choices = [name for name in preferred if name in normalized]
    if choices:
        chosen_short = rng.choice(choices)
        map_name = normalized[chosen_short]
    elif available_maps:
        # Avoid large tiled maps when possible on an 8 GB GPU.
        small = [m for m in available_maps if "Town10" not in m and "Town12" not in m and "Town13" not in m and "Town15" not in m]
        map_name = rng.choice(small or available_maps)
    else:
        raise RuntimeError("CARLA reported no available maps")

    scfg = cfg["scenario"]
    tcfg = cfg["traffic"]
    first = scfg["hazard_first_window_s"]
    second = scfg["hazard_second_window_s"]
    duration_range = scfg["hazard_brake_duration_s"]
    brake_range = scfg["hazard_brake_intensity"]
    event_count = int(scfg.get("hazard_events", 2))
    windows = [first, second]
    events: list[HazardEvent] = []
    for idx in range(min(event_count, len(windows))):
        win = windows[idx]
        events.append(HazardEvent(
            trigger_s=rng.uniform(float(win[0]), float(win[1])),
            duration_s=rng.uniform(float(duration_range[0]), float(duration_range[1])),
            brake=rng.uniform(float(brake_range[0]), float(brake_range[1])),
        ))
    return ScenarioSpec(
        seed=seed,
        map_name=map_name,
        weather=rng.choice(list(scfg["weather_choices"])),
        npc_vehicles=rng.randint(int(tcfg["npc_vehicles_min"]), int(tcfg["npc_vehicles_max"])),
        pedestrians=rng.randint(int(tcfg["pedestrians_min"]), int(tcfg["pedestrians_max"])),
        lead_distance_m=rng.uniform(float(scfg["lead_spawn_distance_m"][0]), float(scfg["lead_spawn_distance_m"][1])),
        hazard_events=events,
    )


def scenario_from_dict(data: dict[str, Any]) -> ScenarioSpec:
    events = [HazardEvent(**event) for event in data.get("hazard_events", [])]
    return ScenarioSpec(
        seed=int(data["seed"]),
        map_name=str(data["map_name"]),
        weather=str(data["weather"]),
        npc_vehicles=int(data["npc_vehicles"]),
        pedestrians=int(data["pedestrians"]),
        lead_distance_m=float(data["lead_distance_m"]),
        hazard_events=events,
    )
