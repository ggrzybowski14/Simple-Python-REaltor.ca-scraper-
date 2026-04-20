from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scraper import SupabaseConfig, load_dotenv, supabase_request


BACKFILL_FIELDS = [
    "address",
    "price",
    "bedrooms",
    "bathrooms",
    "listing_description",
    "property_type",
    "building_type",
    "square_feet",
    "land_size",
    "built_in",
    "annual_taxes",
    "hoa_fees",
    "time_on_realtor",
    "zoning_type",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backfill enriched listing fields from a scraper output JSON file")
    parser.add_argument("output", help="Path to a scraper output JSON file")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    load_dotenv()

    supabase_url = Path(".env.local").read_text(encoding="utf-8")
    if "SUPABASE_URL=" not in supabase_url:
        raise RuntimeError("SUPABASE_URL is not configured in .env.local")

    import os

    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_KEY")
    if not url or not key:
        raise RuntimeError("SUPABASE_URL and SUPABASE_KEY must be configured")

    payload = json.loads(Path(args.output).read_text(encoding="utf-8"))
    listings = payload.get("listings")
    if not isinstance(listings, list):
        raise RuntimeError("Output JSON does not contain a listings array")

    rows = []
    for listing in listings:
        if not isinstance(listing, dict):
            continue
        url_value = listing.get("url")
        if not isinstance(url_value, str) or not url_value.strip():
            continue
        enriched = {field: listing.get(field) for field in BACKFILL_FIELDS if field in listing}
        if len(enriched) <= 4:
            continue
        enriched["source"] = "realtor.ca"
        enriched["source_listing_key"] = url_value
        enriched["url"] = url_value
        enriched["raw_listing"] = listing
        rows.append(enriched)

    if not rows:
        print("No enriched listing rows found to backfill.")
        return

    config = SupabaseConfig(url=url.rstrip("/"), key=key)
    result = supabase_request(
        config,
        "listings",
        method="POST",
        query={"on_conflict": "source_listing_key", "select": "id,source_listing_key"},
        payload=rows,
        prefer="resolution=merge-duplicates,return=representation",
    )
    count = len(result) if isinstance(result, list) else 0
    print(f"Backfilled {count} listing row(s) from {args.output}")


if __name__ == "__main__":
    main()
