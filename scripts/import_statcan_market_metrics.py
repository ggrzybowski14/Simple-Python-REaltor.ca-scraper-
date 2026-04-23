from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib import error, parse, request

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@dataclass
class SupabaseConfig:
    url: str
    key: str


METRIC_FIELD_DEFINITIONS = {
    "population": {
        "metric_key": "population",
        "unit": "people",
    },
    "population_growth_percent": {
        "metric_key": "population_growth_percent",
        "unit": "percent",
    },
    "unemployment_rate_percent": {
        "metric_key": "unemployment_rate_percent",
        "unit": "percent",
    },
    "median_household_income": {
        "metric_key": "median_household_income",
        "unit": "cad",
    },
}


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
    config: SupabaseConfig,
    path: str,
    *,
    method: str = "GET",
    query: dict[str, Any] | None = None,
    payload: Any | None = None,
    prefer: str | None = None,
) -> Any:
    endpoint = f"{config.url}/rest/v1/{path}"
    if query:
        endpoint = f"{endpoint}?{parse.urlencode(query, doseq=True)}"
    headers = {
        "apikey": config.key,
        "Authorization": f"Bearer {config.key}",
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
        with request.urlopen(req, timeout=30) as response:
            raw = response.read().decode("utf-8", errors="replace")
            return json.loads(raw) if raw else None
    except error.HTTPError as exc:
        details = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Supabase request failed with status {exc.code}: {details}") from exc
    except error.URLError as exc:
        raise RuntimeError(f"Supabase request failed: {exc.reason}") from exc


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Bulk import Statistics Canada market metrics into market_profiles and market_metrics"
    )
    parser.add_argument(
        "csv_path",
        nargs="?",
        default=str(ROOT / "data" / "statcan_bc_market_metrics.csv"),
        help="Path to a CSV file containing market metrics rows",
    )
    parser.add_argument(
        "--source-name",
        default="Statistics Canada 2021 Census",
        help="Default source name when the CSV row does not override it",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse the CSV and print counts without writing to Supabase",
    )
    return parser.parse_args()


def parse_optional_float(value: str | None) -> float | None:
    if value is None:
        return None
    cleaned = value.strip().replace(",", "")
    if not cleaned:
        return None
    try:
        return float(cleaned)
    except ValueError as exc:
        raise RuntimeError(f"Invalid numeric value: {value!r}") from exc


def load_csv_rows(csv_path: Path) -> list[dict[str, str]]:
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = [dict(row) for row in reader]
    return rows


def build_market_profiles(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    profiles_by_key: dict[str, dict[str, Any]] = {}
    for row in rows:
        market_key = (row.get("market_key") or "").strip()
        market_name = (row.get("market_name") or "").strip()
        if not market_key or not market_name:
            raise RuntimeError("Each CSV row must include market_key and market_name")
        profiles_by_key[market_key] = {
            "market_key": market_key,
            "market_name": market_name,
            "province": (row.get("province") or "").strip() or None,
            "geography_type": (row.get("geography_type") or "").strip() or "market",
            "status": (row.get("status") or "").strip() or "active",
            "notes": (row.get("profile_notes") or "").strip() or None,
        }
    return list(profiles_by_key.values())


def build_market_metrics(rows: list[dict[str, str]], *, default_source_name: str) -> list[dict[str, Any]]:
    metrics_payload: list[dict[str, Any]] = []
    for row in rows:
        market_key = (row.get("market_key") or "").strip()
        source_name = (row.get("source_name") or "").strip() or default_source_name
        source_url = (row.get("source_url") or "").strip() or None
        source_date = (row.get("source_date") or "").strip() or None
        confidence = (row.get("confidence") or "").strip() or "high"

        for field_name, definition in METRIC_FIELD_DEFINITIONS.items():
            numeric_value = parse_optional_float(row.get(field_name))
            if numeric_value is None:
                continue
            notes_field = f"{field_name}_notes"
            metrics_payload.append(
                {
                    "market_key": market_key,
                    "metric_key": definition["metric_key"],
                    "value_numeric": numeric_value,
                    "unit": definition["unit"],
                    "source_name": source_name,
                    "source_url": source_url,
                    "source_date": source_date,
                    "confidence": confidence,
                    "notes": (row.get(notes_field) or "").strip() or None,
                }
            )
    return metrics_payload


def main() -> None:
    args = parse_args()
    csv_path = Path(args.csv_path)
    if not csv_path.exists():
        raise RuntimeError(f"CSV not found: {csv_path}")

    rows = load_csv_rows(csv_path)
    if not rows:
        raise RuntimeError(f"No rows found in CSV: {csv_path}")

    profiles_payload = build_market_profiles(rows)
    metrics_payload = build_market_metrics(rows, default_source_name=args.source_name)

    if args.dry_run:
        print(
            json.dumps(
                {
                    "csv_path": str(csv_path),
                    "market_profiles": len(profiles_payload),
                    "market_metrics": len(metrics_payload),
                },
                indent=2,
            )
        )
        return

    load_dotenv()
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_KEY")
    if not url or not key:
        raise RuntimeError("SUPABASE_URL and SUPABASE_KEY must be configured")

    config = SupabaseConfig(url=url.rstrip("/"), key=key)
    profile_result = supabase_request(
        config,
        "market_profiles",
        method="POST",
        query={"on_conflict": "market_key"},
        payload=profiles_payload,
        prefer="resolution=merge-duplicates,return=representation",
    )
    metric_result = supabase_request(
        config,
        "market_metrics",
        method="POST",
        query={"on_conflict": "market_key,metric_key"},
        payload=metrics_payload,
        prefer="resolution=merge-duplicates,return=representation",
    )
    print(
        json.dumps(
            {
                "csv_path": str(csv_path),
                "profiles_upserted": len(profile_result) if isinstance(profile_result, list) else 0,
                "metrics_upserted": len(metric_result) if isinstance(metric_result, list) else 0,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
