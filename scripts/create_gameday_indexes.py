#!/usr/bin/env python3
"""Create Paciolan and Square POS indexes for game day revenue demo."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from es_config import ROOT, get_client
from demo_profile import add_profile_argument, load_profile

BASE_INDEXES = {
    "paciolan-ticket-events": ROOT / "elastic" / "paciolan-ticket-events-mapping.json",
    "square-pos-transactions": ROOT / "elastic" / "square-pos-transactions-mapping.json",
}


def create_index(client, name: str, mapping_path: Path, recreate: bool) -> None:
    if client.indices.exists(index=name):
        if recreate:
            print(f"Deleting {name}")
            client.indices.delete(index=name)
        else:
            print(f"{name} already exists (use --recreate to replace)")
            return
    mapping = json.loads(mapping_path.read_text(encoding="utf-8"))
    print(f"Creating {name}")
    client.indices.create(index=name, mappings=mapping["mappings"])
    print(f"✓ {name}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Create gameday revenue indexes")
    add_profile_argument(parser)
    parser.add_argument("--recreate", action="store_true")
    args = parser.parse_args()
    profile = load_profile(args.profile)

    client = get_client()
    for base_name, path in BASE_INDEXES.items():
        create_index(client, profile.index(base_name), path, args.recreate)


if __name__ == "__main__":
    main()
