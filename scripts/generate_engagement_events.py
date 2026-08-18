#!/usr/bin/env python3
"""Generate low-signal engagement events to trigger the at-risk donor alert."""

from __future__ import annotations

import argparse
import json
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

from es_config import ROOT, get_client
from demo_profile import add_profile_argument, load_profile

EVENT_TYPES = [
    ("portal_login", 0.05, 18),
    ("email_open", 0.02, 12),
    ("event_attendance", 0.08, 25),
    ("call_completed", 0.03, 15),
]
CAMPAIGNS = [
    "gift-officer-outreach",
    "annual-fund-ask",
    "bowl-game-invite",
    "athletic-director-note",
    "giving-tuesday",
    "season-ticket-renewal",
]
FISCAL_YEARS = ["FY2024", "FY2025", "FY2026"]


def ensure_engagement_index(client, engagement_index: str) -> None:
    if client.indices.exists(index=engagement_index):
        return
    mapping = json.loads(
        (ROOT / "elastic" / "booster-engagement-events-mapping.json").read_text(
            encoding="utf-8"
        )
    )
    print(f"Creating {engagement_index}")
    client.indices.create(index=engagement_index, mappings=mapping["mappings"])


def fetch_high_affinity_donors(client, boosters_index: str, engagement_index: str, limit: int) -> list[str]:
    existing_ids: set[str] = set()
    if client.indices.exists(index=engagement_index) and client.count(index=engagement_index)["count"]:
        existing = client.esql.query(
            query=f"""
            FROM {engagement_index}
            | STATS cnt = COUNT(*) BY donor_id
            | KEEP donor_id
            | LIMIT 1000
            """
        )
        existing_ids = {row[0] for row in existing["values"]}

    candidates = client.search(
        index=boosters_index,
        size=limit * 3,
        query={"range": {"affinity_score": {"gte": 70}}},
        sort=[{"affinity_score": "desc"}],
        _source=["donor_id"],
    )
    donor_ids = []
    for hit in candidates["hits"]["hits"]:
        donor_id = hit["_source"]["donor_id"]
        if donor_id not in existing_ids:
            donor_ids.append(donor_id)
        if len(donor_ids) >= limit:
            break
    return donor_ids


def fetch_borderline_donors(client, engagement_index: str, limit: int = 10) -> list[str]:
    if not client.indices.exists(index=engagement_index):
        return []
    if client.count(index=engagement_index)["count"] == 0:
        return []
    result = client.esql.query(
        query=f"""
        FROM {engagement_index}
        | STATS avg_signal = AVG(signal_value), event_count = COUNT(*) BY donor_id
        | WHERE avg_signal >= 50 AND avg_signal < 55
        | SORT avg_signal ASC
        | KEEP donor_id
        | LIMIT {limit}
        """
    )
    return [row[0] for row in result["values"]]


def generate_events(
    donor_ids: list[str],
    events_per_donor: int,
    signal_min: float,
    signal_max: float,
    seed: int = 42,
) -> list[dict]:
    random.seed(seed)
    now = datetime.now(timezone.utc)
    events = []

    for donor_id in donor_ids:
        for _ in range(events_per_donor):
            event_type, _, _ = random.choices(
                EVENT_TYPES,
                weights=[w for _, w, _ in EVENT_TYPES],
            )[0]
            _, type_min, type_max = next(t for t in EVENT_TYPES if t[0] == event_type)
            lo = max(signal_min, type_min)
            hi = min(signal_max, type_max)
            days_ago = random.randint(0, 89)
            event_date = (now - timedelta(days=days_ago)).replace(
                hour=random.randint(8, 20),
                minute=random.randint(0, 59),
                second=0,
                microsecond=0,
            )
            events.append(
                {
                    "donor_id": donor_id,
                    "event_type": event_type,
                    "event_date": event_date.isoformat().replace("+00:00", "Z"),
                    "signal_value": round(random.uniform(lo, hi), 2),
                    "campaign": random.choice(CAMPAIGNS),
                    "fiscal_year": random.choice(FISCAL_YEARS),
                }
            )
    return events


