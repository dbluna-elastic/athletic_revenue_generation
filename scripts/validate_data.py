#!/usr/bin/env python3
"""Validate affinity score distribution and demo query matches in Elasticsearch."""

from __future__ import annotations

import argparse

from es_config import INDEX_NAME, get_client


def run_validation(client) -> None:
    count = client.count(index=INDEX_NAME)["count"]
    print(f"Total documents: {count}")

    tiers = client.search(
        index=INDEX_NAME,
        size=0,
        aggs={
            "affinity_tiers": {
                "range": {
                    "field": "affinity_score",
                    "ranges": [
                        {"key": "low", "to": 50},
                        {"key": "medium", "from": 50, "to": 75},
                        {"key": "high", "from": 75},
                    ],
                }
            }
        },
    )
    print("\nAffinity score tiers:")
    for bucket in tiers["aggregations"]["affinity_tiers"]["buckets"]:
        print(f"  {bucket['key']}: {bucket['doc_count']}")

    demo = client.search(
        index=INDEX_NAME,
        size=5,
        query={
            "bool": {
                "filter": [
                    {"term": {"location.state": "TX"}},
                    {"range": {"engagement.game_attendance_count": {"gte": 3}}},
                    {"range": {"wealth_signals.real_estate_value_est": {"gte": 2000000}}},
                ]
            }
        },
        sort=[{"affinity_score": "desc"}],
        _source=[
            "donor_id",
            "first_name",
            "last_name",
            "affinity_score",
            "engagement.game_attendance_count",
            "wealth_signals.real_estate_value_est",
        ],
    )
    total_demo = demo["hits"]["total"]["value"]
    print(f"\nDemo filter matches (TX, 3+ games, $2M+ RE): {total_demo}")
    print("Top 5 by affinity_score:")
    for hit in demo["hits"]["hits"]:
        src = hit["_source"]
        print(
            f"  {src['donor_id']} {src['first_name']} {src['last_name']} "
            f"score={src['affinity_score']} games={src['engagement']['game_attendance_count']} "
            f"re=${src['wealth_signals']['real_estate_value_est']:,}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate indexed donor data")
    parser.parse_args()
    client = get_client()
    if not client.indices.exists(index=INDEX_NAME):
        raise SystemExit(f"Index {INDEX_NAME} does not exist. Run create_index.py first.")
    run_validation(client)


if __name__ == "__main__":
    main()
