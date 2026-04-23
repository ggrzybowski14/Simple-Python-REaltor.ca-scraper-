from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "import_statcan_market_metrics.py"
SPEC = importlib.util.spec_from_file_location("import_statcan_market_metrics", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
importer = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = importer
SPEC.loader.exec_module(importer)


def test_build_market_profiles_deduplicates_market_key() -> None:
    rows = [
        {
            "market_key": "vancouver_bc",
            "market_name": "Vancouver",
            "province": "BC",
            "geography_type": "cma",
            "status": "active",
            "profile_notes": "Profile note",
        },
        {
            "market_key": "vancouver_bc",
            "market_name": "Vancouver",
            "province": "BC",
            "geography_type": "cma",
            "status": "active",
            "profile_notes": "Profile note",
        },
    ]

    profiles = importer.build_market_profiles(rows)

    assert len(profiles) == 1
    assert profiles[0]["market_key"] == "vancouver_bc"
    assert profiles[0]["market_name"] == "Vancouver"


def test_build_market_metrics_creates_four_metric_rows() -> None:
    rows = [
        {
            "market_key": "sidney_bc",
            "source_name": "Statistics Canada 2021 Census",
            "source_url": "https://example.com",
            "confidence": "high",
            "population": "12,318",
            "population_notes": "Population note",
            "population_growth_percent": "5.5",
            "population_growth_percent_notes": "Growth note",
            "unemployment_rate_percent": "4.7",
            "unemployment_rate_percent_notes": "Unemployment note",
            "median_household_income": "68,500",
            "median_household_income_notes": "Income note",
        }
    ]

    metrics = importer.build_market_metrics(rows, default_source_name="Statistics Canada 2021 Census")

    assert len(metrics) == 4
    assert {metric["metric_key"] for metric in metrics} == {
        "population",
        "population_growth_percent",
        "unemployment_rate_percent",
        "median_household_income",
    }
    population_metric = next(metric for metric in metrics if metric["metric_key"] == "population")
    assert population_metric["value_numeric"] == 12318.0
    assert population_metric["notes"] == "Population note"
