# FlashEats: Late Delivery KPI Pipeline

**Track A (FlashEats-style).** A repeatable pipeline from FlashEats' client systems (SQL, API, files) to a trustworthy late-delivery KPI, plus the metrics that show where the delay comes from.

## Problem
Late deliveries are hurting customer experience. Leadership says the **Late Delivery Rate is 56%**, but:
- nobody owns the definition, and four teams define "late" differently (`data/client_metric_definitions.json`);
- the data behind the number is spread across an orders database, a dispatch API, a driver app export and an ops intervention log that do not agree with each other.

Leadership needs to know whether 56% is real, **where in the order lifecycle the delay builds up**, and **whether current interventions help**.

## Users / stakeholders
| Stakeholder | What they need from this |
|---|---|
| VP Operations (proposed KPI owner) | a single trusted late rate and where to act |
| Dispatch / Ops team | whether their interventions happen in time and work |
| Support Lead | the "meaningfully late" (> 10 min) view |
| Finance | cancelled orders kept out of operational performance |
| Data Team | a reproducible definition that replaces the old dashboard logic |

## Project KPI
**Late Delivery Rate** = delivered orders that arrive after `promised_eta` ÷ delivered orders with a valid promise.
- *Late* means any minute past the promise (VP Ops). That is the time the customer was shown.
- Cancelled orders are excluded (Finance). They were never delivered, so they are neither late nor on time.
- Orders that got a credit or refund stay in. The credit is a *result* of lateness, so removing them would hide it.
- The Support Lead's "> 10 min" threshold is reported next to it as a **severity tier (M2)**, not a replacement.

## Final evidence table
Full generated version, with validation findings and reconciliation: [output/evidence.md](output/evidence.md).

| # | Metric | Value | Basis |
|---|---|---|---|
| **M1** | **Late Delivery Rate (KPI)** | **56.5%** | 863 / 1,528 delivered orders |
| M2 | Severe Late Rate (> 10 min) | 23.2% | 354 / 1,528 |
| M3 | Share of late minutes that build up **before pickup** | 98.9% | 13,566 of 13,716 late minutes |
| M4 | Late orders that got an intervention while still awaiting pickup | 19.6% | 169 / 863 |
| M5 | Intervention late rate vs comparable orders (points) | Restaurant contact −2.0, priority dispatch −1.7, reassignment +3.4, credit +4.2 | 17–147 orders each |

**Where the delay builds up** (median minutes):

| Stage | On time | Late |
|---|---|---|
| created → driver assigned | 2.3 | 2.3 |
| assigned → picked up | 16.6 | **28.8** |
| picked up → delivered | 45.5 | 49.0 |
| pickup slip vs estimate | 1.8 | **13.9** |
| transit vs plan | −7.9 | −5.9 |

**Reconciling leadership's 56%:**

| Step | Late rate |
|---|---|
| Old dashboard logic (delivered rows with a non-null delivery time) | 56.3% (reproduces the claim) |
| − 3 duplicated orders, + 37 delivery times recovered from driver app, − 4 impossible promises | **56.5% = M1** |
| Support Lead definition (> 10 min) on the same orders | 23.2% |
| Cancelled orders left in the denominator (not recommended) | 53.9% |

## What the output says, and the decision it supports
1. **56% is real**, but mostly as mild lateness: only 23% of orders are more than 10 minutes late. Leadership should report both numbers, and VP Ops should own the definition.
2. **The delay is created before pickup, not on the road.** Dispatch plans pickup at exactly 18 minutes after the order for *every* order. The actual median is 26 minutes, and 84% of orders are picked up later than planned. Transit usually *beats* its plan: only 5% of orders run over it. **Decision: fix the pickup estimate and the first-mile process (restaurant prep and rider arrival). Do not invest in routing or last-mile speed.**
3. **Interventions are late and rare.** 80% of late orders get no preventive intervention. The ones that do happen come at minute 18 (the median), when the pickup estimate has already been missed. Against comparable orders, none shows a clear benefit: restaurant contact and priority dispatch are about 2 points better, reassignment is about 3 points worse. **Decision: trigger interventions earlier, and pilot restaurant contact / priority dispatch as a controlled test before scaling.**

## Sources
Full source map (questions → information → systems, owners, grain, gaps): [docs/source_map.md](docs/source_map.md).

| Source | Retrieval mode | Used for |
|---|---|---|
| `database/flasheats.db` (orders, restaurants, drivers) | SQL | promise, status, context, dimensions |
| Dispatch API (`api/mock_dispatch_api.py`) | REST API, paginated | assignment, estimated pickup, reassignment |
| `data/driver_events.json` | JSON file | pickup and delivery times (system of record) |
| `data/order_interventions.csv` | CSV file | interventions |
| `data/order_outcomes.csv` | CSV file | reconciliation check only |

Workflow and data model diagrams: [docs/data_model.md](docs/data_model.md).

