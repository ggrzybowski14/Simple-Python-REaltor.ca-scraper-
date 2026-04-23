from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from io import BytesIO
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

from market_data import normalize_market_key


CREA_SOURCE_KEY = "crea_hpi"
CREA_SOURCE_NAME = "CREA MLS HPI"
CREA_SOURCE_URL = "https://www.crea.ca/housing-market-stats/mls-home-price-index/hpi-tool/"
SEASONAL_ADJUSTMENT_SEASONALLY_ADJUSTED = "seasonally_adjusted"
PRIMARY_WORKBOOK_NAME = "Seasonally Adjusted (M).xlsx"
WORKBOOK_XML_NS = {
    "main": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "rel": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
}

PROVINCE_NAME_TO_CODE = {
    "BRITISH_COLUMBIA": "BC",
    "ALBERTA": "AB",
    "SASKATCHEWAN": "SK",
    "ONTARIO": "ON",
    "QUEBEC": "QC",
    "NEW_BRUNSWICK": "NB",
    "NOVA_SCOTIA": "NS",
    "PRINCE_EDWARD_ISLAND": "PE",
    "NEWFOUNDLAND_AND_LABRADOR": "NL",
}

SERIES_KEY_BY_PROPERTY_TYPE = {
    "composite": "crea_mls_hpi_composite",
    "single_family": "crea_mls_hpi_single_family",
    "one_storey": "crea_mls_hpi_one_storey",
    "two_storey": "crea_mls_hpi_two_storey",
    "townhouse": "crea_mls_hpi_townhouse",
    "apartment": "crea_mls_hpi_apartment",
}

PROPERTY_TYPE_COLUMN_MAP = {
    "composite": {
        "label": "Composite",
        "index_header": "Composite_HPI_SA",
        "benchmark_header": "Composite_Benchmark_SA",
        "series_key": SERIES_KEY_BY_PROPERTY_TYPE["composite"],
    },
    "single_family": {
        "label": "Single Family",
        "index_header": "Single_Family_HPI_SA",
        "benchmark_header": "Single_Family_Benchmark_SA",
        "series_key": SERIES_KEY_BY_PROPERTY_TYPE["single_family"],
    },
    "one_storey": {
        "label": "One-Storey",
        "index_header": "One_Storey_HPI_SA",
        "benchmark_header": "One_Storey_Benchmark_SA",
        "series_key": SERIES_KEY_BY_PROPERTY_TYPE["one_storey"],
    },
    "two_storey": {
        "label": "Two-Storey",
        "index_header": "Two_Storey_HPI_SA",
        "benchmark_header": "Two_Storey_Benchmark_SA",
        "series_key": SERIES_KEY_BY_PROPERTY_TYPE["two_storey"],
    },
    "townhouse": {
        "label": "Townhouse",
        "index_header": "Townhouse_HPI_SA",
        "benchmark_header": "Townhouse_Benchmark_SA",
        "series_key": SERIES_KEY_BY_PROPERTY_TYPE["townhouse"],
    },
    "apartment": {
        "label": "Apartment",
        "index_header": "Apartment_HPI_SA",
        "benchmark_header": "Apartment_Benchmark_SA",
        "series_key": SERIES_KEY_BY_PROPERTY_TYPE["apartment"],
    },
}

MARKET_NAME_OVERRIDES = {
    "AGGREGATE": {"market_name": "Canada", "market_key": "canada", "province": None, "geography_type": "country"},
    "GREATER_VANCOUVER": {"market_name": "Vancouver", "market_key": "vancouver_bc"},
    "VICTORIA": {"market_name": "Victoria", "market_key": "victoria_bc"},
}


@dataclass(frozen=True)
class WorkbookInspection:
    workbook_name: str
    sheet_names: list[str]
    header_row: list[str]
    relevant_columns: list[str]
    date_representation: str
    market_representation: str
    property_type_representation: str


