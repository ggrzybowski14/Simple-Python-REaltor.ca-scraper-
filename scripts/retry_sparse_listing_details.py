from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from playwright.async_api import async_playwright
from playwright_stealth import Stealth

from app import SupabaseReadConfig, supabase_get
from scraper import (
    SupabaseConfig,
    build_context,
    is_listing_fully_enriched,
    load_dotenv,
    scrape_detail_page,
    supabase_request,
    variable_listing_pause,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Retry detail scraping only for sparse active listings in a saved search")
    parser.add_argument("--saved-search-id", type=int, required=True)
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--concurrency", type=int, default=2)
    return parser.parse_args()


def get_config() -> tuple[SupabaseReadConfig, SupabaseConfig]:
    import os

    load_dotenv()
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_KEY")
    if not url or not key:
        raise RuntimeError("SUPABASE_URL and SUPABASE_KEY must be configured")
    clean_url = url.rstrip("/")
    return SupabaseReadConfig(url=clean_url, key=key), SupabaseConfig(url=clean_url, key=key)


def fetch_active_saved_search_listings(config: SupabaseReadConfig, saved_search_id: int) -> list[dict[str, Any]]:
    result = supabase_get(
        config,
        "current_active_saved_search_listings",
        query={
            "saved_search_id": f"eq.{saved_search_id}",
            "select": "listing_id,address,price,bedrooms,bathrooms,url,results_page",
            "order": "listing_id.asc",
        },
    )
    return result if isinstance(result, list) else []


def fetch_listing_rows(config: SupabaseReadConfig, listing_ids: list[int]) -> dict[int, dict[str, Any]]:
    unique_ids = sorted({listing_id for listing_id in listing_ids if isinstance(listing_id, int)})
    if not unique_ids:
        return {}
    result = supabase_get(
        config,
        "listings",
        query={
            "id": f"in.({','.join(str(listing_id) for listing_id in unique_ids)})",
            "select": (
                "id,address,price,bedrooms,bathrooms,listing_description,property_type,building_type,"
                "square_feet,land_size,built_in,annual_taxes,hoa_fees,time_on_realtor,zoning_type,raw_listing"
            ),
        },
    )
    rows = result if isinstance(result, list) else []
    return {row["id"]: row for row in rows if isinstance(row, dict) and isinstance(row.get("id"), int)}


def serialize_listing_for_update(listing: dict[str, Any], scraped_at: str) -> dict[str, Any]:
    return {
        "source": "realtor.ca",
        "source_listing_key": listing["url"],
        "url": listing["url"],
        "address": listing.get("address"),
        "price": listing.get("price"),
        "bedrooms": listing.get("bedrooms"),
        "bathrooms": listing.get("bathrooms"),
        "listing_description": listing.get("listing_description"),
        "property_type": listing.get("property_type"),
        "building_type": listing.get("building_type"),
        "square_feet": listing.get("square_feet"),
        "land_size": listing.get("land_size"),
        "built_in": listing.get("built_in"),
        "annual_taxes": listing.get("annual_taxes"),
        "hoa_fees": listing.get("hoa_fees"),
        "time_on_realtor": listing.get("time_on_realtor"),
        "zoning_type": listing.get("zoning_type"),
        "raw_listing": listing,
        "last_scraped_at": scraped_at,
    }


async def scrape_targets(targets: list[dict[str, Any]], concurrency: int) -> tuple[list[dict[str, Any]], list[str]]:
    async with async_playwright() as playwright:
        context = await build_context(playwright)
        await Stealth().apply_stealth_async(context)
        semaphore = asyncio.Semaphore(max(1, concurrency))
        failures: list[str] = []

        async def worker(summary: dict[str, Any]) -> dict[str, Any] | None:
            async with semaphore:
                await variable_listing_pause()
                try:
                    return await scrape_detail_page(context, summary)
                except Exception:
                    failures.append(summary["url"])
                    return None

        try:
            results = await asyncio.gather(*(worker(target) for target in targets))
        finally:
            await context.close()
        enriched = [item for item in results if item is not None]
        return enriched, failures


def main() -> None:
    args = parse_args()
    read_config, write_config = get_config()
    active = fetch_active_saved_search_listings(read_config, args.saved_search_id)
    rows_by_id = fetch_listing_rows(read_config, [item["listing_id"] for item in active if isinstance(item.get("listing_id"), int)])

    sparse_targets: list[dict[str, Any]] = []
    for listing in active:
        listing_id = listing.get("listing_id")
        existing = rows_by_id.get(listing_id) if isinstance(listing_id, int) else None
        if not existing or not is_listing_fully_enriched(existing):
            sparse_targets.append(listing)

    sparse_targets = sparse_targets[: max(0, args.limit)]
    if not sparse_targets:
        print(f"No sparse active listings found for saved search {args.saved_search_id}.")
        return

    enriched, failures = asyncio.run(scrape_targets(sparse_targets, args.concurrency))
    scraped_at = datetime.now(timezone.utc).isoformat()
    if enriched:
        rows = [serialize_listing_for_update(listing, scraped_at) for listing in enriched]
        supabase_request(
            write_config,
            "listings",
            method="POST",
            query={"on_conflict": "source_listing_key", "select": "id"},
            payload=rows,
            prefer="resolution=merge-duplicates,return=representation",
        )

    print(
        f"Retried {len(sparse_targets)} sparse listing(s) for saved search {args.saved_search_id}; "
        f"updated {len(enriched)}, failed {len(failures)}."
    )
    if failures:
        print("Failed URLs:")
        for url in failures:
            print(url)


if __name__ == "__main__":
    main()
