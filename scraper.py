from __future__ import annotations

import argparse
import asyncio
import json
import logging
import random
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from playwright.async_api import BrowserContext, Error, Page, TimeoutError, async_playwright
from playwright_stealth import Stealth


START_URL = (
    "https://www.realtor.ca/map#ZoomLevel=13&Center=48.427549%2C-123.358326"
    "&LatitudeMax=48.45459&LongitudeMax=-123.25868&LatitudeMin=48.40049"
    "&LongitudeMin=-123.45798&Sort=6-D&PGeoIds=g30_c2878bj4&GeoName=Victoria%2C%20BC"
    "&PropertyTypeGroupID=1&TransactionTypeId=2&PropertySearchTypeId=0&Currency=CAD"
)
DEFAULT_MAX_PAGES = 10
DEFAULT_MAX_LISTINGS = 100
DEFAULT_DETAIL_LIMIT = 25
DEFAULT_DETAIL_CONCURRENCY = 2
ARTIFACTS_DIR = Path("artifacts")
OUTPUTS_DIR = Path("outputs")
TOP_FILTER_WAIT_MS = 3500
PROPERTY_TYPE_OPTIONS = {
    "house": {"value": "1", "label": "House"},
    "apartment": {"value": "17", "label": "Apartment"},
    "condo": {"value": "17", "label": "Apartment"},
}


@dataclass
class SearchCriteria:
    location: str
    beds_min: int | None = None
    property_type: str | None = None
    min_price: int | None = None
    max_price: int | None = None


@dataclass
class ScrapeLimits:
    max_pages: int = DEFAULT_MAX_PAGES
    max_listings: int = DEFAULT_MAX_LISTINGS
    detail_limit: int = DEFAULT_DETAIL_LIMIT
    detail_concurrency: int = DEFAULT_DETAIL_CONCURRENCY


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
        datefmt="%H:%M:%S",
    )


async def human_pause(min_seconds: float = 0.6, max_seconds: float = 1.6) -> None:
    await asyncio.sleep(random.uniform(min_seconds, max_seconds))


async def move_mouse_like_human(page: Page) -> None:
    viewport = page.viewport_size or {"width": 1440, "height": 960}
    points = [
        (random.randint(80, 260), random.randint(120, 220)),
        (random.randint(260, 520), random.randint(200, 380)),
        (random.randint(420, viewport["width"] - 160), random.randint(220, viewport["height"] - 160)),
    ]
    for x, y in points:
        await page.mouse.move(x, y, steps=random.randint(12, 28))
        await human_pause(0.15, 0.45)


async def variable_listing_pause() -> None:
    if random.random() < 0.2:
        await human_pause(2.5, 4.5)
    else:
        await human_pause(0.9, 2.0)


async def save_failure_artifacts(page: Page, label: str) -> None:
    ARTIFACTS_DIR.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    png_path = ARTIFACTS_DIR / f"{timestamp}_{label}.png"
    html_path = ARTIFACTS_DIR / f"{timestamp}_{label}.html"
    try:
        await page.screenshot(path=str(png_path), full_page=True)
        html_path.write_text(await page.content(), encoding="utf-8")
        logging.info("Saved failure artifacts: %s and %s", png_path, html_path)
    except Exception as artifact_error:
        logging.warning("Failed to save failure artifacts: %s", artifact_error)


def save_results(payload: Any) -> Path:
    OUTPUTS_DIR.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = OUTPUTS_DIR / f"{timestamp}_listings.json"
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    logging.info("Saved results to %s", output_path)
    return output_path


async def dismiss_popups_if_present(page: Page) -> None:
    patterns = [
        "Accept",
        "I agree",
        "Got it",
        "Close",
    ]
    for pattern in patterns:
        try:
            await page.get_by_role("button", name=re.compile(pattern, re.I)).click(timeout=2500)
            logging.info("Clicked popup button matching '%s'", pattern)
            await human_pause(0.7, 1.4)
            return
        except TimeoutError:
            continue
        except Error as popup_error:
            logging.info("Popup click skipped for '%s': %s", pattern, popup_error)
            continue