## How the pipeline works
`run_pipeline.py`: **ingest → profile → validate → model → metrics → output**

| Step | Code | What it does |
|---|---|---|
| Ingest | [pipeline/ingest.py](pipeline/ingest.py), [pipeline/api_client.py](pipeline/api_client.py) | Pulls every source into `raw/<run_id>/` unchanged. Proves completeness: SQL rows = `COUNT(*)`; API records = `total_records`, with unique IDs; file checksums match the source. Writes `manifest.json` with rows and sha256. |
| Profile | [pipeline/profile.py](pipeline/profile.py) | Nulls, duplicates, ranges and categories per source → `output/data_profile.md`. |
| Validate | [pipeline/validate.py](pipeline/validate.py) | 22 business rules, each logged with its count and the action taken: **block** (stop the run), **quarantine** (exclude and list in `quarantine.csv`), **correct** (standardise or take the system-of-record value), **warn** (keep, noted as a limitation). Nothing is fixed silently. |
| Model | [pipeline/model.py](pipeline/model.py) | Builds `fact_orders`, `order_events`, `interventions` and the dimensions → `output/model.db`. |
| Metrics | [pipeline/metrics.py](pipeline/metrics.py) | M1–M5, stage table, definition bridge. |
| Output | [pipeline/report.py](pipeline/report.py) | `metrics.csv`, `evidence.md`, `validation_report.csv`, `run_history.csv`. |

**Dependability**
- **Retries:** API calls retry on 500 and 429 with backoff, honouring `retry_after_seconds`. The mock API fails pages 3 and 5 on the first call, and the logs show both being recovered.
- **Fails loudly:** the run stops on an unreachable API, a missing file, an incomplete pull, a missing column, orders without a dispatch record, more than 5% of orders quarantined, M1 out of range, or any disagreement with the client's `order_outcomes` late flags.
- **Last good output kept:** outputs are built in a staging folder and published to `output/` only if every step passes. A failed pull deletes its partial raw snapshot.
- **Reruns:** each run gets its own `run_id`, raw snapshot and log (`logs/<run_id>.log`), and is appended to `output/run_history.csv`. The same raw input always gives the same metrics.
- **Rebuild from raw:** `--from-raw <run_id>` recomputes everything from a saved snapshot, after checking every file against the manifest checksums. It refuses a snapshot that has changed.

## Setup and run
Requires Python 3.10+.
```bash
pip install -r requirements.txt

# terminal 1: the client's dispatch API
python api/mock_dispatch_api.py

# terminal 2: full run (pull from all systems)
python run_pipeline.py

# rebuild outputs from a saved snapshot (no API needed)
python run_pipeline.py --from-raw 20260924T210041Z
```
Outputs land in `output/`. The committed `raw/` and `output/` folders are from the run above.

## Known / Unknown / Assumption / Limitation
**Known**
- The 56% claim is reproducible, and after cleaning the KPI is 56.5% (863/1,528).
- 98.9% of late minutes come from pickup happening later than dispatch planned. The transit leg has about 6–8 minutes of slack.
- Dispatch's pickup estimate is a fixed 18 minutes for every order.
- The orders DB is missing 37 delivery times (recovered from the driver app) and has 5 pickup times recorded after delivery.

**Unknown**
- Whether the pickup delay is **kitchen prep or rider arrival**. No source has a "food ready" time, restaurant status is only a latest snapshot for 31% of orders, and GPS pings are interpolated, so rider arrival at the restaurant cannot be detected.
- Which intervention log is correct. `order_events.csv` and `order_interventions.csv` disagree, and 147 of 155 logged reassignments are not in dispatch.
- Who formally owns the KPI definition. VP Ops is our proposal.

**Assumptions**
- The driver app is the system of record for pickup and delivery times (it matches the DB exactly wherever both exist).
- For the 3 duplicated orders, the first row is kept. The copies differ only in `traffic_bucket`.
- A promise made before the order existed (4 orders) is a data error, not a real promise, so those orders are quarantined.
- Pickups a few minutes before assignment (14 orders) are clock skew between apps and are kept.

**Limitations**
- M5 is an association, not proof of effect. Ops chose which orders to intervene on, and the "same stage, same minute" comparison removes the timing bias but not every reason ops chose an order. Sample sizes are 17–147 per type.
- The data covers 4 weeks (1–28 Aug 2026), a single city, and 1,600 orders.
- `distance_km_estimate` is a placeholder (18.0) for half of all orders, so distance is not used.

## Repository layout
```
run_pipeline.py        entry point
config.py              paths, sources, thresholds
pipeline/              ingest, api_client, profile, validate, model, metrics, report
docs/                  source_map.md, data_model.md
api/ data/ database/   client systems (inputs, unchanged)
raw/<run_id>/          preserved raw snapshot + manifest
output/                latest successful run: evidence.md, metrics.csv, model.db, ...
logs/                  one log per run
```
