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
  generate_donors.py   # Synthetic data → NDJSON
  create_index.py      # Create athletic-boosters index
  bulk_index.py        # Bulk load donors.ndjson
  validate_data.py     # Tier + demo query checks
  es_config.py         # Shared ES client
elastic/
  athletic-boosters-mapping.json
  demo-hybrid-search.json
data/
  donors.ndjson        # Generated (gitignored)
```

### Golden records

The first 50 generated donors are seeded as high-affinity Texas prospects: 10+ game attendance, iWave 75–99, $2M+ real estate, and strong giving — so the demo query surfaces known hits in the top results.

## Next phases

- **Phase 2:** Search tuning & scripted demo queries
- **Phase 3:** AI donor brief (LLM inference endpoint)
- **Phase 4:** Kibana dashboards
- **Phase 5:** React + EUI web app

See [booster-prospect-discovery-build-plan.md](booster-prospect-discovery-build-plan.md) for the full build plan.
