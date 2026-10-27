from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

from .config import load_config, repo_root
from .experiment import ExperimentRunner
from .system import doctor


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="HALOShield-CARLA randomized safety experiment")
    parser.add_argument("--config", type=Path, default=None, help="YAML configuration file")
    parser.add_argument("--seed", type=int, default=None, help="Reproduce a seeded scenario")
    parser.add_argument("--duration", type=float, default=None, help="Simulation duration in seconds")
    parser.add_argument("--headless", action="store_true", help="Do not open the live dashboard; video is still recorded")
    parser.add_argument("--quality", choices=["Low", "Epic"], default=None, help="CARLA quality preset")
    parser.add_argument("--mode", choices=["shield", "baseline"], default=None, help="Enable the proposed shield or run nominal baseline")
    parser.add_argument("--scenario-density", choices=["low", "medium", "high"], default=None)
    parser.add_argument("--replay", type=Path, default=None, help="Replay a saved scenario.json exactly")
    parser.add_argument("--doctor", action="store_true", help="Run diagnostics without starting a simulation")
    return parser


def _overrides(args: argparse.Namespace) -> dict:
    overrides: dict = {}
    if args.duration is not None:
        overrides.setdefault("experiment", {})["duration_s"] = args.duration
    if args.quality is not None:
        overrides.setdefault("server", {})["quality"] = args.quality
    if args.mode is not None:
        overrides.setdefault("experiment", {})["mode"] = args.mode
    if args.scenario_density:
        bands = {
            "low": (5, 8, 1, 3),
            "medium": (10, 18, 4, 10),
            "high": (18, 24, 8, 14),
        }
        vmin, vmax, pmin, pmax = bands[args.scenario_density]
        overrides["traffic"] = {
            "npc_vehicles_min": vmin,
            "npc_vehicles_max": vmax,
            "pedestrians_min": pmin,
            "pedestrians_max": pmax,
        }
    return overrides


def run_doctor(cfg: dict) -> int:
    checks = doctor(repo_root(), str(cfg["server"]["host"]), int(cfg["server"]["port"]))
    print("HALOShield-CARLA diagnostic\n")
    width = max(len(check.name) for check in checks)
    for check in checks:
        print(f"{check.status:4}  {check.name:<{width}}  {check.detail}")
        if check.fix:
            print(f"      fix: {check.fix}")
    failures = sum(check.status == "FAIL" for check in checks)
    warnings = sum(check.status == "WARN" for check in checks)
    print(f"\nResult: {failures} FAIL, {warnings} WARN")
    return 1 if failures else 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    cfg = load_config(args.config, _overrides(args))
    if args.doctor:
        return run_doctor(cfg)

    replay = None
    if args.replay:
        replay = json.loads(args.replay.read_text(encoding="utf-8"))
        args.seed = int(replay["seed"])

    runner = ExperimentRunner(
        cfg,
        seed=args.seed,
        headless=args.headless,
        mode=args.mode,
        replay_scenario=replay,
    )
    summary = runner.run()
    metrics_csv = runner.run_dir / "metrics.csv"
    with metrics_csv.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(summary.keys()))
        writer.writeheader()
        writer.writerow(summary)
    print("\n=== HALOShield-CARLA COMPLETE ===")
    print(f"Run directory: {runner.run_dir.resolve()}")
    print(f"Demo video:    {(runner.run_dir / 'demo.mp4').resolve()}")
    print(f"Seed:          {runner.seed}")
    print(f"Mode:          {runner.mode}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
