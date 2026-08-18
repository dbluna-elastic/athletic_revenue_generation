#!/usr/bin/env bash
# Phase 1 gameday pipeline: indexes → seed → validate → enrich → ML
set -euo pipefail
cd "$(dirname "$0")/.."
source .venv/bin/activate 2>/dev/null || { python3 -m venv .venv && source .venv/bin/activate; }
pip install -q -r requirements.txt

PROFILE_ARGS=()
RECREATE_ARGS=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --profile)
      PROFILE_ARGS=(--profile "$2")
      shift 2
      ;;
    --recreate)
      RECREATE_ARGS=(--recreate)
      shift
      ;;
    *)
      echo "Unknown argument: $1"
      exit 1
      ;;
  esac
done

echo "=== Creating indexes ==="
python scripts/create_gameday_indexes.py "${PROFILE_ARGS[@]}" "${RECREATE_ARGS[@]}"

echo "=== Seeding game data ==="
python scripts/gameday_replay.py "${PROFILE_ARGS[@]}" seed

echo "=== Validating ==="
python scripts/validate_gameday_data.py "${PROFILE_ARGS[@]}"

echo "=== Enrich policy ==="
python scripts/setup_gameday_enrich.py "${PROFILE_ARGS[@]}" --recreate

echo "=== ML anomaly job ==="
python scripts/setup_gameday_ml.py "${PROFILE_ARGS[@]}" --recreate --start

echo "Done."
