#!/usr/bin/env bash
set -Eeuo pipefail
VERSION="0.9.16"
CACHE_ROOT="${HALOSHIELD_CARLA_CACHE:-$HOME/.cache/haloshield}"
TARGET="$CACHE_ROOT/CARLA_${VERSION}"
URL="https://carla-releases.s3.us-east-005.backblazeb2.com/Linux/CARLA_${VERSION}.tar.gz"
MIN_FREE_GB=26

valid_root() { [[ -x "$1/CarlaUE4.sh" && -d "$1/PythonAPI" ]]; }

if [[ -n "${CARLA_ROOT:-}" ]] && valid_root "$CARLA_ROOT"; then
  printf '%s\n' "$CARLA_ROOT"
  exit 0
fi

for candidate in "$TARGET" "$HOME/CARLA_${VERSION}" "$HOME/carla/${VERSION}" "/opt/carla/${VERSION}"; do
  if valid_root "$candidate"; then
    printf '%s\n' "$candidate"
    exit 0
  fi
done

mkdir -p "$CACHE_ROOT"
FREE_GB=$(df -Pk "$CACHE_ROOT" | awk 'NR==2 {printf "%.1f", $4/1024/1024}')
python3 - "$FREE_GB" "$MIN_FREE_GB" <<'PY'
import sys
free, needed = map(float, sys.argv[1:])
if free < needed:
    raise SystemExit(f"CARLA install blocked: {free:.1f} GiB free, but at least {needed:.0f} GiB is required for a streamed ~20 GiB installation with safety margin.")
PY

TMP="${TARGET}.partial"
rm -rf "$TMP"
mkdir -p "$TMP"
echo "[SETUP] Streaming CARLA ${VERSION} directly into $TARGET (archive is not retained)." >&2
echo "[SETUP] Source: $URL" >&2
set +e
curl --fail --location --retry 3 --connect-timeout 20 "$URL" | tar -xz -C "$TMP"
STATUS=("${PIPESTATUS[@]}")
set -e
if [[ "${STATUS[0]}" -ne 0 || "${STATUS[1]}" -ne 0 ]]; then
  rm -rf "$TMP"
  echo "[SETUP] CARLA download/extraction failed. Partial installation was removed." >&2
  exit 1
fi
if ! valid_root "$TMP"; then
  rm -rf "$TMP"
  echo "[SETUP] Download completed but CARLA validation failed (CarlaUE4.sh/PythonAPI missing)." >&2
  exit 1
fi
mv "$TMP" "$TARGET"
chmod +x "$TARGET/CarlaUE4.sh"
printf '%s\n' "$TARGET"
