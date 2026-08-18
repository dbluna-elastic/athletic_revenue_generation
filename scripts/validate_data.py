#!/usr/bin/env python3
"""Validate affinity score distribution and demo query matches in Elasticsearch."""

from __future__ import annotations

import argparse

from es_config import get_client
from demo_profile import add_profile_argument, load_profile


def run_validation(client, profile) -> None:
    index_name = profile.index("athletic-boosters")
    count = client.count(index=index_name)["count"]
    print(f"Total documents: {count}")

    tiers = client.search(
        index=index_name,
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
        index=index_name,
        size=5,
        query={
            "bool": {
                "filter": [
                    {"term": {"location.state": profile.home_state}},
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
    print(
        f"\nDemo filter matches ({profile.home_state}, 3+ games, $2M+ RE): {total_demo}"
    )
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
    add_profile_argument(parser)
    args = parser.parse_args()
    profile = load_profile(args.profile)
    index_name = profile.index("athletic-boosters")
    client = get_client()
    if not client.indices.exists(index=index_name):
        raise SystemExit(f"Index {index_name} does not exist. Run create_index.py first.")
    run_validation(client, profile)


if __name__ == "__main__":
    main()