def write_ndjson(events: list[dict], output_path: Path, index_name: str) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        for i, event in enumerate(events):
            doc_id = f"{event['donor_id']}-{event['event_type']}-{i}"
            f.write(json.dumps({"index": {"_index": index_name, "_id": doc_id}}) + "\n")
            f.write(json.dumps(event) + "\n")


def bulk_index(client, events: list[dict], engagement_index: str, chunk_size: int = 500) -> None:
    lines = []
    for i, event in enumerate(events):
        doc_id = f"low-signal-{event['donor_id']}-{i}"
        lines.append(json.dumps({"index": {"_index": engagement_index, "_id": doc_id}}))
        lines.append(json.dumps(event))

    total = len(events)
    indexed = 0
    for start in range(0, len(lines), chunk_size * 2):
        chunk = "\n".join(lines[start : start + chunk_size * 2]) + "\n"
        response = client.bulk(body=chunk, refresh=False)
        if response.get("errors"):
            errors = [
                (item.get("index") or {}).get("error")
                for item in response.get("items", [])
                if (item.get("index") or {}).get("error")
            ]
            raise RuntimeError(f"Bulk errors: {errors[:3]}")
        indexed += min(chunk_size, total - indexed)
        print(f"  … {indexed}/{total}")

    client.indices.refresh(index=engagement_index)


def count_alert_matches(client, engagement_index: str) -> int:
    if not client.indices.exists(index=engagement_index):
        return 0
    if client.count(index=engagement_index)["count"] == 0:
        return 0
    result = client.esql.query(
        query=f"""
        FROM {engagement_index}
        | STATS avg_signal = AVG(signal_value), event_count = COUNT(*) BY donor_id
        | WHERE avg_signal < 50
        | STATS match_count = COUNT(*)
        """
    )
    return result["values"][0][0] if result["values"] else 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate low-signal engagement events for alert demo"
    )
    add_profile_argument(parser)
    parser.add_argument("--new-donors", type=int, default=25)
    parser.add_argument("--events-per-donor", type=int, default=40)
    parser.add_argument("--borderline-donors", type=int, default=8)
    parser.add_argument("--borderline-events", type=int, default=20)
    parser.add_argument("--signal-min", type=float, default=5.0)
    parser.add_argument("--signal-max", type=float, default=35.0)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    profile = load_profile(args.profile)
    boosters_index = profile.index("athletic-boosters")
    engagement_index = profile.index("booster-engagement-events")
    output = args.output or ROOT / "data" / (
        "okstate-engagement-events-low-signal.ndjson"
        if profile.index_prefix
        else "engagement-events-low-signal.ndjson"
    )

    client = get_client()
    ensure_engagement_index(client, engagement_index)
    before = count_alert_matches(client, engagement_index)
    print(f"Alert matches before: {before}")

    new_donor_ids = fetch_high_affinity_donors(
        client, boosters_index, engagement_index, args.new_donors
    )
    borderline_ids = fetch_borderline_donors(
        client, engagement_index, args.borderline_donors
    )
    print(f"Targeting {len(new_donor_ids)} new high-affinity donors")
    print(f"Targeting {len(borderline_ids)} borderline donors: {borderline_ids[:5]}…")

    events = []
    events.extend(
        generate_events(
            new_donor_ids,
            args.events_per_donor,
            args.signal_min,
            args.signal_max,
        )
    )
    events.extend(
        generate_events(
            borderline_ids,
            args.borderline_events,
            args.signal_min,
            min(args.signal_max, 20.0),
        )
    )

    write_ndjson(events, output, engagement_index)
    print(f"Generated {len(events)} events → {output}")

    if args.dry_run:
        return

    print("Bulk indexing…")
    bulk_index(client, events, engagement_index)

    after = count_alert_matches(client, engagement_index)
    print(f"Alert matches after: {after}")

    preview = client.esql.query(
        query=f"""
        FROM {engagement_index}
        | STATS avg_signal = AVG(signal_value), event_count = COUNT(*) BY donor_id
        | WHERE avg_signal < 50
        | SORT avg_signal ASC
        | KEEP donor_id, avg_signal, event_count
        | LIMIT 10
        """
    )
    print("\nTop alert matches:")
    for row in preview["values"]:
        print(f"  {row[0]} avg={row[1]:.1f} events={row[2]}")


if __name__ == "__main__":
    main()
