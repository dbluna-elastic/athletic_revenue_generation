#!/usr/bin/env python3
"""Generate and replay game day revenue events (Paciolan + Square POS)."""

from __future__ import annotations

import argparse
import random
import time
import uuid
from datetime import datetime, timedelta, timezone

from elasticsearch import helpers
from tqdm import tqdm

from es_config import get_client
from demo_profile import DEFAULT_STANDS, add_profile_argument, load_profile

PACIOLAN_INDEX = "paciolan-ticket-events"
POS_INDEX = "square-pos-transactions"

GAME_ID = "GAME-2025-HOME-01"
GATES_OPEN = datetime(2025, 9, 6, 13, 0, 0)
GAME_END = datetime(2025, 9, 6, 17, 30, 0)
DEFAULT_SPEED = 10

ANOMALY_START = datetime(2025, 9, 6, 15, 50, 0)
ANOMALY_END = datetime(2025, 9, 6, 16, 5, 0)
ANOMALY_STANDS = {"S04", "S06", "S09"}

TICKET_TYPES = [
    {"type": "student", "tier": "Student", "price": 12.00, "pct": 0.18},
    {"type": "alumni_general", "tier": "Alumni", "price": 65.00, "pct": 0.38},
    {"type": "premium_club", "tier": "Premium", "price": 195.00, "pct": 0.22},
    {"type": "suite", "tier": "Suite Holder", "price": 450.00, "pct": 0.06},
    {"type": "walk_up", "tier": "Walk-Up", "price": 80.00, "pct": 0.10},
    {"type": "faculty_staff", "tier": "Faculty/Staff", "price": 0.00, "pct": 0.06},
]

GATES = ["Gate A", "Gate B", "Gate C", "Gate D", "Gate E", "Gate F"]
METHODS = ["card", "card", "card", "mobile_pay", "cash"]
STANDS = list(DEFAULT_STANDS)


def apply_profile(profile) -> None:
    global PACIOLAN_INDEX, POS_INDEX, GAME_ID, GATES, STANDS
    PACIOLAN_INDEX = profile.index("paciolan-ticket-events")
    POS_INDEX = profile.index("square-pos-transactions")
    GAME_ID = profile.game_id
    GATES = list(profile.gates)
    STANDS = list(profile.stands)

random.seed(42)


def iso_ts(ts: datetime) -> str:
    return ts.strftime("%Y-%m-%dT%H:%M:%S") + "Z"


def txn_rate(ts: datetime) -> float:
    hour = ts.hour + ts.minute / 60
    if hour < 13:
        return 0
    if hour < 14:
        return 80
    if hour < 15:
        return 50
    if hour < 15.25:
        return 40
    if hour < 15.67:
        return 45
    if hour < 15.83:
        return 250
    if hour < 16.25:
        return 40
    if hour < 16.67:
        return 35
    return 20


def in_anomaly(ts: datetime, live: bool, replay_start: datetime | None) -> bool:
    if not live:
        return ANOMALY_START <= ts <= ANOMALY_END
    if replay_start is None:
        return False
    anomaly_start_live = replay_start + (ANOMALY_START - GATES_OPEN)
    anomaly_end_live = replay_start + (ANOMALY_END - GATES_OPEN)
    return anomaly_start_live <= ts <= anomaly_end_live


def gen_ticket_scan(ts: datetime) -> dict:
    ticket = random.choices(TICKET_TYPES, weights=[t["pct"] for t in TICKET_TYPES])[0]
    return {
        "_index": PACIOLAN_INDEX,
        "_id": str(uuid.uuid4()),
        "_source": {
            "event_id": str(uuid.uuid4()),
            "game_id": GAME_ID,
            "scan_timestamp": iso_ts(ts),
            "gate": random.choice(GATES),
            "section": str(random.randint(100, 350)),
            "ticket_type": ticket["type"],
            "fan_tier": ticket["tier"],
            "ticket_price": ticket["price"],
            "payment_method": random.choice(METHODS),
            "is_resale": random.random() < 0.08,
            "source_system": "paciolan",
        },
    }


