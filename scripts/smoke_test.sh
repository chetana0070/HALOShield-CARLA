#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
python -m compileall -q src tests
pytest -q
bash -n run_project.sh run_benchmark.sh scripts/bootstrap.sh scripts/install_carla.sh scripts/smoke_test.sh
python -m haloshield.cli --doctor || true
