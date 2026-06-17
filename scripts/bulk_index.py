#!/usr/bin/env python3
"""Bulk index donor NDJSON into Elasticsearch."""

from __future__ import annotations

import argparse
from pathlib import Path

from es_config import INDEX_NAME, ROOT, get_client


def bulk_index(client, ndjson_path: Path, chunk_size: int = 500) -> None:
    if not ndjson_path.exists():
        raise SystemExit(
            f"File not found: {ndjson_path}\nRun: python scripts/generate_donors.py"
        )

    lines = ndjson_path.read_text(encoding="utf-8").splitlines()
    if len(lines) % 2 != 0:
        raise SystemExit("NDJSON file has odd line count; expected index/doc pairs")

    total_docs = len(lines) // 2
    print(f"Indexing {total_docs} documents from {ndjson_path} → {INDEX_NAME}")

    indexed = 0
    errors = []

    for start in range(0, len(lines), chunk_size * 2):
        chunk = "\n".join(lines[start : start + chunk_size * 2]) + "\n"
        response = client.bulk(body=chunk, refresh=False)
        if response.get("errors"):
            for item in response.get("items", []):
                action = item.get("index") or item.get("create") or {}
                if action.get("error"):
                    errors.append(action["error"])
        indexed += min(chunk_size, total_docs - indexed)
        print(f"  … {indexed}/{total_docs}")

    client.indices.refresh(index=INDEX_NAME)

    if errors:
        print(f"✗ Bulk index completed with {len(errors)} errors")
        for err in errors[:5]:
            print(f"  - {err}")
        raise SystemExit(1)

    count = client.count(index=INDEX_NAME)["count"]
    print(f"✓ Indexed successfully. Document count: {count}")


def verify_sample(client) -> None:
    sample = client.search(
        index=INDEX_NAME,
        size=1,
        sort=[{"affinity_score": "desc"}],
        _source=["donor_id", "affinity_score", "bio_text", "location.state"],
    )
    hit = sample["hits"]["hits"][0]["_source"]
    print("\nSample high-affinity document:")
    print(f"  donor_id: {hit['donor_id']}")
    print(f"  affinity_score: {hit['affinity_score']}")
    print(f"  state: {hit['location']['state']}")
    bio = hit.get("bio_text", "")
    if isinstance(bio, dict):
        print("  bio_text: semantic_text field populated (ELSER inference ran)")
    else:
        print(f"  bio_text: {str(bio)[:120]}…")


def main() -> None:
    parser = argparse.ArgumentParser(description="Bulk index donors.ndjson")
    parser.add_argument(
        "--file",
        type=Path,
        default=ROOT / "data" / "donors.ndjson",
    )
    parser.add_argument("--chunk-size", type=int, default=50)
    parser.add_argument("--verify", action="store_true", help="Print sample doc after index")
    args = parser.parse_args()

    client = get_client()
    bulk_index(client, args.file, args.chunk_size)
    if args.verify:
        verify_sample(client)


if __name__ == "__main__":
    main()
