# Game Day Revenue — Data Setup Plan

Covers the Elastic data architecture and Python-based live replay pipeline for three demo use cases: **Live Revenue Ticker**, **Fan Segment Revenue Breakdown**, and **Revenue Anomaly Detection**. Data appears to originate from two external systems — Paciolan (ticketing) and Square/Clover (POS concessions) — and streams into Elasticsearch in real time via a replay script.

---

## Decisions Locked

| Question | Decision |
|---|---|
| Ingest method | Python live replay script — streams events to Elastic at realistic intervals |
| Source systems | Paciolan (ticketing + gate scans) + Square/Clover (POS concessions + merch) |
| Anomaly scenario | Multiple stands spike at halftime then drop — simulates payment processor issue |
| Environment | Existing Elastic cluster |

---

## 1. The Demo Data Story

The replay script simulates **a single football game** — a Saturday home opener with 58,000 fans. The game runs across a compressed 3-hour window that can be replayed at 10× speed (18 minutes) for demo sessions, or at real speed for longer demonstrations.

### Game Day Timeline

| Phase | Real Time | Replay (10×) | Revenue Pattern |
|---|---|---|---|
| Gates open | 1:00 PM | T+0:00 | Ticket scans spike, parking begins |
| Pre-game | 1:00–3:00 PM | T+0:00–T+0:12 | Steady concession spend, merch purchases |
| Kickoff | 3:00 PM | T+0:12 | Ticket scan tail-off, concessions steady |
| Q1–Q2 | 3:00–3:40 PM | T+0:12–T+0:16 | Moderate POS activity |
| Halftime rush | 3:40–4:00 PM | T+0:16–T+0:18 | **All stands spike simultaneously** |
| Anomaly window | 3:50–4:05 PM | T+0:17–T+0:18 | **Stands 4, 6, 9 drop to zero** |
| Q3–Q4 | 4:00–4:50 PM | T+0:18–T+0:26 | Recovery, steady spend |
| Post-game | 4:50–5:30 PM | T+0:26–T+0:30 | Merch surge, ticket scan exit |

---

## 2. Index Architecture

Two indexes mirror the two external source systems. A third index provides a unified view for dashboards.

### Index 1: `paciolan-ticket-events`
Mirrors a Paciolan gate scan + ticket API export.

```json
PUT /paciolan-ticket-events
{
  "mappings": {
    "properties": {
      "event_id":        { "type": "keyword" },
      "game_id":         { "type": "keyword" },
      "scan_timestamp":  { "type": "date" },
      "gate":            { "type": "keyword" },
      "section":         { "type": "keyword" },
      "ticket_type":     { "type": "keyword" },
      "fan_tier":        { "type": "keyword" },
      "ticket_price":    { "type": "float" },
      "payment_method":  { "type": "keyword" },
      "is_resale":       { "type": "boolean" },
      "source_system":   { "type": "keyword" }
    }
  }
}
```

**Fan tier values** (derived from `ticket_type` at ingest):

| ticket_type | fan_tier |
|---|---|
| `student` | `Student` |
| `alumni_general` | `Alumni` |
| `premium_club` | `Premium` |
| `suite` | `Suite Holder` |
| `walk_up` | `Walk-Up` |
| `faculty_staff` | `Faculty/Staff` |

---

### Index 2: `square-pos-transactions`
Mirrors a Square/Clover POS webhook or daily export.

```json
PUT /square-pos-transactions
{
  "mappings": {
    "properties": {
      "transaction_id":   { "type": "keyword" },
      "game_id":          { "type": "keyword" },
      "transaction_time": { "type": "date" },
      "stand_id":         { "type": "keyword" },
      "stand_name":       { "type": "keyword" },
      "stand_zone":       { "type": "keyword" },
      "category":         { "type": "keyword" },
      "item_name":        { "type": "keyword" },
      "quantity":         { "type": "integer" },
      "unit_price":       { "type": "float" },
      "total_amount":     { "type": "float" },
      "payment_method":   { "type": "keyword" },
      "is_anomaly":       { "type": "boolean" },
      "source_system":    { "type": "keyword" }
    }
  }
}
```

**Stand configuration** (used in generator):

