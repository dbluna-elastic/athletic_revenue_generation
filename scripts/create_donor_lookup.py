#!/usr/bin/env python3
"""Create booster-donor-lookup index and sync profile fields from athletic-boosters."""

from __future__ import annotations

import argparse
import json

from es_config import INDEX_NAME as BOOSTERS_INDEX, get_client

LOOKUP_INDEX = "booster-donor-lookup"

LOOKUP_MAPPING = {
    "settings": {"index.mode": "lookup"},
    "mappings": {
        "properties": {
            "donor_id": {"type": "keyword"},
            "first_name": {"type": "keyword"},
            "last_name": {"type": "keyword"},
            "affinity_score": {"type": "float"},
            "state": {"type": "keyword"},
            "degree": {"type": "keyword"},
            "graduation_year": {"type": "integer"},
        }
    },
}


def recreate_lookup_index(client, recreate: bool) -> None:
    if client.indices.exists(index=LOOKUP_INDEX):
        if recreate:
            print(f"Deleting {LOOKUP_INDEX}")
            client.indices.delete(index=LOOKUP_INDEX)
        else:
            print(f"{LOOKUP_INDEX} already exists (use --recreate to rebuild)")
            return
    print(f"Creating lookup index: {LOOKUP_INDEX}")
    client.indices.create(index=LOOKUP_INDEX, body=LOOKUP_MAPPING)


def sync_profiles(client, chunk_size: int = 500) -> int:
    response = client.search(
        index=BOOSTERS_INDEX,
        scroll="2m",
        size=chunk_size,
        _source=[
            "donor_id",
            "first_name",
            "last_name",
            "affinity_score",
            "location.state",
            "degree",
            "graduation_year",
        ],
    )
    scroll_id = response["_scroll_id"]
    total = 0

    while True:
        hits = response["hits"]["hits"]
        if not hits:
            break

        lines = []
        for hit in hits:
            src = hit["_source"]
            doc = {
                "donor_id": src["donor_id"],
                "first_name": src["first_name"],
                "last_name": src["last_name"],
                "affinity_score": src["affinity_score"],
                "state": src.get("location", {}).get("state"),
                "degree": src.get("degree"),
                "graduation_year": src.get("graduation_year"),
            }
            lines.append(
                json.dumps({"index": {"_index": LOOKUP_INDEX, "_id": doc["donor_id"]}})
            )
            lines.append(json.dumps(doc))

        bulk = "\n".join(lines) + "\n"
        result = client.bulk(body=bulk, refresh=False)
        if result.get("errors"):
            raise RuntimeError(f"Bulk sync failed: {result}")

        total += len(hits)
        print(f"  … synced {total}")
        response = client.scroll(scroll_id=scroll_id, scroll="2m")

    client.clear_scroll(scroll_id=scroll_id)
    client.indices.refresh(index=LOOKUP_INDEX)
    return total


def verify_join(client) -> None:
    result = client.esql.query(
        query=f"""
        FROM booster-engagement-events
        | STATS avg_signal = AVG(signal_value), event_count = COUNT(*) BY donor_id
        | WHERE avg_signal < 50
        | LOOKUP JOIN {LOOKUP_INDEX} ON donor_id
        | EVAL donor_name = CONCAT(first_name, " ", last_name)
        | SORT avg_signal ASC
        | KEEP donor_id, donor_name, state, affinity_score, avg_signal, event_count
        | LIMIT 5
        """
    )
    print("\nSample joined rows:")
    for row in result["values"]:
        print(f"  {row}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync athletic-boosters into lookup index")
    parser.add_argument("--recreate", action="store_true")
    args = parser.parse_args()

    client = get_client()
    recreate_lookup_index(client, args.recreate)
    if args.recreate or not client.count(index=LOOKUP_INDEX)["count"]:
        count = sync_profiles(client)
        print(f"✓ Synced {count} donor profiles to {LOOKUP_INDEX}")
    verify_join(client)


if __name__ == "__main__":
    main()
