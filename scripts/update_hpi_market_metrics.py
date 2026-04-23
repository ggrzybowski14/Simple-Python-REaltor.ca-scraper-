from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any
from urllib import error, parse, request

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from crea_hpi import (
    CREA_SOURCE_KEY,
    CREA_SOURCE_NAME,
    CREA_SOURCE_URL,
    PROPERTY_TYPE_COLUMN_MAP,
    SEASONAL_ADJUSTMENT_SEASONALLY_ADJUSTED,
    SERIES_KEY_BY_PROPERTY_TYPE,
    build_market_metric_snapshot,
)


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'").strip('"')
        if key and key not in os.environ:
            os.environ[key] = value


def load_dotenv() -> None:
    for path in (ROOT / ".env", ROOT / ".env.local"):
        load_env_file(path)


def supabase_request(
    url: str,
    key: str,
    path: str,
    *,
    method: str = "GET",
    query: dict[str, Any] | None = None,
    payload: Any | None = None,
    prefer: str | None = None,
) -> Any:
    endpoint = f"{url.rstrip('/')}/rest/v1/{path}"
    if query:
        endpoint = f"{endpoint}?{parse.urlencode(query, doseq=True)}"
    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Accept": "application/json",
    }
    body = None
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if prefer:
        headers["Prefer"] = prefer
    req = request.Request(endpoint, data=body, method=method, headers=headers)
    try:
        with request.urlopen(req, timeout=60) as response:
            raw = response.read().decode("utf-8", errors="replace")
            return json.loads(raw) if raw else None
    except error.HTTPError as exc:
        details = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Supabase request failed with status {exc.code}: {details}") from exc
    except error.URLError as exc:
        raise RuntimeError(f"Supabase request failed: {exc.reason}") from exc


def fetch_all_hpi_observations(url: str, key: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    offset = 0
    page_size = 1000
    while True:
        batch = supabase_request(
            url,
            key,
            "hpi_observations",
            query={
                "source": f"eq.{CREA_SOURCE_KEY}",
                "seasonal_adjustment": f"eq.{SEASONAL_ADJUSTMENT_SEASONALLY_ADJUSTED}",
                "select": (
                    "market_key,market_name,province,property_type_slug,property_type_label,"
                    "point_date,index_value,benchmark_price,source_file_name"
                ),
                "order": "market_key.asc,property_type_slug.asc,point_date.asc",
                "limit": page_size,
                "offset": offset,
            },
        )
        batch_rows = batch if isinstance(batch, list) else []
        rows.extend(batch_rows)
        if len(batch_rows) < page_size:
            break
        offset += page_size
    return rows


def chunk_records(records: list[dict[str, Any]], chunk_size: int = 500) -> list[list[dict[str, Any]]]:
    return [records[index : index + chunk_size] for index in range(0, len(records), chunk_size)]


def build_series_payload(observations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    series_payload: list[dict[str, Any]] = []
    for observation in observations:
        property_type_slug = observation["property_type_slug"]
        series_payload.append(
            {
                "market_key": observation["market_key"],
                "series_key": SERIES_KEY_BY_PROPERTY_TYPE[property_type_slug],
                "point_date": observation["point_date"],
                "value_numeric": observation["index_value"],
                "unit": "index_2005_100",
                "source_name": CREA_SOURCE_NAME,
                "source_url": CREA_SOURCE_URL,
                "source_date": observation["point_date"],
                "confidence": "high",
                "notes": (
                    f"{PROPERTY_TYPE_COLUMN_MAP[property_type_slug]['label']} CREA MLS HPI "
                    "seasonally adjusted monthly index series."
                ),
                "raw_payload": {
                    "property_type_slug": property_type_slug,
                    "benchmark_price": observation.get("benchmark_price"),
                    "source_file_name": observation.get("source_file_name"),
                },
            }
        )
    return series_payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Calculate CREA HPI market metrics and publish source-specific appreciation series"
    )
    parser.add_argument("--dry-run", action="store_true", help="Calculate metrics without writing to Supabase")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    load_dotenv()
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_KEY")
    if not url or not key:
        raise RuntimeError("SUPABASE_URL and SUPABASE_KEY must be configured")

    observations = fetch_all_hpi_observations(url, key)
    if not observations:
        raise RuntimeError("No CREA HPI observations were found in hpi_observations")

    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for observation in observations:
        grouped[(observation["market_key"], observation["property_type_slug"])].append(observation)

    metric_rows: list[dict[str, Any]] = []
    for (market_key, property_type_slug), series_observations in grouped.items():
        sample = series_observations[0]
        metric_rows.append(
            build_market_metric_snapshot(
                series_observations,
                source=CREA_SOURCE_KEY,
                market_key=market_key,
                market_name=sample["market_name"],
                province=sample.get("province"),
                property_type_slug=property_type_slug,
                property_type_label=sample["property_type_label"],
            )
        )

    series_payload = build_series_payload(observations)

    summary = {
        "source": CREA_SOURCE_KEY,
        "observation_count": len(observations),
        "market_property_series": len(grouped),
        "metric_rows": len(metric_rows),
        "series_points": len(series_payload),
    }
    if args.dry_run:
        print(json.dumps(summary, indent=2))
        return

    for batch in chunk_records(metric_rows):
        supabase_request(
            url,
            key,
            "hpi_market_metrics",
            method="POST",
            query={"on_conflict": "source,market_key,property_type_slug"},
            payload=batch,
            prefer="resolution=merge-duplicates,return=minimal",
        )
    for batch in chunk_records(series_payload):
        supabase_request(
            url,
            key,
            "market_metric_series",
            method="POST",
            query={"on_conflict": "market_key,series_key,point_date"},
            payload=batch,
            prefer="resolution=merge-duplicates,return=minimal",
        )

    print(
        json.dumps(
            {
                **summary,
                "hpi_market_metrics_upserted": len(metric_rows),
                "market_metric_series_upserted": len(series_payload),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
