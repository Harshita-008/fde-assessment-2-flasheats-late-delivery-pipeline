"""Paths, source lists and business thresholds used across the pipeline."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent

# Client systems (inputs, never modified)
SQLITE_PATH = ROOT / "database" / "flasheats.db"
DATA_DIR = ROOT / "data"
API_URL = "http://127.0.0.1:8000"

# Pipeline locations
RAW_DIR = ROOT / "raw"          # one immutable snapshot per run
OUTPUT_DIR = ROOT / "output"    # latest successful run only
LOG_DIR = ROOT / "logs"

# What we pull from each system (see docs/source_map.md for why)
SQL_TABLES = ["orders", "restaurants", "drivers"]
FILE_SOURCES = ["driver_events.json", "order_interventions.csv", "order_outcomes.csv"]

# API behaviour
API_PAGE_SIZE = 100
API_MAX_RETRIES = 4
API_TIMEOUT_SEC = 10

# Business rules
SEVERE_LATE_MIN = 10            # Support Lead's "meaningfully late" threshold
VALID_STATUSES = {"delivered", "cancelled"}
VALID_TRAFFIC = {"low", "medium", "high", "severe"}
VALID_WEATHER = {"clear", "rain", "heavy_rain"}
BENGALURU_BBOX = {"lat": (12.6, 13.4), "lon": (77.3, 77.9)}

# Stop the run if more than this share of delivered orders cannot be trusted
MAX_QUARANTINE_SHARE = 0.05