async def build_context(playwright) -> BrowserContext:
    logging.info("Launching visible Chromium browser")
    browser = await playwright.chromium.launch(
        headless=False,
        slow_mo=140,
        args=["--disable-blink-features=AutomationControlled"],
    )
    context = await browser.new_context(
        viewport={"width": 1440, "height": 960},
        locale="en-CA",
        timezone_id="America/Vancouver",
        user_agent=(
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/123.0.0.0 Safari/537.36"
        ),
    )
    context.set_default_timeout(15000)
    return context


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Realtor.ca Playwright scraper")
    parser.add_argument("--location", help="City or location, for example 'Victoria'")
    parser.add_argument("--beds-min", type=int, help="Minimum number of bedrooms")
    parser.add_argument("--property-type", help="Supported values: house, apartment, condo")
    parser.add_argument("--min-price", type=int, help="Minimum price in whole dollars")
    parser.add_argument("--max-price", type=int, help="Maximum price in whole dollars")
    parser.add_argument("--max-pages", type=int, default=DEFAULT_MAX_PAGES)
    parser.add_argument("--max-listings", type=int, default=DEFAULT_MAX_LISTINGS)
    parser.add_argument("--detail-limit", type=int, default=DEFAULT_DETAIL_LIMIT)
    parser.add_argument("--detail-concurrency", type=int, default=DEFAULT_DETAIL_CONCURRENCY)
    return parser.parse_args()


def normalize_property_type(value: str | None) -> str | None:
    if not value:
        return None
    normalized = value.strip().lower()
    if normalized not in PROPERTY_TYPE_OPTIONS:
        supported = ", ".join(sorted(PROPERTY_TYPE_OPTIONS))
        raise ValueError(f"Unsupported property type '{value}'. Supported values: {supported}")
    return normalized


def prompt_optional_int(label: str, current: int | None = None, *, prompt_enabled: bool = True) -> int | None:
    if current is not None:
        return current
    if not prompt_enabled:
        return None
    raw = input(f"{label} (press Enter to skip): ").strip()
    if not raw:
        return None
    return int(raw.replace(",", ""))


def collect_search_criteria(args: argparse.Namespace) -> SearchCriteria:
    prompt_enabled = not any(getattr(args, field) is not None for field in vars(args))

    location = (args.location or input("Location: ").strip()).strip()
    if not location:
        raise ValueError("Location is required")

    property_type = args.property_type
    if property_type is None and prompt_enabled:
        property_type = input("Property type [house/apartment/condo] (press Enter to skip): ").strip() or None

    return SearchCriteria(
        location=location,
        beds_min=prompt_optional_int("Minimum beds", args.beds_min, prompt_enabled=prompt_enabled),
        property_type=normalize_property_type(property_type),
        min_price=prompt_optional_int("Minimum price", args.min_price, prompt_enabled=prompt_enabled),
        max_price=prompt_optional_int("Maximum price", args.max_price, prompt_enabled=prompt_enabled),
    )


def collect_scrape_limits(args: argparse.Namespace) -> ScrapeLimits:
    if args.max_pages < 1:
        raise ValueError("--max-pages must be at least 1")
    if args.max_listings < 1:
        raise ValueError("--max-listings must be at least 1")
    if args.detail_limit < 0:
        raise ValueError("--detail-limit cannot be negative")
    if args.detail_concurrency < 1:
        raise ValueError("--detail-concurrency must be at least 1")
    return ScrapeLimits(
        max_pages=args.max_pages,
        max_listings=args.max_listings,
        detail_limit=args.detail_limit,
        detail_concurrency=args.detail_concurrency,
    )


def normalize_spaces(value: str | None) -> str | None:
    if not value:
        return None
    compact = re.sub(r"\s+", " ", value).strip()
    return compact or None


def extract_numeric_feature(text: str, labels: list[str]) -> int | None:
    for label in labels:
        match = re.search(rf"(\d+)\s*{label}\b", text, re.I)
        if match:
            return int(match.group(1))
    return None


def format_price_option(value: int) -> str:
    return f"{value:,}"


def format_beds_option(value: int) -> str:
    return f"{value}+"


async def wait_for_listings(page: Page) -> None:
    cards = page.locator("div.cardCon, article.cardCon, .cardCon")
    await cards.first.wait_for(state="visible", timeout=20000)


async def wait_for_results_refresh(page: Page, previous_url: str | None = None) -> None:
    if previous_url:
        try:
            await page.wait_for_function(
                "previous => window.location.href !== previous",
                arg=previous_url,
                timeout=15000,
            )
        except TimeoutError:
            logging.info("URL did not change after filter update; relying on listing wait instead")
    await human_pause(1.0, 1.8)
    await wait_for_listings(page)