def humanize_sheet_name(sheet_name: str) -> str:
    override = MARKET_NAME_OVERRIDES.get(sheet_name)
    if override and override.get("market_name"):
        return str(override["market_name"])
    words = sheet_name.split("_")
    rendered: list[str] = []
    for word in words:
        if word == "ST":
            rendered.append("St.")
        elif word == "NL":
            rendered.append("NL")
        elif word == "NB":
            rendered.append("NB")
        elif word == "PEI":
            rendered.append("PEI")
        elif word == "CMA":
            rendered.append("CMA")
        else:
            rendered.append(word.title())
    return " ".join(rendered)


def coerce_numeric_cell(value: str | None) -> float | None:
    if value is None:
        return None
    cleaned = str(value).strip().replace(",", "")
    if not cleaned:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def parse_excel_serial_date(raw_value: str) -> date:
    base = datetime(1899, 12, 30)
    return (base + timedelta(days=float(raw_value))).date()


def parse_cell_date(raw_value: str | None) -> date | None:
    if raw_value is None:
        return None
    cleaned = str(raw_value).strip()
    if not cleaned:
        return None
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", cleaned):
        return date.fromisoformat(cleaned)
    numeric = coerce_numeric_cell(cleaned)
    if numeric is None:
        return None
    return parse_excel_serial_date(cleaned)


def load_xlsx_shared_strings(workbook: zipfile.ZipFile) -> list[str]:
    try:
        shared_strings_xml = workbook.read("xl/sharedStrings.xml")
    except KeyError:
        return []
    root = ET.fromstring(shared_strings_xml)
    strings: list[str] = []
    for item in root:
        parts = [node.text or "" for node in item.iter("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}t")]
        strings.append("".join(parts))
    return strings


def load_xlsx_sheet_targets(workbook: zipfile.ZipFile) -> list[tuple[str, str]]:
    workbook_root = ET.fromstring(workbook.read("xl/workbook.xml"))
    relationships_root = ET.fromstring(workbook.read("xl/_rels/workbook.xml.rels"))
    relationship_targets = {
        rel.attrib["Id"]: rel.attrib["Target"]
        for rel in relationships_root
    }
    sheets: list[tuple[str, str]] = []
    for sheet in workbook_root.find("main:sheets", WORKBOOK_XML_NS) or []:
        sheet_name = sheet.attrib.get("name", "")
        relationship_id = sheet.attrib.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id", "")
        target = relationship_targets.get(relationship_id)
        if sheet_name and target:
            sheets.append((sheet_name, f"xl/{target}"))
    return sheets


def read_sheet_rows(workbook: zipfile.ZipFile, target: str, shared_strings: list[str]) -> list[list[str]]:
    root = ET.fromstring(workbook.read(target))
    sheet_data = root.find("main:sheetData", WORKBOOK_XML_NS)
    rows: list[list[str]] = []
    if sheet_data is None:
        return rows
    for row in sheet_data:
        cells: dict[int, str] = {}
        for cell in row:
            reference = cell.attrib.get("r", "")
            match = re.match(r"([A-Z]+)", reference)
            if match is None:
                continue
            column_letters = match.group(1)
            column_index = 0
            for char in column_letters:
                column_index = column_index * 26 + (ord(char) - 64)
            column_index -= 1
            value_node = cell.find("main:v", WORKBOOK_XML_NS)
            value = value_node.text if value_node is not None else ""
            if cell.attrib.get("t") == "s" and value:
                try:
                    value = shared_strings[int(value)]
                except (ValueError, IndexError):
                    pass
            cells[column_index] = value
        if not cells:
            rows.append([])
            continue
        max_index = max(cells)
        rows.append([cells.get(index, "") for index in range(max_index + 1)])
    return rows


def build_market_identity(sheet_name: str, current_province: str | None) -> dict[str, Any]:
    override = MARKET_NAME_OVERRIDES.get(sheet_name, {})
    market_name = str(override.get("market_name") or humanize_sheet_name(sheet_name))
    province = override.get("province") if "province" in override else current_province
    market_key = str(override.get("market_key") or normalize_market_key(market_name, province))
    geography_type = str(override.get("geography_type") or ("province" if sheet_name in PROVINCE_NAME_TO_CODE else "market"))
    return {
        "market_name": market_name,
        "market_key": market_key,
        "province": province,
        "geography_type": geography_type,
    }


