#!/usr/bin/env python3
"""Create the athletic-boosters index with ELSER semantic_text mapping."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from es_config import INDEX_NAME, ROOT, get_client


def load_mapping(path: Path) -> dict:
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def check_elser(client) -> None:
    try:
        stats = client.ml.get_trained_models_stats(model_id=".elser*")
        deployments = [
            d
            for m in stats.get("trained_model_stats", [])
            for d in [m.get("deployment_stats")]
            if d
        ]
        started = [d for d in deployments if d.get("state") == "started"]
        if started:
            print(f"✓ ELSER deployment running: {started[0]['deployment_id']}")
            return
        print("⚠ ELSER found but not fully started. Wait for deployment to finish.")
    except Exception as exc:
        print(
            "⚠ Could not verify ELSER. Deploy before indexing:\n"
            "  POST _ml/trained_models/.elser-2-elasticsearch/deployment/_start\n"
            f"  ({exc})"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Create athletic-boosters index")
    parser.add_argument(
        "--mapping",
        type=Path,
        default=ROOT / "elastic" / "athletic-boosters-mapping.json",
    )
    parser.add_argument(
        "--recreate",
        action="store_true",
        help="Delete existing index before creating",
    )
    args = parser.parse_args()

    client = get_client()
    mapping = load_mapping(args.mapping)

    if client.indices.exists(index=INDEX_NAME):
        if args.recreate:
            print(f"Deleting existing index: {INDEX_NAME}")
            client.indices.delete(index=INDEX_NAME)
        else:
            print(f"Index {INDEX_NAME} already exists. Use --recreate to replace.")
            return

    print(f"Creating index: {INDEX_NAME}")
    client.indices.create(index=INDEX_NAME, mappings=mapping["mappings"])
    print("✓ Index created")

    check_elser(client)


if __name__ == "__main__":
    main()
