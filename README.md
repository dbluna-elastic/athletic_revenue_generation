# Booster Prospect Discovery — Demo

Elastic-powered demo for athletic department gift officers: natural-language prospect search over synthetic donor records with hybrid BM25 + ELSER ranking.

## Phase 1: Data & Elasticsearch (current)

### Prerequisites

- Python 3.10+
- Elasticsearch 8.x cluster with **ELSER** deployed (`.elser-2-elasticsearch`)
- API key or basic auth credentials

### Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Edit .env with your cluster URL and API key
```

**Configured cluster:** `gawdzilla-0d3e9e` (Elasticsearch 9.4.2, us-east-2)

- Elasticsearch: `https://gawdzilla-0d3e9e.es.us-east-2.aws.elastic-cloud.com`
- Kibana: [https://gawdzilla-0d3e9e.kb.us-east-2.aws.elastic-cloud.com](https://gawdzilla-0d3e9e.kb.us-east-2.aws.elastic-cloud.com)
- Index: `athletic-boosters` (5,000 docs indexed)

### Deploy ELSER (if not already running)

In Kibana Dev Tools:

```json
POST _ml/trained_models/.elser-2-elasticsearch/deployment/_start
```

Wait until deployment state is `started`.

### Generate & index data

```bash
# 1. Generate 5,000 synthetic donors → data/donors.ndjson
python scripts/generate_donors.py

# 2. Create index with semantic_text mapping
python scripts/create_index.py

# 3. Bulk index (ELSER runs at index time on bio_text)
python scripts/bulk_index.py --verify

# 4. Validate affinity tiers and demo query matches
python scripts/validate_data.py
```

To recreate the index from scratch:

```bash
python scripts/create_index.py --recreate
python scripts/bulk_index.py --verify
```

### Demo hybrid search

Run in [Kibana Dev Tools](https://gawdzilla-0d3e9e.kb.us-east-2.aws.elastic-cloud.com/app/dev_tools#/console):

```
POST /athletic-boosters/_search
<paste body from elastic/demo-hybrid-search.json>
```

Uses RRF over two `match` queries on `bio_text` (ELSER semantic_text) with TX / game attendance / real estate filters. Note: RRF retriever cannot be combined with `sort` — rank by `_score` from the retriever instead.

### Project layout

```
scripts/
  generate_donors.py          # Synthetic donors → NDJSON
  generate_engagement_events.py  # Low-signal events for at-risk alert
  create_index.py             # Create athletic-boosters index
  bulk_index.py        # Bulk load donors.ndjson
  validate_data.py     # Tier + demo query checks
  es_config.py         # Shared ES client
  create_donor_lookup.py      # Sync athletic-boosters → lookup index for joins
  deploy_kibana_dashboard.py
elastic/
  athletic-boosters-mapping.json
  demo-hybrid-search.json
kibana/
  at-risk-engagement-dashboard.json
data/
  donors.ndjson        # Generated (gitignored)
```

### Kibana dashboard

Deploy the at-risk engagement dashboard:

```bash
export KIBANA_URL=https://gawdzilla-0d3e9e.kb.us-east-2.aws.elastic-cloud.com
export KIBANA_API_KEY=$ELASTICSEARCH_API_KEY
python scripts/deploy_kibana_dashboard.py
```

Or open directly: [Booster Engagement — At-Risk Donors](https://gawdzilla-0d3e9e.kb.us-east-2.aws.elastic-cloud.com/app/dashboards#/view/booster-at-risk-engagement)

Panels include:
- **At-Risk Donors** and **High-Affinity At-Risk** KPIs (linked via lookup index)
- Bar chart with donor **names** (not just IDs)
- **High-Affinity Donors with Declining Engagement** table
- **All At-Risk Donors (Alert Query + CRM Link)** — name, state, degree, affinity, signal


The `booster-engagement-events` index powers an ES|QL alert for donors with declining engagement (`avg_signal < 50`).

```bash
# Seed low-signal events for high-affinity donors (triggers alert)
python scripts/generate_engagement_events.py

# Preview only (writes NDJSON, no index)
python scripts/generate_engagement_events.py --dry-run
```

Default run adds ~1,000 events across 25 high-affinity donors (no prior events) plus borderline donors near the threshold. After indexing, the alert query returns **27+ matches** (up from 1).

### Donor profile lookup (CRM link)

Dashboard panels join at-risk `donor_id`s to names and affinity from `athletic-boosters` via `booster-donor-lookup`:

```bash
python scripts/create_donor_lookup.py --recreate
python scripts/deploy_kibana_dashboard.py
```

Uses ES|QL `LOOKUP JOIN booster-donor-lookup ON donor_id` — see `elastic/at-risk-donors-linked.esql`.

---

## Game Day Revenue Demo

Live replay pipeline for **Live Revenue Ticker**, **Fan Segment Breakdown**, and **Revenue Anomaly Detection**. See [gameday-revenue-data-setup-plan.md](gameday-revenue-data-setup-plan.md).

### Quick setup (Phase 1–3)

```bash
source .venv/bin/activate
./scripts/setup_gameday.sh --recreate
```

Or step by step:

```bash
python scripts/create_gameday_indexes.py --recreate
python scripts/gameday_replay.py seed
python scripts/validate_gameday_data.py
python scripts/setup_gameday_enrich.py --recreate
python scripts/setup_gameday_ml.py --recreate --start
```

### Indexes

| Index | Source | Docs (seeded) |
|---|---|---|
| `paciolan-ticket-events` | Paciolan gate scans | ~4,700 |
| `square-pos-transactions` | Square/Clover POS | ~14,500 |

**Game:** `GAME-2025-HOME-01` (2025-09-06 home opener) · **Combined revenue:** ~$908K  
**Anomaly:** Stands S04, S06, S09 go dark 15:50–16:05 (validated: 0 transactions)

### Live replay (demo session)

```bash
# Historical timestamps at 10× speed (~18 min)
python scripts/gameday_replay.py replay --speed 10

# Current UTC timestamps (Kibana "Last 15 minutes" filter)
python scripts/gameday_replay.py replay --speed 10 --live
```

### ML anomaly job

- Job ID: `gameday-stand-revenue`
- View in Kibana → **Machine Learning → Anomaly Detection → Anomaly Explorer**

### Kibana dashboards

```bash
python scripts/deploy_gameday_dashboards.py
```

| Dashboard | URL |
|---|---|
| **Live Overview** | [gameday-revenue-overview](https://gawdzilla-0d3e9e.kb.us-east-2.aws.elastic-cloud.com/app/dashboards#/view/gameday-revenue-overview) |
| **Fan Segments & Anomalies** | [gameday-fan-segments](https://gawdzilla-0d3e9e.kb.us-east-2.aws.elastic-cloud.com/app/dashboards#/view/gameday-fan-segments) |

Default time range: **2025-09-06 13:00–18:00 UTC** (game day). For live replay, switch to **Last 15 minutes** and run `python scripts/gameday_replay.py replay --speed 10 --live`.

---

## Oklahoma State profile (`okstate-`)

A second, isolated copy of the demo for Oklahoma State Athletics. Existing Texas indexes are not modified.

```bash
source .venv/bin/activate
./scripts/setup_okstate.sh
```

Or pass `--profile oklahoma-state` to any script:

```bash
python scripts/generate_donors.py --profile oklahoma-state
python scripts/create_index.py --profile oklahoma-state --recreate
python scripts/bulk_index.py --profile oklahoma-state --verify
python scripts/gameday_replay.py --profile oklahoma-state seed
python scripts/deploy_gameday_dashboards.py --profile oklahoma-state
python scripts/deploy_kibana_dashboard.py --profile oklahoma-state kibana/at-risk-engagement-dashboard.json --id booster-at-risk-engagement
```

| Artifact | Name |
|---|---|
| Boosters | `okstate-athletic-boosters` |
| Lookup | `okstate-booster-donor-lookup` |
| Engagement | `okstate-booster-engagement-events` |
| Tickets | `okstate-paciolan-ticket-events` |
| POS | `okstate-square-pos-transactions` |
| Enrich policy | `okstate-section-to-fan-tier` |
| ML job | `okstate-gameday-stand-revenue` |

Hybrid search body: `elastic/okstate-demo-hybrid-search.json` (`POST /okstate-athletic-boosters/_search`). Golden records are OK alumni.

| Dashboard | URL |
|---|---|
| Live Overview | [okstate-gameday-revenue-overview](https://gawdzilla-0d3e9e.kb.us-east-2.aws.elastic-cloud.com/app/dashboards#/view/okstate-gameday-revenue-overview) |
| Fan Segments & Anomalies | [okstate-gameday-fan-segments](https://gawdzilla-0d3e9e.kb.us-east-2.aws.elastic-cloud.com/app/dashboards#/view/okstate-gameday-fan-segments) |
| At-Risk Donors | [okstate-booster-at-risk-engagement](https://gawdzilla-0d3e9e.kb.us-east-2.aws.elastic-cloud.com/app/dashboards#/view/okstate-booster-at-risk-engagement) |

Profile definition: [profiles/oklahoma-state.yaml](profiles/oklahoma-state.yaml).

### Golden records are seeded as high-affinity Texas prospects: 10+ game attendance, iWave 75–99, $2M+ real estate, and strong giving — so the demo query surfaces known hits in the top results.

## Next phases

- **Phase 2:** Search tuning & scripted demo queries
- **Phase 3:** AI donor brief (LLM inference endpoint)
- **Phase 4:** Kibana dashboards
- **Phase 5:** React + EUI web app

See [booster-prospect-discovery-build-plan.md](booster-prospect-discovery-build-plan.md) for the full build plan.