def inspect_crea_workbook_bytes(workbook_bytes: bytes, *, workbook_name: str) -> WorkbookInspection:
    with zipfile.ZipFile(BytesIO(workbook_bytes)) as workbook:
        shared_strings = load_xlsx_shared_strings(workbook)
        sheet_targets = load_xlsx_sheet_targets(workbook)
        if not sheet_targets:
            raise RuntimeError(f"Workbook {workbook_name} did not contain any worksheets")
        first_sheet_name, first_target = sheet_targets[0]
        rows = read_sheet_rows(workbook, first_target, shared_strings)
        if not rows or not rows[0]:
            raise RuntimeError(f"Workbook {workbook_name} did not contain a readable header row")
        header_row = rows[0]
        expected_headers = ["Date"] + [
            definition["index_header"] for definition in PROPERTY_TYPE_COLUMN_MAP.values()
        ] + [
            definition["benchmark_header"] for definition in PROPERTY_TYPE_COLUMN_MAP.values()
        ]
        missing_headers = [header for header in expected_headers if header not in header_row]
        if missing_headers:
            raise RuntimeError(
                f"Workbook {workbook_name} is missing expected CREA HPI headers: {', '.join(missing_headers)}"
            )
        return WorkbookInspection(
            workbook_name=workbook_name,
            sheet_names=[sheet_name for sheet_name, _ in sheet_targets],
            header_row=header_row,
            relevant_columns=expected_headers,
            date_representation="Excel serial date in the Date column, one row per month",
            market_representation=f"Worksheet name, for example {first_sheet_name}",
            property_type_representation="Paired HPI and Benchmark columns per property type",
        )


def parse_crea_workbook_bytes(
    workbook_bytes: bytes,
    *,
    workbook_name: str,
    source_file_name: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], WorkbookInspection]:
    inspection = inspect_crea_workbook_bytes(workbook_bytes, workbook_name=workbook_name)
    observations: list[dict[str, Any]] = []
    profiles_by_market_key: dict[str, dict[str, Any]] = {}

    with zipfile.ZipFile(BytesIO(workbook_bytes)) as workbook:
        shared_strings = load_xlsx_shared_strings(workbook)
        current_province: str | None = None
        for sheet_name, target in load_xlsx_sheet_targets(workbook):
            if sheet_name in PROVINCE_NAME_TO_CODE:
                current_province = PROVINCE_NAME_TO_CODE[sheet_name]
            market_identity = build_market_identity(sheet_name, current_province)
            profiles_by_market_key[market_identity["market_key"]] = {
                **market_identity,
                "status": "active",
                "notes": "Imported from CREA MLS HPI seasonally adjusted monthly workbook.",
            }

            rows = read_sheet_rows(workbook, target, shared_strings)
            if not rows or not rows[0]:
                continue
            header_row = rows[0]
            header_index = {header: index for index, header in enumerate(header_row)}

            for row in rows[1:]:
                raw_date = row[header_index["Date"]] if header_index["Date"] < len(row) else ""
                point_date = parse_cell_date(raw_date)
                if point_date is None:
                    continue
                for property_type_slug, definition in PROPERTY_TYPE_COLUMN_MAP.items():
                    if definition["index_header"] not in header_index and definition["benchmark_header"] not in header_index:
                        continue
                    index_raw = row[header_index[definition["index_header"]]] if header_index[definition["index_header"]] < len(row) else ""
                    benchmark_raw = row[header_index[definition["benchmark_header"]]] if header_index[definition["benchmark_header"]] < len(row) else ""
                    index_value = coerce_numeric_cell(index_raw)
                    benchmark_price = coerce_numeric_cell(benchmark_raw)
                    if index_value is None and benchmark_price is None:
                        continue
                    observations.append(
                        {
                            "source": CREA_SOURCE_KEY,
                            "market_key": market_identity["market_key"],
                            "market_name": market_identity["market_name"],
                            "province": market_identity["province"],
                            "property_type_slug": property_type_slug,
                            "property_type_label": definition["label"],
                            "point_date": point_date.isoformat(),
                            "year": point_date.year,
                            "month": point_date.month,
                            "index_value": index_value,
                            "benchmark_price": benchmark_price,
                            "seasonal_adjustment": SEASONAL_ADJUSTMENT_SEASONALLY_ADJUSTED,
                            "source_file_name": source_file_name,
                            "raw_payload": {
                                "workbook_name": workbook_name,
                                "sheet_name": sheet_name,
                                "date_cell": raw_date,
                                "index_header": definition["index_header"],
                                "benchmark_header": definition["benchmark_header"],
                            },
                        }
                    )

    return observations, list(profiles_by_market_key.values()), inspection


