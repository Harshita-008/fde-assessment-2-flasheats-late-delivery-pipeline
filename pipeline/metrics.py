"""Step 5 - Metrics: KPI plus the metrics that explain it.

M1 Late Delivery Rate (project KPI)
M2 Severe Late Rate (> 10 min)
M3 Pre-pickup share of late minutes (where delay accumulates)
M4 Preventive intervention coverage of late orders
M5 Intervention late rate vs comparable orders (which interventions help)
"""
import pandas as pd

import config


def rate(num, den):
    return round(num / den, 4) if den else None


def metric(mid, name, num, den, definition, value=None):
    return {"metric_id": mid, "metric": name, "value": rate(num, den) if value is None else value,
            "numerator": num, "denominator": den, "definition": definition}


def kpi_metrics(kpi):
    n = len(kpi)
    late = kpi[kpi["is_late"]]

    # Positive minutes only: how much each part pushed late orders past the promise
    slip = late["pickup_slip_min"].clip(lower=0).sum()
    overrun = late["transit_overrun_min"].clip(lower=0).sum()

    return [
        metric("M1", "Late Delivery Rate", int(kpi["is_late"].sum()), n,
               "delivered orders arriving after promised_eta / delivered orders with a valid promise"),
        metric("M2", "Severe Late Rate", int(kpi["is_severe_late"].sum()), n,
               f"delivered orders more than {config.SEVERE_LATE_MIN} min after promised_eta / same population"),
        metric("M3", "Pre-pickup share of late minutes", round(slip, 1), round(slip + overrun, 1),
               "late orders: minutes of pickup slip (actual vs estimated pickup) / "
               "(pickup slip + transit overrun minutes)"),
    ]


def coverage_metric(kpi, interventions):
    late_ids = set(kpi.loc[kpi["is_late"], "order_id"])
    early = interventions[interventions["stage_at_intervention"] == "awaiting_pickup"]
    covered = late_ids & set(early["order_id"])
    return metric("M4", "Preventive intervention coverage", len(covered), len(late_ids),
                  "late orders that got any intervention while still awaiting pickup / late orders")


def comparable_late_rate(row, control):
    """Late rate of non-intervened orders that were in the same stage at the same minute."""
    t = row.min_since_created
    pickup = control["pickup_min"]
    if row.stage_at_intervention == "awaiting_pickup":
        peers = control[pickup > t]
    else:  # in_transit
        peers = control[(pickup <= t) & (control["deliver_min"] > t)]
    return peers["is_late"].mean()


def intervention_table(kpi, interventions):
    """M5. A naive intervened-vs-not comparison is biased: ops intervene on orders that are
    already slipping. So each intervened order is compared with orders that got no
    intervention but were in the same stage at the same minute since creation."""
    kpi = kpi.assign(pickup_min=(kpi["picked_up_at"] - kpi["created_at"]).dt.total_seconds() / 60,
                     deliver_min=(kpi["delivered_at"] - kpi["created_at"]).dt.total_seconds() / 60)
    control = kpi[~kpi["order_id"].isin(interventions["order_id"])]

    # After delivery (credits) cannot change the outcome, so only preventive stages count
    iv = interventions[interventions["stage_at_intervention"].isin(["awaiting_pickup", "in_transit"])]
    iv = iv.merge(kpi[["order_id", "is_late"]], on="order_id")
    iv["comparable_late"] = [comparable_late_rate(r, control) for r in iv.itertuples()]

    table = (iv.groupby("intervention_type")
               .agg(orders=("order_id", "size"), late_rate=("is_late", "mean"),
                    comparable_late_rate=("comparable_late", "mean"))
               .reset_index())
    table["naive_baseline"] = control["is_late"].mean()
    table["difference_pts"] = (table["late_rate"] - table["comparable_late_rate"]) * 100
    return table.round(3)


def intervention_timing(interventions):
    """When interventions happen relative to the order's stage."""
    return (interventions.groupby("stage_at_intervention")
            .agg(interventions=("intervention_id", "size"),
                 median_min_since_created=("min_since_created", "median"))
            .round(1).reset_index())


def stage_table(kpi):
    cols = {"dispatch_min": "created -> assigned", "first_mile_min": "assigned -> picked up",
            "last_mile_min": "picked up -> delivered", "pickup_slip_min": "pickup slip vs estimate",
            "transit_overrun_min": "transit vs plan", "delay_min": "delay vs promise"}
    t = kpi.groupby("is_late")[list(cols)].median().T.round(1)
    t.columns = ["on_time_median_min", "late_median_min"]
    t.insert(0, "stage", [cols[c] for c in t.index])
    return t.reset_index(drop=True)


def definition_bridge(raw_orders, fact):
    """Walk from leadership's 56% to our KPI, then show each stakeholder definition."""
    o = raw_orders.copy()
    for col in ["promised_eta", "actual_delivery_at"]:
        o[col] = pd.to_datetime(o[col], format="mixed")
    o["late"] = o["actual_delivery_at"] > o["promised_eta"]

    rows = []

    def add(step, late, total, note):
        rows.append({"step": step, "late": int(late), "orders": int(total), "late_rate": rate(late, total), "note": note})

    # 1. The historical dashboard: delivered rows with a non-null delivery time, as stored
    dash = o[o["actual_delivery_at"].notna()]
    add("Dashboard as reported (Data Team)", dash["late"].sum(), len(dash), "reproduces the 56% claim")

    # 2. Remove duplicate order rows
    dedup = dash.drop_duplicates("order_id")
    add("- duplicate order rows", dedup["late"].sum(), len(dedup), "3 orders counted twice")

    # 3. Add delivered orders whose time exists only in the driver app
    delivered = fact[(fact["final_status"] == "delivered") & fact["delivered_at"].notna()]
    add("+ delivery times from driver app", delivered["is_late"].sum(), len(delivered),
        "orders DB was missing the timestamp")

    # 4. Remove quarantined orders -> the KPI
    kpi = fact[fact["in_kpi"]]
    add("- impossible promises (quarantined) = M1", kpi["is_late"].sum(), len(kpi), "promised_eta before order creation")

    # Stakeholder variants on the same clean data
    add("Support Lead: > 10 min late", kpi["is_severe_late"].sum(), len(kpi), "= M2")
    add("If cancelled orders stay in the denominator", kpi["is_late"].sum(), len(fact),
        "Finance: not recommended, hides lateness")
    return pd.DataFrame(rows)


def compute_metrics(model, raw_orders):
    fact, interventions = model["fact_orders"], model["interventions"]
    kpi = fact[fact["in_kpi"]]

    rows = kpi_metrics(kpi) + [coverage_metric(kpi, interventions)]
    iv_table = intervention_table(kpi, interventions)
    for r in iv_table.itertuples():
        rows.append(metric(f"M5.{r.intervention_type}", f"Late rate after {r.intervention_type} vs comparable",
                           None, int(r.orders), "late rate of intervened orders minus late rate of comparable "
                           "non-intervened orders (same stage, same minute), in points",
                           value=round(r.difference_pts, 1)))

    tables = {"bridge": definition_bridge(raw_orders, fact), "stages": stage_table(kpi),
              "interventions": iv_table, "intervention_timing": intervention_timing(interventions)}
    return pd.DataFrame(rows, dtype=object), tables
