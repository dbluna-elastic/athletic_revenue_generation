#!/usr/bin/env bash
# Full Phase 1 pipeline: generate → create index → bulk index → validate
set -euo pipefail

cd "$(dirname "$0")/.."

if [[ ! -d .venv ]]; then
  python3 -m venv .venv
fi
source .venv/bin/activate
pip install -q -r requirements.txt

if [[ ! -f .env ]]; then
  echo "Copy .env.example to .env and configure Elasticsearch credentials first."
  exit 1
fi

echo "=== Generating donors ==="
python scripts/generate_donors.py

echo "=== Creating index ==="
python scripts/create_index.py "$@"

echo "=== Bulk indexing ==="
python scripts/bulk_index.py --verify

echo "=== Validating ==="
python scripts/validate_data.py

echo "Done."
