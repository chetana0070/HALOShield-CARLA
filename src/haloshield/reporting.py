from __future__ import annotations

from pathlib import Path
from typing import Any


def write_safety_report(path: Path, scenario: dict[str, Any], summary: dict[str, Any], system_info: dict[str, Any], mode: str, events: list[dict[str, Any]]) -> None:
    hazard_lines = "\n".join(
        f"- t={event.get('sim_time_s', 0):.1f}s — {event.get('type', 'event')}: {event.get('detail', '')}"
        for event in events[:40]
    ) or "- No significant events were recorded."
    content = f"""# HALOShield-CARLA Safety Report

## Run identity
- Mode: **{mode}**
- Seed: **{scenario.get('seed')}**
- Map: **{scenario.get('map_name')}**
- Weather: **{scenario.get('weather')}**

## Method
The proposed mode uses an independent uncertainty-inflated short-horizon predictive safety shield. The nominal controller remains responsible for lane following and target speed; the shield can cap throttle or override braking when predicted time-to-collision or clearance enters configured risk thresholds. Baseline mode runs the same nominal controller without the override.

## Observed results
- Duration: {summary.get('duration_s')} s
- Termination: {summary.get('termination_reason')}
- Collisions: **{summary.get('collisions')}**
- Safety intervention events: **{summary.get('intervention_events')}**
- Minimum TTC: **{summary.get('min_ttc_s')} s**
- Minimum predicted clearance: **{summary.get('min_predicted_clearance_m')} m**
- Distance traveled: **{summary.get('distance_m')} m**
- Mean speed: **{summary.get('mean_speed_mps')} m/s**
- Mean safety-layer latency: **{summary.get('mean_safety_latency_ms')} ms**

## Significant events
{hazard_lines}

## Resource context
- GPU: {system_info.get('gpu', {}).get('name', 'unknown')}
- Driver: {system_info.get('gpu', {}).get('driver_version', 'unknown')}
- RAM total: {system_info.get('ram_total_gib')} GiB
- Disk free at start: {system_info.get('disk_free_gib')} GiB

## Interpretation boundary
The measurements above are observations from this simulation run. They are not evidence that the software is safe for use on public roads, are not NVIDIA certification, and are not an ASIL assessment. Statistical claims require paired repeated experiments across identical seeds in baseline and shield modes.
"""
    path.write_text(content, encoding="utf-8")
