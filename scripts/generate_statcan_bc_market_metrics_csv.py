from __future__ import annotations

import csv
import io
import json
import os
import re
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from urllib import error, request

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


CMA_CA_URL = (
    "https://www12.statcan.gc.ca/census-recensement/2021/dp-pd/prof/details/"
    "download-telecharger/comp/GetFile.cfm?Lang=E&FILETYPE=CSV&GEONO=002"
)
BC_CSD_URL = (
    "https://www12.statcan.gc.ca/census-recensement/2021/dp-pd/prof/details/"
    "download-telecharger/comp/GetFile.cfm?Lang=E&FILETYPE=CSV&GEONO=025"
)
DEFAULT_OUTPUT_PATH = ROOT / "data" / "statcan_bc_market_metrics.csv"

TARGET_CHARACTERISTICS = {
    "Population, 2021": "population",
    "Population percentage change, 2016 to 2021": "population_growth_percent",
    "Unemployment rate": "unemployment_rate_percent",
    "Median after-tax income of household in 2020 ($)": "median_household_income",
}

PROFILE_NOTES_BY_GEOGRAPHY = {
    "cma": "Bulk-generated from official Statistics Canada 2021 Census Profile data. CMHC housing fundamentals are read separately from market_reference_data.",
    "ca": "Bulk-generated from official Statistics Canada 2021 Census Profile data. CMHC housing fundamentals are read separately from market_reference_data.",
    "csd": "Bulk-generated from official Statistics Canada 2021 Census Profile data. CMHC housing fundamentals are read separately from market_reference_data.",
    "market": "Bulk-generated from official Statistics Canada 2021 Census Profile data. CMHC housing fundamentals are read separately from market_reference_data.",
}

NOTES_BY_METRIC = {
    "population": "{label} population in the 2021 Census.",
    "population_growth_percent": "Population change from 2016 to 2021 for {label}.",
    "unemployment_rate_percent": "Census unemployment rate for the population aged 15+ in {label}.",
    "median_household_income": "Median after-tax household income in 2020 for {label}.",
}


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


def supabase_request(config: SupabaseConfig, path: str) -> Any:
    endpoint = f"{config.url}/rest/v1/{path}"
    req = request.Request(
        endpoint,
        headers={
            "apikey": config.key,
            "Authorization": f"Bearer {config.key}",
            "Accept": "application/json",
        },
    )
    try:
        with request.urlopen(req, timeout=30) as response:
            raw = response.read().decode("utf-8", errors="replace")
            return json.loads(raw) if raw else None
    except error.HTTPError as exc:
        details = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Supabase request failed with status {exc.code}: {details}") from exc
    except error.URLError as exc:
        raise RuntimeError(f"Supabase request failed: {exc.reason}") from exc


def normalize_name(value: str) -> str:
    cleaned = value.strip().lower()
    cleaned = cleaned.replace("st. ", "saint ").replace("st ", "saint ")
    cleaned = re.sub(r",.*$", "", cleaned)
    cleaned = re.sub(r"\s*-\s*", " ", cleaned)
    cleaned = re.sub(r"\s*\([^)]*\)", "", cleaned)
    cleaned = re.sub(r"[^a-z0-9]+", " ", cleaned)
    return cleaned.strip()


def fetch_bc_market_targets(config: SupabaseConfig) -> list[dict[str, str]]:
    rows = supabase_request(
        config,
        "market_reference_data?select=market_key,market_name,province&province=eq.BC&order=market_name.asc",
    )
    unique: dict[str, dict[str, str]] = {}
    for row in rows if isinstance(rows, list) else []:
        market_key = row.get("market_key")
        market_name = row.get("market_name")
        if not market_key or not market_name:
            continue
        if market_key.startswith("british_columbia_") or "_zone_" in market_key:
            continue
        unique.setdefault(
            market_key,
            {
                "market_key": market_key,
                "market_name": market_name,
                "province": row.get("province") or "BC",
            },
        )
    return list(unique.values())


def download_zip(url: str, destination: Path) -> None:
    with request.urlopen(url, timeout=60) as response:
        destination.write_bytes(response.read())


