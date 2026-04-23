from __future__ import annotations

import re
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from market_data import normalize_market_key


NS = {"a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main", "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships"}
REL_NS = {"rel": "http://schemas.openxmlformats.org/package/2006/relationships"}


@dataclass(frozen=True)
class TableConfig:
    property_type: str
    metric: str
    columns: dict[int | None, str]


TABLE_CONFIGS = {
    "Table 1.1.1": TableConfig("apartment", "vacancy", {1: "I", 2: "N", 3: "S", None: "X"}),
    "Table 1.1.2": TableConfig("apartment", "rent", {1: "I", 2: "N", 3: "S", None: "X"}),
    "Table 2.1.1": TableConfig("townhouse", "vacancy", {1: "I", 2: "N", 3: "S", None: "X"}),
    "Table 2.1.2": TableConfig("townhouse", "rent", {1: "H", 2: "L", 3: "P", None: "T"}),
    "Table 4.1.1": TableConfig("condo_apartment", "vacancy", {None: "D"}),
    "Table 4.1.2": TableConfig("condo_apartment", "rent", {1: "G", 2: "L", 3: "Q"}),
}


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


def parse_numeric(value: str | None) -> float | None:
    if not value:
        return None
    cleaned = value.replace(",", "").strip()
    if not cleaned or cleaned in {"**", "-", "Δ", "++"}:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def clean_market_name(value: str) -> str:
    cleaned = value.replace(" CMA", "").replace(" CA", "").replace(" RDA", "").strip()
    return cleaned


def get_workbook_sheet_map(zf: zipfile.ZipFile) -> dict[str, str]:
    workbook_root = ET.fromstring(zf.read("xl/workbook.xml"))
    rels_root = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
    target_by_rel_id = {
        rel.attrib["Id"]: rel.attrib["Target"].removeprefix("/xl/")
        for rel in rels_root.findall("rel:Relationship", REL_NS)
        if rel.attrib.get("Target")
    }
    sheets: dict[str, str] = {}
    for sheet in workbook_root.findall("a:sheets/a:sheet", NS):
        rel_id = sheet.attrib.get(f"{{{NS['r']}}}id")
        name = sheet.attrib.get("name")
        target = target_by_rel_id.get(rel_id or "")
        if name and target:
            sheet_path = target if target.startswith("worksheets/") else f"worksheets/{Path(target).name}"
            sheets[name] = f"xl/{sheet_path}"
    return sheets


def extract_market_metadata(title: str, province: str, *, fallback_year: str | None = None) -> tuple[str, str, str | None]:
    normalized_title = " ".join((title or "").split())
    market_match = re.search(r" - (?P<market>.+?)(?:\s+\(October\s+\d{4}\))?$", normalized_title)
    if not market_match:
        raise RuntimeError(f"Could not parse market name from CMHC table title: {title}")
    market_name = clean_market_name(market_match.group("market"))
    year_match = re.search(r"(20\d{2})", normalized_title)
    year_value = year_match.group(1) if year_match else fallback_year
    source_date = f"{year_value}-10-01" if year_value else None
    return market_name, normalize_market_key(market_name, province), source_date


def find_market_total_row(rows: list[dict[str, str]], market_name: str) -> dict[str, str] | None:
    candidates = {
        market_name,
        f"{market_name} CMA",
        f"{market_name} CA",
        f"{market_name} (CA)",
        f"{market_name} (CMA)",
    }
    for row in rows:
        label = (row.get("A") or "").strip()
        if label in candidates:
            return row
    return None


def parse_market_rental_workbook(
    workbook_path: str | Path,
    *,
    province: str,
    source_dataset: str,
    source_url: str = "",
) -> list[dict[str, Any]]:
    path = Path(workbook_path)
    if not path.exists():
        raise RuntimeError(f"Workbook not found: {path}")

    with zipfile.ZipFile(path) as zf:
        sheet_map = get_workbook_sheet_map(zf)
        parsed_rows: list[dict[str, Any]] = []
        metrics_by_property_type: dict[str, dict[str, dict[int | None, float | None]]] = {}
        metadata_by_property_type: dict[str, dict[str, Any]] = {}
        fallback_year_match = re.search(r"(20\d{2})", path.stem)
        fallback_year = fallback_year_match.group(1) if fallback_year_match else None

        for sheet_name, config in TABLE_CONFIGS.items():
            sheet_path = sheet_map.get(sheet_name)
            if not sheet_path:
                continue
            rows = parse_sheet_rows(zf, sheet_path)
            title = next((row.get("A") for row in rows if (row.get("A") or "").strip()), "")
            market_name, market_key, source_date = extract_market_metadata(title or "", province, fallback_year=fallback_year)
            total_row = find_market_total_row(rows, market_name)
            if total_row is None:
                continue
            property_metrics = metrics_by_property_type.setdefault(config.property_type, {"rent": {}, "vacancy": {}})
            metadata_by_property_type[config.property_type] = {
                "market_name": market_name,
                "market_key": market_key,
                "source_date": source_date,
            }
            for bedroom_count, column in config.columns.items():
                property_metrics[config.metric][bedroom_count] = parse_numeric(total_row.get(column))

        for property_type, property_metrics in metrics_by_property_type.items():
            metadata = metadata_by_property_type[property_type]
            rent_by_bedroom = property_metrics.get("rent", {})
            vacancy_by_bedroom = property_metrics.get("vacancy", {})
            bedroom_counts: set[int | None] = set(rent_by_bedroom) | set(vacancy_by_bedroom)
            for bedroom_count in sorted(bedroom_counts, key=lambda value: (-1 if value is None else value)):
                average_rent = rent_by_bedroom.get(bedroom_count)
                vacancy_rate = vacancy_by_bedroom.get(bedroom_count)
                if vacancy_rate is None:
                    vacancy_rate = vacancy_by_bedroom.get(None)
                if average_rent is None and vacancy_rate is None:
                    continue
                parsed_rows.append(
                    {
                        "source": "cmhc",
                        "source_dataset": source_dataset,
                        "market_name": metadata["market_name"],
                        "province": province,
                        "market_key": metadata["market_key"],
                        "geography_type": "market",
                        "property_type": property_type,
                        "bedroom_count": bedroom_count,
                        "average_rent_monthly": average_rent,
                        "vacancy_rate_percent": vacancy_rate,
                        "source_url": source_url or None,
                        "source_date": metadata["source_date"],
                        "raw_payload": {
                            "workbook_name": path.name,
                            "property_type": property_type,
                            "metric_snapshot": {
                                "rent": rent_by_bedroom,
                                "vacancy": vacancy_by_bedroom,
                            },
                        },
                    }
                )

    return parsed_rows
