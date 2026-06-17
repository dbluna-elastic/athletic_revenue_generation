# Booster Prospect Discovery — Elastic Demo Build Plan

A gift officer types a natural-language query and instantly gets a ranked list of high-affinity athletic donors surfaced from messy, incomplete records across multiple systems. This is the demo.

---

## Decisions Locked

| Question | Decision |
|---|---|
| Data | Fully synthetic, bulk-indexed into Elastic |
| UI | Kibana dashboards **+** custom React web app |
| iWave | Simulated scores generated in synthetic dataset |
| CRM writeback | UI mock only (no real API call) |
| Environment | Existing Elastic cluster |
| AI features | Yes — LLM donor brief summarization included |

---

## 1. The Story Arc (What the Demo Shows)

**Persona:** A major gifts officer at a Power 5 athletic department  
**Problem:** 80,000 alumni records in the CRM — only 200 are actively managed. High-capacity boosters are hiding in the noise.

**Demo flow:**

1. Officer opens the React web app and types: *"Find Texas alumni who've attended 3+ football games and likely have real estate holdings over $2M"*
2. Elastic returns a ranked list of prospects — names the CRM's manual filter would have missed
3. Each result shows a composite affinity score: giving history + game attendance + behavioral signals + simulated iWave wealth score
4. Officer clicks a record → full donor profile with engagement timeline and AI-generated donor brief
5. Officer clicks "Add to portfolio" → mock confirmation (no real CRM write)
6. Athletic director opens Kibana → sees the same pipeline as a live dashboard

**The wow moments:**
- Natural language query finds donors SQL filters miss
- AI brief gives the gift officer a personalized talking-points summary in seconds

---

## 2. Synthetic Data Generator

### Script: `generate_donors.py`

Generate 5,000 records using Python + Faker. Key distributions to build in:

```python
# pip install faker numpy
from faker import Faker
import random, json, math

fake = Faker()

def affinity_score(record):
    score = 0
    score += min(record["wealth_signals"]["iwave_score"] * 0.30, 30)
    score += min(math.log1p(record["giving_history"]["lifetime_total"]) / math.log1p(500000) * 25, 25)
    score += min(record["engagement"]["game_attendance_count"] / 20 * 20, 20)
    score += record["engagement"]["email_open_rate_90d"] * 15
    score += min(record["engagement"]["events_attended_ytd"] / 10 * 10, 10)
    return round(score, 1)

def generate_donor(i):
    state = random.choices(
        ["TX", "CA", "FL", "NY", "OH", "GA", "NC", "IL"],
        weights=[25, 15, 12, 10, 8, 8, 8, 14]
    )[0]

    giving_years = random.randint(0, 20)
    lifetime_total = sum(random.randint(500, 25000) for _ in range(giving_years))
    last_gift = random.randint(500, 10000) if giving_years > 0 else 0
    game_attendance = random.randint(0, 30)
    iwave = random.randint(10, 99)

    # Seed ~50 "golden" high-score records for demo queries
    if i < 50:
        state = "TX"
        game_attendance = random.randint(10, 30)
        iwave = random.randint(75, 99)
        lifetime_total = random.randint(20000, 200000)
        last_gift = random.randint(5000, 25000)

    record = {
        "donor_id": f"ALUM-{10000 + i}",
        "first_name": fake.first_name(),
        "last_name": fake.last_name(),
        "email": fake.email(),
        "graduation_year": random.randint(1975, 2018),
        "degree": random.choice(["Business", "Engineering", "Communications", "Education", "Law", "Medicine"]),
        "location": {
            "city": fake.city(),
            "state": state,
            "zip": fake.zipcode()
        },
        "giving_history": {
            "lifetime_total": lifetime_total,
            "last_gift_date": fake.date_between(start_date="-3y", end_date="today").isoformat() if giving_years > 0 else None,
            "last_gift_amount": last_gift,
            "gift_count": giving_years,
            "largest_gift": max(last_gift, random.randint(500, lifetime_total // max(giving_years, 1) + 1)) if giving_years > 0 else 0,
            "restricted_to": random.choice(["Athletics", "Athletics", "Unrestricted", "Scholarship", "Athletics"])
        },
        "engagement": {
            "email_open_rate_90d": round(random.uniform(0, 1), 2),
            "last_email_open": fake.date_between(start_date="-90d", end_date="today").isoformat(),
            "events_attended_ytd": random.randint(0, 8),
            "game_attendance_count": game_attendance,
            "video_play_rate": round(random.uniform(0, 1), 2),
            "portal_logins_90d": random.randint(0, 20)
        },
        "wealth_signals": {
            "iwave_score": iwave,
            "estimated_capacity": random.choice(["<100k", "100k-500k", "500k-1M", "1M-5M", "5M+"]),
            "real_estate_value_est": random.randint(0, 5000000),
            "business_ownership": random.choice([True, False]),
            "political_giving_total": random.randint(0, 50000)
        }
    }

    record["bio_text"] = (
        f"{record['first_name']} {record['last_name']} graduated in {record['graduation_year']} "
        f"with a degree in {record['degree']}. Based in {record['location']['city']}, {record['location']['state']}. "
        f"Has attended {game_attendance} football games. "
        f"Lifetime giving: ${lifetime_total:,} to the athletics fund. "
        f"iWave score: {iwave}. "
        f"{'Owns a business. ' if record['wealth_signals']['business_ownership'] else ''}"
        f"Estimated real estate holdings: ${record['wealth_signals']['real_estate_value_est']:,}."
    )

    record["affinity_score"] = affinity_score(record)
    return record

donors = [generate_donor(i) for i in range(5000)]

with open("donors.ndjson", "w") as f:
    for d in donors:
        f.write(json.dumps({"index": {"_id": d["donor_id"]}}) + "\n")
        f.write(json.dumps(d) + "\n")

print(f"Generated {len(donors)} donors")
```

