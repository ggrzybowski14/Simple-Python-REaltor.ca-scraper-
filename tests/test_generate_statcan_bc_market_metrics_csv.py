from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "generate_statcan_bc_market_metrics_csv.py"
SPEC = importlib.util.spec_from_file_location("generate_statcan_bc_market_metrics_csv", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
generator = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = generator
SPEC.loader.exec_module(generator)


def test_normalize_name_handles_statcan_csd_labels() -> None:
    assert generator.normalize_name("Sidney, Town (T)") == "sidney"
    assert generator.normalize_name("Abbotsford - Mission") == "abbotsford mission"
    assert generator.normalize_name("Fort St. John") == "fort saint john"


def test_build_output_rows_matches_targets_from_metric_sources() -> None:
    targets = [
        {"market_key": "sidney_bc", "market_name": "Sidney", "province": "BC"},
        {"market_key": "vancouver_bc", "market_name": "Vancouver", "province": "BC"},
    ]
    cma_ca_metrics = {
        "vancouver": {
            "geo_name": "Vancouver",
            "geo_level": "Census metropolitan area",
            "population": "2642825",
            "population_growth_percent": "7.3",
            "unemployment_rate_percent": "8.6",
            "median_household_income": "79500",
        }
    }
    csd_metrics = {
        "sidney": {
            "geo_name": "Sidney, Town (T)",
            "geo_level": "Census subdivision",
            "population": "12318",
            "population_growth_percent": "5.5",
            "unemployment_rate_percent": "4.7",
            "median_household_income": "68500",
        }
    }

    rows = generator.build_output_rows(targets, cma_ca_metrics=cma_ca_metrics, csd_metrics=csd_metrics)

    assert len(rows) == 2
    sidney = next(row for row in rows if row["market_key"] == "sidney_bc")
    assert sidney["geography_type"] == "csd"
    assert sidney["population"] == "12318"
    vancouver = next(row for row in rows if row["market_key"] == "vancouver_bc")
    assert vancouver["geography_type"] == "cma"
    assert vancouver["median_household_income"] == "79500"
