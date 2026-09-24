"""Step 4 - Model: reorganise source-shaped data around the order workflow.

Tables (see docs/data_model.md):
  fact_orders    one row per order: workflow timestamps, stage durations, outcome
  order_events   one row per workflow event, from all systems, in one shape
  interventions  one row per intervention, with the stage the order was in at that moment
  dim_restaurants, dim_drivers
"""
import sqlite3
from contextlib import closing

import numpy as np
import pandas as pd

import config


def minutes(later, earlier):
    return (later - earlier).dt.total_seconds() / 60


def build_fact_orders(clean, quarantine):
    orders, dispatch, events = clean["orders"], clean["dispatch"], clean["driver_events"]

    driver = (events[events["type"].isin(["picked_up", "delivered"])]
              .pivot_table(index="order_id", columns="type", values="timestamp", aggfunc="min")
              .rename(columns={"picked_up": "picked_up_at", "delivered": "delivered_at"}))

    f = (orders[["order_id", "customer_id", "restaurant_id", "created_at", "promised_eta",
                 "final_status", "traffic_bucket", "weather_bucket"]]
         .merge(dispatch[["order_id", "driver_id", "original_driver_id", "assigned_at", "reassigned_at",
                          "estimated_pickup_at", "eta_model_version"]], on="order_id", how="left")
         .merge(driver, on="order_id", how="left"))

    # Source of each workflow timestamp (system of record):
    #   created_at, promised_eta  -> orders DB
    #   assigned_at, estimated_pickup_at -> dispatch API
    #   picked_up_at, delivered_at -> driver app
    f["was_reassigned"] = f["reassigned_at"].notna()

    # Stage durations (actual)
    f["dispatch_min"] = minutes(f["assigned_at"], f["created_at"])
    f["first_mile_min"] = minutes(f["picked_up_at"], f["assigned_at"])
    f["last_mile_min"] = minutes(f["delivered_at"], f["picked_up_at"])

    # Delay vs promise, split into where it came from:
    #   delay = pickup_slip (actual vs estimated pickup) + transit_overrun (actual vs planned transit)
    f["delay_min"] = minutes(f["delivered_at"], f["promised_eta"])
    f["pickup_slip_min"] = minutes(f["picked_up_at"], f["estimated_pickup_at"])
    f["transit_overrun_min"] = f["delay_min"] - f["pickup_slip_min"]

    f["is_late"] = f["delay_min"] > 0
    f["is_severe_late"] = f["delay_min"] > config.SEVERE_LATE_MIN

    # KPI population: delivered, with a timestamp, not quarantined
    bad = set(quarantine.loc[quarantine["entity"] == "order", "id"])
    f["in_kpi"] = (f["final_status"] == "delivered") & f["delivered_at"].notna() & ~f["order_id"].isin(bad)
    f["exclusion_reason"] = np.select(
        [f["final_status"] != "delivered", f["order_id"].isin(bad), f["delivered_at"].isna()],
        ["cancelled", "quarantined", "no delivery time"], default="")
    return f


def stage_at(t, fact_row):
    if pd.isna(fact_row.picked_up_at) and pd.isna(fact_row.delivered_at):
        return "not_delivered"
    if t < fact_row.picked_up_at:
        return "awaiting_pickup"
    if t <= fact_row.delivered_at:
        return "in_transit"
    return "after_delivery"


def build_interventions(clean, fact, quarantine):
    bad = set(quarantine.loc[quarantine["entity"] == "intervention", "id"])
    iv = clean["interventions"][~clean["interventions"]["intervention_id"].isin(bad)].copy()
    lookup = fact.set_index("order_id")

    iv["stage_at_intervention"] = [stage_at(t, lookup.loc[o]) for t, o in zip(iv["intervention_at"], iv["order_id"])]
    iv["min_since_created"] = minutes(iv["intervention_at"], iv["order_id"].map(lookup["created_at"]))
    return iv


def build_order_events(fact, interventions):
    """Long event log: the order lifecycle as a sequence of states, from every system."""
    steps = [
        ("ORDER_CREATED", "created_at", "orders_db"),
        ("DRIVER_ASSIGNED", "assigned_at", "dispatch_api"),
        ("DRIVER_REASSIGNED", "reassigned_at", "dispatch_api"),
        ("PICKED_UP", "picked_up_at", "driver_app"),
        ("DELIVERED", "delivered_at", "driver_app"),
    ]
    parts = [fact[["order_id", col]].dropna().rename(columns={col: "event_time"}).assign(event_type=name, source=src)
             for name, col, src in steps]
    parts.append(interventions[["order_id", "intervention_at", "intervention_type"]]
                 .rename(columns={"intervention_at": "event_time", "intervention_type": "event_type"})
                 .assign(event_type=lambda d: "INTERVENTION_" + d["event_type"], source="ops_log"))
    return pd.concat(parts).sort_values(["order_id", "event_time"]).reset_index(drop=True)


def build_model(clean, quarantine):
    fact = build_fact_orders(clean, quarantine)
    interventions = build_interventions(clean, fact, quarantine)
    return {
        "fact_orders": fact,
        "order_events": build_order_events(fact, interventions),
        "interventions": interventions,
        "dim_restaurants": clean["restaurants"],
        "dim_drivers": clean["drivers"],
    }


def save_model(model, path):
    with closing(sqlite3.connect(path)) as conn:
        for name, df in model.items():
            df.to_sql(name, conn, index=False, if_exists="replace")