Bulk index command:
```bash
curl -X POST "https://<your-cluster>/_bulk" \
  -H "Content-Type: application/x-ndjson" \
  --data-binary @donors.ndjson \
  -u elastic:<password>
```

---

## 3. Elasticsearch Index Mapping

```json
PUT /athletic-boosters
{
  "mappings": {
    "properties": {
      "donor_id":        { "type": "keyword" },
      "first_name":      { "type": "keyword" },
      "last_name":       { "type": "keyword" },
      "email":           { "type": "keyword" },
      "graduation_year": { "type": "integer" },
      "degree":          { "type": "keyword" },
      "location": {
        "properties": {
          "city":  { "type": "keyword" },
          "state": { "type": "keyword" },
          "zip":   { "type": "keyword" }
        }
      },
      "giving_history": {
        "properties": {
          "lifetime_total":   { "type": "float" },
          "last_gift_date":   { "type": "date" },
          "last_gift_amount": { "type": "float" },
          "gift_count":       { "type": "integer" },
          "largest_gift":     { "type": "float" },
          "restricted_to":    { "type": "keyword" }
        }
      },
      "engagement": {
        "properties": {
          "email_open_rate_90d":    { "type": "float" },
          "last_email_open":        { "type": "date" },
          "events_attended_ytd":    { "type": "integer" },
          "game_attendance_count":  { "type": "integer" },
          "video_play_rate":        { "type": "float" },
          "portal_logins_90d":      { "type": "integer" }
        }
      },
      "wealth_signals": {
        "properties": {
          "iwave_score":            { "type": "integer" },
          "estimated_capacity":     { "type": "keyword" },
          "real_estate_value_est":  { "type": "long" },
          "business_ownership":     { "type": "boolean" },
          "political_giving_total": { "type": "float" }
        }
      },
      "affinity_score": { "type": "float" },
      "bio_text": {
        "type": "semantic_text",
        "inference_id": ".elser-2-elasticsearch"
      }
    }
  }
}
```

