from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import SupabaseReadConfig, supabase_post
from scraper import load_dotenv


MARKET_PROFILES = [
    {
        "market_key": "victoria_bc",
        "market_name": "Victoria",
        "province": "BC",
        "geography_type": "cma",
        "status": "active",
        "notes": "First-pass structured market context seeded from official Statistics Canada pages. CMHC housing fundamentals are read separately from market_reference_data.",
    },
    {
        "market_key": "duncan_bc",
        "market_name": "Duncan",
        "province": "BC",
        "geography_type": "ca",
        "status": "active",
        "notes": "First-pass structured market context seeded from official Statistics Canada pages. CMHC housing fundamentals currently use the explicit Victoria proxy already defined in the app.",
    },
]


MARKET_METRICS = [
    {
        "market_key": "victoria_bc",
        "metric_key": "population",
        "value_numeric": 397237,
        "unit": "people",
        "source_name": "Statistics Canada 2021 Census",
        "source_url": "https://www12.statcan.gc.ca/census-recensement/2021/as-sa/fogs-spg/page.cfm?dguid=2021S0503935&lang=E&topic=1",
        "confidence": "high",
        "notes": "Victoria CMA population in the 2021 Census.",
    },
    {
        "market_key": "victoria_bc",
        "metric_key": "population_growth_percent",
        "value_numeric": 8.0,
        "unit": "percent",
        "source_name": "Statistics Canada 2021 Census",
        "source_url": "https://www12.statcan.gc.ca/census-recensement/2021/as-sa/fogs-spg/page.cfm?dguid=2021S0503935&lang=E&topic=1",
        "confidence": "high",
        "notes": "Population change from 2016 to 2021 for Victoria CMA.",
    },
    {
        "market_key": "victoria_bc",
        "metric_key": "unemployment_rate_percent",
        "value_numeric": 6.9,
        "unit": "percent",
        "source_name": "Statistics Canada 2021 Census",
        "source_url": "https://www12.statcan.gc.ca/census-recensement/2021/as-sa/fogs-spg/page.cfm?dguid=2021S0503935&lang=E&topic=12",
        "confidence": "medium",
        "notes": "Census unemployment rate for the population aged 15+ in Victoria CMA. This is not the same as the monthly Labour Force Survey series.",
    },
    {
        "market_key": "victoria_bc",
        "metric_key": "median_household_income",
        "value_numeric": 75500,
        "unit": "cad",
        "source_name": "Statistics Canada 2021 Census",
        "source_url": "https://www12.statcan.gc.ca/census-recensement/2021/as-sa/fogs-spg/Page.cfm?dguid=2021S0503935&lang=e&topic=5",
        "confidence": "high",
        "notes": "Median after-tax household income in 2020 for Victoria CMA.",
    },
    {
        "market_key": "duncan_bc",
        "metric_key": "population",
        "value_numeric": 47582,
        "unit": "people",
        "source_name": "Statistics Canada 2021 Census",
        "source_url": "https://www12.statcan.gc.ca/census-recensement/2021/as-sa/fogs-spg/Page.cfm?dguid=2021S0504937&lang=E&topic=1",
        "confidence": "high",
        "notes": "Duncan CA population in the 2021 Census.",
    },
    {
        "market_key": "duncan_bc",
        "metric_key": "population_growth_percent",
        "value_numeric": 7.0,
        "unit": "percent",
        "source_name": "Statistics Canada 2021 Census",
        "source_url": "https://www12.statcan.gc.ca/census-recensement/2021/as-sa/fogs-spg/Page.cfm?dguid=2021S0504937&lang=E&topic=1",
        "confidence": "high",
        "notes": "Population change from 2016 to 2021 for Duncan CA.",
    },
    {
        "market_key": "duncan_bc",
        "metric_key": "unemployment_rate_percent",
        "value_numeric": 7.5,
        "unit": "percent",
        "source_name": "Statistics Canada 2021 Census",
        "source_url": "https://www12.statcan.gc.ca/census-recensement/2021/as-sa/fogs-spg/page.cfm?dguid=2021S0504937&lang=E&topic=12",
        "confidence": "medium",
        "notes": "Census unemployment rate for the population aged 15+ in Duncan CA.",
    },
    {
        "market_key": "duncan_bc",
        "metric_key": "median_household_income",
        "value_numeric": 69000,
        "unit": "cad",
        "source_name": "Statistics Canada 2021 Census",
        "source_url": "https://www12.statcan.gc.ca/census-recensement/2021/as-sa/fogs-spg/page.cfm?dguid=2021S0504937&lang=E&topic=5",
        "confidence": "high",
        "notes": "Median after-tax household income in 2020 for Duncan CA.",
    },
]

MARKET_METRIC_SERIES = [
    ("victoria_bc", "2017-01-01", 95.1),
    ("victoria_bc", "2017-04-01", 100.2),
    ("victoria_bc", "2017-07-01", 102.5),
    ("victoria_bc", "2017-10-01", 102.1),
    ("victoria_bc", "2018-01-01", 104.7),
    ("victoria_bc", "2018-04-01", 107.8),
    ("victoria_bc", "2018-07-01", 107.5),
    ("victoria_bc", "2018-10-01", 108.2),
    ("victoria_bc", "2019-01-01", 106.3),
    ("victoria_bc", "2019-04-01", 109.4),
    ("victoria_bc", "2019-07-01", 108.6),
    ("victoria_bc", "2019-10-01", 111.0),
    ("victoria_bc", "2020-01-01", 111.5),
    ("victoria_bc", "2020-04-01", 112.0),
    ("victoria_bc", "2020-07-01", 113.9),
    ("victoria_bc", "2020-10-01", 118.3),
]


def build_series_payload() -> list[dict[str, object]]:
    payload: list[dict[str, object]] = []
    for market_key, point_date, value_numeric in MARKET_METRIC_SERIES:
        payload.append(
            {
                "market_key": market_key,
                "series_key": "residential_property_price_index_total",
                "point_date": point_date,
                "value_numeric": value_numeric,
                "unit": "index_2017_100",
                "source_name": "Statistics Canada RPPI",
                "source_url": "https://www150.statcan.gc.ca/n1/daily-quotidien/210208/cg-b007-png-eng.htm",
                "confidence": "high",
                "notes": "Statistics Canada residential property price index for Victoria, total series.",
            }
        )
    return payload


def main() -> None:
    load_dotenv()
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_KEY")
    if not url or not key:
        raise RuntimeError("SUPABASE_URL and SUPABASE_KEY must be configured")

    config = SupabaseReadConfig(url=url.rstrip("/"), key=key)

    profile_result = supabase_post(
        config,
        "market_profiles",
        query={"on_conflict": "market_key"},
        payload=MARKET_PROFILES,
        prefer="resolution=merge-duplicates,return=representation",
    )
    metric_result = supabase_post(
        config,
        "market_metrics",
        query={"on_conflict": "market_key,metric_key"},
        payload=MARKET_METRICS,
        prefer="resolution=merge-duplicates,return=representation",
    )
    series_result = supabase_post(
        config,
        "market_metric_series",
        query={"on_conflict": "market_key,series_key,point_date"},
        payload=build_series_payload(),
        prefer="resolution=merge-duplicates,return=representation",
    )

    print(
        json.dumps(
            {
                "profiles_upserted": len(profile_result) if isinstance(profile_result, list) else 0,
                "metrics_upserted": len(metric_result) if isinstance(metric_result, list) else 0,
                "series_points_upserted": len(series_result) if isinstance(series_result, list) else 0,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