async def extract_results_count(page: Page) -> int | None:
    body_text = await page.locator("body").inner_text()
    match = re.search(r"Results:\s*([\d,]+)\s+Listings", body_text, re.I)
    if match:
        return int(match.group(1).replace(",", ""))
    return None


async def extract_page_indicator(page: Page) -> str | None:
    body_text = await page.locator("body").inner_text()
    match = re.search(r"\b(\d+)\s+of\s+(\d+\+?)\b", body_text)
    if match:
        return f"{match.group(1)} of {match.group(2)}"
    return None


async def extract_rendered_property_type(page: Page) -> str | None:
    selectors = [
        "#ddlBuildingType-container",
        "#ddlPropertyTypeRes-container",
    ]
    for selector in selectors:
        locator = page.locator(selector)
        if await locator.count():
            text = normalize_spaces(await locator.first.text_content())
            if text:
                return text
    return None


async def extract_rendered_location(page: Page) -> str | None:
    selectors = [
        "#locationSearchFilterText",
        "input[placeholder='City, Neighbourhood, Address or MLS® number']",
    ]
    for selector in selectors:
        locator = page.locator(selector)
        if await locator.count():
            if selector.startswith("input"):
                value = normalize_spaces(await locator.first.input_value())
                if value:
                    return value
            else:
                text = normalize_spaces(await locator.first.text_content())
                if text:
                    return text
    return None


async def log_results_snapshot(page: Page, label: str) -> None:
    results_count = await extract_results_count(page)
    page_indicator = await extract_page_indicator(page)
    rendered_property_type = await extract_rendered_property_type(page)
    rendered_location = await extract_rendered_location(page)
    visible_cards = await page.locator("div.cardCon, article.cardCon, .cardCon").count()
    logging.info(
        "%s | results_count=%s | page_indicator=%s | rendered_location=%s | rendered_property_type=%s | visible_cards=%s | url=%s",
        label,
        results_count if results_count is not None else "unknown",
        page_indicator or "unknown",
        rendered_location or "unknown",
        rendered_property_type or "unknown",
        visible_cards,
        page.url,
    )


async def set_select_value(page: Page, selector: str, *, value: str | None = None, label: str | None = None) -> None:
    locator = page.locator(selector)
    await locator.select_option(value=value, label=label, force=True)
    await locator.evaluate("el => el.dispatchEvent(new Event('change', { bubbles: true }))")


async def apply_location(page: Page, location: str) -> None:
    logging.info("Applying location filter: %s", location)
    search_box = page.locator("input[placeholder='City, Neighbourhood, Address or MLS® number']").first
    await search_box.click()
    await human_pause(0.4, 0.9)
    await search_box.fill(location)
    await human_pause(0.8, 1.4)
    previous_url = page.url
    await page.locator("button[aria-label='Search']").click()
    await wait_for_results_refresh(page, previous_url)


async def apply_top_select_filter(page: Page, selector: str, *, label: str) -> None:
    previous_url = page.url
    await set_select_value(page, selector, label=label)
    await page.wait_for_timeout(TOP_FILTER_WAIT_MS)
    await wait_for_results_refresh(page, previous_url)


async def apply_property_type(page: Page, property_type: str) -> None:
    option = PROPERTY_TYPE_OPTIONS[property_type]
    logging.info("Applying property type filter: %s", option["label"])
    await page.locator("button:has-text('Filters')").click()
    await human_pause(1.0, 1.6)
    previous_url = page.url
    await set_select_value(page, "#ddlBuildingType", value=option["value"])
    await human_pause(0.8, 1.4)
    await page.locator("#mapMoreFiltersSearchBtn").click()
    await page.wait_for_timeout(4000)
    await wait_for_results_refresh(page, previous_url)


async def apply_search_criteria(page: Page, criteria: SearchCriteria) -> None:
    await apply_location(page, criteria.location)

    if criteria.min_price is not None:
        logging.info("Applying minimum price filter: %s", criteria.min_price)
        await apply_top_select_filter(page, "#ddlMinPriceTop", label=format_price_option(criteria.min_price))

    if criteria.max_price is not None:
        logging.info("Applying maximum price filter: %s", criteria.max_price)
        await apply_top_select_filter(page, "#ddlMaxPriceTop", label=format_price_option(criteria.max_price))

    if criteria.beds_min is not None:
        logging.info("Applying minimum beds filter: %s+", criteria.beds_min)
        await apply_top_select_filter(page, "#ddlBedsTop", label=format_beds_option(criteria.beds_min))

    if criteria.property_type is not None:
        await apply_property_type(page, criteria.property_type)

    await log_results_snapshot(page, "After filters")


