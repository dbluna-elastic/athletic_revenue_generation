#!/usr/bin/env python3
"""Validate seeded game day revenue data."""

from __future__ import annotations

import argparse

from es_config import get_client
from demo_profile import add_profile_argument, load_profile

ANOMALY_STANDS = ["S04", "S06", "S09"]


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate seeded gameday data")
    add_profile_argument(parser)
    args = parser.parse_args()
    profile = load_profile(args.profile)
    paciolan = profile.index("paciolan-ticket-events")
    pos = profile.index("square-pos-transactions")

    client = get_client()

    pac_count = client.count(index=paciolan)["count"]
    pos_count = client.count(index=pos)["count"]
    print(f"{paciolan}: {pac_count:,} docs")
    print(f"{pos}: {pos_count:,} docs")

    tiers = client.search(
        index=paciolan,
        size=0,
        aggs={
            "by_tier": {
                "terms": {"field": "fan_tier", "size": 10},
                "aggs": {
                    "revenue": {"sum": {"field": "ticket_price"}},
                    "avg_price": {"avg": {"field": "ticket_price"}},
                },
            }
        },
    )
    print("\nFan tier distribution:")
    for b in tiers["aggregations"]["by_tier"]["buckets"]:
        print(
            f"  {b['key']}: {b['doc_count']:,} scans, "
            f"${b['revenue']['value']:,.0f} revenue, "
            f"avg ${b['avg_price']['value']:.2f}"
        )

    anomaly_hits = client.count(
        index=pos,
        query={
            "bool": {
                "filter": [
                    {"terms": {"stand_id": ANOMALY_STANDS}},
                    {
                        "range": {
                            "transaction_time": {
                                "gte": "2025-09-06T15:50:00Z",
                                "lte": "2025-09-06T16:05:00Z",
                            }
                        }
                    },
                ]
            }
        },
    )["count"]
    print(f"\nAnomaly window transactions (S04/S06/S09, 15:50–16:05): {anomaly_hits}")
    print("  ✓ Expected 0" if anomaly_hits == 0 else "  ✗ Expected 0 — check seed data")

    pos_revenue = client.search(
        index=pos,
        size=0,
        aggs={"total": {"sum": {"field": "total_amount"}}},
    )["aggregations"]["total"]["value"]
    ticket_revenue = client.search(
        index=paciolan,
        size=0,
        aggs={"total": {"sum": {"field": "ticket_price"}}},
    )["aggregations"]["total"]["value"]
    print(f"\nTotal POS revenue: ${pos_revenue:,.2f}")
    print(f"Total ticket revenue: ${ticket_revenue:,.2f}")
    print(f"Combined: ${pos_revenue + ticket_revenue:,.2f}")

    halftime = client.search(
        index=pos,
        size=0,
        query={
            "range": {
                "transaction_time": {
                    "gte": "2025-09-06T15:38:00Z",
                    "lte": "2025-09-06T15:52:00Z",
                }
            }
        },
        aggs={
            "by_minute": {
                "date_histogram": {
                    "field": "transaction_time",
                    "calendar_interval": "minute",
                }
            }
        },
    )
    peak = max(
        halftime["aggregations"]["by_minute"]["buckets"],
        key=lambda b: b["doc_count"],
        default={"key_as_string": "n/a", "doc_count": 0},
    )
    print(
        f"\nHalftime peak minute: {peak.get('key_as_string', 'n/a')} "
        f"({peak.get('doc_count', 0)} transactions)"
    )


if __name__ == "__main__":
    main()