| stand_id | stand_name | zone | categories |
|---|---|---|---|
| `S01` | North Concourse Beer Garden | North | beer, wine, spirits |
| `S02` | Main Grill — Gate A | North | food, non-alcoholic |
| `S03` | South End Zone Cantina | South | food, beer |
| `S04` | Premium Club Bar | Premium | beer, wine, spirits |
| `S05` | Student Section Snacks | Student | food, non-alcoholic |
| `S06` | West Concourse Grill | West | food, beer |
| `S07` | Team Store — Main | Main | merch |
| `S08` | Team Store — South | South | merch |
| `S09` | East End Zone Bar | East | beer, spirits |
| `S10` | Visiting Fan Concessions | Visitor | food, non-alcoholic |

**Anomaly stands:** S04, S06, S09 go dark during the halftime anomaly window.

---

## 3. Python Live Replay Script

The script has two modes:
- **`--seed`**: Generates and bulk-indexes the full game history (run once before the demo)
- **`--replay`**: Streams events to Elastic in real time at a configurable speed multiplier

```python
#!/usr/bin/env python3
# gameday_replay.py
# pip install elasticsearch faker tqdm

import argparse
import json
import random
import time
import uuid
from datetime import datetime, timedelta
from faker import Faker
from elasticsearch import Elasticsearch, helpers

fake = Faker()

# ── Configuration ──────────────────────────────────────────────────────────────

ES_HOST     = "https://<your-cluster>"
ES_USER     = "elastic"
ES_PASSWORD = "<password>"
GAME_ID     = "GAME-2025-HOME-01"
GAME_DATE   = datetime(2025, 9, 6)       # Saturday home opener
GATES_OPEN  = datetime(2025, 9, 6, 13, 0)
GAME_END    = datetime(2025, 9, 6, 17, 30)
TOTAL_FANS  = 58000
SPEED       = 10                          # 10× replay speed (18-min demo window)

# Anomaly window: halftime payment processor issue
ANOMALY_START   = datetime(2025, 9, 6, 15, 50)
ANOMALY_END     = datetime(2025, 9, 6, 16, 5)
ANOMALY_STANDS  = {"S04", "S06", "S09"}

# ── Ticket configuration ────────────────────────────────────────────────────────

TICKET_TYPES = [
    {"type": "student",       "tier": "Student",      "price": 12.00,  "pct": 0.18},
    {"type": "alumni_general","tier": "Alumni",        "price": 65.00,  "pct": 0.38},
    {"type": "premium_club",  "tier": "Premium",       "price": 195.00, "pct": 0.22},
    {"type": "suite",         "tier": "Suite Holder",  "price": 450.00, "pct": 0.06},
    {"type": "walk_up",       "tier": "Walk-Up",       "price": 80.00,  "pct": 0.10},
    {"type": "faculty_staff", "tier": "Faculty/Staff", "price": 0.00,   "pct": 0.06},
]

GATES   = ["Gate A", "Gate B", "Gate C", "Gate D", "Gate E", "Gate F"]
METHODS = ["card", "card", "card", "mobile_pay", "cash"]

# ── POS configuration ───────────────────────────────────────────────────────────

STANDS = [
    {"id": "S01", "name": "North Concourse Beer Garden", "zone": "North",
     "items": [("Draft Beer", 12.0), ("Craft Beer", 14.0), ("Wine", 11.0), ("Spirits", 13.0)]},
    {"id": "S02", "name": "Main Grill — Gate A",         "zone": "North",
     "items": [("Hot Dog", 7.0), ("Nachos", 9.0), ("Soda", 5.0), ("Water", 4.0), ("Burger", 12.0)]},
    {"id": "S03", "name": "South End Zone Cantina",      "zone": "South",
     "items": [("Tacos", 11.0), ("Draft Beer", 12.0), ("Soda", 5.0), ("Chips", 6.0)]},
    {"id": "S04", "name": "Premium Club Bar",            "zone": "Premium",
     "items": [("Craft Beer", 16.0), ("Wine", 14.0), ("Cocktail", 18.0), ("Charcuterie", 22.0)]},
    {"id": "S05", "name": "Student Section Snacks",      "zone": "Student",
     "items": [("Hot Dog", 6.0), ("Soda", 4.0), ("Popcorn", 5.0), ("Water", 3.0)]},
    {"id": "S06", "name": "West Concourse Grill",        "zone": "West",
     "items": [("Burger", 12.0), ("Draft Beer", 12.0), ("Fries", 7.0), ("Soda", 5.0)]},
    {"id": "S07", "name": "Team Store — Main",           "zone": "Main",
     "items": [("Jersey", 120.0), ("Hat", 35.0), ("Shirt", 45.0), ("Hoodie", 75.0)]},
    {"id": "S08", "name": "Team Store — South",          "zone": "South",
     "items": [("Jersey", 120.0), ("Hat", 35.0), ("Pennant", 18.0), ("Shirt", 45.0)]},
    {"id": "S09", "name": "East End Zone Bar",           "zone": "East",
     "items": [("Draft Beer", 12.0), ("Craft Beer", 14.0), ("Spirits", 13.0), ("Shot", 9.0)]},
    {"id": "S10", "name": "Visiting Fan Concessions",    "zone": "Visitor",
     "items": [("Hot Dog", 7.0), ("Soda", 5.0), ("Nachos", 9.0), ("Water", 4.0)]},
]
STAND_MAP = {s["id"]: s for s in STANDS}

# ── Transaction rate by game phase ─────────────────────────────────────────────
# Returns approx transactions-per-minute for a given timestamp

def txn_rate(ts: datetime) -> float:
    hour = ts.hour + ts.minute / 60
    if hour < 13:    return 0
    if hour < 14:    return 80    # gates open
    if hour < 15:    return 50    # pre-game steady
    if hour < 15.25: return 40    # kickoff
    if hour < 15.67: return 45    # Q1-Q2
    if hour < 15.83: return 250   # halftime SPIKE
    if hour < 16.25: return 40    # Q3
    if hour < 16.67: return 35    # Q4
    return 20                     # post-game

# ── Event generators ───────────────────────────────────────────────────────────

def gen_ticket_scan(ts: datetime) -> dict:
    t = random.choices(TICKET_TYPES, weights=[x["pct"] for x in TICKET_TYPES])[0]
    return {
        "_index": "paciolan-ticket-events",
        "_id": str(uuid.uuid4()),
        "_source": {
            "event_id":       str(uuid.uuid4()),
            "game_id":        GAME_ID,
            "scan_timestamp": ts.isoformat() + "Z",
            "gate":           random.choice(GATES),
            "section":        f"{random.randint(100, 350)}",
            "ticket_type":    t["type"],
            "fan_tier":       t["tier"],
            "ticket_price":   t["price"],
            "payment_method": random.choice(METHODS),
            "is_resale":      random.random() < 0.08,
            "source_system":  "paciolan"
        }
    }

def gen_pos_transaction(ts: datetime) -> dict:
    stand = random.choice(STANDS)
    in_anomaly = (
        ts >= ANOMALY_START
        and ts <= ANOMALY_END
        and stand["id"] in ANOMALY_STANDS
    )
    if in_anomaly:
        return None   # stand is down — no transaction generated

    item_name, unit_price = random.choice(stand["items"])
    qty = random.choices([1, 2, 3], weights=[0.70, 0.22, 0.08])[0]
    return {
        "_index": "square-pos-transactions",
        "_id": str(uuid.uuid4()),
        "_source": {
            "transaction_id":   str(uuid.uuid4()),
            "game_id":          GAME_ID,
            "transaction_time": ts.isoformat() + "Z",
            "stand_id":         stand["id"],
            "stand_name":       stand["name"],
            "stand_zone":       stand["zone"],
            "category":         item_name.lower().replace(" ", "_"),
            "item_name":        item_name,
            "quantity":         qty,
            "unit_price":       unit_price,
            "total_amount":     round(unit_price * qty, 2),
            "payment_method":   random.choice(METHODS),
            "is_anomaly":       False,
            "source_system":    "square_clover"
        }
    }

# ── Seed mode: generate full game history and bulk index ───────────────────────

def seed(es: Elasticsearch):
    print(f"Seeding full game history for {GAME_ID}...")
    current = GATES_OPEN
    step    = timedelta(minutes=1)
    batch   = []
    total   = 0

    while current <= GAME_END:
        rate = txn_rate(current)

        # Ticket scans (heavy at gate open, trailing off after kickoff)
        scan_rate = max(0, int(rate * 0.6)) if current.hour < 15 else 0
        for _ in range(scan_rate):
            jitter = timedelta(seconds=random.randint(0, 59))
            batch.append(gen_ticket_scan(current + jitter))

        # POS transactions
        for _ in range(int(rate)):
            jitter = timedelta(seconds=random.randint(0, 59))
            doc = gen_pos_transaction(current + jitter)
            if doc:
                batch.append(doc)

        # Bulk index in chunks of 500
        if len(batch) >= 500:
            helpers.bulk(es, batch)
            total += len(batch)
            print(f"  Indexed {total:,} docs — game time {current.strftime('%H:%M')}")
            batch = []

        current += step

    if batch:
        helpers.bulk(es, batch)
        total += len(batch)

    print(f"Done. {total:,} total documents indexed.")

# ── Replay mode: stream events in real time at SPEED multiplier ────────────────

def replay(es: Elasticsearch, speed: int = SPEED):
    print(f"Starting live replay at {speed}× speed (1 real minute = {60/speed:.0f}s)...")
    print(f"Game window: {GATES_OPEN.strftime('%I:%M %p')} → {GAME_END.strftime('%I:%M %p')}")
    print("Press Ctrl+C to stop.\n")

    current  = GATES_OPEN
    step     = timedelta(minutes=1)
    sleep_s  = 60 / speed

    while current <= GAME_END:
        rate = txn_rate(current)
        batch = []

        scan_rate = max(0, int(rate * 0.6)) if current.hour < 15 else 0
        for _ in range(scan_rate):
            batch.append(gen_ticket_scan(current))

        for _ in range(int(rate)):
            doc = gen_pos_transaction(current)
            if doc:
                batch.append(doc)

        if batch:
            helpers.bulk(es, batch)

        phase = "🚨 ANOMALY" if ANOMALY_START <= current <= ANOMALY_END else "▶"
        print(f"  {phase} {current.strftime('%H:%M')} | +{len(batch):>3} docs | rate: {rate:.0f} txn/min")

        current += step
        time.sleep(sleep_s)

    print("\nReplay complete.")

# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Game Day Revenue Replay")
    parser.add_argument("mode", choices=["seed", "replay"], help="seed or replay")
    parser.add_argument("--speed", type=int, default=SPEED, help="Replay speed multiplier (default 10)")
    args = parser.parse_args()

    es = Elasticsearch(ES_HOST, basic_auth=(ES_USER, ES_PASSWORD), verify_certs=False)

    if args.mode == "seed":
        seed(es)
    else:
        replay(es, args.speed)
```

