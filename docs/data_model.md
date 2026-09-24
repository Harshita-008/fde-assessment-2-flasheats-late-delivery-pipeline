# Workflow and data model

## 1. Order workflow (states, events, where each fact comes from)

```mermaid
flowchart LR
    A([ORDER_CREATED<br/>orders DB]) --> B([DRIVER_ASSIGNED<br/>dispatch API])
    B --> C([PICKED_UP<br/>driver app])
    C --> D([DELIVERED<br/>driver app])
    A --> X([CANCELLED<br/>orders DB])
    B -. reassigned .-> B

    I1{{Interventions while awaiting pickup:<br/>reassignment, priority dispatch,<br/>restaurant contact}} -.-> B
    I2{{Interventions in transit}} -.-> C
    I3{{Credit after delivery:<br/>recovery, not prevention}} -.-> D

    D --> O[(Outcome:<br/>on time / late / severe late)]
```

The promise is built from two planned legs. Comparing each leg with what actually happened
shows where the delay came from:

```
created ──(planned 18 min)──► estimated_pickup ──(planned transit)──► promised_eta
created ──(actual)──────────► picked_up ─────────(actual transit)───► delivered

delay_min       = delivered − promised_eta
                = pickup_slip_min                   + transit_overrun_min
                = (picked_up − estimated_pickup)    + (actual transit − planned transit)
```

## 2. Relational model (`output/model.db`)

```mermaid
erDiagram
    fact_orders ||--o{ order_events : "has"
    fact_orders ||--o{ interventions : "receives"
    dim_restaurants ||--o{ fact_orders : "prepares"
    dim_drivers ||--o{ fact_orders : "delivers"

    fact_orders {
        text order_id PK
        text restaurant_id FK
        text driver_id FK
        datetime created_at
        datetime assigned_at
        datetime estimated_pickup_at
        datetime picked_up_at
        datetime delivered_at
        datetime promised_eta
        text final_status
        float dispatch_min
        float first_mile_min
        float last_mile_min
        float pickup_slip_min
        float transit_overrun_min
        float delay_min
        bool is_late
        bool is_severe_late
        bool in_kpi
        text exclusion_reason
    }
    order_events {
        text order_id FK
        text event_type
        datetime event_time
        text source
    }
    interventions {
        text intervention_id PK
        text order_id FK
        text intervention_type
        datetime intervention_at
        text initiated_by
        text reason
        text stage_at_intervention
        float min_since_created
    }
    dim_restaurants {
        text restaurant_id PK
        text cuisine
        int manual_status_updates
    }
    dim_drivers {
        text driver_id PK
        float rating
        text vehicle_type
        int experience_months
    }
```

- **Entities:** order, restaurant, driver.
- **Events and states:** `order_events` puts every system's events into one shape (`order_id, event_type, event_time, source`).
- **Interventions:** each one is tagged with the stage the order was in at that moment.
- **Outcomes:** `delay_min`, `is_late` and `is_severe_late` on `fact_orders`.

## 3. Pipeline

```mermaid
flowchart LR
    S1[(SQLite)] --> I
    S2[Dispatch API] --> I
    S3[JSON / CSV files] --> I
    I[1 Ingest<br/>raw/run_id + manifest<br/>row counts, sha256] --> P[2 Profile<br/>data_profile.md]
    P --> V[3 Validate<br/>22 rules<br/>block / quarantine / correct / warn]
    V --> M[4 Model<br/>fact_orders, order_events,<br/>interventions]
    M --> K[5 Metrics<br/>M1–M5 + sanity checks<br/>+ reconciliation]
    K --> O[6 Output<br/>staging → output/]
    V -. blocking rule .-> F[run fails,<br/>last good output kept]
    K -. check fails .-> F
```