def gen_pos_transaction(
    ts: datetime, live: bool = False, replay_start: datetime | None = None
) -> dict | None:
    stand = random.choice(STANDS)
    if in_anomaly(ts, live, replay_start) and stand["id"] in ANOMALY_STANDS:
        return None

    item_name, unit_price = random.choice(stand["items"])
    qty = random.choices([1, 2, 3], weights=[0.70, 0.22, 0.08])[0]
    return {
        "_index": POS_INDEX,
        "_id": str(uuid.uuid4()),
        "_source": {
            "transaction_id": str(uuid.uuid4()),
            "game_id": GAME_ID,
            "transaction_time": iso_ts(ts),
            "stand_id": stand["id"],
            "stand_name": stand["name"],
            "stand_zone": stand["zone"],
            "category": item_name.lower().replace(" ", "_"),
            "item_name": item_name,
            "quantity": qty,
            "unit_price": unit_price,
            "total_amount": round(unit_price * qty, 2),
            "payment_method": random.choice(METHODS),
            "is_anomaly": False,
            "source_system": "square_clover",
        },
    }


def docs_for_minute(
    game_ts: datetime,
    live: bool = False,
    replay_start: datetime | None = None,
    event_ts: datetime | None = None,
) -> list[dict]:
    stamp = event_ts if live and event_ts else game_ts
    rate = txn_rate(game_ts)
    docs: list[dict] = []

    scan_rate = max(0, int(rate * 0.6)) if game_ts.hour < 15 else 0
    for _ in range(scan_rate):
        jitter = timedelta(seconds=random.randint(0, 59))
        docs.append(gen_ticket_scan(stamp + jitter if live else game_ts + jitter))

    for _ in range(int(rate)):
        jitter = timedelta(seconds=random.randint(0, 59))
        ts = stamp + jitter if live else game_ts + jitter
        doc = gen_pos_transaction(ts, live=live, replay_start=replay_start)
        if doc:
            docs.append(doc)

    return docs


def bulk_docs(es, batch: list[dict]) -> None:
    if not batch:
        return
    success, errors = helpers.bulk(es, batch, raise_on_error=False)
    if errors:
        raise RuntimeError(f"Bulk index errors: {errors[:3]}")


def seed(es) -> None:
    print(f"Seeding full game history for {GAME_ID}...")
    current = GATES_OPEN
    step = timedelta(minutes=1)
    batch: list[dict] = []
    total = 0
    minutes = int((GAME_END - GATES_OPEN).total_seconds() // 60) + 1

    for _ in tqdm(range(minutes), desc="Game minutes"):
        batch.extend(docs_for_minute(current))
        if len(batch) >= 500:
            bulk_docs(es, batch)
            total += len(batch)
            batch = []
        current += step

    if batch:
        bulk_docs(es, batch)
        total += len(batch)

    es.indices.refresh(index=PACIOLAN_INDEX)
    es.indices.refresh(index=POS_INDEX)
    print(f"Done. {total:,} documents indexed.")


def replay(es, speed: int = DEFAULT_SPEED, live: bool = False) -> None:
    print(f"Starting live replay at {speed}× speed ({60 / speed:.0f}s per game minute)...")
    if live:
        print("Live mode: timestamps use current UTC (visible in Kibana default time range)")
    print(f"Game window: {GATES_OPEN.strftime('%I:%M %p')} → {GAME_END.strftime('%I:%M %p')}")
    print("Press Ctrl+C to stop.\n")

    replay_start = datetime.now(timezone.utc).replace(tzinfo=None)
    current = GATES_OPEN
    step = timedelta(minutes=1)
    sleep_s = 60 / speed

    try:
        while current <= GAME_END:
            event_ts = datetime.now(timezone.utc).replace(tzinfo=None) if live else None
            batch = docs_for_minute(
                current, live=live, replay_start=replay_start, event_ts=event_ts
            )
            bulk_docs(es, batch)

            in_window = (
                in_anomaly(event_ts or current, live, replay_start)
                if live
                else ANOMALY_START <= current <= ANOMALY_END
            )
            phase = "🚨 ANOMALY" if in_window else "▶"
            print(
                f"  {phase} {current.strftime('%H:%M')} | +{len(batch):>3} docs | "
                f"rate: {txn_rate(current):.0f} txn/min"
            )

            current += step
            time.sleep(sleep_s)
    except KeyboardInterrupt:
        print("\nReplay stopped.")
        return

    print("\nReplay complete.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Game day revenue seed/replay")
    add_profile_argument(parser)
    parser.add_argument("mode", choices=["seed", "replay"])
    parser.add_argument("--speed", type=int, default=DEFAULT_SPEED)
    parser.add_argument(
        "--live",
        action="store_true",
        help="Stamp replay events with current UTC time for Kibana live dashboards",
    )
    args = parser.parse_args()
    apply_profile(load_profile(args.profile))

    es = get_client()
    if args.mode == "seed":
        seed(es)
    else:
        replay(es, speed=args.speed, live=args.live)


if __name__ == "__main__":
    main()
