#!/usr/bin/env bash
# Seed Oklahoma State (okstate-*) indexes and dashboards without touching Texas demo data.
set -euo pipefail
cd "$(dirname "$0")/.."
source .venv/bin/activate 2>/dev/null || { python3 -m venv .venv && source .venv/bin/activate; }
pip install -q -r requirements.txt

PROFILE=(--profile oklahoma-state)

echo "=== Donors ==="
python scripts/generate_donors.py "${PROFILE[@]}"
python scripts/create_index.py "${PROFILE[@]}" --recreate
python scripts/bulk_index.py "${PROFILE[@]}" --verify
python scripts/validate_data.py "${PROFILE[@]}"

echo "=== Gameday ==="
python scripts/create_gameday_indexes.py "${PROFILE[@]}" --recreate
python scripts/gameday_replay.py "${PROFILE[@]}" seed
python scripts/validate_gameday_data.py "${PROFILE[@]}"
python scripts/setup_gameday_enrich.py "${PROFILE[@]}" --recreate
python scripts/setup_gameday_ml.py "${PROFILE[@]}" --recreate --start

echo "=== Engagement + lookup ==="
python scripts/generate_engagement_events.py "${PROFILE[@]}"
python scripts/create_donor_lookup.py "${PROFILE[@]}" --recreate

echo "=== Dashboards ==="
python scripts/deploy_gameday_dashboards.py "${PROFILE[@]}"
python scripts/deploy_kibana_dashboard.py "${PROFILE[@]}" kibana/at-risk-engagement-dashboard.json --id booster-at-risk-engagement

echo "Oklahoma State demo ready."
