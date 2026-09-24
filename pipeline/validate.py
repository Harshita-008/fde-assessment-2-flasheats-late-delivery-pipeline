"""Step 3 - Validate: business rules on the raw snapshot.

Nothing is fixed silently. Every rule writes a row to the validation report with
how many records failed and what we did about it:
  block      -> stop the run, output would not be trustworthy
  quarantine -> record excluded from metrics, listed in quarantine.csv
  correct    -> standardised or taken from the system of record, logged here
  warn       -> kept as-is, limits some analysis (see README limitations)
"""
import logging

import pandas as pd

import config

log = logging.getLogger(__name__)

REQUIRED_COLUMNS = {
    "orders": ["order_id", "created_at", "promised_eta", "final_status", "pickup_at", "actual_delivery_at"],
    "dispatch": ["order_id", "assigned_at", "estimated_pickup_at", "dispatch_status"],
    "driver_events": ["order_id", "driver_id", "type", "timestamp"],
    "interventions": ["intervention_id", "order_id", "intervention_type", "intervention_at"],
}


class ValidationError(Exception):
    pass


class Report:
    def __init__(self):
        self.rows = []
        self.quarantine = []

    def add(self, rule_id, source, rule, severity, failed_ids, action):
        failed_ids = list(failed_ids)
        self.rows.append({
            "rule_id": rule_id, "source": source, "rule": rule, "severity": severity,
            "failed": len(failed_ids), "action": action if failed_ids else "-",
            "examples": ", ".join(map(str, failed_ids[:5])),
        })
        if severity == "quarantine":
            entity = "intervention" if source == "interventions" else "order"
            self.quarantine += [{"entity": entity, "id": i, "rule_id": rule_id, "reason": rule} for i in failed_ids]
        if failed_ids:
            log.log(logging.WARNING if severity != "correct" else logging.INFO,
                    "%s [%s] %s: %s failed", rule_id, severity, rule, len(failed_ids))

    def to_frames(self):
        return pd.DataFrame(self.rows), pd.DataFrame(self.quarantine, columns=["entity", "id", "rule_id", "reason"])


def to_time(series):
    return pd.to_datetime(series, format="mixed", errors="coerce")


def check_schema(raw):
    for name, cols in REQUIRED_COLUMNS.items():
        missing = [c for c in cols if c not in raw[name].columns]
        if missing:
            raise ValidationError(f"{name} is missing required columns {missing}")