> **Note:** `semantic_text` automatically runs ELSER inference at index time. No separate ingest pipeline step needed for embeddings.

---

## 4. Search Layer

### Hybrid Search Query (BM25 + ELSER via RRF)

```json
POST /athletic-boosters/_search
{
  "retriever": {
    "rrf": {
      "retrievers": [
        {
          "standard": {
            "query": {
              "bool": {
                "should": [
                  { "match": { "bio_text": "Texas alumni football games real estate" } }
                ],
                "filter": [
                  { "term": { "location.state": "TX" } },
                  { "range": { "engagement.game_attendance_count": { "gte": 3 } } },
                  { "range": { "wealth_signals.real_estate_value_est": { "gte": 2000000 } } }
                ]
              }
            }
          }
        },
        {
          "knn": {
            "field": "bio_text",
            "query_vector_builder": {
              "text_embedding": {
                "model_id": ".elser-2-elasticsearch",
                "model_text": "Texas alumni football games real estate holdings"
              }
            },
            "k": 50,
            "num_candidates": 200
          }
        }
      ],
      "rank_window_size": 50,
      "rank_constant": 20
    }
  },
  "size": 20,
  "sort": [
    { "affinity_score": "desc" }
  ]
}
```

### Affinity Score Formula (computed at ingest)

| Signal | Weight | Notes |
|---|---|---|
| iWave score | 30% | Simulated 0–99 |
| Lifetime giving (log-scaled) | 25% | Normalizes against $500K ceiling |
| Game attendance count | 20% | Normalized against 20 games |
| Email open rate (90d) | 15% | Raw 0–1 float |
| Events attended YTD | 10% | Normalized against 10 events |

---

## 5. AI Donor Brief

When a gift officer opens a donor profile, trigger an LLM call to generate a personalized brief.

### Inference Pipeline

```
Elasticsearch donor record
    ↓
Retrieve top 5 fields (bio_text, giving_history, engagement, wealth_signals)
    ↓
Prompt template → LLM (via Elastic inference endpoint or direct API call)
    ↓
Rendered in donor detail drawer
```

### Prompt Template

```
You are an assistant to a major gifts officer at a university athletic department.

Given the following donor profile, write a 3-sentence brief that covers:
1. Who this person is and their connection to the university
2. Their giving history and capacity signals
3. A suggested next action for the gift officer

Donor profile:
{bio_text}

Lifetime giving: ${lifetime_total}
Game attendance: {game_attendance_count} games
iWave score: {iwave_score} / 99
Last engagement: {last_email_open}

Keep the tone professional and concise. Do not fabricate information not present above.
```

### Output Example

> *James Chen graduated in 1998 with a Business degree and has been one of our most consistent athletic fund supporters, with $47,500 in lifetime giving across 12 gifts. His iWave score of 87 and estimated real estate holdings of $2.4M suggest significant untapped capacity well above his current gift level of $5,000. Recommended next action: schedule a personal call before fiscal year-end to discuss a major gift ask in the $25,000–$50,000 range, leading with his 14-game attendance record as a conversation anchor.*

---

## 6. Kibana Dashboards

### Dashboard 1: Prospect Pipeline Overview

| Panel | Type | Data |
|---|---|---|
| Total prospects by affinity tier (Low/Med/High) | Donut chart | `affinity_score` ranges |
| Geographic heat map | Maps | `location.state` count |
| Top 20 unassigned high-score prospects | Data table | Sort by `affinity_score` desc, filter unassigned |
| Giving capacity distribution | Histogram | `wealth_signals.estimated_capacity` |
| Game attendance vs. lifetime giving | Scatter plot | `game_attendance_count` × `lifetime_total` |

### Dashboard 2: Engagement Signals

| Panel | Type | Data |
|---|---|---|
| Email open rate distribution | Bar chart | `engagement.email_open_rate_90d` buckets |
| Events attended YTD by state | Stacked bar | `engagement.events_attended_ytd` × `location.state` |
| Donor segments by degree | Pie | `degree` facet |
| iWave score vs. affinity score | Scatter | Correlation view |
| High-affinity, low-contact donors | Table | `affinity_score` > 75 AND `gift_count` = 0 |

