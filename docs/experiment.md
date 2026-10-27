# Experiment protocol

## Independent variables

- runtime shield mode: `baseline` vs `shield`;
- prediction horizon;
- uncertainty inflation parameters;
- TTC and clearance thresholds;
- hazard timing/intensity;
- traffic density;
- map/weather/seed.

## Dependent variables

- collisions;
- minimum TTC;
- minimum predicted clearance;
- near-miss exposure;
- distance traveled;
- mean speed;
- intervention count;
- safety-layer latency.

## Failure criteria

A run is operationally failed if the simulator crashes, ego cannot be spawned, CARLA connectivity is lost, output evidence cannot be finalized, or an unhandled exception terminates the experiment. Safety failures are reported separately (for example a collision or extreme TTC) rather than hidden as software failures.

## Standard demo

```bash
./run_project.sh
```

Expected simulation time: ~120 seconds. Wall-clock time can exceed 120 seconds on a thermally or computationally constrained laptop because synchronous CARLA advances only when each tick completes.

## Paired comparison

```bash
./run_project.sh --mode baseline --seed 12345
./run_project.sh --mode shield --seed 12345
```

For publication-style evidence, prefer the automated paired benchmark and retain all output directories.

## Ablation examples

Copy `config/default.yaml`, alter one safety parameter at a time, then run with `--config path/to/config.yaml --seed <same-seed>`.