def extract_metrics_from_zip(zip_path: Path) -> dict[str, dict[str, str]]:
    metrics_by_geo: dict[str, dict[str, str]] = {}
    with zipfile.ZipFile(zip_path) as zf:
        csv_name = zf.namelist()[0]
        with zf.open(csv_name) as raw_file:
            text = io.TextIOWrapper(raw_file, encoding="latin-1", newline="")
            reader = csv.DictReader(text)
            for row in reader:
                characteristic = (row.get("CHARACTERISTIC_NAME") or "").strip()
                metric_field = TARGET_CHARACTERISTICS.get(characteristic)
                if metric_field is None:
                    continue
                geo_name = (row.get("GEO_NAME") or "").strip()
                normalized = normalize_name(geo_name)
                if not normalized:
                    continue
                bucket = metrics_by_geo.setdefault(
                    normalized,
                    {
                        "geo_name": geo_name,
                        "geo_level": (row.get("GEO_LEVEL") or "").strip(),
                    },
                )
                bucket[metric_field] = (row.get("C1_COUNT_TOTAL") or "").strip()
    return metrics_by_geo


def derive_geography_type(geo_level: str) -> str:
    normalized = geo_level.strip().lower()
    if normalized == "census metropolitan area":
        return "cma"
    if normalized == "census agglomeration":
        return "ca"
    if normalized == "census subdivision":
        return "csd"
    return "market"


def build_output_rows(
    market_targets: list[dict[str, str]],
    *,
    cma_ca_metrics: dict[str, dict[str, str]],
    csd_metrics: dict[str, dict[str, str]],
) -> list[dict[str, str]]:
    output_rows: list[dict[str, str]] = []
    for target in market_targets:
        normalized = normalize_name(target["market_name"])
        metric_source = cma_ca_metrics.get(normalized) or csd_metrics.get(normalized)
        if metric_source is None:
            continue
        geography_type = derive_geography_type(metric_source.get("geo_level") or "")
        label = metric_source.get("geo_name") or target["market_name"]
        output_rows.append(
            {
                "market_key": target["market_key"],
                "market_name": target["market_name"],
                "province": target["province"],
                "geography_type": geography_type,
                "status": "active",
                "source_name": "Statistics Canada 2021 Census",
                "source_url": (
                    "https://www12.statcan.gc.ca/census-recensement/2021/dp-pd/prof/details/"
                    "download-telecharger.cfm?Lang=E"
                ),
                "source_date": "",
                "confidence": "high",
                "profile_notes": PROFILE_NOTES_BY_GEOGRAPHY.get(geography_type, PROFILE_NOTES_BY_GEOGRAPHY["market"]),
                "population": metric_source.get("population", ""),
                "population_notes": NOTES_BY_METRIC["population"].format(label=label),
                "population_growth_percent": metric_source.get("population_growth_percent", ""),
                "population_growth_percent_notes": NOTES_BY_METRIC["population_growth_percent"].format(label=label),
                "unemployment_rate_percent": metric_source.get("unemployment_rate_percent", ""),
                "unemployment_rate_percent_notes": NOTES_BY_METRIC["unemployment_rate_percent"].format(label=label),
                "median_household_income": metric_source.get("median_household_income", ""),
                "median_household_income_notes": NOTES_BY_METRIC["median_household_income"].format(label=label),
            }
        )
    return sorted(output_rows, key=lambda row: row["market_name"].lower())


def write_csv(rows: list[dict[str, str]], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "market_key",
        "market_name",
        "province",
        "geography_type",
        "status",
        "source_name",
        "source_url",
        "source_date",
        "confidence",
        "profile_notes",
        "population",
        "population_notes",
        "population_growth_percent",
        "population_growth_percent_notes",
        "unemployment_rate_percent",
        "unemployment_rate_percent_notes",
        "median_household_income",
        "median_household_income_notes",
    ]
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    load_dotenv()
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_KEY")
    if not url or not key:
        raise RuntimeError("SUPABASE_URL and SUPABASE_KEY must be configured")

    config = SupabaseConfig(url=url.rstrip("/"), key=key)
    targets = fetch_bc_market_targets(config)
    if not targets:
        raise RuntimeError("No BC market targets found in market_reference_data")

    with TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        cma_ca_zip = tmp_path / "statcan_cma_ca.zip"
        bc_csd_zip = tmp_path / "statcan_bc_csd.zip"
        download_zip(CMA_CA_URL, cma_ca_zip)
        download_zip(BC_CSD_URL, bc_csd_zip)
        cma_ca_metrics = extract_metrics_from_zip(cma_ca_zip)
        csd_metrics = extract_metrics_from_zip(bc_csd_zip)

    rows = build_output_rows(targets, cma_ca_metrics=cma_ca_metrics, csd_metrics=csd_metrics)
    if not rows:
        raise RuntimeError("No matching BC market rows were generated from the StatCan files")

    write_csv(rows, DEFAULT_OUTPUT_PATH)
    print(
        json.dumps(
            {
                "output_csv": str(DEFAULT_OUTPUT_PATH),
                "target_markets": len(targets),
                "rows_written": len(rows),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