async def scrape_card(card) -> dict[str, Any] | None:
    link = card.locator("a[href*='/real-estate/'], a[href*='/real-estate-properties/']").first
    href = await link.get_attribute("href")
    if not href:
        return None

    text_blob = " ".join(part.strip() for part in await card.all_text_contents() if part.strip())
    price_match = re.search(r"\$[\d,]+", text_blob)
    address_match = re.search(
        r"\$\d[\d,]*\s+(?:true|false\s+)?(.+?),\s*British Columbia",
        text_blob,
        re.I,
    )

    listing = {
        "price": price_match.group(0) if price_match else None,
        "address": normalize_spaces(
            f"{address_match.group(1)}, British Columbia" if address_match else await link.text_content()
        ),
        "bedrooms": extract_numeric_feature(text_blob, ["bedroom", "bedrooms", "bed", "beds", "bd"]),
        "bathrooms": extract_numeric_feature(text_blob, ["bathroom", "bathrooms", "bath", "baths"]),
        "url": f"https://www.realtor.ca{href}" if href.startswith("/") else href,
    }

    if not listing["price"]:
        return None
    return listing


async def extract_labeled_value(page: Page, label: str) -> str | None:
    try:
        locator = page.locator(f"text=/{re.escape(label)}/i").first
        await locator.wait_for(timeout=5000)
        container = locator.locator("xpath=ancestor::*[self::div or self::section][1]")
        container_text = await container.text_content()
        if container_text:
            compact = normalize_spaces(container_text)
            if compact and compact.lower().startswith(label.lower()):
                value = compact[len(label):].strip(" :")
                return value or None
    except Exception:
        return None
    return None


async def scrape_detail_page(context: BrowserContext, listing: dict[str, Any]) -> dict[str, Any]:
    detail_page = await context.new_page()
    try:
        logging.info("Opening detail page: %s", listing["url"])
        await detail_page.goto(listing["url"], wait_until="domcontentloaded")
        await human_pause(2.0, 3.0)
        await dismiss_popups_if_present(detail_page)
        await move_mouse_like_human(detail_page)
        await detail_page.mouse.wheel(0, random.randint(400, 900))
        await human_pause(1.0, 1.8)

        await detail_page.locator("text=/MLS.*Number|Property Summary|Listing Description/i").first.wait_for(
            timeout=15000
        )
        logging.info("Detail page loaded for %s", listing["url"])

        detail_text = normalize_spaces(await detail_page.locator("body").text_content()) or ""
        land_size = await extract_labeled_value(detail_page, "Land Size")
        built_in = await extract_labeled_value(detail_page, "Built in")

        if not land_size:
            match = re.search(r"Land Size\s+(.+?)(?=\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\s|$)", detail_text)
            if match:
                land_size = normalize_spaces(match.group(1))
        if not built_in:
            match = re.search(r"Built in\s+(\d{4})", detail_text, re.I)
            if match:
                built_in = match.group(1)

        merged = dict(listing)
        merged["land_size"] = land_size
        merged["built_in"] = built_in
        return merged
    except Exception as error:
        logging.error("Detail scrape failed for %s: %s", listing["url"], error)
        await save_failure_artifacts(detail_page, "detail_failure")
        raise
    finally:
        await detail_page.close()


async def collect_listing_summaries_from_current_page(page: Page, limit: int) -> list[dict[str, Any]]:
    cards = page.locator("div:has(a[href*='/real-estate/']), article:has(a[href*='/real-estate/'])")
    listings_by_url: dict[str, dict[str, Any]] = {}
    card_count = await cards.count()
    logging.info("Scanning %s visible result cards on current page", card_count)

    for idx in range(card_count):
        card = cards.nth(idx)
        listing = await scrape_card(card)
        if not listing:
            continue
        listings_by_url.setdefault(listing["url"], listing)
        if len(listings_by_url) >= limit:
            break

    return list(listings_by_url.values())[:limit]