### Usage

```bash
# Install dependencies
pip install elasticsearch faker tqdm --break-system-packages

# Step 1: Create indexes (run mapping PUTs in Dev Tools first)

# Step 2: Seed full game history (run once — takes ~2 minutes)
python gameday_replay.py seed

# Step 3: During demo — stream live events at 10× speed
python gameday_replay.py replay --speed 10

# Slower replay for longer sessions (5× = 36-minute window)
python gameday_replay.py replay --speed 5
```

---

## 4. Simulating the External Source Story

The `source_system` field on every document is the key to the "data from outside Elastic" narrative. During the demo, frame it this way:

| What the audience sees | What's actually happening |
|---|---|
| "This is a live feed from Paciolan's ticketing API" | `paciolan-ticket-events` index, `source_system: paciolan` |
| "These POS transactions are coming from Square terminals at each stand" | `square-pos-transactions` index, `source_system: square_clover` |
| "In production, you'd use the Elastic Logstash Square connector or a webhook → Logstash pipeline" | Python script replay approximates this exactly |

### Logstash Pipeline (Production Reference — include in demo narrative)

Show this as the "how it works in production" slide/panel:

```ruby
# logstash-gameday.conf

input {
  # Paciolan webhook (ticket scan events)
  http {
    port => 8080
    codec => json
    tags => ["paciolan"]
  }

  # Square webhook (POS transaction events)
  http {
    port => 8081
    codec => json
    tags => ["square"]
  }
}

filter {
  if "paciolan" in [tags] {
    mutate {
      add_field => { "source_system" => "paciolan" }
      rename    => { "scannedAt" => "scan_timestamp" }
    }
  }

  if "square" in [tags] {
    mutate {
      add_field => { "source_system" => "square_clover" }
      rename    => { "created_at" => "transaction_time" }
    }
    ruby {
      code => "event.set('total_amount', event.get('base_price_money')['amount'] / 100.0)"
    }
  }
}

output {
  if "paciolan" in [tags] {
    elasticsearch {
      hosts     => ["https://<your-cluster>"]
      index     => "paciolan-ticket-events"
      user      => "elastic"
      password  => "<password>"
    }
  }
  if "square" in [tags] {
    elasticsearch {
      hosts     => ["https://<your-cluster>"]
      index     => "square-pos-transactions"
      user      => "elastic"
      password  => "<password>"
    }
  }
}
```

