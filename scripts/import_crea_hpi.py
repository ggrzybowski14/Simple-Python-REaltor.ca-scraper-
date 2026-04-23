from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any
from urllib import error, parse, request

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from crea_hpi import CREA_SOURCE_KEY, load_crea_workbook_candidates, parse_crea_workbook_bytes


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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Import CREA seasonally adjusted monthly HPI workbook data into Supabase"
    )
    parser.add_argument("folder_path", help="Local folder containing CREA monthly workbook zip or xlsx files")
    parser.add_argument("--dry-run", action="store_true", help="Parse workbooks and print counts without writing to Supabase")
    return parser.parse_args()


def dedupe_records(records: list[dict[str, Any]], *, key_fields: tuple[str, ...]) -> tuple[list[dict[str, Any]], int]:
    deduped: dict[tuple[Any, ...], dict[str, Any]] = {}
    duplicate_count = 0
    for record in records:
        key = tuple(record.get(field) for field in key_fields)
        if key in deduped:
            duplicate_count += 1
        deduped[key] = record
    return list(deduped.values()), duplicate_count


def chunk_records(records: list[dict[str, Any]], chunk_size: int = 500) -> list[list[dict[str, Any]]]:
    return [records[index : index + chunk_size] for index in range(0, len(records), chunk_size)]


def main() -> None:
    args = parse_args()
    folder_path = Path(args.folder_path).expanduser().resolve()
    candidates = load_crea_workbook_candidates(folder_path)

    parsed_observations: list[dict[str, Any]] = []
    parsed_profiles: list[dict[str, Any]] = []
    inspection_summaries: list[dict[str, Any]] = []

    for source_file_name, workbook_bytes in candidates:
        observations, profiles, inspection = parse_crea_workbook_bytes(
            workbook_bytes,
            workbook_name=source_file_name.split(":")[-1],
            source_file_name=source_file_name,
        )
        parsed_observations.extend(observations)
        parsed_profiles.extend(profiles)
        inspection_summaries.append(
            {
                "workbook_name": inspection.workbook_name,
                "sheet_count": len(inspection.sheet_names),
                "header_row": inspection.header_row,
            }
        )

    deduped_profiles, duplicate_profiles = dedupe_records(parsed_profiles, key_fields=("market_key",))
    deduped_observations, duplicate_observations = dedupe_records(
        parsed_observations,
        key_fields=("source", "market_key", "property_type_slug", "point_date", "seasonal_adjustment"),
    )

    summary = {
        "source": CREA_SOURCE_KEY,
        "folder_path": str(folder_path),
        "workbooks_found": len(candidates),
        "workbook_summaries": inspection_summaries,
        "market_profiles_parsed": len(parsed_profiles),
        "market_profiles_upsert_candidates": len(deduped_profiles),
        "market_profile_duplicates_collapsed": duplicate_profiles,
        "observations_parsed": len(parsed_observations),
        "observations_upsert_candidates": len(deduped_observations),
        "observation_duplicates_collapsed": duplicate_observations,
        "skipped_invalid_rows": 0,
    }

    if args.dry_run:
        print(json.dumps(summary, indent=2))
        return

    load_dotenv()
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_KEY")
    if not url or not key:
        raise RuntimeError("SUPABASE_URL and SUPABASE_KEY must be configured")

    supabase_request(
        url,
        key,
        "market_profiles",
        method="POST",
        query={"on_conflict": "market_key"},
        payload=deduped_profiles,
        prefer="resolution=merge-duplicates,return=minimal",
    )
    for batch in chunk_records(deduped_observations):
        supabase_request(
            url,
            key,
            "hpi_observations",
            method="POST",
            query={"on_conflict": "source,market_key,property_type_slug,point_date,seasonal_adjustment"},
            payload=batch,
            prefer="resolution=merge-duplicates,return=minimal",
        )

    print(
        json.dumps(
            {
                **summary,
                "market_profiles_upserted": len(deduped_profiles),
                "hpi_observations_upserted": len(deduped_observations),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
