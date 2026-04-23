from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any
from urllib import error, parse, request

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cmhc_rental import parse_market_rental_workbook
from scripts.import_cmhc_market_data import SupabaseConfig, load_dotenv


DATA_SOURCE = "/sitecore/content/CMHC/Sites/Main/Home/professionals/housing-markets-data-and-research/housing-data/data-tables/rental-market/rental-market-report-data-tables"
CMHC_RENTAL_TABLES_URL = (
    "https://www.cmhc-schl.gc.ca/professionals/housing-markets-data-and-research/"
    "housing-data/data-tables/rental-market/rental-market-report-data-tables"
)

BC_CENTRE_IDS = {
    "abbotsford_mission_bc": {"name": "Abbotsford – Mission", "city_id": "41CD2F31-475F-42FB-9739-D6A6D8BDD5CF"},
    "chilliwack_bc": {"name": "Chilliwack", "city_id": "263160E9-EB02-4369-B192-B9E3DD7F9723"},
    "kamloops_bc": {"name": "Kamloops", "city_id": "72782360-CD20-41A4-A218-C120339E5501"},
    "kelowna_bc": {"name": "Kelowna", "city_id": "8A50806C-8CA6-4E7C-9AF4-60BADA49CFED"},
    "nanaimo_bc": {"name": "Nanaimo", "city_id": "BF270FF5-22C7-41A9-A859-229E48924953"},
    "vancouver_bc": {"name": "Vancouver", "city_id": "F31F2160-40D5-42FB-A13A-F8353703523A"},
    "victoria_bc": {"name": "Victoria", "city_id": "84C78B93-4DBC-41C4-9593-B30F6E58F9F8"},
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Download and import CMHC market rental workbooks for BC centres")
    parser.add_argument("--edition", default="2025", help="Edition year to import, default 2025")
    parser.add_argument("--province", default="BC")
    parser.add_argument("--market-keys", nargs="*", help="Optional subset of BC market keys to import")
    parser.add_argument("--keep-workbooks", action="store_true", help="Keep downloaded workbooks in a temp directory for inspection")
    return parser.parse_args()


def json_request(url: str, *, query: dict[str, str]) -> Any:
    endpoint = f"{url}?{parse.urlencode(query)}"
    req = request.Request(
        endpoint,
        headers={
            "Accept": "application/json",
            "User-Agent": "Mozilla/5.0",
            "Referer": CMHC_RENTAL_TABLES_URL,
        },
    )
    with request.urlopen(req, timeout=30) as response:
        raw = response.read().decode("utf-8", errors="replace")
    return json.loads(raw)


def download_file(url: str, destination: Path) -> None:
    req = request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Referer": CMHC_RENTAL_TABLES_URL,
        },
    )
    with request.urlopen(req, timeout=60) as response:
        destination.write_bytes(response.read())


def supabase_request(
    config: SupabaseConfig,
    path: str,
    *,
    method: str = "GET",
    payload: Any | None = None,
    prefer: str | None = None,
    query: dict[str, str] | None = None,
) -> Any:
    endpoint = f"{config.url}/rest/v1/{path}"
    if query:
        endpoint = f"{endpoint}?{parse.urlencode(query)}"
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
        with request.urlopen(req, timeout=60) as response:
            raw = response.read().decode("utf-8", errors="replace")
            return json.loads(raw) if raw else None
    except error.HTTPError as exc:
        details = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Supabase request failed with status {exc.code}: {details}") from exc


def get_latest_edition_id(city_id: str, edition_label: str) -> str:
    editions = json_request(
        "https://www.cmhc-schl.gc.ca/api/Sitecore/PubsAndReports/GetEditionList",
        query={
            "cityId": city_id,
            "dataSource": DATA_SOURCE,
            "contextLanguage": "en",
        },
    )
    for edition in editions:
        if str(edition.get("Editions")) == edition_label:
            return str(edition["Itemid"])
    raise RuntimeError(f"Edition {edition_label} not found for city id {city_id}")


def get_workbook_url(city_id: str, edition_id: str) -> str:
    details = json_request(
        "https://www.cmhc-schl.gc.ca/api/Sitecore/PubsAndReports/GetFileDetails",
        query={
            "cityId": city_id,
            "edition": edition_id,
            "dataSource": DATA_SOURCE,
            "contextLanguage": "en",
        },
    )
    workbook_url = details.get("DocumentUrl")
    if not workbook_url:
        raise RuntimeError(f"No workbook URL returned for city id {city_id}")
    return str(workbook_url)


def source_dataset_for(market_key: str, edition: str) -> str:
    return f"cmhc_rental_market_report_{edition}_{market_key}"


def delete_existing_rows(config: SupabaseConfig, source_dataset: str) -> None:
    supabase_request(
        config,
        "market_reference_data",
        method="DELETE",
        query={"source": "eq.cmhc", "source_dataset": f"eq.{source_dataset}"},
        prefer="return=minimal",
    )


def main() -> None:
    args = parse_args()
    load_dotenv()
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_KEY")
    if not url or not key:
        raise RuntimeError("SUPABASE_URL and SUPABASE_KEY must be configured")

    config = SupabaseConfig(url=url.rstrip("/"), key=key)
    selected_market_keys = args.market_keys or list(BC_CENTRE_IDS.keys())
    unknown_keys = sorted(set(selected_market_keys) - set(BC_CENTRE_IDS.keys()))
    if unknown_keys:
        raise RuntimeError(f"Unknown BC market keys: {', '.join(unknown_keys)}")

    temp_dir_obj = tempfile.TemporaryDirectory(prefix="cmhc_bc_workbooks_")
    temp_dir = Path(temp_dir_obj.name)
    imported_markets: list[dict[str, Any]] = []
    total_rows = 0

    try:
        for market_key in selected_market_keys:
            market = BC_CENTRE_IDS[market_key]
            edition_id = get_latest_edition_id(market["city_id"], args.edition)
            workbook_url = get_workbook_url(market["city_id"], edition_id)
            workbook_path = temp_dir / f"{market_key}_{args.edition}.xlsx"
            download_file(workbook_url, workbook_path)

            source_dataset = source_dataset_for(market_key, args.edition)
            rows = parse_market_rental_workbook(
                workbook_path,
                province=args.province,
                source_dataset=source_dataset,
                source_url=workbook_url,
            )
            delete_existing_rows(config, source_dataset)
            if rows:
                result = supabase_request(
                    config,
                    "market_reference_data",
                    method="POST",
                    payload=rows,
                    prefer="return=representation",
                )
                imported_count = len(result) if isinstance(result, list) else 0
            else:
                imported_count = 0
            total_rows += imported_count
            imported_markets.append(
                {
                    "market_key": market_key,
                    "market_name": market["name"],
                    "edition": args.edition,
                    "rows_imported": imported_count,
                    "workbook_url": workbook_url,
                }
            )
        print(json.dumps({"markets": imported_markets, "total_rows_imported": total_rows, "source_page": CMHC_RENTAL_TABLES_URL}, indent=2))
    finally:
        if args.keep_workbooks:
            print(json.dumps({"download_dir": str(temp_dir)}, indent=2))
            temp_dir_obj.cleanup = lambda: None  # type: ignore[method-assign]
        else:
            temp_dir_obj.cleanup()


if __name__ == "__main__":
    main()