---

## 5. Fan Segment Classification

Fan tier lives on the ticket event (`fan_tier` field). To join POS spend to fan tier for the **Fan Segment Revenue Breakdown** demo, use an Elasticsearch **Enrich Policy** that looks up the fan's section → tier mapping.

### Enrich Policy: Section → Fan Tier

```json
PUT /_enrich/policy/section-to-fan-tier
{
  "match": {
    "indices":       "paciolan-ticket-events",
    "match_field":   "section",
    "enrich_fields": ["fan_tier", "ticket_type"]
  }
}

POST /_enrich/policy/section-to-fan-tier/_execute
```

For the demo, fan tier is already on ticket events, so Kibana can directly break down ticket revenue by `fan_tier`. POS transactions don't carry fan tier (as in real life — a concession stand doesn't know who's buying). The demo story for segment breakdown focuses on **ticket revenue by fan tier**, with POS shown as total volume.

---

## 6. ML Anomaly Detection Setup

### Anomaly Job: Per-Stand Transaction Rate

```json
PUT _ml/anomaly_detectors/gameday-stand-revenue
{
  "description": "Detects abnormal transaction rate drops at individual concession stands",
  "analysis_config": {
    "bucket_span": "2m",
    "detectors": [
      {
        "function":          "low_count",
        "over_field_name":   "stand_id",
        "detector_description": "Unusually low transaction count per stand per 2-minute window"
      },
      {
        "function":          "low_sum",
        "field_name":        "total_amount",
        "over_field_name":   "stand_id",
        "detector_description": "Unusually low revenue per stand per 2-minute window"
      }
    ],
    "influencers": ["stand_id", "stand_zone"]
  },
  "data_description": {
    "time_field": "transaction_time"
  },
  "datafeed_config": {
    "indices": ["square-pos-transactions"],
    "query":   { "match_all": {} }
  }
}
```

