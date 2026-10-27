from __future__ import annotations

import argparse
import csv
import json
import random
from datetime import datetime
from pathlib import Path
from statistics import mean

import matplotlib.pyplot as plt

from .config import load_config
from .experiment import ExperimentRunner
from .carla_bridge import CarlaServerManager
from .utils import write_json


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Paired baseline-vs-shield CARLA benchmark")
    p.add_argument("--runs", type=int, default=10, help="Number of scenario seeds")
    p.add_argument("--duration", type=float, default=60.0, help="Seconds per mode per seed")
    p.add_argument("--seed", type=int, default=20261027, help="Master seed used to derive paired scenario seeds")
    p.add_argument("--headless", action="store_true", default=True)
    return p


def _aggregate(rows: list[dict]) -> dict:
    result: dict = {"runs": len(rows)}
    for mode in ("baseline", "shield"):
        subset = [r for r in rows if r["mode"] == mode]
        result[mode] = {
            "mean_collisions": mean(float(r["collisions"]) for r in subset) if subset else None,
            "mean_min_ttc_s": mean(float(r["min_ttc_s"]) for r in subset if r["min_ttc_s"] is not None) if any(r["min_ttc_s"] is not None for r in subset) else None,
            "mean_distance_m": mean(float(r["distance_m"]) for r in subset) if subset else None,
            "mean_intervention_events": mean(float(r["intervention_events"]) for r in subset) if subset else None,
        }
    return result


def _plot(rows: list[dict], outdir: Path) -> None:
    for metric, ylabel in [("collisions", "Collisions per run"), ("distance_m", "Distance traveled (m)")]:
        modes = ["baseline", "shield"]
        values = [mean(float(r[metric]) for r in rows if r["mode"] == mode) for mode in modes]
        fig, ax = plt.subplots(figsize=(6, 4))
        ax.bar(modes, values)
        ax.set_ylabel(ylabel)
        ax.set_title(f"HALOShield paired benchmark: {metric}")
        fig.tight_layout()
        fig.savefig(outdir / f"{metric}.png", dpi=160)
        plt.close(fig)


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if args.runs < 1:
        raise SystemExit("--runs must be >= 1")
    cfg = load_config(overrides={"experiment": {"duration_s": args.duration}})
    stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    outdir = Path("benchmark_outputs") / stamp
    outdir.mkdir(parents=True, exist_ok=False)
    rng = random.Random(args.seed)
    seeds = [rng.randrange(1, 2**32 - 1) for _ in range(args.runs)]
    rows: list[dict] = []

    # Keep one CARLA server alive for the whole benchmark. Each ExperimentRunner
    # detects the existing server and therefore does not terminate it.
    server = CarlaServerManager(cfg["server"], outdir / "carla_server.log")
    server.start_if_needed()
    server.wait_until_ready()
    try:
        # Run each seed in both modes. Scenario generation is seed-deterministic, so
        # this is a paired experiment rather than two unrelated samples.
        for index, seed in enumerate(seeds, start=1):
            print(f"\nPaired scenario {index}/{args.runs}: seed={seed}")
            baseline = ExperimentRunner(cfg, seed=seed, headless=True, mode="baseline", output_root=outdir / "runs")
            baseline_summary = baseline.run()
            rows.append(baseline_summary)
            scenario = json.loads((baseline.run_dir / "scenario.json").read_text(encoding="utf-8"))
            shield = ExperimentRunner(
                cfg, seed=seed, headless=True, mode="shield", output_root=outdir / "runs", replay_scenario=scenario
            )
            rows.append(shield.run())
    finally:
        server.stop()

    csv_path = outdir / "paired_results.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    aggregate = _aggregate(rows)
    aggregate["master_seed"] = args.seed
    aggregate["scenario_seeds"] = seeds
    write_json(outdir / "summary.json", aggregate)
    _plot(rows, outdir)
    (outdir / "statistics.md").write_text(
        "# Paired benchmark statistical summary\n\n"
        + "```json\n" + json.dumps(aggregate, indent=2) + "\n```\n\n"
        + "This file reports descriptive statistics only. Inferential claims require a larger experiment design and appropriate paired statistical testing.\n",
        encoding="utf-8",
    )
    print(f"Benchmark outputs: {outdir.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