def load_crea_workbook_candidates(folder_path: Path) -> list[tuple[str, bytes]]:
    if not folder_path.exists() or not folder_path.is_dir():
        raise RuntimeError(f"Folder not found: {folder_path}")

    candidates: list[tuple[str, bytes]] = []
    for path in sorted(folder_path.iterdir()):
        if path.is_dir():
            continue
        lower_name = path.name.lower()
        if path.name == PRIMARY_WORKBOOK_NAME:
            candidates.append((path.name, path.read_bytes()))
            continue
        if lower_name.endswith(".zip"):
            with zipfile.ZipFile(path) as archive:
                matching_name = next(
                    (name for name in archive.namelist() if Path(name).name == PRIMARY_WORKBOOK_NAME),
                    None,
                )
                if matching_name is not None:
                    candidates.append((f"{path.name}:{matching_name}", archive.read(matching_name)))
    if not candidates:
        raise RuntimeError(
            f"No CREA seasonally adjusted monthly workbook was found in {folder_path}. "
            f"Expected {PRIMARY_WORKBOOK_NAME} directly or inside a zip."
        )
    return candidates


def calculate_change_percent(current_value: float | None, previous_value: float | None) -> float | None:
    if current_value is None or previous_value in {None, 0}:
        return None
    return (current_value / previous_value) - 1.0


def find_closest_observation(
    observations: list[dict[str, Any]],
    target_date: date,
    *,
    tolerance_days: int = 45,
) -> dict[str, Any] | None:
    best_observation: dict[str, Any] | None = None
    best_distance: int | None = None
    for observation in observations:
        point_date_value = observation.get("point_date")
        if isinstance(point_date_value, str):
            point_date = date.fromisoformat(point_date_value)
        elif isinstance(point_date_value, date):
            point_date = point_date_value
        else:
            continue
        distance = abs((point_date - target_date).days)
        if distance > tolerance_days:
            continue
        if best_distance is None or distance < best_distance:
            best_observation = observation
            best_distance = distance
    return best_observation


