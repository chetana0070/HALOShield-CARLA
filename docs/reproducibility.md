# Reproducibility

A normal run chooses a random 32-bit seed using the operating system's secure random source. The seed controls scenario parameters and is stored in `scenario.json` and `summary.json`.

Reproduce by seed:

```bash
./run_project.sh --seed 194827361
```

Replay the saved scenario contract:

```bash
./run_project.sh --replay outputs/<run>/scenario.json
```

For research results, also pin the Git commit and retain `config_snapshot.yaml`, `system_info.json`, `carla_server.log`, and telemetry. Exact numerical determinism can still be affected by simulator internals, hardware, driver changes, CARLA Traffic Manager behavior, and nondeterministic GPU/runtime execution.
