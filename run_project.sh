#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

DOCTOR=0
for arg in "$@"; do
  [[ "$arg" == "--doctor" ]] && DOCTOR=1
done

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