def validate(raw):
    rep = Report()
    check_schema(raw)

    orders = raw["orders"].copy()
    dispatch = raw["dispatch"].copy()
    events = raw["driver_events"].copy()
    ivs = raw["interventions"].copy()

    # --- orders DB -------------------------------------------------------
    dup = orders["order_id"].duplicated()
    rep.add("V01", "orders", "order_id is unique", "correct", orders.loc[dup, "order_id"],
            "kept first row; the copies disagree on traffic_bucket, so traffic for these is uncertain")
    orders = orders[~dup].copy()

    status = orders["final_status"].str.strip().str.lower()
    rep.add("V02", "orders", "final_status uses standard lowercase values", "correct",
            orders.loc[status != orders["final_status"], "order_id"], "lower-cased (e.g. 'Delivered')")
    orders["final_status"] = status
    rep.add("V03", "orders", "final_status is delivered or cancelled", "quarantine",
            orders.loc[~status.isin(config.VALID_STATUSES), "order_id"], "excluded from metrics")

    traffic = orders["traffic_bucket"].str.strip().str.lower()
    rep.add("V04", "orders", "traffic_bucket uses standard values", "correct",
            orders.loc[traffic != orders["traffic_bucket"], "order_id"], "lower-cased (e.g. 'HIGH')")
    orders["traffic_bucket"] = traffic
    bad_ctx = ~traffic.isin(config.VALID_TRAFFIC) | ~orders["weather_bucket"].isin(config.VALID_WEATHER)
    rep.add("V05", "orders", "traffic/weather bucket is a known value", "warn",
            orders.loc[bad_ctx, "order_id"], "kept; context unknown for these orders")

    for col in ["created_at", "promised_eta", "pickup_at", "actual_delivery_at"]:
        orders[col] = to_time(orders[col])
    bad_promise = orders["promised_eta"] <= orders["created_at"]
    rep.add("V06", "orders", "promised_eta is after order creation", "quarantine",
            orders.loc[bad_promise, "order_id"], "excluded: lateness cannot be judged against an impossible promise")

    rep.add("V07", "orders", "restaurant_id and driver_id are present", "warn",
            orders.loc[orders["restaurant_id"].isna() | orders["driver_id"].isna(), "order_id"],
            "kept in KPI; driver taken from dispatch; excluded from restaurant breakdowns")

    default_dist = orders["distance_km_estimate"] == 18.0
    rep.add("V08", "orders", "distance_km_estimate looks measured (not the 18.0 default)", "warn",
            orders.loc[default_dist, "order_id"], "distance not used in any metric")

    # --- dispatch API ----------------------------------------------------
    missing_dispatch = set(orders["order_id"]) ^ set(dispatch["order_id"])
    rep.add("V09", "dispatch", "every order has exactly one dispatch record", "block",
            sorted(missing_dispatch), "run stopped")
    for col in ["assigned_at", "reassigned_at", "estimated_pickup_at", "current_delivery_eta"]:
        dispatch[col] = to_time(dispatch[col])

    merged = orders.merge(dispatch[["order_id", "dispatch_status"]], on="order_id")
    expected = merged["final_status"].map({"delivered": "completed", "cancelled": "cancelled"})
    rep.add("V10", "dispatch", "dispatch_status agrees with order status", "warn",
            merged.loc[expected != merged["dispatch_status"], "order_id"], "kept; order status used")

    # --- driver app events -----------------------------------------------
    events["timestamp"] = to_time(events["timestamp"])
    pings = events[events["type"] == "gps_ping"]
    (lat_lo, lat_hi), (lon_lo, lon_hi) = config.BENGALURU_BBOX["lat"], config.BENGALURU_BBOX["lon"]
    off_map = ~pings["lat"].between(lat_lo, lat_hi) | ~pings["lon"].between(lon_lo, lon_hi)
    rep.add("V11", "driver_events", "GPS ping is inside Bengaluru", "warn",
            pings.loc[off_map, "order_id"].unique(), "pings not used in metrics")

    driver = (events[events["type"] != "gps_ping"]
              .pivot_table(index="order_id", columns="type", values="timestamp", aggfunc="min"))
    o = orders.set_index("order_id").join(driver[["picked_up", "delivered"]])
    o = o.join(dispatch.set_index("order_id")["assigned_at"])
    delivered = o["final_status"] == "delivered"

    no_db_time = delivered & o["actual_delivery_at"].isna()
    rep.add("V12", "orders vs driver_events", "delivered order has a delivery time in orders DB", "correct",
            o.index[no_db_time & o["delivered"].notna()],
            "delivery time taken from driver app (system of record for delivery)")
    rep.add("V13", "orders vs driver_events", "delivered order has a delivery time in some system", "quarantine",
            o.index[delivered & o["delivered"].isna()], "excluded from metrics")

    both = o["actual_delivery_at"].notna() & o["delivered"].notna()
    rep.add("V14", "orders vs driver_events", "DB and driver app agree on delivery time", "warn",
            o.index[both & (o["actual_delivery_at"] != o["delivered"])], "driver app used")

    pickup_gap = (o["pickup_at"] - o["picked_up"]).abs() > pd.Timedelta(minutes=1)
    rep.add("V15", "orders vs driver_events", "DB pickup_at agrees with driver app pickup", "correct",
            o.index[delivered & pickup_gap], "driver app used (DB value is after delivery for these orders)")
    rep.add("V16", "orders vs driver_events", "cancelled order has no pickup_at in DB", "warn",
            o.index[~delivered & o["pickup_at"].notna() & o["picked_up"].isna()],
            "DB pickup_at filled for cancelled orders with no driver pickup; DB pickup_at not trusted")

    rep.add("V17", "driver_events", "delivered is after picked_up", "quarantine",
            o.index[o["delivered"] < o["picked_up"]], "excluded from metrics")
    rep.add("V18", "driver_events", "picked_up is after driver assignment", "warn",
            o.index[o["picked_up"] < o["assigned_at"]],
            "kept; gap is seconds to minutes, likely clock skew between apps")

    # --- interventions log -----------------------------------------------
    ivs["intervention_at"] = to_time(ivs["intervention_at"])
    ivs = ivs.merge(orders[["order_id", "created_at"]], on="order_id", how="left")
    rep.add("V19", "interventions", "intervention belongs to a known order", "quarantine",
            ivs.loc[ivs["created_at"].isna(), "intervention_id"], "excluded from intervention analysis")
    rep.add("V20", "interventions", "intervention happens after the order was created", "quarantine",
            ivs.loc[ivs["intervention_at"] < ivs["created_at"], "intervention_id"],
            "excluded from intervention analysis")

    reassigned = set(dispatch.loc[dispatch["reassigned_at"].notna(), "order_id"])
    iv_reassign = ivs[ivs["intervention_type"] == "DRIVER_REASSIGNMENT"]
    rep.add("V21", "interventions vs dispatch", "logged DRIVER_REASSIGNMENT is visible in dispatch",
            "warn", iv_reassign.loc[~iv_reassign["order_id"].isin(reassigned), "intervention_id"],
            "kept; the two systems disagree, so intervention results are indicative only")

    # --- run-level gate --------------------------------------------------
    report, quarantine = rep.to_frames()
    bad_orders = quarantine.loc[quarantine["entity"] == "order", "id"].nunique()
    share = bad_orders / max(delivered.sum(), 1)
    gate_ids = [f"{share:.1%} quarantined"] if share > config.MAX_QUARANTINE_SHARE else []
    rep.add("V22", "run", f"quarantined orders <= {config.MAX_QUARANTINE_SHARE:.0%} of delivered", "block",
            gate_ids, "run stopped")
    report, quarantine = rep.to_frames()

    blocking = report[(report["severity"] == "block") & (report["failed"] > 0)]
    if not blocking.empty:
        raise ValidationError("blocking rule failed: " + "; ".join(blocking["rule_id"] + " " + blocking["rule"]))

    clean = {
        "orders": orders, "dispatch": dispatch, "driver_events": events,
        "interventions": ivs.drop(columns="created_at"),
        "restaurants": raw["restaurants"], "drivers": raw["drivers"],
    }
    return clean, report, quarantine


def reconcile_outcomes(fact, reference):
    """Compare our late flag with the client's existing order_outcomes table."""
    ref = reference.set_index("order_id")
    ours = fact[fact["in_kpi"]].set_index("order_id")
    common = ours.index.intersection(ref.index[ref["late_flag"].notna()])
    differ = common[ours.loc[common, "is_late"].astype(int) != ref.loc[common, "late_flag"].astype(int)]
    only_ours = ours.index.difference(ref.index[ref["late_flag"].notna()])
    return {
        "orders_compared": len(common),
        "late_flag_disagreements": len(differ),
        "in_our_kpi_but_unknown_in_reference": len(only_ours),
    }
