"""Client for the dispatch API: paginated, retries transient errors, proves completeness."""
import json
import logging
import time

import requests

import config

log = logging.getLogger(__name__)


class RetrievalError(Exception):
    pass


def check_health(base_url):
    try:
        resp = requests.get(f"{base_url}/health", timeout=config.API_TIMEOUT_SEC)
        resp.raise_for_status()
    except requests.RequestException as exc:
        raise RetrievalError(
            f"Dispatch API not reachable at {base_url} ({exc}). "
            "Start it with: python api/mock_dispatch_api.py"
        )


def get_page(base_url, page):
    """Fetch one page, retrying on 5xx / 429. Returns (body, attempts)."""
    url = f"{base_url}/dispatch/orders"
    params = {"page": page, "page_size": config.API_PAGE_SIZE}

    for attempt in range(1, config.API_MAX_RETRIES + 1):
        try:
            resp = requests.get(url, params=params, timeout=config.API_TIMEOUT_SEC)
        except requests.RequestException as exc:
            wait, reason = 2 ** (attempt - 1), str(exc)
        else:
            if resp.status_code == 200:
                return resp.json(), attempt
            if resp.status_code == 429:
                wait = resp.json().get("retry_after_seconds", 2 ** (attempt - 1))
                reason = "rate limited"
            elif resp.status_code >= 500:
                wait, reason = 2 ** (attempt - 1), f"HTTP {resp.status_code}"
            else:
                # 4xx other than 429 will not fix itself
                raise RetrievalError(f"page {page}: HTTP {resp.status_code} {resp.text}")

        log.warning("page %s attempt %s failed (%s), retrying in %ss", page, attempt, reason, wait)
        time.sleep(wait)

    raise RetrievalError(f"page {page}: gave up after {config.API_MAX_RETRIES} attempts")


def fetch_dispatch_orders(base_url, out_dir):
    """Save every page as received and return a completeness summary."""
    check_health(base_url)
    out_dir.mkdir(parents=True, exist_ok=True)

    page, records, retries, expected_total = 1, [], 0, None
    while True:
        body, attempts = get_page(base_url, page)
        retries += attempts - 1
        (out_dir / f"page_{page:03d}.json").write_text(json.dumps(body, indent=1))

        if expected_total is None:
            expected_total = body["total_records"]
        elif body["total_records"] != expected_total:
            raise RetrievalError("total_records changed between pages - source moved during pull")

        records.extend(body["data"])
        if not body["has_more"]:
            break
        page += 1

    # Completeness: count matches what the API says it has, and nothing was repeated
    unique_ids = {r["order_id"] for r in records}
    if len(records) != expected_total or len(unique_ids) != expected_total:
        raise RetrievalError(
            f"incomplete pull: got {len(records)} records / {len(unique_ids)} unique, "
            f"API reports {expected_total}"
        )

    log.info("dispatch API: %s records over %s pages (%s retries)", len(records), page, retries)
    return {"rows": len(records), "pages": page, "retries": retries,
            "completeness": f"{len(records)} == total_records {expected_total}, ids unique"}