async def go_to_next_results_page(page: Page, previous_first_url: str) -> bool:
    next_link = page.locator("a[aria-label='Go to the next page']").first
    if await next_link.count() == 0:
        logging.warning("Next-page control was not found")
        return False

    current_class = await next_link.get_attribute("class") or ""
    if "disabled" in current_class.lower():
        logging.info("Next-page control appears disabled")
        return False

    logging.info("Navigating to the next results page")
    await next_link.click()
    await human_pause(1.2, 2.2)

    try:
        await page.wait_for_function(
            """
            previousUrl => {
                const links = Array.from(document.querySelectorAll("a[href*='/real-estate/'], a[href*='/real-estate-properties/']"));
                return links.some(link => link.getAttribute('href') && !link.getAttribute('href').includes(previousUrl.split('/').pop()));
            }
            """,
            arg=previous_first_url,
            timeout=15000,
        )
    except TimeoutError:
        logging.warning("Timed out waiting for next results page to change")
        return False

    await log_results_snapshot(page, "After page transition")
    return True


async def collect_listing_summaries_across_pages(page: Page, page_limit: int, total_limit: int) -> list[dict[str, Any]]:
    logging.info(
        "Collecting up to %s listing(s) across %s results page(s)",
        total_limit,
        page_limit,
    )
    collected: list[dict[str, Any]] = []
    seen_urls: set[str] = set()

    for page_index in range(1, page_limit + 1):
        remaining = total_limit - len(collected)
        if remaining <= 0:
            break

        await log_results_snapshot(page, f"Before scanning results page {page_index}")
        page_listings = await collect_listing_summaries_from_current_page(page, remaining)
        page_listings = [listing for listing in page_listings if listing["url"] not in seen_urls]

        if not page_listings:
            logging.warning("No new listings found on results page %s", page_index)
            break

        for listing in page_listings:
            listing["results_page"] = page_index
            collected.append(listing)
            seen_urls.add(listing["url"])

        logging.info(
            "Collected %s listing(s) from results page %s",
            len(page_listings),
            page_index,
        )

        if len(collected) >= total_limit or page_index == page_limit:
            break

        first_url = page_listings[0]["url"]
        if not await go_to_next_results_page(page, first_url):
            break

    return collected


async def enrich_detail_worker(
    context: BrowserContext,
    listing: dict[str, Any],
    semaphore: asyncio.Semaphore,
) -> tuple[dict[str, Any] | None, str | None]:
    async with semaphore:
        await variable_listing_pause()
        try:
            return await scrape_detail_page(context, listing), None
        except Exception:
            return None, listing["url"]


async def enrich_listings(
    context: BrowserContext,
    listings: list[dict[str, Any]],
    detail_limit: int,
    detail_concurrency: int,
) -> tuple[list[dict[str, Any]], list[str], int, int]:
    listings_to_enrich = listings[:detail_limit] if detail_limit else []
    semaphore = asyncio.Semaphore(detail_concurrency)

    async def run_batch(targets: list[dict[str, Any]], concurrency: int) -> tuple[list[dict[str, Any]], list[str]]:
        local_semaphore = asyncio.Semaphore(concurrency)
        tasks = [
            asyncio.create_task(enrich_detail_worker(context, listing, local_semaphore))
            for listing in targets
        ]
        batch_results = await asyncio.gather(*tasks)
        enriched = [item for item, failed in batch_results if item is not None]
        failed_urls = [failed for item, failed in batch_results if failed is not None]
        return enriched, failed_urls

    enriched_listings, failed_urls = await run_batch(listings_to_enrich, detail_concurrency)

    if failed_urls and detail_concurrency > 1 and len(failed_urls) >= 3:
        logging.warning(
            "Detail failures reached %s with concurrency=%s; retrying failed detail pages sequentially",
            len(failed_urls),
            detail_concurrency,
        )
        failed_map = {listing["url"]: listing for listing in listings_to_enrich}
        retry_targets = [failed_map[url] for url in failed_urls if url in failed_map]
        retry_results, retry_failed_urls = await run_batch(retry_targets, 1)
        retry_urls = {listing["url"] for listing in retry_results}
        enriched_listings.extend(retry_results)
        failed_urls = [url for url in failed_urls if url not in retry_urls]
        failed_urls = [url for url in failed_urls if url in retry_failed_urls or url not in retry_urls]

    enriched_by_url = {listing["url"]: listing for listing in enriched_listings}
    merged_listings = [enriched_by_url.get(listing["url"], dict(listing)) for listing in listings]
    return merged_listings, failed_urls, len(listings_to_enrich), len(enriched_listings)


