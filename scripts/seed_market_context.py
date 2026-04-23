from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import SupabaseReadConfig, supabase_post
from market_seed_data import MARKET_METRIC_SERIES, MARKET_METRICS, MARKET_PROFILES
from scraper import load_dotenv


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
        payload=MARKET_METRIC_SERIES,
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
