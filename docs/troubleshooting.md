# Troubleshooting

## Start with diagnostics

```bash
./run_project.sh --doctor
```

## CARLA server does not start

Inspect `outputs/<run>/carla_server.log`. Check that `nvidia-smi` works and that port 2000 is not occupied by an unrelated process. CARLA 0.9.16 officially documents Ubuntu 20.04/22.04; Ubuntu 24.04 is therefore a compatibility deployment, not an officially listed target.

## Vulkan / GPU memory failure

Keep `server.quality: Low`, camera at 960×540, and scenario density low/medium. Close GPU-heavy applications. Do not switch to CARLA UE5 on this 8 GB GPU merely for newer graphics.

## First installation says disk is insufficient

The installer requires a conservative 26 GiB free before streaming/extracting CARLA. Free space or point `HALOSHIELD_CARLA_CACHE` to a filesystem with adequate space. AdditionalMaps are deliberately not installed.

## Python 3.13 selected by the OS

The bootstrap script intentionally chooses Python 3.10, 3.12, then 3.11. Ensure one of those interpreters exists. CARLA 0.9.16 documentation lists support through Python 3.12.

## `ffmpeg` unavailable

```bash
sudo apt install ffmpeg
```

Bootstrap attempts to install it automatically if missing.

## Live dashboard fails but simulation runs

Use `--headless`. MP4 recording does not depend on a visible Pygame window.

## Collision occurs in shield mode

That is research evidence, not necessarily a software bug. Inspect `telemetry.csv` around the collision, `events.jsonl`, and the video. Check whether the actor was inside the monitor corridor and whether TTC/clearance crossed intervention thresholds early enough.
