"""Step 1 - Ingest: pull from SQL, API and files into an immutable raw snapshot.

Every run writes raw/<run_id>/ with a manifest (rows, sha256, completeness check).
Later steps only ever read from a snapshot, so any output can be rebuilt from it.
"""
import hashlib
import json
import logging
import shutil
import sqlite3
from contextlib import closing
from datetime import datetime, timezone

import pandas as pd

import config
from pipeline.api_client import RetrievalError, fetch_dispatch_orders

log = logging.getLogger(__name__)


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def extract_sql(snap):
    """Full-table extract; completeness = extracted rows equal COUNT(*) at source."""
    entries = []
    with closing(sqlite3.connect(config.SQLITE_PATH)) as conn:
        for table in config.SQL_TABLES:
            source_count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            df = pd.read_sql(f"SELECT * FROM {table}", conn)
            if len(df) != source_count:
                raise RetrievalError(f"{table}: extracted {len(df)} rows, source has {source_count}")

            path = snap / "sql" / f"{table}.csv"
            path.parent.mkdir(parents=True, exist_ok=True)
            df.to_csv(path, index=False)
            entries.append({"source": f"sqlite:{table}", "mode": "SQL", "path": path.relative_to(snap).as_posix(),
                            "rows": len(df), "completeness": f"{len(df)} == COUNT(*) {source_count}"})
            log.info("SQL %s: %s rows", table, len(df))
    return entries


def count_records(path):
    if path.suffix == ".csv":
        return len(pd.read_csv(path))
    data = json.loads(path.read_text())
    # driver_events.json is nested: one object per driver with a list of events
    return sum(len(d["events"]) for d in data)


def copy_files(snap):
    """Byte-for-byte copy; completeness = checksum of copy equals checksum of source."""
    entries = []
    for name in config.FILE_SOURCES:
        src = config.DATA_DIR / name
        if not src.exists():
            raise RetrievalError(f"missing source file: {src}")
        dst = snap / "files" / name
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        if sha256(src) != sha256(dst):
            raise RetrievalError(f"copy of {name} does not match source")

        rows = count_records(dst)
        entries.append({"source": f"file:{name}", "mode": "file", "path": dst.relative_to(snap).as_posix(),
                        "rows": rows, "completeness": "sha256 of copy matches source"})
        log.info("file %s: %s records", name, rows)
    return entries


def ingest(run_id, api_url=config.API_URL):
    """The manifest is written last, so a snapshot without one is incomplete.
    If any source fails, the partial snapshot is removed."""
    snap = config.RAW_DIR / run_id
    snap.mkdir(parents=True)
    try:
        pull_all(snap, run_id, api_url)
    except Exception:
        shutil.rmtree(snap, ignore_errors=True)
        raise
    return snap


def pull_all(snap, run_id, api_url):
    entries = extract_sql(snap)
    api = fetch_dispatch_orders(api_url, snap / "api")
    entries.append({"source": "api:/dispatch/orders", "mode": "API", "path": "api/",
                    "rows": api["rows"], "completeness": api["completeness"],
                    "pages": api["pages"], "retries": api["retries"]})
    entries += copy_files(snap)

    # Checksums let a later rebuild prove the snapshot was not altered
    for e in entries:
        target = snap / e["path"]
        files = sorted(target.glob("*.json")) if target.is_dir() else [target]
        e["sha256"] = {f.name: sha256(f) for f in files}

    manifest = {"run_id": run_id, "retrieved_at": datetime.now(timezone.utc).isoformat(), "sources": entries}
    (snap / "manifest.json").write_text(json.dumps(manifest, indent=2))


def verify_snapshot(snap):
    """Used on --from-raw: refuse to rebuild from a snapshot that is incomplete or has changed."""
    if not (snap / "manifest.json").exists():
        raise RetrievalError(f"{snap} has no manifest - snapshot missing or incomplete")
    manifest = json.loads((snap / "manifest.json").read_text())
    for e in manifest["sources"]:
        target = snap / e["path"]
        for fname, digest in e["sha256"].items():
            f = target / fname if target.is_dir() else target
            if not f.exists() or sha256(f) != digest:
                raise RetrievalError(f"snapshot file changed or missing: {f}")
    log.info("snapshot %s verified against manifest", snap.name)


def load_snapshot(snap):
    """Read a raw snapshot into DataFrames (no cleaning here)."""
    raw = {t: pd.read_csv(snap / "sql" / f"{t}.csv") for t in config.SQL_TABLES}

    pages = sorted((snap / "api").glob("page_*.json"))
    raw["dispatch"] = pd.DataFrame([r for p in pages for r in json.loads(p.read_text())["data"]])

    drivers = json.loads((snap / "files" / "driver_events.json").read_text())
    raw["driver_events"] = pd.DataFrame(
        [{"driver_id": d["driver_id"], **ev} for d in drivers for ev in d["events"]]
    )
    raw["interventions"] = pd.read_csv(snap / "files" / "order_interventions.csv")
    raw["outcomes_reference"] = pd.read_csv(snap / "files" / "order_outcomes.csv")
    return raw