### Why Two Detectors

- `low_count` catches when a stand stops processing entirely (the clearest demo signal)
- `low_sum` catches when a stand processes but at reduced amounts (catches partial outages)

During the anomaly window (15:50–16:05), stands S04, S06, and S09 produce zero transactions. Both detectors will fire with anomaly scores approaching 100 — the anomaly explorer will show three simultaneous red cells in the swimlane view.

### Anomaly Alert → Kibana Cases

```
Rule: Anomaly score ≥ 90 on job gameday-stand-revenue
Action: Create Kibana Case
Title: "⚠️ Stand Outage Detected: {{stand_id}} — Revenue Loss in Progress"
Tags: game-day, pos-outage, ops
Severity: Critical
```

---

## 7. Validation Queries

Run these in Dev Tools after seeding to confirm data looks right.

### Total revenue by source system
```json
GET /paciolan-ticket-events,square-pos-transactions/_search
{
  "size": 0,
  "aggs": {
    "by_source": {
      "terms": { "field": "source_system" },
      "aggs": {
        "total_revenue": {
          "sum": {
            "field": "ticket_price",
            "missing": 0
          }
        }
      }
    }
  }
}
```

### Confirm anomaly window has zero transactions on target stands
```json
GET /square-pos-transactions/_search
{
  "query": {
    "bool": {
      "filter": [
        { "terms": { "stand_id": ["S04", "S06", "S09"] } },
        { "range": { "transaction_time": {
          "gte": "2025-09-06T15:50:00Z",
          "lte": "2025-09-06T16:05:00Z"
        }}}
      ]
    }
  }
}
```
> Should return 0 hits.

### Fan tier distribution
```json
GET /paciolan-ticket-events/_search
{
  "size": 0,
  "aggs": {
    "by_tier": {
      "terms": { "field": "fan_tier" },
      "aggs": {
        "total_ticket_revenue": { "sum": { "field": "ticket_price" } },
        "avg_ticket_price":     { "avg": { "field": "ticket_price" } }
      }
    }
  }
}
```

