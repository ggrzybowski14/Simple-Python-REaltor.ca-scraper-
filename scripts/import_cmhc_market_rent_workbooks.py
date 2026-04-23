from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any
from urllib import error, request

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cmhc_rental import parse_market_rental_workbook
from scripts.import_cmhc_market_data import SupabaseConfig, load_dotenv


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Import CMHC market-specific rental workbooks into market_reference_data")
    parser.add_argument("path", help="Path to a workbook file or folder containing CMHC rental workbooks")
    parser.add_argument("--source-dataset-prefix", default="cmhc_rental_market_report")
    parser.add_argument("--source-url", default="")
    parser.add_argument("--province", default="BC")
    return parser.parse_args()


def supabase_request(
    config: SupabaseConfig,
    path: str,
    *,
    method: str = "GET",
    payload: Any | None = None,
    prefer: str | None = None,
) -> Any:
    endpoint = f"{config.url}/rest/v1/{path}"
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


def discover_workbooks(path: Path) -> list[Path]:
    if path.is_file():
        return [path]
    return sorted(candidate for candidate in path.rglob("*.xlsx") if candidate.is_file())


def build_source_dataset(prefix: str, workbook_path: Path) -> str:
    stem = workbook_path.stem.lower().replace(" ", "_").replace("-", "_")
    return f"{prefix}_{stem}"


def main() -> None:
    args = parse_args()
    root = Path(args.path)
    if not root.exists():
        raise RuntimeError(f"Path not found: {root}")

    load_dotenv()
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_KEY")
    if not url or not key:
        raise RuntimeError("SUPABASE_URL and SUPABASE_KEY must be configured")

    workbooks = discover_workbooks(root)
    if not workbooks:
        raise RuntimeError(f"No XLSX workbooks found under: {root}")

    payload: list[dict[str, Any]] = []
    for workbook_path in workbooks:
        rows = parse_market_rental_workbook(
            workbook_path,
            province=args.province,
            source_dataset=build_source_dataset(args.source_dataset_prefix, workbook_path),
            source_url=args.source_url,
        )
        payload.extend(rows)

    if not payload:
        print(json.dumps({"parsed": 0, "imported": 0}, indent=2))
        return

    config = SupabaseConfig(url=url.rstrip("/"), key=key)
    result = supabase_request(
        config,
        "market_reference_data",
        method="POST",
        payload=payload,
        prefer="return=representation",
    )
    count = len(result) if isinstance(result, list) else 0
    print(json.dumps({"parsed": len(payload), "imported": count, "workbooks": len(workbooks)}, indent=2))


if __name__ == "__main__":
    main()
