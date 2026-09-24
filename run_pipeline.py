"""FlashEats late-delivery KPI pipeline.

    python run_pipeline.py                      # pull fresh data from all systems
    python run_pipeline.py --from-raw <run_id>  # rebuild outputs from a saved raw snapshot

ingest -> profile -> validate -> model -> metrics -> output
Outputs are written to a temp folder and only swapped into output/ if every step passes,
so a failed run never overwrites the last good result.
"""
import argparse
import csv
import json
import logging
import shutil
import sys
from datetime import datetime, timezone

import config
from pipeline import ingest, metrics, model, profile, report, validate

log = logging.getLogger("pipeline")


def setup_logging(run_id):
    config.LOG_DIR.mkdir(exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        handlers=[logging.StreamHandler(sys.stdout),
                  logging.FileHandler(config.LOG_DIR / f"{run_id}.log", encoding="utf-8")],
    )


def record_run(run_id, status, source_run, detail):
    path = config.OUTPUT_DIR / "run_history.csv"
    config.OUTPUT_DIR.mkdir(exist_ok=True)
    is_new = not path.exists()
    with path.open("a", newline="") as fh:
        writer = csv.writer(fh)
        if is_new:
            writer.writerow(["run_id", "status", "raw_snapshot", "finished_at", "detail"])
        writer.writerow([run_id, status, source_run, datetime.now(timezone.utc).isoformat(), detail])


def run(run_id, from_raw=None, api_url=config.API_URL):
    # 1. Ingest (or reuse a snapshot)
    if from_raw:
        snap = config.RAW_DIR / from_raw
        ingest.verify_snapshot(snap)
    else:
        snap = ingest.ingest(run_id, api_url)
    raw = ingest.load_snapshot(snap)

    staging = config.OUTPUT_DIR.parent / f".staging_{run_id}"
    staging.mkdir(parents=True)
    try:
        # 2. Profile
        (staging / "data_profile.md").write_text(profile.build_profile(raw, snap.name), encoding="utf-8")

        # 3. Validate
        clean, checks, quarantine = validate.validate(raw)
        checks.to_csv(staging / "validation_report.csv", index=False)
        quarantine.to_csv(staging / "quarantine.csv", index=False)

        # 4. Model
        tables = model.build_model(clean, quarantine)
        model.save_model(tables, staging / "model.db")
        tables["fact_orders"].to_csv(staging / "fact_orders.csv", index=False)

        # 5. Metrics + sanity checks on the output itself
        result, extra = metrics.compute_metrics(tables, raw["orders"])
        m1 = result.set_index("metric_id").loc["M1"]
        if not (0 < m1["value"] < 1) or m1["denominator"] == 0:
            raise ValueError(f"M1 out of range: {m1['value']} over {m1['denominator']} orders")
        recon = validate.reconcile_outcomes(tables["fact_orders"], raw["outcomes_reference"])
        if recon["late_flag_disagreements"] > 0:
            raise ValueError(f"late flag disagrees with client reference on {recon['late_flag_disagreements']} orders")

        # 6. Output
        result.to_csv(staging / "metrics.csv", index=False)
        for name, df in extra.items():
            df.to_csv(staging / f"{name}.csv", index=False)
        (staging / "evidence.md").write_text(
            report.build_evidence(run_id, result, extra, checks, recon), encoding="utf-8")
        (staging / "run_info.json").write_text(json.dumps({"run_id": run_id, "raw_snapshot": snap.name}, indent=2))

        # Publish only when everything succeeded (run_history is kept across runs)
        history = config.OUTPUT_DIR / "run_history.csv"
        if history.exists():
            shutil.copy2(history, staging / "run_history.csv")
        if config.OUTPUT_DIR.exists():
            shutil.rmtree(config.OUTPUT_DIR)
        shutil.copytree(staging, config.OUTPUT_DIR)
    finally:
        shutil.rmtree(staging, ignore_errors=True)

    return snap.name, m1


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--from-raw", metavar="RUN_ID", help="rebuild from raw/<RUN_ID> instead of pulling")
    parser.add_argument("--api-url", default=config.API_URL)
    args = parser.parse_args()

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    setup_logging(run_id)
    log.info("run %s started%s", run_id, f" from snapshot {args.from_raw}" if args.from_raw else "")

    try:
        snapshot, m1 = run(run_id, args.from_raw, args.api_url)
    except Exception as exc:
        log.error("run %s FAILED: %s", run_id, exc)
        record_run(run_id, "failed", args.from_raw or run_id, str(exc))
        log.info("output/ still holds the last successful run")
        sys.exit(1)

    detail = f"M1 late rate {m1['value']:.1%} ({m1['numerator']}/{m1['denominator']})"
    record_run(run_id, "success", snapshot, detail)
    log.info("run %s succeeded: %s", run_id, detail)


if __name__ == "__main__":
    main()