def build_market_metric_snapshot(
    observations: list[dict[str, Any]],
    *,
    source: str,
    market_key: str,
    market_name: str,
    province: str | None,
    property_type_slug: str,
    property_type_label: str,
) -> dict[str, Any]:
    sorted_observations = sorted(
        [observation for observation in observations if observation.get("index_value") is not None],
        key=lambda item: item["point_date"],
    )
    if not sorted_observations:
        raise RuntimeError(f"No numeric HPI observations available for {market_key} / {property_type_slug}")

    latest = sorted_observations[-1]
    latest_date = date.fromisoformat(latest["point_date"])
    latest_index = float(latest["index_value"])
    latest_benchmark = latest.get("benchmark_price")
    if latest_benchmark is not None:
        latest_benchmark = float(latest_benchmark)

    lookup_notes: list[str] = []

    def lookup_months_back(months_back: int) -> dict[str, Any] | None:
        target_date = latest_date - timedelta(days=round(months_back * 30.4375))
        match = find_closest_observation(sorted_observations, target_date)
        if match is not None:
            matched_date = date.fromisoformat(match["point_date"])
            if matched_date != target_date:
                lookup_notes.append(
                    f"Used {matched_date.isoformat()} as the closest match for the {months_back}-month lookback target {target_date.isoformat()}."
                )
        return match

    one_month = lookup_months_back(1)
    three_month = lookup_months_back(3)
    twelve_month = lookup_months_back(12)
    five_year = lookup_months_back(60)
    ten_year = lookup_months_back(120)

    change_1m = calculate_change_percent(latest_index, float(one_month["index_value"])) if one_month else None
    change_3m = calculate_change_percent(latest_index, float(three_month["index_value"])) if three_month else None
    change_12m = calculate_change_percent(latest_index, float(twelve_month["index_value"])) if twelve_month else None
    appreciation_5y_total = calculate_change_percent(latest_index, float(five_year["index_value"])) if five_year else None
    appreciation_10y_total = calculate_change_percent(latest_index, float(ten_year["index_value"])) if ten_year else None

    appreciation_5y_cagr = None
    if appreciation_5y_total is not None and five_year is not None:
        historical = float(five_year["index_value"])
        appreciation_5y_cagr = ((latest_index / historical) ** (1 / 5.0)) - 1.0 if historical else None

    appreciation_10y_cagr = None
    if appreciation_10y_total is not None and ten_year is not None:
        historical = float(ten_year["index_value"])
        appreciation_10y_cagr = ((latest_index / historical) ** (1 / 10.0)) - 1.0 if historical else None

    change_3m_annualized = None
    if change_3m is not None:
        change_3m_annualized = ((1.0 + change_3m) ** 4) - 1.0

    if appreciation_10y_cagr is not None and appreciation_5y_cagr is not None and change_12m is not None and change_1m is not None:
        data_quality_flag = "high"
    elif appreciation_5y_cagr is not None and change_12m is not None:
        data_quality_flag = "medium"
    else:
        data_quality_flag = "low"

    return {
        "source": source,
        "market_key": market_key,
        "market_name": market_name,
        "province": province,
        "property_type_slug": property_type_slug,
        "property_type_label": property_type_label,
        "latest_date": latest_date.isoformat(),
        "latest_index_value": latest_index,
        "latest_benchmark_price": latest_benchmark,
        "appreciation_5y_total_pct": appreciation_5y_total,
        "appreciation_5y_cagr": appreciation_5y_cagr,
        "appreciation_10y_total_pct": appreciation_10y_total,
        "appreciation_10y_cagr": appreciation_10y_cagr,
        "change_12m_pct": change_12m,
        "change_3m_pct": change_3m,
        "change_3m_annualized_pct": change_3m_annualized,
        "change_1m_pct": change_1m,
        "trend_direction": derive_appreciation_signal(
            {
                "appreciation_5y_cagr": appreciation_5y_cagr,
                "change_12m_pct": change_12m,
                "change_1m_pct": change_1m,
                "data_quality_flag": data_quality_flag,
            }
        ),
        "data_quality_flag": data_quality_flag,
        "observation_count": len(sorted_observations),
        "method_notes": " ".join(lookup_notes) if lookup_notes else None,
    }


def derive_appreciation_signal(metrics: dict[str, Any] | None) -> str:
    if not metrics or metrics.get("data_quality_flag") == "low":
        return "insufficient_data"
    long_term_growth = metrics.get("appreciation_5y_cagr")
    recent_change = metrics.get("change_12m_pct")
    one_month_change = metrics.get("change_1m_pct")

    if isinstance(long_term_growth, (int, float)) and long_term_growth >= 0.06 and isinstance(recent_change, (int, float)) and recent_change >= 0:
        return "strong_long_term_growth"
    if isinstance(recent_change, (int, float)) and recent_change < -0.03:
        return "recent_cooling"
    if isinstance(recent_change, (int, float)) and abs(recent_change) <= 0.03 and isinstance(one_month_change, (int, float)) and abs(one_month_change) <= 0.01:
        return "stable_market"
    return "mixed_market"


def format_signal_label(signal: str) -> str:
    return signal.replace("_", " ").title()
