#!/usr/bin/env python3
"""Create booster-donor-lookup index and sync profile fields from athletic-boosters."""

from __future__ import annotations

import argparse
import json

from es_config import get_client
from demo_profile import add_profile_argument, load_profile

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


def recreate_lookup_index(client, lookup_index: str, recreate: bool) -> None:
    if client.indices.exists(index=lookup_index):
        if recreate:
            print(f"Deleting {lookup_index}")
            client.indices.delete(index=lookup_index)
        else:
            print(f"{lookup_index} already exists (use --recreate to rebuild)")
            return
    print(f"Creating lookup index: {lookup_index}")
    client.indices.create(index=lookup_index, body=LOOKUP_MAPPING)


def sync_profiles(client, boosters_index: str, lookup_index: str, chunk_size: int = 500) -> int:
    response = client.search(
        index=boosters_index,
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
                json.dumps({"index": {"_index": lookup_index, "_id": doc["donor_id"]}})
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
    client.indices.refresh(index=lookup_index)
    return total


def verify_join(client, engagement_index: str, lookup_index: str) -> None:
    if not client.indices.exists(index=engagement_index):
        print(f"Skip join check — {engagement_index} does not exist yet")
        return
    if client.count(index=engagement_index)["count"] == 0:
        print(f"Skip join check — {engagement_index} is empty")
        return
    result = client.esql.query(
        query=f"""
        FROM {engagement_index}
        | STATS avg_signal = AVG(signal_value), event_count = COUNT(*) BY donor_id
        | WHERE avg_signal < 50
        | LOOKUP JOIN {lookup_index} ON donor_id
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
    add_profile_argument(parser)
    parser.add_argument("--recreate", action="store_true")
    args = parser.parse_args()
    profile = load_profile(args.profile)
    boosters_index = profile.index("athletic-boosters")
    lookup_index = profile.index("booster-donor-lookup")
    engagement_index = profile.index("booster-engagement-events")

    client = get_client()
    recreate_lookup_index(client, lookup_index, args.recreate)
    if args.recreate or not client.count(index=lookup_index)["count"]:
        count = sync_profiles(client, boosters_index, lookup_index)
        print(f"✓ Synced {count} donor profiles to {lookup_index}")
    verify_join(client, engagement_index, lookup_index)


if __name__ == "__main__":
    main()