### Halftime transaction spike (confirms the anomaly setup)
```json
GET /square-pos-transactions/_search
{
  "size": 0,
  "aggs": {
    "by_minute": {
      "date_histogram": {
        "field":             "transaction_time",
        "calendar_interval": "minute"
      },
      "aggs": {
        "txn_count":    { "value_count": { "field": "transaction_id" } },
        "total_revenue": { "sum":         { "field": "total_amount" } }
      }
    }
  }
}
```
> Should show a clear spike at 15:40–15:50, followed by a drop for S04/S06/S09 at 15:50.

---

## 8. Build Checklist

### Phase 1 — Index Setup (Day 1)
- [ ] Create `paciolan-ticket-events` index with mapping
- [ ] Create `square-pos-transactions` index with mapping
- [ ] Install Python dependencies (`elasticsearch`, `faker`)
- [ ] Configure `ES_HOST`, `ES_USER`, `ES_PASSWORD` in `gameday_replay.py`
- [ ] Run seed mode: `python gameday_replay.py seed`
- [ ] Run validation queries — confirm counts, revenue totals, zero-hit anomaly window

### Phase 2 — Fan Segment (Day 1–2)
- [ ] Confirm `fan_tier` field populated correctly across all ticket types
- [ ] Create and execute `section-to-fan-tier` enrich policy
- [ ] Run fan tier distribution query — confirm 6 tiers present with realistic percentages

### Phase 3 — ML Anomaly Job (Day 2)
- [ ] Create `gameday-stand-revenue` anomaly detector
- [ ] Start datafeed over seeded data
- [ ] Open Anomaly Explorer — confirm S04, S06, S09 show red cells during anomaly window
- [ ] Confirm anomaly scores ≥ 90 for all three stands
- [ ] Create alerting rule → Kibana Cases
- [ ] Test alert fires for the anomaly window

### Phase 4 — Replay Mode Validation (Day 2–3)
- [ ] Run `python gameday_replay.py replay --speed 10`
- [ ] Open Kibana Discover — confirm events appearing in real time
- [ ] Confirm timestamp on events matches current clock (not historical)
  > **Note:** For live replay, the script should use `datetime.utcnow()` instead of `GAME_DATE` — update timestamps to stream as "now" so Kibana's default time filter shows them. Add a `--live` flag for this mode.
- [ ] Verify anomaly stands go dark at the right replay minute
- [ ] Confirm Kibana dashboard updates on each auto-refresh cycle

### Phase 5 — Demo Dry Run (Day 3)
- [ ] Re-seed historical data (fresh game)
- [ ] Start replay at 10× speed
- [ ] Walk through all three demo scenarios in sequence:
  - [ ] Live Revenue Ticker — watch counter climb
  - [ ] Fan Segment Breakdown — switch tier filter, compare revenue per head
  - [ ] Anomaly Detection — watch S04/S06/S09 go dark, case fires in Kibana
- [ ] Confirm total demo runtime fits in 15 minutes at 10× speed
- [ ] Screenshot key moments for slide deck backup

---

## 9. Tech Stack Summary

| Layer | Tool |
|---|---|
| Ticketing data | `paciolan-ticket-events` index, `source_system: paciolan` |
| POS data | `square-pos-transactions` index, `source_system: square_clover` |
| Live ingest simulation | Python replay script (Elasticsearch bulk API) |
| Production ingest reference | Logstash HTTP input → dual-index output |
| Fan segmentation | `fan_tier` field + Enrich policy |
| Anomaly detection | Elastic ML — `low_count` + `low_sum` detectors per stand |
| Alerting | Kibana Alerting rule → Cases |
| Dashboards | Kibana Lens (see separate dashboard plan) |
| Environment | Existing Elastic cluster |

---

## 10. How This Feeds All Three Demos

| Demo | Index Used | Key Field | What to Show |
|---|---|---|---|
| Live Revenue Ticker | Both | `transaction_time`, `total_amount`, `ticket_price` | Metric panels + TSVB line updating every 5s |
| Fan Segment Breakdown | `paciolan-ticket-events` | `fan_tier`, `ticket_price` | Lens bar breakdown — revenue and avg price per tier |
| Revenue Anomaly Detection | `square-pos-transactions` | `stand_id`, `total_amount` | Anomaly Explorer swimlane — S04/S06/S09 go red |

All three share the same seeded dataset. The replay script drives all three simultaneously — one running script, three open Kibana tabs, one story.
