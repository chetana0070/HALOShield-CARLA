#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"
"$ROOT/scripts/bootstrap.sh"
# shellcheck disable=SC1091
source "$ROOT/.venv/bin/activate"
[[ -f "$ROOT/.haloshield.env" ]] && source "$ROOT/.haloshield.env"
export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
exec python -m haloshield.benchmark "$@"
