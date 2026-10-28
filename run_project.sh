#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

DOCTOR=0
for arg in "$@"; do
  [[ "$arg" == "--doctor" ]] && DOCTOR=1
done

# Remove a stale CARLA 0.9.16 process left by an abnormal previous run.
# This only targets CARLA's Unreal process on HALOShield's RPC port.
if [[ "$DOCTOR" -eq 0 ]]; then
  if pgrep -af "CarlaUE4-Linux-Shipping.*carla-rpc-port=2000" >/dev/null 2>&1; then
    echo "[CARLA] Removing stale managed CARLA process from previous run"
    pkill -TERM -f "CarlaUE4-Linux-Shipping.*carla-rpc-port=2000" 2>/dev/null || true
    sleep 3
    pkill -KILL -f "CarlaUE4-Linux-Shipping.*carla-rpc-port=2000" 2>/dev/null || true
    sleep 2
  fi
fi

if [[ "$DOCTOR" -eq 1 ]]; then
  "$ROOT/scripts/bootstrap.sh" --no-carla
else
  "$ROOT/scripts/bootstrap.sh"
fi

# shellcheck disable=SC1091
source "$ROOT/.venv/bin/activate"
[[ -f "$ROOT/.haloshield.env" ]] && source "$ROOT/.haloshield.env"
export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
exec python -m haloshield.cli "$@"