---

## 7. React Web App

### Component Structure

```
App
├── SearchBar          — natural language input, fires hybrid search
├── FilterPanel        — state, capacity range, game attendance min, giving tier
├── ResultsList
│   └── ProspectCard   — name, affinity score badge, 3 key signal chips
├── DonorDrawer        — slides in on card click
│   ├── DonorHeader    — name, location, graduation year
│   ├── Affinity Score — gauge / score breakdown
│   ├── EngagementTimeline — game attendance, email events, gift dates
│   ├── WealthPanel    — iWave score, capacity tier, real estate est.
│   ├── AIBrief        — "Generate brief" button → LLM call → rendered text
│   └── AddToPortfolio — mock button, shows success toast
└── KibanaLink         — opens Kibana dashboard in new tab
```

### Tech

- **React** + **Elastic UI (EUI)** for components
- **Elasticsearch JS client** for search calls (or proxy through a lightweight Express backend to keep credentials server-side)
- **Fetch / Axios** for LLM brief endpoint
- No build required for demo: Vite dev server is fine

---

## 8. Build Checklist

### Phase 1 — Data & Index (Days 1–3)
- [ ] Create `athletic-boosters` index with mapping above
- [ ] Deploy ELSER model (`.elser-2-elasticsearch`) on existing cluster
- [ ] Run `generate_donors.py` → produces `donors.ndjson`
- [ ] Bulk index 5,000 records
- [ ] Confirm `semantic_text` inference ran (check `bio_text` field in a sample doc)
- [ ] Validate affinity scores look right across high/mid/low tiers

### Phase 2 — Search (Days 3–5)
- [ ] Test hybrid RRF query in Kibana Dev Tools
- [ ] Run 5 scripted demo queries, confirm golden records surface in top 5
- [ ] Add geographic and attendance filters
- [ ] Tune `rank_constant` and `rank_window_size` for best ranking feel

### Phase 3 — AI Brief (Days 4–6)
- [ ] Set up Elastic inference endpoint (or direct LLM API call from backend)
- [ ] Write and test prompt template against 10 donor records
- [ ] Confirm output is grounded (no hallucinations beyond supplied fields)
- [ ] Add "Generate brief" button + loading state in UI

### Phase 4 — Kibana Dashboards (Days 5–7)
- [ ] Build Pipeline Overview dashboard (5 panels)
- [ ] Build Engagement Signals dashboard (5 panels)
- [ ] Save and test both dashboards
- [ ] Create a shareable dashboard URL for demo

### Phase 5 — React UI (Days 6–10)
- [ ] Scaffold Vite + React + EUI app
- [ ] Build SearchBar → connects to Elasticsearch
- [ ] Build FilterPanel (state, capacity, attendance)
- [ ] Build ResultsList + ProspectCard
- [ ] Build DonorDrawer with all sub-panels
- [ ] Wire AI brief call into drawer
- [ ] Add mock "Add to portfolio" toast
- [ ] Add Kibana link button

### Phase 6 — Demo Polish (Days 10–12)
- [ ] Script 3 demo queries with known outputs
- [ ] Confirm sub-200ms search response time
- [ ] Record Loom walkthrough
- [ ] Write one-page demo narrative for AE / SC use

---

## 9. Tech Stack Summary

| Layer | Tool |
|---|---|
| Search & storage | Elasticsearch 8.x (existing cluster) |
| Semantic search | ELSER `.elser-2-elasticsearch` via `semantic_text` |
| Dashboards | Kibana Lens + Maps |
| Web app | React + Elastic UI (EUI), Vite |
| AI brief | Elastic inference endpoint → LLM |
| Synthetic data | Python + Faker → NDJSON bulk index |
| iWave scores | Simulated in generator script |
| CRM writeback | UI mock (toast notification only) |
