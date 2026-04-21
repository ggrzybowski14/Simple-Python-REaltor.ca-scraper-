from __future__ import annotations

import argparse
import json
import os
import sys
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib import error, parse, request

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from market_data import normalize_market_key


@dataclass
class SupabaseConfig:
    url: str
    key: str


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


NS = {"a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Import CMHC rent and vacancy reference rows from an XLSX workbook")
    parser.add_argument("xlsx_path", help="Path to a CMHC Rental Market Report XLSX file")
    parser.add_argument("--source-dataset", default="cmhc_rental_market_2025_bc")
    parser.add_argument("--source-url", default="")
    parser.add_argument("--province", default="BC")
    return parser.parse_args()


def col_letters(cell_ref: str) -> str:
    letters = []
    for ch in cell_ref:
        if ch.isalpha():
            letters.append(ch)
        else:
            break
    return "".join(letters)


def cell_value(cell: ET.Element) -> str:
    cell_type = cell.attrib.get("t")
    if cell_type == "inlineStr":
        texts = [node.text or "" for node in cell.findall(".//a:t", NS)]
        return "".join(texts).strip()
    value = cell.find("a:v", NS)
    return (value.text or "").strip() if value is not None else ""


def parse_sheet_rows(zf: zipfile.ZipFile, sheet_path: str) -> list[dict[str, str]]:
    root = ET.fromstring(zf.read(sheet_path))
    sheet_data = root.find("a:sheetData", NS)
    rows: list[dict[str, str]] = []
    if sheet_data is None:
        return rows
    for row in sheet_data.findall("a:row", NS):
        values: dict[str, str] = {}
        for cell in row.findall("a:c", NS):
            values[col_letters(cell.attrib["r"])] = cell_value(cell)
        rows.append(values)
    return rows


def clean_market_name(value: str) -> str:
    cleaned = value.replace(" CMA", "").replace(" CA", "").replace(" RDA", "").strip()
    return cleaned


def parse_numeric(value: str | None) -> float | None:
    if not value:
        return None
    cleaned = value.replace(",", "").strip()
    if not cleaned or cleaned == "**":
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def build_market_rows(
    rent_rows: list[dict[str, str]],
    vacancy_rows: list[dict[str, str]],
    *,
    province: str,
    source_dataset: str,
    source_url: str,
) -> list[dict[str, Any]]:
    vacancy_by_centre: dict[str, float | None] = {}
    for row in vacancy_rows:
        centre = row.get("A", "").strip()
        if not centre or centre == "Centre":
            continue
        # Total Oct-25 vacancy is column X in Table 1.1.1
        vacancy_by_centre[centre] = parse_numeric(row.get("X"))

    market_rows: list[dict[str, Any]] = []
    for row in rent_rows:
        centre = row.get("A", "").strip()
        if not centre or centre == "Centre":
            continue
        cleaned_market_name = clean_market_name(centre)
        market_key = normalize_market_key(cleaned_market_name, province)
        # Oct-25 columns in Table 1.1.2:
        # H=1 bed, L=2 bed, P=3 bed+, T=total
        bedroom_map = {
            1: parse_numeric(row.get("H")),
            2: parse_numeric(row.get("L")),
            3: parse_numeric(row.get("P")),
        }
        vacancy_rate = vacancy_by_centre.get(centre)
        for bedroom_count, average_rent in bedroom_map.items():
            if average_rent is None and vacancy_rate is None:
                continue
            market_rows.append(
                {
                    "source": "cmhc",
                    "source_dataset": source_dataset,
                    "market_name": cleaned_market_name,
                    "province": province,
                    "market_key": market_key,
                    "geography_type": "market",
                    "property_type": "apartment",
                    "bedroom_count": bedroom_count,
                    "average_rent_monthly": average_rent,
                    "vacancy_rate_percent": vacancy_rate,
                    "source_url": source_url or None,
                    "raw_payload": {
                        "rent_row": row,
                        "vacancy_rate_percent": vacancy_rate,
                    },
                }
            )
    return market_rows


def main() -> None:
    args = parse_args()
    workbook_path = Path(args.xlsx_path)
    if not workbook_path.exists():
        raise RuntimeError(f"Workbook not found: {workbook_path}")

    load_dotenv()

    import os

    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_KEY")
    if not url or not key:
        raise RuntimeError("SUPABASE_URL and SUPABASE_KEY must be configured")

    with zipfile.ZipFile(workbook_path) as zf:
        vacancy_rows = parse_sheet_rows(zf, "xl/worksheets/sheet2.xml")
        rent_rows = parse_sheet_rows(zf, "xl/worksheets/sheet3.xml")

    payload = build_market_rows(
        rent_rows,
        vacancy_rows,
        province=args.province,
        source_dataset=args.source_dataset,
        source_url=args.source_url,
    )
    if not payload:
        print("No CMHC rows parsed from workbook.")
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
    print(json.dumps({"imported": count}, indent=2))


if __name__ == "__main__":
    main()