async def scrape_listings(criteria: SearchCriteria, limits: ScrapeLimits) -> dict[str, Any]:
    async with async_playwright() as playwright:
        context = await build_context(playwright)
        logging.info("Applying playwright-stealth")
        await Stealth().apply_stealth_async(context)
        page = await context.new_page()

        try:
            logging.info("Opening start URL")
            await page.goto(START_URL, wait_until="domcontentloaded")
            await human_pause(2.0, 3.2)

            await dismiss_popups_if_present(page)
            await move_mouse_like_human(page)
            await page.mouse.wheel(0, random.randint(250, 700))
            await human_pause(1.0, 1.8)

            await apply_search_criteria(page, criteria)

            logging.info("Waiting for listing links to appear")
            await wait_for_listings(page)

            visible_link_count = await page.locator("a[href*='/real-estate/'], a[href*='/real-estate-properties/']").count()
            logging.info("Found %s listing links after applying filters", visible_link_count)

            summaries = await collect_listing_summaries_across_pages(
                page,
                page_limit=limits.max_pages,
                total_limit=limits.max_listings,
            )

            if not summaries:
                raise RuntimeError("No listing data was extracted from the visible results cards")

            merged_listings, failed_detail_urls, detail_attempted, detail_succeeded = await enrich_listings(
                context,
                summaries,
                detail_limit=min(limits.detail_limit, len(summaries)),
                detail_concurrency=limits.detail_concurrency,
            )

            logging.info(
                "Detail scraping summary: %s attempted, %s succeeded, %s failed",
                detail_attempted,
                detail_succeeded,
                len(failed_detail_urls),
            )
            if failed_detail_urls:
                logging.warning("Failed detail URLs: %s", failed_detail_urls)

            await context.close()
            return {
                "listing_summaries": summaries,
                "listings": merged_listings,
                "summary_count": len(summaries),
                "detail_attempted": detail_attempted,
                "detail_succeeded": detail_succeeded,
                "failed_detail_urls": failed_detail_urls,
            }

        except Exception as error:
            logging.error("Scrape failed: %s", error)
            await save_failure_artifacts(page, "scrape_failure")
            await context.close()
            raise


def print_listings(listings: list[dict[str, Any]]) -> None:
    print()
    print(f"Scraped {len(listings)} listing(s)")
    for idx, listing in enumerate(listings, start=1):
        print(f"Listing {idx}")
        for key, value in listing.items():
            print(f"  {key}: {value}")
        print()


async def async_main() -> int:
    configure_logging()
    logging.info("Starting Realtor.ca input-driven scraper")
    try:
        args = parse_args()
        criteria = collect_search_criteria(args)
        limits = collect_scrape_limits(args)
        scrape_result = await scrape_listings(criteria, limits)
        output_path = save_results(
            {
                "search_criteria": {
                    "location": criteria.location,
                    "beds_min": criteria.beds_min,
                    "property_type": criteria.property_type,
                    "min_price": criteria.min_price,
                    "max_price": criteria.max_price,
                },
                "scrape_limits": {
                    "max_pages": limits.max_pages,
                    "max_listings": limits.max_listings,
                    "detail_limit": limits.detail_limit,
                    "detail_concurrency": limits.detail_concurrency,
                },
                "summary_count": scrape_result["summary_count"],
                "detail_attempted": scrape_result["detail_attempted"],
                "detail_succeeded": scrape_result["detail_succeeded"],
                "failed_detail_urls": scrape_result["failed_detail_urls"],
                "listing_count": len(scrape_result["listings"]),
                "listing_summaries": scrape_result["listing_summaries"],
                "listings": scrape_result["listings"],
            }
        )
        logging.info("Scrape completed successfully")
        print(f"\nSaved JSON: {output_path}")
        print_listings(scrape_result["listings"])
        return 0
    except ValueError as error:
        logging.error("%s", error)
        return 1
    except KeyboardInterrupt:
        logging.error("Scrape cancelled by user")
        return 0
    except Exception:
        logging.error("Scrape finished with errors")
        return 1


def main() -> int:
    return asyncio.run(async_main())


if __name__ == "__main__":
    sys.exit(main())
