#!/usr/bin/env python3
"""Generate synthetic athletic booster donor records for Elastic bulk indexing."""

from __future__ import annotations

import argparse
import json
import math
import random
from pathlib import Path

from faker import Faker

from es_config import ROOT
from demo_profile import add_profile_argument, load_profile

fake = Faker()
Faker.seed(42)
random.seed(42)

CAPACITY_TIERS = ["<100k", "100k-500k", "500k-1M", "1M-5M", "5M+"]
DEGREES = ["Business", "Engineering", "Communications", "Education", "Law", "Medicine"]


def affinity_score(record: dict) -> float:
    score = 0.0
    score += min(record["wealth_signals"]["iwave_score"] * 0.30, 30)
    score += min(
        math.log1p(record["giving_history"]["lifetime_total"])
        / math.log1p(500_000)
        * 25,
        25,
    )
    score += min(record["engagement"]["game_attendance_count"] / 20 * 20, 20)
    score += record["engagement"]["email_open_rate_90d"] * 15
    score += min(record["engagement"]["events_attended_ytd"] / 10 * 10, 10)
    return round(score, 1)


def capacity_tier_for_iwave(iwave: int, real_estate: int) -> str:
    if iwave >= 90 or real_estate >= 3_000_000:
        return "5M+"
    if iwave >= 80 or real_estate >= 2_000_000:
        return "1M-5M"
    if iwave >= 65 or real_estate >= 1_000_000:
        return "500k-1M"
    if iwave >= 45 or real_estate >= 300_000:
        return "100k-500k"
    return "<100k"


def generate_donor(i: int, profile, golden: bool = False) -> dict:
    state = random.choices(profile.states, weights=profile.state_weights)[0]
    giving_years = random.randint(0, 20)
    lifetime_total = sum(random.randint(500, 25_000) for _ in range(giving_years))
    last_gift = random.randint(500, 10_000) if giving_years > 0 else 0
    game_attendance = random.randint(0, 30)
    iwave = random.randint(10, 99)
    real_estate = random.randint(0, 5_000_000)

    if golden:
        state = profile.home_state
        game_attendance = random.randint(10, 30)
        iwave = random.randint(75, 99)
        lifetime_total = random.randint(20_000, 200_000)
        last_gift = random.randint(5_000, 25_000)
        giving_years = max(giving_years, random.randint(5, 15))
        real_estate = random.randint(2_000_000, 5_000_000)

    record = {
        "donor_id": f"ALUM-{10000 + i}",
        "first_name": fake.first_name(),
        "last_name": fake.last_name(),
        "email": fake.email(),
        "graduation_year": random.randint(1975, 2018),
        "degree": random.choice(DEGREES),
        "location": {
            "city": fake.city(),
            "state": state,
            "zip": fake.zipcode(),
        },
        "giving_history": {
            "lifetime_total": lifetime_total,
            "last_gift_date": (
                fake.date_between(start_date="-3y", end_date="today").isoformat()
                if giving_years > 0
                else None
            ),
            "last_gift_amount": last_gift,
            "gift_count": giving_years,
            "largest_gift": (
                max(
                    last_gift,
                    random.randint(500, lifetime_total // max(giving_years, 1) + 1),
                )
                if giving_years > 0
                else 0
            ),
            "restricted_to": random.choice(
                ["Athletics", "Athletics", "Unrestricted", "Scholarship", "Athletics"]
            ),
        },
        "engagement": {
            "email_open_rate_90d": round(random.uniform(0, 1), 2),
            "last_email_open": fake.date_between(
                start_date="-90d", end_date="today"
            ).isoformat(),
            "events_attended_ytd": random.randint(0, 8),
            "game_attendance_count": game_attendance,
            "video_play_rate": round(random.uniform(0, 1), 2),
            "portal_logins_90d": random.randint(0, 20),
        },
        "wealth_signals": {
            "iwave_score": iwave,
            "estimated_capacity": capacity_tier_for_iwave(iwave, real_estate),
            "real_estate_value_est": real_estate,
            "business_ownership": random.choice([True, False]),
            "political_giving_total": random.randint(0, 50_000),
        },
        "portfolio_status": "unassigned",
    }

    if golden:
        record["engagement"]["email_open_rate_90d"] = round(random.uniform(0.6, 1.0), 2)
        record["engagement"]["events_attended_ytd"] = random.randint(3, 8)
        record["wealth_signals"]["business_ownership"] = random.choice([True, True, False])

    record["bio_text"] = (
        f"{record['first_name']} {record['last_name']} graduated in "
        f"{record['graduation_year']} with a degree in {record['degree']}. "
        f"Based in {record['location']['city']}, {record['location']['state']}. "
        f"Has attended {game_attendance} football games. "
        f"Lifetime giving: ${lifetime_total:,} to the {profile.fund_name}. "
        f"iWave score: {iwave}. "
        f"{'Owns a business. ' if record['wealth_signals']['business_ownership'] else ''}"
        f"Estimated real estate holdings: ${real_estate:,}."
    )
    record["affinity_score"] = affinity_score(record)
    return record


def write_ndjson(donors: list[dict], output_path: Path, index_name: str) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        for donor in donors:
            f.write(
                json.dumps({"index": {"_index": index_name, "_id": donor["donor_id"]}})
                + "\n"
            )
            f.write(json.dumps(donor) + "\n")


def summarize_tiers(donors: list[dict]) -> dict:
    tiers = {"low": 0, "medium": 0, "high": 0}
    for d in donors:
        score = d["affinity_score"]
        if score >= 75:
            tiers["high"] += 1
        elif score >= 50:
            tiers["medium"] += 1
        else:
            tiers["low"] += 1
    return tiers


def count_demo_matches(donors: list[dict], home_state: str) -> int:
    return sum(
        1
        for d in donors
        if d["location"]["state"] == home_state
        and d["engagement"]["game_attendance_count"] >= 3
        and d["wealth_signals"]["real_estate_value_est"] >= 2_000_000
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate synthetic donor records")
    add_profile_argument(parser)
    parser.add_argument(
        "--count", type=int, default=5000, help="Number of donor records"
    )
    parser.add_argument(
        "--golden-count",
        type=int,
        default=50,
        help="High-affinity home-state records seeded for demo queries",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output NDJSON path for bulk indexing",
    )
    parser.add_argument(
        "--index",
        default=None,
        help="Target Elasticsearch index name in bulk actions",
    )
    args = parser.parse_args()
    profile = load_profile(args.profile)
    index_name = args.index or profile.index("athletic-boosters")
    output = args.output or ROOT / "data" / (
        "okstate-donors.ndjson" if profile.index_prefix else "donors.ndjson"
    )

    golden_ids = set(range(args.golden_count))
    donors = [
        generate_donor(i, profile, golden=(i in golden_ids)) for i in range(args.count)
    ]

    write_ndjson(donors, output, index_name)

    tiers = summarize_tiers(donors)
    demo_matches = count_demo_matches(donors, profile.home_state)
    golden_scores = sorted(
        (d["affinity_score"] for i, d in enumerate(donors) if i in golden_ids),
        reverse=True,
    )[:5]

    print(f"Generated {len(donors)} donors → {output}")
    print(f"Profile: {profile.display_name} ({profile.id})")
    print(f"Index: {index_name}")
    print(f"Affinity tiers: low={tiers['low']}, medium={tiers['medium']}, high={tiers['high']}")
    print(
        f"Demo query matches ({profile.home_state}, 3+ games, $2M+ RE): {demo_matches}"
    )
    if golden_scores:
        print(f"Top golden affinity scores: {golden_scores}")


if __name__ == "__main__":
    main()
