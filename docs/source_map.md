# Source map

Business question (from `data/class7_model_brief.json`): **where in the order lifecycle do delays
accumulate, and which interventions are associated with better outcomes?** KPI: late delivery rate.

## Business questions → information → source

| # | Business question | Information needed | Source (system of record) |
|---|---|---|---|
| Q1 | How many orders are late? | promise time, actual delivery time, final status | orders DB (promise, status) + driver app (delivery time) |
| Q2 | How late, and how bad? | delay in minutes vs promise | same as Q1 |
| Q3 | Where does the delay build up? | created → assigned → picked up → delivered timestamps, planned pickup | orders DB, dispatch API (assignment, `estimated_pickup_at`), driver app (pickup, delivery) |
| Q4 | Do we intervene on the orders that end up late, and in time? | intervention type and time, order stage at that time | ops interventions log + workflow timestamps |
| Q5 | Which interventions go with better outcomes? | intervention, outcome, comparable orders without one | ops interventions log + fact_orders |

## Source inventory

Owners are not formally documented by the client. The owners below are our best reading of each
system and need confirming.

| Source | Retrieval | Likely owner | Grain | Rows | Used for | Key gaps / issues found |
|---|---|---|---|---|---|---|
| `database/flasheats.db` → `orders` | **SQL** | Order platform (engineering) | 1 row per order (should be) | 1,603 | promise, status, context (traffic/weather) | 3 duplicated orders, 37 delivered with no delivery time, 4 promises before creation, 5 pickups recorded after delivery, mixed-case status/traffic, `distance_km_estimate` = 18.0 default on half of orders |
| `flasheats.db` → `restaurants`, `drivers` | **SQL** | Restaurant ops / Fleet ops | 1 row per restaurant / driver | 60 / 120 | dimensions | 3 orders have no restaurant_id, 3 no driver_id |
| Dispatch API `/dispatch/orders` | **API** (paginated) | Dispatch / logistics | 1 row per order | 1,600 | assignment time, **estimated pickup**, reassignment, ETA model version | page 3 returns 500 and page 5 returns 429 on first call; `estimated_pickup_at` is always created + 18 min |
| `data/driver_events.json` | **File (JSON, nested)** | Driver app / fleet | 1 row per driver event (assigned, picked_up, delivered, gps_ping) | 10,035 | **pickup and delivery times** | GPS pings are interpolated straight lines (not real positions), 76 orders have off-map pings, 14 pickups a few minutes before assignment |
| `data/order_interventions.csv` | **File (CSV)** | Operations / support / dispatch | 1 row per intervention | 430 | interventions (type, time, reason, who) | 1 logged before the order existed; 147 of 155 reassignments are not visible in dispatch |
| `data/order_outcomes.csv` | File (CSV) | Data team (derived table) | 1 row per order | 1,600 | **reconciliation only**: our late flag is checked against it | 37 orders "unknown" (the missing DB timestamps) |

Not pulled into the pipeline, on purpose:

| Source | Why not |
|---|---|
| `customers` table | Has names and emails (PII) and nothing the KPI needs. Data minimisation. |
| `data/restaurants.csv` | Same content as the SQL `restaurants` table (checked row by row). We use the DB copy. |
| `data/order_events.csv` | Same order platform as the DB (pickup times identical, including the 5 bad ones). Its 260 intervention rows conflict with the ops log (only 75 orders overlap and the types differ), so they cannot be merged without an owner deciding which log is right. |
| `data/restaurant_status.csv` | Only the *latest* status for 500 orders (31%), labels inconsistent (`READY`, `ready `, `handoff`), no "food ready" timestamp. It cannot time kitchen prep. |
| `support_tickets.csv`, `customer_interactions.csv`, `customer_app_actions.csv` | Customer-experience signals that come *after* the delay. They do not help locate it. Tickets also have duplicates, 3 without an order_id, and inconsistent categories. |

## Systems-of-record decisions

Where two systems hold the same fact, we picked one and logged every disagreement (see `output/validation_report.csv`):

- **Pickup and delivery time → driver app.** It is closest to the physical event. It matches the DB exactly where both exist, fills the 37 missing DB delivery times, and is plausible for the 5 orders where the DB pickup is after delivery.
- **Promise and status → orders DB.** Only the DB has `promised_eta`, and it is what the customer saw.
- **Planned pickup and assignment → dispatch API.**
- **Interventions → ops log (`order_interventions.csv`)**, the only source with reason and initiator.
