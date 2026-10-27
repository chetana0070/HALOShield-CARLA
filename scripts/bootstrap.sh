#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
NO_CARLA=0
[[ "${1:-}" == "--no-carla" ]] && NO_CARLA=1

need_command() { command -v "$1" >/dev/null 2>&1; }

missing_pkgs=()
need_command curl || missing_pkgs+=(curl ca-certificates)
need_command ffmpeg || missing_pkgs+=(ffmpeg)
if need_command dpkg; then
  dpkg -s libvulkan1 >/dev/null 2>&1 || missing_pkgs+=(libvulkan1)
  dpkg -s libomp5 >/dev/null 2>&1 || missing_pkgs+=(libomp5)
fi
if (( ${#missing_pkgs[@]} )); then
  echo "[SETUP] Installing minimal Ubuntu runtime packages: ${missing_pkgs[*]}"
  echo "[SETUP] sudo may request your password."
  sudo apt-get update
  sudo apt-get install -y "${missing_pkgs[@]}"
fi

choose_python() {
  for candidate in python3.10 python3.12 python3.11; do
    if need_command "$candidate"; then echo "$candidate"; return 0; fi
  done
  return 1
}
PYTHON_BIN="$(choose_python || true)"
if [[ -z "$PYTHON_BIN" ]]; then
  echo "[SETUP] ERROR: Python 3.10-3.12 is required. Python 3.13 is intentionally not used for CARLA 0.9.16." >&2
  exit 1
fi

if [[ ! -x "$ROOT/.venv/bin/python" ]]; then
  echo "[SETUP] Creating isolated environment with $PYTHON_BIN"
  if ! "$PYTHON_BIN" -m venv "$ROOT/.venv"; then
    rm -rf "$ROOT/.venv"
    VENV_PKG="$($PYTHON_BIN -c 'import sys; print(f"python{sys.version_info.major}.{sys.version_info.minor}-venv")')"
    echo "[SETUP] Python venv support is missing; installing $VENV_PKG"
    sudo apt-get update
    sudo apt-get install -y "$VENV_PKG"
    "$PYTHON_BIN" -m venv "$ROOT/.venv"
  fi
fi
# shellcheck disable=SC1091
source "$ROOT/.venv/bin/activate"
python -m pip install --upgrade pip setuptools wheel >/dev/null
python -m pip install -r "$ROOT/requirements.txt" >/dev/null
python -m pip install -e "$ROOT" >/dev/null

if [[ "$NO_CARLA" -eq 0 ]]; then
  CARLA_ROOT_RESOLVED="$($ROOT/scripts/install_carla.sh)"
  printf 'export CARLA_ROOT=%q\n' "$CARLA_ROOT_RESOLVED" > "$ROOT/.haloshield.env"
  AGENTS_PATH="$CARLA_ROOT_RESOLVED/PythonAPI/carla"
  printf 'export PYTHONPATH=%q:${PYTHONPATH:-}\n' "$AGENTS_PATH" >> "$ROOT/.haloshield.env"

  PYTAG="cp$(python -c 'import sys; print(f"{sys.version_info.major}{sys.version_info.minor}")')"
  WHEEL="$(find "$CARLA_ROOT_RESOLVED/PythonAPI/carla/dist" -maxdepth 1 -type f -name "carla-0.9.16-${PYTAG}*.whl" 2>/dev/null | head -n1 || true)"
  if [[ -n "$WHEEL" ]]; then
    python -m pip install "$WHEEL" >/dev/null
  else
    echo "[SETUP] Matching bundled CARLA wheel not found; installing carla==0.9.16 from PyPI."
    python -m pip install "carla==0.9.16" >/dev/null
  fi
fi
