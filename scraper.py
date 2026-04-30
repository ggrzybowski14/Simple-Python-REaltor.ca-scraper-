from __future__ import annotations

import argparse
import asyncio
import difflib
import json
import logging
import os
import random
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib import error, parse, request

from market_data import build_market_profile_from_saved_search
from market_data import get_market_seed_bootstrap_payload
from typing import Any

from playwright.async_api import BrowserContext, Error, Page, TimeoutError, async_playwright
from playwright_stealth import Stealth


START_URL = "https://www.realtor.ca/map"
DEFAULT_MAX_PAGES = 10
DEFAULT_MAX_LISTINGS = 100
DEFAULT_DETAIL_LIMIT = 25
DEFAULT_DETAIL_CONCURRENCY = 2
ARTIFACTS_DIR = Path("artifacts")
OUTPUTS_DIR = Path("outputs")
TOP_FILTER_WAIT_MS = 600
PROPERTY_FILTER_WAIT_MS = 800
POPUP_BUTTON_TIMEOUT_MS = 600
RESULT_CARD_SELECTOR = "div.cardCon, article.cardCon"
DETAIL_BLOCKED_RESOURCE_TYPES = {"image", "media", "font"}
DETAIL_BLOCKED_URL_TERMS = (
    "google-analytics",
    "googletagmanager",
    "doubleclick",
    "facebook.net",
    "hotjar",
    "clarity.ms",
    "optimizely",
    "adservice",
)
SECURITY_CHALLENGE_TERMS = (
    "additional security check is required",
    "click to verify",
    "verify that you are an actual human",
)
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
    detail_pause_min: float = 0.25
    detail_pause_max: float = 0.6
    block_detail_assets: bool = False


@dataclass
class SupabaseConfig:
    url: str
    key: str


@dataclass
class ProxyConfig:
    server: str
    username: str | None = None
    password: str | None = None


class SecurityChallengeError(RuntimeError):
    pass


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
        datefmt="%H:%M:%S",
    )


async def human_pause(min_seconds: float = 0.25, max_seconds: float = 0.7) -> None:
    await asyncio.sleep(random.uniform(min_seconds, max_seconds))


async def move_mouse_like_human(page: Page) -> None:
    viewport = page.viewport_size or {"width": 1440, "height": 960}
    points = [
        (random.randint(80, 260), random.randint(120, 220)),
        (random.randint(420, viewport["width"] - 160), random.randint(220, viewport["height"] - 160)),
    ]
    for x, y in points:
        await page.mouse.move(x, y, steps=random.randint(8, 18))
        await human_pause(0.08, 0.22)


async def variable_listing_pause(min_seconds: float = 0.25, max_seconds: float = 0.6) -> None:
    if random.random() < 0.2:
        await human_pause(max(min_seconds, 1.0), max(max_seconds, 1.8))
    else:
        await human_pause(min_seconds, max_seconds)


def elapsed_seconds(started_at: float) -> float:
    return round(time.perf_counter() - started_at, 3)


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
    for path in (Path(".env"), Path(".env.local")):
        load_env_file(path)


async def dismiss_popups_if_present(page: Page) -> None:
    patterns = [
        "Accept",
        "I agree",
        "Got it",
        "Close",
    ]
    for pattern in patterns:
        try:
            await page.get_by_role("button", name=re.compile(pattern, re.I)).click(timeout=POPUP_BUTTON_TIMEOUT_MS)
            logging.info("Clicked popup button matching '%s'", pattern)
            await human_pause(0.2, 0.5)
            return
        except TimeoutError:
            continue
        except Error as popup_error:
            logging.info("Popup click skipped for '%s': %s", pattern, popup_error)
            continue


def env_flag_enabled(value: str | None) -> bool:
    if value is None:
        return False
    return value.strip().lower() in {"1", "true", "yes", "on"}


def normalize_proxy_server(value: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise ValueError("SCRAPER_PROXY_SERVER cannot be empty when proxying is enabled")
    if "://" not in cleaned:
        return f"http://{cleaned}"
    return cleaned


def should_block_detail_request(resource_type: str, url: str) -> bool:
    if resource_type in DETAIL_BLOCKED_RESOURCE_TYPES:
        return True
    lowered_url = url.lower()
    return any(term in lowered_url for term in DETAIL_BLOCKED_URL_TERMS)


def text_has_security_challenge(value: str | None) -> bool:
    if not value:
        return False
    lowered = value.lower()
    return any(term in lowered for term in SECURITY_CHALLENGE_TERMS)


async def page_has_security_challenge(page: Page) -> bool:
    try:
        return text_has_security_challenge(await page.locator("body").inner_text(timeout=1500))
    except Exception:
        return False


def build_proxy_config_from_webshare_proxy(row: dict[str, Any], *, mode: str = "direct") -> ProxyConfig | None:
    if row.get("valid") is False:
        return None
    username = row.get("username")
    password = row.get("password")
    port = row.get("port")
    proxy_address = row.get("proxy_address")
    if not username or not password or not port:
        return None

    clean_mode = (mode or "direct").strip().lower()
    if clean_mode == "backbone":
        server_host = "p.webshare.io"
    else:
        server_host = proxy_address
    if not server_host:
        return None

    return ProxyConfig(
        server=normalize_proxy_server(f"{server_host}:{port}"),
        username=str(username),
        password=str(password),
    )


def fetch_webshare_proxy_configs(
    api_key: str,
    *,
    mode: str = "direct",
    country_codes: str | None = None,
    page_size: int = 100,
) -> list[ProxyConfig]:
    clean_mode = (mode or "direct").strip().lower()
    if clean_mode not in {"direct", "backbone"}:
        raise ValueError("WEBSHARE_PROXY_MODE must be either 'direct' or 'backbone'")

    query: dict[str, Any] = {
        "mode": clean_mode,
        "page": 1,
        "page_size": page_size,
    }
    if country_codes:
        query["country_code__in"] = country_codes
    endpoint = f"https://proxy.webshare.io/api/v2/proxy/list/?{parse.urlencode(query)}"
    req = request.Request(
        endpoint,
        headers={
            "Authorization": f"Token {api_key}",
            "Accept": "application/json",
        },
    )
    try:
        with request.urlopen(req, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8", errors="replace"))
    except error.HTTPError as exc:
        details = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Webshare API request failed with status {exc.code}: {details}") from exc
    except error.URLError as exc:
        raise RuntimeError(f"Webshare API request failed: {exc.reason}") from exc

    rows = payload.get("results") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        raise RuntimeError("Webshare API response did not include a proxy results list")

    configs = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        config = build_proxy_config_from_webshare_proxy(row, mode=clean_mode)
        if config is not None:
            configs.append(config)
    return configs


def get_env_proxy_config() -> ProxyConfig | None:
    enabled = env_flag_enabled(os.getenv("SCRAPER_PROXY_ENABLED"))
    server = os.getenv("SCRAPER_PROXY_SERVER")

    if not server:
        if enabled:
            raise ValueError("SCRAPER_PROXY_SERVER is required when SCRAPER_PROXY_ENABLED=true")
        return None

    username = os.getenv("SCRAPER_PROXY_USERNAME") or None
    password = os.getenv("SCRAPER_PROXY_PASSWORD") or None
    if bool(username) != bool(password):
        raise ValueError("SCRAPER_PROXY_USERNAME and SCRAPER_PROXY_PASSWORD must be set together")

    return ProxyConfig(
        server=normalize_proxy_server(server),
        username=username,
        password=password,
    )


def get_scraper_proxy_config() -> ProxyConfig | None:
    api_key = (os.getenv("WEBSHARE_API_KEY") or "").strip()
    if api_key:
        mode = os.getenv("WEBSHARE_PROXY_MODE", "direct")
        country_codes = os.getenv("WEBSHARE_PROXY_COUNTRY_CODES") or None
        try:
            configs = fetch_webshare_proxy_configs(api_key, mode=mode, country_codes=country_codes)
        except Exception as exc:
            logging.warning("Webshare API proxy lookup failed; falling back to SCRAPER_PROXY_* config: %s", exc)
        else:
            if configs:
                selected = random.choice(configs)
                logging.info("Selected Webshare API proxy from %s valid candidate(s)", len(configs))
                return selected
            logging.warning("Webshare API returned no valid proxies; falling back to SCRAPER_PROXY_* config")

    return get_env_proxy_config()

def describe_proxy_config(proxy_config: ProxyConfig) -> str:
    parsed = parse.urlparse(proxy_config.server)
    host = parsed.hostname or proxy_config.server
    port = f":{parsed.port}" if parsed.port else ""
    scheme = f"{parsed.scheme}://" if parsed.scheme else ""
    auth_label = "authenticated" if proxy_config.username and proxy_config.password else "unauthenticated"
    return f"{scheme}{host}{port} ({auth_label})"


async def build_context(playwright) -> BrowserContext:
    headless = env_flag_enabled(os.getenv("SCRAPER_HEADLESS"))
    logging.info("Launching %s Chromium browser", "headless" if headless else "visible")
    proxy_config = get_scraper_proxy_config()
    launch_options: dict[str, Any] = {
        "headless": headless,
        "slow_mo": 60,
        "args": [
            "--disable-blink-features=AutomationControlled",
            "--deny-permission-prompts",
        ],
    }
    if proxy_config is not None:
        proxy_options = {"server": proxy_config.server}
        if proxy_config.username and proxy_config.password:
            proxy_options["username"] = proxy_config.username
            proxy_options["password"] = proxy_config.password
        launch_options["proxy"] = proxy_options
        logging.info("Browser proxy enabled: %s", describe_proxy_config(proxy_config))

    browser = await playwright.chromium.launch(
        **launch_options,
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
    parser.add_argument("--detail-pause-min", type=float, default=0.25)
    parser.add_argument("--detail-pause-max", type=float, default=0.6)
    parser.add_argument(
        "--block-detail-assets",
        action="store_true",
        help="Block detail-page images, media, fonts, and common tracking requests while scraping",
    )
    parser.add_argument("--save-to-supabase", action="store_true", help="Upsert scraped listings into Supabase")
    parser.add_argument("--no-supabase", action="store_true", help="Disable Supabase writes even if env vars are present")
    parser.add_argument("--no-print-listings", action="store_true", help="Skip printing full listing payloads after a run")
    return parser.parse_args()


def normalize_property_type(value: str | None) -> str | None:
    if not value:
        return None
    normalized = value.strip().lower()
    if normalized not in PROPERTY_TYPE_OPTIONS:
        supported = ", ".join(sorted(PROPERTY_TYPE_OPTIONS))
        raise ValueError(f"Unsupported property type '{value}'. Supported values: {supported}")
    return normalized


def normalize_location_fragment(value: str | None) -> str:
    compact = re.sub(r"[^a-z0-9]+", " ", (value or "").strip().lower())
    return re.sub(r"\s+", " ", compact).strip()


def location_search_parts(value: str | None) -> tuple[str, str | None]:
    raw_parts = [part.strip() for part in (value or "").split(",") if part.strip()]
    city = normalize_location_fragment(raw_parts[0] if raw_parts else value)
    province = normalize_location_fragment(raw_parts[1]) if len(raw_parts) > 1 else None
    return city, province


def location_text_matches_requested_location(value: str | None, requested_location: str) -> bool:
    normalized_value = normalize_location_fragment(value)
    requested_city, requested_province = location_search_parts(requested_location)
    if not normalized_value or not requested_city:
        return False
    if requested_city in normalized_value and location_province_matches(normalized_value, requested_province):
        return True
    value_parts = [part for part in normalized_value.split() if part]
    requested_parts = [part for part in requested_city.split() if part]
    if not value_parts or not requested_parts:
        return False
    requested_compact = "".join(requested_parts)
    value_candidates = ["".join(value_parts[index : index + len(requested_parts)]) for index in range(len(value_parts))]
    if len(requested_compact) >= 5 and any(
        difflib.SequenceMatcher(None, requested_compact, candidate).ratio() >= 0.86
        for candidate in value_candidates
    ):
        return location_province_matches(normalized_value, requested_province)
    return False


def location_province_matches(address: str, province: str | None) -> bool:
    if not province:
        return True
    aliases = {
        "bc": ["bc", "british columbia"],
        "b c": ["bc", "british columbia"],
        "british columbia": ["bc", "british columbia"],
    }
    province_options = aliases.get(province, [province])
    return any(option in address for option in province_options)


def address_matches_requested_location(address: str | None, requested_location: str) -> bool:
    normalized_address = normalize_location_fragment(address)
    city, province = location_search_parts(requested_location)
    if not normalized_address or not city:
        return False
    return location_text_matches_requested_location(normalized_address, requested_location) and location_province_matches(
        normalized_address,
        province,
    )


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
    prompt_enabled = not any(
        value is not None
        for value in (args.location, args.beds_min, args.property_type, args.min_price, args.max_price)
    )

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
    if args.detail_pause_min < 0:
        raise ValueError("--detail-pause-min cannot be negative")
    if args.detail_pause_max < args.detail_pause_min:
        raise ValueError("--detail-pause-max must be greater than or equal to --detail-pause-min")
    return ScrapeLimits(
        max_pages=args.max_pages,
        max_listings=args.max_listings,
        detail_limit=args.detail_limit,
        detail_concurrency=args.detail_concurrency,
        detail_pause_min=args.detail_pause_min,
        detail_pause_max=args.detail_pause_max,
        block_detail_assets=args.block_detail_assets,
    )


def normalize_spaces(value: str | None) -> str | None:
    if not value:
        return None
    compact = re.sub(r"\s+", " ", value).strip()
    return compact or None


def normalize_multiline_text(value: str | None) -> str | None:
    if not value:
        return None
    lines = [re.sub(r"\s+", " ", line).strip() for line in value.replace("\r", "").splitlines()]
    non_empty_lines = [line for line in lines if line]
    if not non_empty_lines:
        return None
    return "\n".join(non_empty_lines)


def normalize_numeric_text(value: str | None) -> str | None:
    if not value:
        return None
    return normalize_spaces(value.replace(",", ""))


def normalize_photo_url(value: str | None) -> str | None:
    if not value:
        return None
    compact = normalize_spaces(value)
    if not compact or not re.match(r"^https?://", compact, re.I):
        return None
    lowered = compact.lower()
    blocked_terms = (
        "logo",
        "icon",
        "avatar",
        "placeholder",
        "spinner",
        "loading",
        "banner",
        "sprite",
        "map",
        "googleapis",
        "gstatic",
    )
    if any(term in lowered for term in blocked_terms):
        return None
    return compact


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


def parse_price_option_text(value: str | None) -> int | None:
    if not value:
        return None
    digits = "".join(ch for ch in value if ch.isdigit())
    return int(digits) if digits else None


def choose_numeric_option(
    options: list[dict[str, Any]],
    requested_value: int,
    *,
    mode: str,
) -> dict[str, Any] | None:
    numeric_options = [
        {**option, "number": parsed}
        for option in options
        if (parsed := parse_price_option_text(str(option.get("label") or option.get("value") or ""))) is not None
    ]
    if not numeric_options:
        return None
    exact = next((option for option in numeric_options if option["number"] == requested_value), None)
    if exact:
        return exact
    if mode == "max":
        higher_or_equal = [option for option in numeric_options if option["number"] >= requested_value]
        return min(higher_or_equal, key=lambda option: option["number"]) if higher_or_equal else max(
            numeric_options,
            key=lambda option: option["number"],
        )
    if mode == "min":
        lower_or_equal = [option for option in numeric_options if option["number"] <= requested_value]
        return max(lower_or_equal, key=lambda option: option["number"]) if lower_or_equal else min(
            numeric_options,
            key=lambda option: option["number"],
        )
    raise ValueError("mode must be 'min' or 'max'")


async def wait_for_listings(page: Page) -> None:
    cards = page.locator(RESULT_CARD_SELECTOR)
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
    await human_pause(0.2, 0.5)
    await wait_for_listings(page)


async def snapshot_results_state(page: Page) -> tuple[int | None, str | None, tuple[str, ...]]:
    results_count = await extract_results_count(page)
    page_indicator = await extract_page_indicator(page)
    urls = await get_visible_listing_urls(page)
    return results_count, page_indicator, urls


async def get_visible_listing_urls(page: Page, limit: int = 12) -> tuple[str, ...]:
    cards = page.locator(RESULT_CARD_SELECTOR).filter(
        has=page.locator("a[href*='/real-estate/'], a[href*='/real-estate-properties/']")
    )
    card_count = min(await cards.count(), limit)
    urls: list[str] = []
    for index in range(card_count):
        link = cards.nth(index).locator("a[href*='/real-estate/'], a[href*='/real-estate-properties/']").first
        try:
            if await link.count() == 0:
                continue
            href = await link.get_attribute("href", timeout=1500)
            if not href:
                continue
        except TimeoutError:
            continue
        urls.append(f"https://www.realtor.ca{href}" if href.startswith("/") else href)
    return tuple(urls)


async def wait_for_visible_listing_urls_to_stabilize(
    page: Page,
    *,
    expected_page: int | None = None,
    previous_urls: tuple[str, ...] = (),
    minimum_urls: int = 1,
) -> tuple[str, ...]:
    stable_samples = 0
    previous_sample: tuple[str, ...] | None = None
    last_urls: tuple[str, ...] = ()

    for _ in range(16):
        page_indicator = parse_page_indicator(await extract_page_indicator(page))
        urls = await get_visible_listing_urls(page)
        page_matches = expected_page is None or (page_indicator is not None and page_indicator[0] == expected_page)
        has_minimum = len(urls) >= minimum_urls
        changed_from_previous = not previous_urls or bool(set(urls) - set(previous_urls))

        logging.info(
            "Card stabilization sample | expected_page=%s | page_indicator=%s | urls=%s | changed=%s",
            expected_page or "unknown",
            f"{page_indicator[0]} of {page_indicator[1]}" if page_indicator else "unknown",
            len(urls),
            changed_from_previous,
        )

        if page_matches and has_minimum and changed_from_previous and urls == previous_sample:
            stable_samples += 1
        else:
            stable_samples = 0

        previous_sample = urls
        last_urls = urls
        if stable_samples >= 1:
            return urls
        await page.wait_for_timeout(500)

    logging.warning(
        "Visible listing URLs did not fully stabilize; expected_page=%s | last_url_count=%s",
        expected_page or "unknown",
        len(last_urls),
    )
    return last_urls


async def wait_for_results_stabilization(page: Page) -> tuple[int | None, str | None]:
    stable_samples = 0
    previous_state: tuple[int | None, str | None, tuple[str, ...]] | None = None
    last_state: tuple[int | None, str | None, tuple[str, ...]] | None = None

    for _ in range(10):
        state = await snapshot_results_state(page)
        results_count, page_indicator, urls = state
        logging.info(
            "Results stabilization sample | results_count=%s | page_indicator=%s | first_urls=%s",
            results_count if results_count is not None else "unknown",
            page_indicator or "unknown",
            len(urls),
        )
        if state == previous_state:
            stable_samples += 1
        else:
            stable_samples = 0
        previous_state = state
        last_state = state
        if stable_samples >= 2:
            break
        await page.wait_for_timeout(800)

    if last_state is None:
        return None, None
    return last_state[0], last_state[1]


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


def parse_page_indicator(value: str | None) -> tuple[int, int] | None:
    if not value:
        return None
    match = re.search(r"(\d+)\s+of\s+(\d+)", value)
    if not match:
        return None
    return int(match.group(1)), int(match.group(2))


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
    visible_cards = await page.locator(RESULT_CARD_SELECTOR).count()
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


async def set_numeric_select_value(page: Page, selector: str, requested_value: int, *, mode: str) -> int | None:
    locator = page.locator(selector)
    options = await locator.evaluate(
        """
        select => Array.from(select.options).map(option => ({
            value: option.value,
            label: option.textContent || option.label || option.value,
        }))
        """
    )
    selected = choose_numeric_option(options, requested_value, mode=mode)
    if selected is None:
        raise RuntimeError(f"No usable numeric options found for {selector}")
    selected_number = int(selected["number"])
    if selected_number != requested_value:
        logging.info(
            "Adjusted %s price filter from %s to nearest available Realtor.ca option %s",
            mode,
            requested_value,
            selected_number,
        )
    await set_select_value(page, selector, value=str(selected["value"]))
    return selected_number


async def apply_location(page: Page, location: str) -> None:
    logging.info("Applying location filter: %s", location)
    search_box = page.locator("input[placeholder='City, Neighbourhood, Address or MLS® number']").first
    await search_box.click()
    await human_pause(0.15, 0.35)
    await search_box.fill("")
    await search_box.type(location, delay=random.randint(35, 70))
    await human_pause(0.3, 0.7)

    auto_complete = page.locator("#AutoCompleteCon-txtMapSearchInput")
    selected_location = False
    try:
        await auto_complete.wait_for(state="visible", timeout=6000)
        suggestion_selectors = [
            "#AutoCompleteApiLocations-txtMapSearchInput > *",
            "#AutoCompleteSuggestionsCon-txtMapSearchInput > *",
            "#AutoCompleteApiListings-txtMapSearchInput > *",
        ]
        for selector in suggestion_selectors:
            suggestion = page.locator(selector).first
            if await suggestion.count():
                await suggestion.click()
                selected_location = True
                logging.info("Selected autocomplete suggestion using %s", selector)
                break
    except TimeoutError:
        logging.info("Autocomplete suggestions did not become visible for '%s'", location)

    if not selected_location:
        logging.info("Falling back to keyboard selection for location '%s'", location)
        await page.keyboard.press("ArrowDown")
        await human_pause(0.1, 0.25)
        await page.keyboard.press("Enter")
        await human_pause(0.2, 0.45)

    previous_url = page.url
    search_button = page.locator("button[aria-label='Search']").first
    try:
        await page.wait_for_function(
            "() => { const button = document.querySelector('#btnMapSearch'); return !!button && !button.disabled; }",
            timeout=8000,
        )
        await search_button.click()
        await wait_for_results_refresh(page, previous_url)
        return
    except TimeoutError:
        logging.info("Search button did not enable after location selection; checking for auto-applied location state")

    try:
        await page.wait_for_function(
            """
            requested => {
                const pill = document.querySelector('#locationSearchFilterText');
                const input = document.querySelector('#txtMapSearchInput');
                const value = (pill?.textContent || input?.value || '').toLowerCase();
                return value.includes(requested.toLowerCase());
            }
            """,
            arg=location,
            timeout=10000,
        )
        await wait_for_results_refresh(page, previous_url)
    except TimeoutError as exc:
        raise RuntimeError(f"Location selection did not activate for '{location}'") from exc


async def apply_top_select_filter(page: Page, selector: str, *, label: str) -> None:
    previous_url = page.url
    await set_select_value(page, selector, label=label)
    await page.wait_for_timeout(TOP_FILTER_WAIT_MS)
    await wait_for_results_refresh(page, previous_url)


async def apply_property_type(page: Page, property_type: str) -> None:
    option = PROPERTY_TYPE_OPTIONS[property_type]
    logging.info("Applying property type filter: %s", option["label"])
    await page.locator("button:has-text('Filters')").click()
    await human_pause(0.2, 0.45)
    previous_url = page.url
    await set_select_value(page, "#ddlBuildingType", value=option["value"])
    await human_pause(0.2, 0.45)
    await page.locator("#mapMoreFiltersSearchBtn").click()
    await page.wait_for_timeout(PROPERTY_FILTER_WAIT_MS)
    await wait_for_results_refresh(page, previous_url)


async def apply_search_criteria(page: Page, criteria: SearchCriteria) -> None:
    await apply_location(page, criteria.location)

    if criteria.min_price is not None:
        logging.info("Applying minimum price filter: %s", criteria.min_price)
        previous_url = page.url
        await set_numeric_select_value(page, "#ddlMinPriceTop", criteria.min_price, mode="min")
        await page.wait_for_timeout(TOP_FILTER_WAIT_MS)
        await wait_for_results_refresh(page, previous_url)

    if criteria.max_price is not None:
        logging.info("Applying maximum price filter: %s", criteria.max_price)
        previous_url = page.url
        await set_numeric_select_value(page, "#ddlMaxPriceTop", criteria.max_price, mode="max")
        await page.wait_for_timeout(TOP_FILTER_WAIT_MS)
        await wait_for_results_refresh(page, previous_url)

    if criteria.beds_min is not None and criteria.beds_min > 0:
        logging.info("Applying minimum beds filter: %s+", criteria.beds_min)
        await apply_top_select_filter(page, "#ddlBedsTop", label=format_beds_option(criteria.beds_min))

    if criteria.property_type is not None:
        await apply_property_type(page, criteria.property_type)

    await log_results_snapshot(page, "After filters")


async def apply_search_within_boundary_if_present(page: Page) -> None:
    boundary_control = page.locator("text=/Search within boundary/i").first
    try:
        if await boundary_control.count() == 0:
            return
        if not await boundary_control.is_visible():
            return
        logging.info("Applying current visible map boundary")
        previous_url = page.url
        await boundary_control.click()
        await wait_for_results_refresh(page, previous_url)
        await log_results_snapshot(page, "After boundary apply")
    except Exception as error:
        logging.info("Search-within-boundary step skipped: %s", error)


async def scrape_card(card) -> dict[str, Any] | None:
    link = card.locator("a[href*='/real-estate/'], a[href*='/real-estate-properties/']").first
    try:
        if await link.count() == 0:
            return None
        href = await link.get_attribute("href", timeout=1500)
    except TimeoutError:
        return None
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
        if await locator.count() == 0:
            return None
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


def extract_labeled_value_from_text(text: str, labels: list[str]) -> str | None:
    lines = [normalize_spaces(line) for line in text.replace("\r", "").splitlines()]
    normalized_lines = [line for line in lines if line]

    for label in labels:
        label_pattern = re.compile(rf"^{re.escape(label)}\s*:?\s*(.+)$", re.I)
        for index, line in enumerate(normalized_lines):
            match = label_pattern.match(line)
            if match and match.group(1):
                return match.group(1).strip()
            if line.lower() == label.lower() and index + 1 < len(normalized_lines):
                next_line = normalized_lines[index + 1]
                if next_line and next_line.lower() != label.lower():
                    return next_line

    compact_text = normalize_spaces(text) or ""
    for label in labels:
        match = re.search(
            rf"{re.escape(label)}\s*:?\s*(.+?)(?=\s+[A-Z][A-Za-z/&() .'-]{{2,40}}\s*:|\s+$)",
            compact_text,
            re.I,
        )
        if match:
            return normalize_spaces(match.group(1))
    return None


async def extract_description(page: Page, detail_text: str) -> str | None:
    selectors = [
        "[data-testid='listing-description']",
        "section:has-text('Description')",
        "div:has(> h2:text-matches('Description', 'i'))",
        "div:has(> h3:text-matches('Description', 'i'))",
    ]
    for selector in selectors:
        locator = page.locator(selector).first
        try:
            if await locator.count():
                text = normalize_multiline_text(await locator.inner_text())
                if text:
                    lines = text.splitlines()
                    if lines and lines[0].strip().lower() in {"description", "listing description"}:
                        text = "\n".join(lines[1:]).strip()
                    if text:
                        return text
        except Exception:
            continue

    lines = [line.strip() for line in detail_text.replace("\r", "").splitlines() if line.strip()]
    start_index = None
    stop_labels = {
        "property summary",
        "building features",
        "building",
        "land",
        "rooms",
        "utilities",
        "parking",
        "features",
        "listing brokerage",
        "open house",
        "property information",
    }

    for index, line in enumerate(lines):
        if line.lower() == "description":
            start_index = index + 1
            break

    if start_index is None:
        return None

    collected: list[str] = []
    for line in lines[start_index:]:
        if line.lower() in stop_labels:
            break
        collected.append(line)

    return normalize_multiline_text("\n".join(collected))


async def extract_json_ld(page: Page) -> dict[str, Any]:
    scripts = page.locator("script[type='application/ld+json']")
    payload: dict[str, Any] = {}
    count = await scripts.count()
    for index in range(count):
        try:
            raw = await scripts.nth(index).text_content()
            if not raw:
                continue
            data = json.loads(raw)
        except Exception:
            continue

        candidates = data if isinstance(data, list) else [data]
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            if candidate.get("@type") in {"House", "SingleFamilyResidence", "Apartment", "Residence"}:
                payload.update(candidate)
            elif "address" in candidate or "description" in candidate:
                payload.update(candidate)
    return payload


def append_photo_candidate(photo_urls: list[str], seen_urls: set[str], url: str | None) -> None:
    normalized = normalize_photo_url(url)
    if not normalized or normalized in seen_urls:
        return
    seen_urls.add(normalized)
    photo_urls.append(normalized)


async def extract_photo_urls(page: Page, json_ld: dict[str, Any]) -> list[str]:
    photo_urls: list[str] = []
    seen_urls: set[str] = set()

    image_payload = json_ld.get("image")
    image_candidates = image_payload if isinstance(image_payload, list) else [image_payload]
    for candidate in image_candidates:
        if isinstance(candidate, str):
            append_photo_candidate(photo_urls, seen_urls, candidate)
        elif isinstance(candidate, dict):
            append_photo_candidate(photo_urls, seen_urls, candidate.get("url"))
            append_photo_candidate(photo_urls, seen_urls, candidate.get("contentUrl"))

    try:
        image_meta = await page.locator("meta[property='og:image'], meta[name='twitter:image']").evaluate_all(
            """
            nodes => nodes
                .map(node => node.getAttribute('content'))
                .filter(Boolean)
            """
        )
        for url in image_meta:
            append_photo_candidate(photo_urls, seen_urls, url)
    except Exception:
        pass

    try:
        image_candidates = await page.locator("img").evaluate_all(
            """
            nodes => nodes.map(img => ({
                url: img.currentSrc || img.src || '',
                width: img.naturalWidth || img.width || 0,
                height: img.naturalHeight || img.height || 0,
                alt: img.alt || ''
            }))
            """
        )
        for candidate in image_candidates:
            if not isinstance(candidate, dict):
                continue
            if (candidate.get("width") or 0) < 320 or (candidate.get("height") or 0) < 180:
                continue
            append_photo_candidate(photo_urls, seen_urls, candidate.get("url"))
    except Exception:
        pass

    return photo_urls[:12]


def clean_zoning(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = re.sub(r"^Description\s+", "", value, flags=re.I)
    cleaned = re.sub(r"^Type\s+", "", cleaned, flags=re.I)
    cleaned = re.sub(r"^Zoning\s+Type\s+", "", cleaned, flags=re.I)
    return normalize_spaces(cleaned)


def clean_square_feet(value: str | None) -> str | None:
    if not value:
        return None
    compact = normalize_spaces(value) or ""
    match = re.search(r"(\d[\d,]*(?:\.\d+)?)\s*(square feet|sq\.?\s*ft\.?|sqft)", compact, re.I)
    if match:
        amount = match.group(1).replace(",", "")
        return f"{amount} sqft"
    return compact or None


def clean_land_size(value: str | None) -> str | None:
    if not value:
        return None
    compact = normalize_spaces(value) or ""
    match = re.search(r"(\d[\d,]*(?:\.\d+)?)\s*(square feet|sq\.?\s*ft\.?|sqft)", compact, re.I)
    if match:
        amount = match.group(1).replace(",", "")
        return f"{amount} sqft"
    return compact or None


def clean_built_in(value: str | None) -> str | None:
    if not value:
        return None
    match = re.search(r"\b(\d{4})\b", value)
    if match:
        return match.group(1)
    return normalize_spaces(value)


def clean_money_value(value: str | None) -> str | None:
    if not value:
        return None
    compact = normalize_spaces(value) or ""
    if compact.lower() in {"none", "n/a", "na", "not applicable"}:
        return None
    match = re.search(r"\$\s*[\d,]+(?:\.\d{2})?", compact)
    if match:
        return match.group(0).replace(" ", "")
    return compact or None


def clean_optional_fee(value: str | None) -> str | None:
    cleaned = clean_money_value(value)
    if not cleaned:
        return None
    if re.search(r"\b(no|none|n/?a|not applicable|included)\b", value or "", re.I):
        return None
    return cleaned


def clean_time_on_realtor(value: str | None) -> str | None:
    if not value:
        return None
    compact = normalize_spaces(value) or ""
    match = re.search(r"(\d+)\s+(hour|hours|day|days)", compact, re.I)
    if match:
        quantity = int(match.group(1))
        base_unit = "hour" if "hour" in match.group(2).lower() else "day"
        unit = base_unit if quantity == 1 else f"{base_unit}s"
        return f"{quantity} {unit}"
    return compact or None


def get_supabase_config(args: argparse.Namespace) -> SupabaseConfig | None:
    if args.no_supabase:
        return None

    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_KEY")

    if not url and not key and not args.save_to_supabase:
        return None
    if not url:
        raise ValueError("SUPABASE_URL is required when Supabase upload is enabled")
    if not key:
        raise ValueError("SUPABASE_KEY is required when Supabase upload is enabled")

    return SupabaseConfig(url=url.rstrip("/"), key=key)


def build_search_criteria_payload(criteria: SearchCriteria) -> dict[str, Any]:
    return {
        "location": criteria.location,
        "beds_min": criteria.beds_min,
        "property_type": criteria.property_type,
        "min_price": criteria.min_price,
        "max_price": criteria.max_price,
    }


def build_saved_search_key(criteria: SearchCriteria) -> str:
    property_type = criteria.property_type or "any-property"
    beds_min = criteria.beds_min if criteria.beds_min is not None else "any-beds"
    min_price = criteria.min_price if criteria.min_price is not None else "any-min"
    max_price = criteria.max_price if criteria.max_price is not None else "any-max"
    location_slug = re.sub(r"[^a-z0-9]+", "-", criteria.location.strip().lower()).strip("-") or "unknown-location"
    return f"{location_slug}__{property_type}__beds-{beds_min}__min-{min_price}__max-{max_price}"


def build_saved_search_name(criteria: SearchCriteria) -> str:
    parts = [criteria.location]
    if criteria.property_type:
        parts.append(criteria.property_type.title())
    if criteria.beds_min is not None:
        parts.append(f"{criteria.beds_min}+ beds")
    if criteria.max_price is not None:
        parts.append(f"under ${criteria.max_price:,}")
    elif criteria.min_price is not None:
        parts.append(f"from ${criteria.min_price:,}")
    return " | ".join(parts)


def build_run_payload(
    criteria: SearchCriteria,
    limits: ScrapeLimits,
    scrape_result: dict[str, Any],
    *,
    run_started_at: str,
    run_finished_at: str,
) -> dict[str, Any]:
    return {
        "saved_search_key": build_saved_search_key(criteria),
        "saved_search_name": build_saved_search_name(criteria),
        "search_criteria": build_search_criteria_payload(criteria),
        "scrape_limits": {
            "max_pages": limits.max_pages,
            "max_listings": limits.max_listings,
            "detail_limit": limits.detail_limit,
            "detail_concurrency": limits.detail_concurrency,
            "detail_pause_min": limits.detail_pause_min,
            "detail_pause_max": limits.detail_pause_max,
            "block_detail_assets": limits.block_detail_assets,
        },
        "run_started_at": run_started_at,
        "run_finished_at": run_finished_at,
        "results_count": scrape_result["results_count"],
        "summary_count": scrape_result["summary_count"],
        "detail_attempted": scrape_result["detail_attempted"],
        "detail_succeeded": scrape_result["detail_succeeded"],
        "failed_detail_urls": scrape_result["failed_detail_urls"],
        "timings": scrape_result.get("timings", {}),
        "listing_count": len(scrape_result["listings"]),
        "listing_summaries": scrape_result["listing_summaries"],
        "listings": scrape_result["listings"],
    }


DETAIL_REUSE_WINDOW = timedelta(hours=24)


def is_listing_fully_enriched(listing: dict[str, Any]) -> bool:
    raw_listing = listing.get("raw_listing") if isinstance(listing.get("raw_listing"), dict) else {}
    photo_urls = listing.get("photo_urls")
    if not isinstance(photo_urls, list):
        raw_photo_urls = raw_listing.get("photo_urls")
        photo_urls = raw_photo_urls if isinstance(raw_photo_urls, list) else []
    primary_photo_url = listing.get("primary_photo_url") or raw_listing.get("primary_photo_url")
    return all(
        [
            listing.get("listing_description") or raw_listing.get("listing_description"),
            listing.get("square_feet") or raw_listing.get("square_feet"),
            listing.get("built_in") or raw_listing.get("built_in"),
            listing.get("annual_taxes") or raw_listing.get("annual_taxes"),
            primary_photo_url or photo_urls,
        ]
    )


def is_listing_recently_scraped(scraped_at: str | None) -> bool:
    if not scraped_at:
        return False
    try:
        parsed = datetime.fromisoformat(scraped_at.replace("Z", "+00:00"))
    except ValueError:
        return False
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - parsed <= DETAIL_REUSE_WINDOW


def build_listing_from_existing(summary: dict[str, Any], existing: dict[str, Any]) -> dict[str, Any]:
    raw_listing = existing.get("raw_listing") if isinstance(existing.get("raw_listing"), dict) else {}
    merged = dict(raw_listing)
    merged.setdefault("url", summary["url"])
    merged["url"] = summary["url"]
    merged["address"] = summary.get("address") or existing.get("address") or merged.get("address")
    merged["price"] = summary.get("price") or existing.get("price") or merged.get("price")
    merged["bedrooms"] = summary.get("bedrooms") if summary.get("bedrooms") is not None else existing.get("bedrooms", merged.get("bedrooms"))
    merged["bathrooms"] = summary.get("bathrooms") if summary.get("bathrooms") is not None else existing.get("bathrooms", merged.get("bathrooms"))
    merged["results_page"] = summary.get("results_page")
    for field in (
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
        "primary_photo_url",
    ):
        if not merged.get(field):
            existing_value = existing.get(field)
            if existing_value:
                merged[field] = existing_value
    if not merged.get("photo_urls"):
        raw_photo_urls = raw_listing.get("photo_urls")
        if isinstance(raw_photo_urls, list):
            merged["photo_urls"] = raw_photo_urls
    return merged


def serialize_listing_for_supabase(listing: dict[str, Any], scraped_at: str) -> dict[str, Any]:
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
        "last_seen_at": scraped_at,
        "last_scraped_at": scraped_at,
    }


def supabase_request(
    config: SupabaseConfig,
    path: str,
    *,
    method: str = "GET",
    query: dict[str, Any] | None = None,
    payload: Any | None = None,
    prefer: str | None = None,
) -> Any:
    endpoint = f"{config.url}/rest/v1/{path}"
    if query:
        endpoint = f"{endpoint}?{parse.urlencode(query, doseq=True)}"

    headers = {
        "apikey": config.key,
        "Authorization": f"Bearer {config.key}",
        "Accept": "application/json",
    }
    body = None
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if prefer:
        headers["Prefer"] = prefer

    req = request.Request(endpoint, data=body, method=method, headers=headers)
    try:
        with request.urlopen(req, timeout=30) as response:
            if response.status >= 400:
                raise RuntimeError(f"Supabase write failed with status {response.status}")
            raw = response.read().decode("utf-8", errors="replace")
            if not raw:
                return None
            return json.loads(raw)
    except error.HTTPError as exc:
        details = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Supabase request failed with status {exc.code}: {details}") from exc
    except error.URLError as exc:
        raise RuntimeError(f"Supabase request failed: {exc.reason}") from exc


def ensure_saved_search(config: SupabaseConfig, payload: dict[str, Any], scraped_at: str) -> dict[str, Any]:
    existing_saved_search = fetch_existing_saved_search(config, payload["saved_search_key"])
    existing_snapshot = existing_saved_search.get("search_snapshot") if isinstance(existing_saved_search, dict) else {}
    merged_snapshot = dict(existing_snapshot) if isinstance(existing_snapshot, dict) else {}
    merged_snapshot.update(payload["search_criteria"])
    row = {
        "search_key": payload["saved_search_key"],
        "name": payload["saved_search_name"],
        "location": payload["search_criteria"]["location"],
        "min_price": payload["search_criteria"]["min_price"],
        "max_price": payload["search_criteria"]["max_price"],
        "beds_min": payload["search_criteria"]["beds_min"],
        "property_type": payload["search_criteria"]["property_type"],
        "search_snapshot": merged_snapshot,
        "last_scraped_at": scraped_at,
        "is_active": True,
    }
    result = supabase_request(
        config,
        "saved_searches",
        method="POST",
        query={"on_conflict": "search_key", "select": "id,search_key,name"},
        payload=[row],
        prefer="resolution=merge-duplicates,return=representation",
    )
    if not isinstance(result, list) or not result:
        raise RuntimeError("Supabase did not return a saved_searches row")
    ensure_market_profile(
        config,
        {
            **row,
            "id": result[0].get("id"),
        },
    )
    return result[0]


def ensure_market_profile(config: SupabaseConfig, saved_search: dict[str, Any]) -> dict[str, Any] | None:
    profile = build_market_profile_from_saved_search(
        saved_search,
        status="discovered",
        notes=(
            "Auto-created from a scraped saved search. Structured metrics, rent growth, and appreciation "
            "series can be populated later as market-context coverage expands."
        ),
    )
    result = supabase_request(
        config,
        "market_profiles",
        method="POST",
        query={"on_conflict": "market_key", "select": "id,market_key,market_name,province,status"},
        payload=[profile],
        prefer="resolution=merge-duplicates,return=representation",
    )
    persisted = result[0] if isinstance(result, list) and result else None
    return bootstrap_market_context(config, saved_search, fallback_profile=persisted)


def bootstrap_market_context(
    config: SupabaseConfig,
    saved_search: dict[str, Any],
    *,
    fallback_profile: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    bundle = get_market_seed_bootstrap_payload(saved_search)
    if bundle is None:
        return fallback_profile

    profile_result = supabase_request(
        config,
        "market_profiles",
        method="POST",
        query={"on_conflict": "market_key", "select": "id,market_key,market_name,province,status"},
        payload=[bundle["profile"]],
        prefer="resolution=merge-duplicates,return=representation",
    )
    if bundle["metrics"]:
        supabase_request(
            config,
            "market_metrics",
            method="POST",
            query={"on_conflict": "market_key,metric_key"},
            payload=bundle["metrics"],
            prefer="resolution=merge-duplicates,return=representation",
        )
    if bundle["series"]:
        supabase_request(
            config,
            "market_metric_series",
            method="POST",
            query={"on_conflict": "market_key,series_key,point_date"},
            payload=bundle["series"],
            prefer="resolution=merge-duplicates,return=representation",
        )

    if isinstance(profile_result, list) and profile_result:
        return profile_result[0]
    return fallback_profile


def fetch_existing_saved_search(config: SupabaseConfig, search_key: str) -> dict[str, Any] | None:
    result = supabase_request(
        config,
        "saved_searches",
        query={
            "search_key": f"eq.{search_key}",
            "select": "id,search_snapshot",
            "limit": 1,
        },
    )
    if isinstance(result, list) and result:
        return result[0]
    return None


def create_scrape_run(config: SupabaseConfig, saved_search_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    row = {
        "saved_search_id": saved_search_id,
        "status": "succeeded",
        "started_at": payload["run_started_at"],
        "finished_at": payload["run_finished_at"],
        "results_count": payload["results_count"],
        "summary_count": payload["summary_count"],
        "detail_attempted": payload["detail_attempted"],
        "detail_succeeded": payload["detail_succeeded"],
        "failed_detail_urls": payload["failed_detail_urls"],
        "search_snapshot": payload["search_criteria"],
        "run_settings": payload["scrape_limits"],
    }
    result = supabase_request(
        config,
        "scrape_runs",
        method="POST",
        query={"select": "id"},
        payload=[row],
        prefer="return=representation",
    )
    if not isinstance(result, list) or not result:
        raise RuntimeError("Supabase did not return a scrape_runs row")
    return result[0]


def get_saved_search_listing_states(config: SupabaseConfig, saved_search_id: int) -> dict[int, dict[str, Any]]:
    result = supabase_request(
        config,
        "saved_search_listings",
        query={
            "saved_search_id": f"eq.{saved_search_id}",
            "select": "id,listing_id,first_seen_at,first_seen_run_id,is_active",
        },
    )
    if result is None:
        return {}
    if not isinstance(result, list):
        raise RuntimeError("Supabase did not return saved_search_listings rows")
    state_by_listing_id: dict[int, dict[str, Any]] = {}
    for row in result:
        listing_id = row.get("listing_id")
        if isinstance(listing_id, int):
            state_by_listing_id[listing_id] = row
    return state_by_listing_id


def get_active_saved_search_listing_ids(config: SupabaseConfig, saved_search_id: int) -> set[int]:
    result = supabase_request(
        config,
        "saved_search_listings",
        query={
            "saved_search_id": f"eq.{saved_search_id}",
            "is_active": "eq.true",
            "select": "listing_id",
        },
    )
    if result is None:
        return set()
    if not isinstance(result, list):
        raise RuntimeError("Supabase did not return active saved_search_listings rows")
    active_ids: set[int] = set()
    for row in result:
        listing_id = row.get("listing_id")
        if isinstance(listing_id, int):
            active_ids.add(listing_id)
    return active_ids


def fetch_existing_listings(config: SupabaseConfig, listing_keys: list[str]) -> dict[str, dict[str, Any]]:
    unique_keys = sorted({key for key in listing_keys if key})
    if not unique_keys:
        return {}

    quoted_keys = ",".join(json.dumps(key) for key in unique_keys)
    result = supabase_request(
        config,
        "listings",
        query={
            "source_listing_key": f"in.({quoted_keys})",
            "select": (
                "source_listing_key,address,price,bedrooms,bathrooms,listing_description,property_type,"
                "building_type,square_feet,land_size,built_in,annual_taxes,hoa_fees,time_on_realtor,"
                "zoning_type,last_scraped_at,raw_listing"
            ),
        },
    )
    if result is None:
        return {}
    if not isinstance(result, list):
        raise RuntimeError("Supabase did not return listings rows")
    rows_by_key: dict[str, dict[str, Any]] = {}
    for row in result:
        key = row.get("source_listing_key")
        if isinstance(key, str):
            rows_by_key[key] = row
    return rows_by_key


def upsert_listings(config: SupabaseConfig, payload: dict[str, Any], scraped_at: str) -> dict[str, int]:
    existing_listing_rows = fetch_existing_listings(config, [listing["url"] for listing in payload["listings"]])
    rows = []
    for listing in payload["listings"]:
        existing = existing_listing_rows.get(listing["url"])
        merged_listing = build_listing_from_existing(listing, existing) if existing else listing
        rows.append(serialize_listing_for_supabase(merged_listing, scraped_at))
    if not rows:
        logging.info("No listings to save to Supabase")
        return {}

    result = supabase_request(
        config,
        "listings",
        method="POST",
        query={"on_conflict": "source_listing_key", "select": "id,source_listing_key"},
        payload=rows,
        prefer="resolution=merge-duplicates,return=representation",
    )
    if not isinstance(result, list):
        raise RuntimeError("Supabase did not return listing rows")
    listing_map: dict[str, int] = {}
    for row in result:
        source_listing_key = row.get("source_listing_key")
        listing_id = row.get("id")
        if isinstance(source_listing_key, str) and isinstance(listing_id, int):
            listing_map[source_listing_key] = listing_id
    return listing_map


def save_scrape_run_listings(
    config: SupabaseConfig,
    *,
    saved_search_id: int,
    scrape_run_id: int,
    payload: dict[str, Any],
    listing_id_by_key: dict[str, int],
    existing_listing_ids: set[int],
) -> int:
    rows = []
    for listing in payload["listings"]:
        listing_id = listing_id_by_key.get(listing["url"])
        if listing_id is None:
            continue
        rows.append(
            {
                "scrape_run_id": scrape_run_id,
                "saved_search_id": saved_search_id,
                "listing_id": listing_id,
                "results_page": listing.get("results_page"),
                "is_new_in_run": listing_id not in existing_listing_ids,
                "raw_listing_snapshot": listing,
            }
        )

    if not rows:
        return 0

    supabase_request(
        config,
        "scrape_run_listings",
        method="POST",
        query={"on_conflict": "scrape_run_id,listing_id"},
        payload=rows,
        prefer="resolution=merge-duplicates,return=minimal",
    )
    return len(rows)


def sync_saved_search_listings(
    config: SupabaseConfig,
    *,
    saved_search_id: int,
    scrape_run_id: int,
    scraped_at: str,
    listing_id_by_key: dict[str, int],
    existing_states: dict[int, dict[str, Any]],
) -> int:
    supabase_request(
        config,
        "saved_search_listings",
        method="PATCH",
        query={"saved_search_id": f"eq.{saved_search_id}"},
        payload={"is_active": False},
        prefer="return=minimal",
    )

    if not listing_id_by_key:
        return 0

    rows = []
    for listing_id in listing_id_by_key.values():
        existing = existing_states.get(listing_id, {})
        rows.append(
            {
                "saved_search_id": saved_search_id,
                "listing_id": listing_id,
                "first_seen_at": existing.get("first_seen_at") or scraped_at,
                "last_seen_at": scraped_at,
                "first_seen_run_id": existing.get("first_seen_run_id") or scrape_run_id,
                "last_seen_run_id": scrape_run_id,
                "is_active": True,
            }
        )

    supabase_request(
        config,
        "saved_search_listings",
        method="POST",
        query={"on_conflict": "saved_search_id,listing_id"},
        payload=rows,
        prefer="resolution=merge-duplicates,return=minimal",
    )
    return len(rows)


def save_to_supabase(config: SupabaseConfig, payload: dict[str, Any]) -> int:
    scraped_at = payload["run_finished_at"]
    saved_search = ensure_saved_search(config, payload, scraped_at)
    scrape_run = create_scrape_run(config, int(saved_search["id"]), payload)
    listing_id_by_key = upsert_listings(config, payload, scraped_at)
    existing_states = get_saved_search_listing_states(config, int(saved_search["id"]))
    previously_active_listing_ids = get_active_saved_search_listing_ids(config, int(saved_search["id"]))
    linked_count = save_scrape_run_listings(
        config,
        saved_search_id=int(saved_search["id"]),
        scrape_run_id=int(scrape_run["id"]),
        payload=payload,
        listing_id_by_key=listing_id_by_key,
        existing_listing_ids=previously_active_listing_ids,
    )
    active_count = sync_saved_search_listings(
        config,
        saved_search_id=int(saved_search["id"]),
        scrape_run_id=int(scrape_run["id"]),
        scraped_at=scraped_at,
        listing_id_by_key=listing_id_by_key,
        existing_states=existing_states,
    )

    logging.info(
        "Saved %s listing(s) into saved_search=%s and scrape_run=%s; active listings now %s",
        linked_count,
        saved_search["search_key"],
        scrape_run["id"],
        active_count,
    )
    return linked_count


async def configure_detail_request_blocking(detail_page: Page) -> None:
    async def route_request(route) -> None:
        req = route.request
        if should_block_detail_request(req.resource_type, req.url):
            await route.abort()
            return
        await route.continue_()

    await detail_page.route("**/*", route_request)


async def scrape_detail_page(
    context: BrowserContext,
    listing: dict[str, Any],
    *,
    block_assets: bool = False,
) -> dict[str, Any]:
    detail_page = await context.new_page()
    try:
        if block_assets:
            await configure_detail_request_blocking(detail_page)
        logging.info("Opening detail page: %s", listing["url"])
        await detail_page.goto(listing["url"], wait_until="domcontentloaded")
        if await page_has_security_challenge(detail_page):
            raise SecurityChallengeError("Realtor.ca security challenge detected")
        await human_pause(0.8, 1.3)
        await dismiss_popups_if_present(detail_page)
        if await page_has_security_challenge(detail_page):
            raise SecurityChallengeError("Realtor.ca security challenge detected")
        await move_mouse_like_human(detail_page)
        await detail_page.mouse.wheel(0, random.randint(250, 600))
        await human_pause(0.2, 0.45)
        if await page_has_security_challenge(detail_page):
            raise SecurityChallengeError("Realtor.ca security challenge detected")

        try:
            await detail_page.locator("text=/MLS.*Number|Property Summary|Listing Description/i").first.wait_for(
                timeout=15000
            )
        except TimeoutError:
            if await page_has_security_challenge(detail_page):
                raise SecurityChallengeError("Realtor.ca security challenge detected") from None
            raise
        logging.info("Detail page loaded for %s", listing["url"])

        detail_text = await detail_page.locator("body").inner_text()
        compact_detail_text = normalize_spaces(detail_text) or ""
        json_ld = await extract_json_ld(detail_page)
        photo_urls = await extract_photo_urls(detail_page, json_ld)

        description = await extract_description(detail_page, detail_text)
        property_type = (
            await extract_labeled_value(detail_page, "Property Type")
            or extract_labeled_value_from_text(detail_text, ["Property Type"])
            or normalize_spaces(json_ld.get("@type") if isinstance(json_ld.get("@type"), str) else None)
        )
        building_type = (
            await extract_labeled_value(detail_page, "Building Type")
            or extract_labeled_value_from_text(detail_text, ["Building Type"])
        )
        square_feet = (
            await extract_labeled_value(detail_page, "Size Interior")
            or await extract_labeled_value(detail_page, "Floor Space")
            or extract_labeled_value_from_text(detail_text, ["Size Interior", "Floor Space", "Total Finished Area"])
        )
        land_size = (
            await extract_labeled_value(detail_page, "Land Size")
            or extract_labeled_value_from_text(detail_text, ["Land Size", "Lot Size"])
        )
        built_in = (
            await extract_labeled_value(detail_page, "Built in")
            or await extract_labeled_value(detail_page, "Year Built")
            or extract_labeled_value_from_text(detail_text, ["Built in", "Year Built"])
        )
        annual_taxes = (
            await extract_labeled_value(detail_page, "Annual Property Taxes")
            or await extract_labeled_value(detail_page, "Annual Taxes")
            or await extract_labeled_value(detail_page, "Taxes")
            or extract_labeled_value_from_text(detail_text, ["Annual Property Taxes", "Annual Taxes", "Taxes"])
        )
        hoa_fees = (
            await extract_labeled_value(detail_page, "Maintenance Fees")
            or await extract_labeled_value(detail_page, "Condo Fees")
            or await extract_labeled_value(detail_page, "Strata Fee")
            or await extract_labeled_value(detail_page, "HOA Fees")
            or extract_labeled_value_from_text(
                detail_text,
                ["Maintenance Fees", "Condo Fees", "Strata Fee", "Strata Fees", "HOA Fees"],
            )
        )
        time_on_realtor = (
            await extract_labeled_value(detail_page, "Time on REALTOR.ca")
            or extract_labeled_value_from_text(detail_text, ["Time on REALTOR.ca"])
        )
        zoning = clean_zoning(
            await extract_labeled_value(detail_page, "Zoning")
            or await extract_labeled_value(detail_page, "Zoning Description")
            or extract_labeled_value_from_text(detail_text, ["Zoning"])
            or extract_labeled_value_from_text(detail_text, ["Zoning Description"])
        )

        if not land_size:
            match = re.search(r"Land Size\s+(.+?)(?=\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\s|$)", compact_detail_text)
            if match:
                land_size = normalize_spaces(match.group(1))
        if not built_in:
            match = re.search(r"(?:Built in|Year Built)\s+(\d{4})", compact_detail_text, re.I)
            if match:
                built_in = match.group(1)
        if not square_feet:
            match = re.search(r"(\d[\d,]*)\s*(sq\.?\s*ft\.?|sqft|square feet)", compact_detail_text, re.I)
            if match:
                square_feet = normalize_spaces(match.group(0))

        merged = dict(listing)
        merged["listing_description"] = description or normalize_spaces(json_ld.get("description"))
        merged["property_type"] = property_type
        merged["building_type"] = building_type
        merged["square_feet"] = clean_square_feet(square_feet)
        merged["land_size"] = clean_land_size(land_size)
        merged["built_in"] = clean_built_in(built_in)
        merged["annual_taxes"] = clean_money_value(annual_taxes)
        merged["hoa_fees"] = clean_optional_fee(hoa_fees)
        merged["time_on_realtor"] = clean_time_on_realtor(time_on_realtor)
        merged["zoning_type"] = zoning
        merged["photo_urls"] = photo_urls
        merged["primary_photo_url"] = photo_urls[0] if photo_urls else None
        return merged
    except Exception as error:
        logging.error("Detail scrape failed for %s: %s", listing["url"], error)
        await save_failure_artifacts(detail_page, "detail_failure")
        raise
    finally:
        await detail_page.close()


async def collect_listing_summaries_from_current_page(
    page: Page,
    limit: int,
) -> list[dict[str, Any]]:
    cards = page.locator(RESULT_CARD_SELECTOR).filter(
        has=page.locator("a[href*='/real-estate/'], a[href*='/real-estate-properties/']")
    )
    listings_by_url: dict[str, dict[str, Any]] = {}
    card_count = await cards.count()
    logging.info("Scanning %s visible result cards on current page", card_count)

    for idx in range(card_count):
        card = cards.nth(idx)
        try:
            if not await card.is_visible():
                continue
        except Exception:
            continue
        listing = await scrape_card(card)
        if not listing:
            continue
        listings_by_url.setdefault(listing["url"], listing)
        if len(listings_by_url) >= limit:
            break

    return list(listings_by_url.values())[:limit]


async def go_to_next_results_page(page: Page, previous_urls: tuple[str, ...]) -> bool:
    page_indicator = parse_page_indicator(await extract_page_indicator(page))
    if page_indicator and page_indicator[0] >= page_indicator[1]:
        logging.info("Already on final results page (%s of %s)", page_indicator[0], page_indicator[1])
        return False

    expected_next_page = page_indicator[0] + 1 if page_indicator else None
    candidates = [
        ("next-aria", page.locator("a[aria-label='Go to the next page']")),
        ("next-class", page.locator("a.lnkNextResultsPage, button.lnkNextResultsPage")),
    ]
    if expected_next_page is not None:
        candidates.extend(
            [
                (
                    f"page-number-link-{expected_next_page}",
                    page.locator(
                        f"a[aria-label='Go to page {expected_next_page}'], button[aria-label='Go to page {expected_next_page}']"
                    ),
                ),
                (
                    f"page-number-text-{expected_next_page}",
                    page.locator(f"a:has-text('{expected_next_page}'), button:has-text('{expected_next_page}')"),
                ),
            ]
        )

    clicked = False
    for label, locator in candidates:
        count = await locator.count()
        for index in range(count):
            candidate = locator.nth(index)
            try:
                if not await candidate.is_visible():
                    continue
                current_class = (await candidate.get_attribute("class") or "").lower()
                disabled_attr = await candidate.get_attribute("disabled")
                aria_disabled = (await candidate.get_attribute("aria-disabled") or "").lower()
                if "disabled" in current_class or disabled_attr is not None or aria_disabled == "true":
                    continue
                await candidate.scroll_into_view_if_needed()
                logging.info("Navigating to the next results page using %s", label)
                try:
                    await candidate.click(timeout=5000)
                except Exception:
                    await candidate.evaluate("(el) => el.click()")
                clicked = True
                break
            except Exception:
                continue
        if clicked:
            break

    if not clicked:
        logging.info(
            "No enabled visible next-page control is available; page_indicator=%s",
            await extract_page_indicator(page) or "unknown",
        )
        return False

    await human_pause(0.15, 0.35)

    try:
        await page.wait_for_function(
            """
            ({ expectedPage }) => {
                if (expectedPage) {
                    const currentUrl = window.location.href;
                    if (currentUrl.includes(`CurrentPage=${expectedPage}`)) {
                        return true;
                    }
                }
                return false;
            }
            """,
            arg={"expectedPage": expected_next_page},
            timeout=15000,
        )
    except TimeoutError:
        logging.warning("Timed out waiting for next results URL to change")
        return False

    stabilized_urls = await wait_for_visible_listing_urls_to_stabilize(
        page,
        expected_page=expected_next_page,
        previous_urls=previous_urls,
        minimum_urls=1,
    )
    refreshed_page_indicator = parse_page_indicator(await extract_page_indicator(page))
    changed_from_previous = bool(set(stabilized_urls) - set(previous_urls))
    page_matches = expected_next_page is None or (
        refreshed_page_indicator is not None and refreshed_page_indicator[0] == expected_next_page
    )

    if not changed_from_previous or not page_matches:
        logging.warning(
            "Next page URL changed before rendered cards updated; reloading current results URL once | expected_page=%s | page_indicator=%s | changed=%s",
            expected_next_page or "unknown",
            f"{refreshed_page_indicator[0]} of {refreshed_page_indicator[1]}" if refreshed_page_indicator else "unknown",
            changed_from_previous,
        )
        await page.reload(wait_until="domcontentloaded")
        await human_pause(0.3, 0.7)
        stabilized_urls = await wait_for_visible_listing_urls_to_stabilize(
            page,
            expected_page=expected_next_page,
            previous_urls=previous_urls,
            minimum_urls=1,
        )
        refreshed_page_indicator = parse_page_indicator(await extract_page_indicator(page))
        changed_from_previous = bool(set(stabilized_urls) - set(previous_urls))
        page_matches = expected_next_page is None or (
            refreshed_page_indicator is not None and refreshed_page_indicator[0] == expected_next_page
        )
        if not changed_from_previous or not page_matches:
            logging.warning(
                "Next page did not render new cards after reload; stopping pagination | expected_page=%s | page_indicator=%s | changed=%s",
                expected_next_page or "unknown",
                f"{refreshed_page_indicator[0]} of {refreshed_page_indicator[1]}" if refreshed_page_indicator else "unknown",
                changed_from_previous,
            )
            return False

    await log_results_snapshot(page, "After page transition")
    return True


async def collect_listing_summaries_across_pages(
    page: Page,
    page_limit: int,
    total_limit: int,
) -> list[dict[str, Any]]:
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

        page_indicator = parse_page_indicator(await extract_page_indicator(page))
        expected_current_page = page_indicator[0] if page_indicator else page_index
        await wait_for_visible_listing_urls_to_stabilize(
            page,
            expected_page=expected_current_page,
            minimum_urls=min(remaining, 12),
        )
        await log_results_snapshot(page, f"Before scanning results page {page_index}")
        current_urls = await get_visible_listing_urls(page)
        page_listings = await collect_listing_summaries_from_current_page(
            page,
            remaining,
        )
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

        page_indicator = parse_page_indicator(await extract_page_indicator(page))
        if page_indicator and page_indicator[0] >= page_indicator[1]:
            break

        if not await go_to_next_results_page(page, current_urls):
            break

    return collected


async def validate_location_before_detail_scrape(
    page: Page,
    criteria: SearchCriteria,
    summaries: list[dict[str, Any]],
) -> None:
    rendered_location = await extract_rendered_location(page)
    if location_text_matches_requested_location(rendered_location, criteria.location):
        logging.info(
            "Location guard passed using rendered Realtor.ca location: requested=%s | rendered=%s",
            criteria.location,
            rendered_location,
        )
        return

    checked = summaries[: min(len(summaries), 12)]
    matching = [
        listing
        for listing in checked
        if address_matches_requested_location(listing.get("address"), criteria.location)
    ]
    required_matches = max(1, min(3, len(checked))) if checked else 1
    if len(matching) >= required_matches:
        logging.info(
            "Location guard passed using visible listing addresses: requested=%s | matches=%s/%s",
            criteria.location,
            len(matching),
            len(checked),
        )
        return

    sample_addresses = [listing.get("address") for listing in checked[:5]]
    raise RuntimeError(
        "Visible Realtor.ca results do not match requested location before detail scraping; "
        f"requested={criteria.location!r}, rendered_location={rendered_location!r}, "
        f"matching_cards={len(matching)}/{len(checked)}, sample_addresses={sample_addresses!r}"
    )


async def enrich_detail_worker(
    context: BrowserContext,
    listing: dict[str, Any],
    semaphore: asyncio.Semaphore,
    detail_pause_min: float,
    detail_pause_max: float,
    block_detail_assets: bool,
    challenge_detected: asyncio.Event,
) -> tuple[dict[str, Any] | None, str | None, bool]:
    async with semaphore:
        if challenge_detected.is_set():
            logging.warning("Skipping queued detail page after security challenge: %s", listing["url"])
            return None, listing["url"], True
        await variable_listing_pause(detail_pause_min, detail_pause_max)
        started_at = time.perf_counter()
        try:
            result = await scrape_detail_page(context, listing, block_assets=block_detail_assets)
            logging.info("Detail timing | seconds=%s | url=%s", elapsed_seconds(started_at), listing["url"])
            return result, None, False
        except SecurityChallengeError:
            challenge_detected.set()
            logging.warning("Security challenge detected on detail page; stopping queued detail work: %s", listing["url"])
            logging.info("Detail timing | seconds=%s | blocked=true | url=%s", elapsed_seconds(started_at), listing["url"])
            return None, listing["url"], True
        except Exception:
            logging.info("Detail timing | seconds=%s | failed=true | url=%s", elapsed_seconds(started_at), listing["url"])
            return None, listing["url"], False


async def enrich_listings(
    context: BrowserContext,
    listings: list[dict[str, Any]],
    detail_limit: int,
    detail_concurrency: int,
    detail_pause_min: float,
    detail_pause_max: float,
    block_detail_assets: bool,
    existing_listing_rows: dict[str, dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], list[str], int, int]:
    existing_listing_rows = existing_listing_rows or {}
    reuse_candidates = listings[:detail_limit] if detail_limit else []
    reused_listings: list[dict[str, Any]] = []
    listings_to_enrich: list[dict[str, Any]] = []

    for listing in reuse_candidates:
        existing = existing_listing_rows.get(listing["url"])
        if existing and is_listing_fully_enriched(existing) and is_listing_recently_scraped(existing.get("last_scraped_at")):
            reused_listings.append(build_listing_from_existing(listing, existing))
        else:
            listings_to_enrich.append(listing)

    if reused_listings:
        logging.info("Reusing recent detail data for %s listing(s)", len(reused_listings))

    async def run_batch(targets: list[dict[str, Any]], concurrency: int) -> tuple[list[dict[str, Any]], list[str], list[str]]:
        local_semaphore = asyncio.Semaphore(concurrency)
        challenge_detected = asyncio.Event()
        tasks = [
            asyncio.create_task(
                enrich_detail_worker(
                    context,
                    listing,
                    local_semaphore,
                    detail_pause_min,
                    detail_pause_max,
                    block_detail_assets,
                    challenge_detected,
                )
            )
            for listing in targets
        ]
        batch_results = await asyncio.gather(*tasks)
        enriched = [item for item, failed, blocked in batch_results if item is not None]
        failed_urls = [failed for item, failed, blocked in batch_results if failed is not None]
        challenge_urls = [failed for item, failed, blocked in batch_results if failed is not None and blocked]
        return enriched, failed_urls, challenge_urls

    enriched_listings, failed_urls, challenge_urls = await run_batch(listings_to_enrich, detail_concurrency)

    if challenge_urls:
        logging.warning(
            "Security challenge detected for %s detail page(s); skipping automatic retries for this run",
            len(challenge_urls),
        )
    elif failed_urls and detail_concurrency > 1 and len(failed_urls) >= detail_concurrency:
        logging.warning(
            "Detail failures reached %s with concurrency=%s; skipping automatic retry to avoid triggering more challenges",
            len(failed_urls),
            detail_concurrency,
        )
    elif failed_urls and detail_concurrency > 1 and len(failed_urls) >= 3:
        logging.warning(
            "Detail failures reached %s with concurrency=%s; retrying failed detail pages sequentially",
            len(failed_urls),
            detail_concurrency,
        )
        failed_map = {listing["url"]: listing for listing in listings_to_enrich}
        retry_targets = [failed_map[url] for url in failed_urls if url in failed_map]
        retry_results, retry_failed_urls, retry_challenge_urls = await run_batch(retry_targets, 1)
        retry_urls = {listing["url"] for listing in retry_results}
        enriched_listings.extend(retry_results)
        failed_urls = [url for url in failed_urls if url not in retry_urls]
        failed_urls = [url for url in failed_urls if url in retry_failed_urls or url not in retry_urls]
        if retry_challenge_urls:
            logging.warning(
                "Security challenge detected during sequential retry for %s detail page(s)",
                len(retry_challenge_urls),
            )

    combined_enriched = reused_listings + enriched_listings
    enriched_by_url = {listing["url"]: listing for listing in combined_enriched}
    merged_listings = [enriched_by_url.get(listing["url"], dict(listing)) for listing in listings]
    return merged_listings, failed_urls, len(listings_to_enrich), len(enriched_listings)


async def scrape_listings(criteria: SearchCriteria, limits: ScrapeLimits) -> dict[str, Any]:
    scrape_started_at = time.perf_counter()
    timings: dict[str, float] = {}
    async with async_playwright() as playwright:
        browser_started_at = time.perf_counter()
        context = await build_context(playwright)
        timings["browser_launch_seconds"] = elapsed_seconds(browser_started_at)
        logging.info("Applying playwright-stealth")
        await Stealth().apply_stealth_async(context)
        page = await context.new_page()

        try:
            setup_started_at = time.perf_counter()
            start_url_started_at = time.perf_counter()
            logging.info("Opening start URL")
            await page.goto(START_URL, wait_until="domcontentloaded")
            await human_pause(0.3, 0.7)
            timings["start_url_open_seconds"] = elapsed_seconds(start_url_started_at)

            pre_filter_started_at = time.perf_counter()
            await dismiss_popups_if_present(page)
            await move_mouse_like_human(page)
            await page.mouse.wheel(0, random.randint(180, 420))
            await human_pause(0.2, 0.45)
            timings["pre_filter_behavior_seconds"] = elapsed_seconds(pre_filter_started_at)

            filter_started_at = time.perf_counter()
            await apply_search_criteria(page, criteria)
            timings["filter_application_seconds"] = elapsed_seconds(filter_started_at)
            timings["search_setup_seconds"] = elapsed_seconds(setup_started_at)

            logging.info("Waiting for listing links to appear")
            stabilization_started_at = time.perf_counter()
            await wait_for_listings(page)
            results_count, stabilized_page_indicator = await wait_for_results_stabilization(page)
            timings["results_stabilization_seconds"] = elapsed_seconds(stabilization_started_at)
            if stabilized_page_indicator:
                logging.info("Settled page indicator before collection: %s", stabilized_page_indicator)

            visible_link_count = await page.locator("a[href*='/real-estate/'], a[href*='/real-estate-properties/']").count()
            logging.info("Found %s listing links after applying filters", visible_link_count)

            summary_started_at = time.perf_counter()
            summaries = await collect_listing_summaries_across_pages(
                page,
                page_limit=limits.max_pages,
                total_limit=limits.max_listings,
            )
            try:
                await validate_location_before_detail_scrape(page, criteria, summaries)
            except RuntimeError as location_error:
                logging.warning("%s", location_error)
                logging.info("Retrying location filter once before detail scraping: %s", criteria.location)
                await apply_location(page, criteria.location)
                stabilization_retry_started_at = time.perf_counter()
                await wait_for_listings(page)
                results_count, stabilized_page_indicator = await wait_for_results_stabilization(page)
                timings["location_retry_stabilization_seconds"] = elapsed_seconds(stabilization_retry_started_at)
                if stabilized_page_indicator:
                    logging.info("Settled page indicator after location retry: %s", stabilized_page_indicator)
                summaries = await collect_listing_summaries_across_pages(
                    page,
                    page_limit=limits.max_pages,
                    total_limit=limits.max_listings,
                )
                await validate_location_before_detail_scrape(page, criteria, summaries)
            timings["summary_collection_seconds"] = elapsed_seconds(summary_started_at)

            if not summaries:
                raise RuntimeError("No listing data was extracted from the visible results cards")

            cache_lookup_started_at = time.perf_counter()
            existing_listing_rows: dict[str, dict[str, Any]] = {}
            supabase_url = os.getenv("SUPABASE_URL")
            supabase_key = os.getenv("SUPABASE_KEY")
            if supabase_url and supabase_key:
                try:
                    existing_listing_rows = fetch_existing_listings(
                        SupabaseConfig(url=supabase_url.rstrip("/"), key=supabase_key),
                        [listing["url"] for listing in summaries],
                    )
                    logging.info("Loaded %s existing listing row(s) for detail reuse check", len(existing_listing_rows))
                except Exception as error:
                    logging.warning("Skipping detail reuse cache lookup: %s", error)
            timings["detail_cache_lookup_seconds"] = elapsed_seconds(cache_lookup_started_at)

            detail_started_at = time.perf_counter()
            merged_listings, failed_detail_urls, detail_attempted, detail_succeeded = await enrich_listings(
                context,
                summaries,
                detail_limit=min(limits.detail_limit, len(summaries)),
                detail_concurrency=limits.detail_concurrency,
                detail_pause_min=limits.detail_pause_min,
                detail_pause_max=limits.detail_pause_max,
                block_detail_assets=limits.block_detail_assets,
                existing_listing_rows=existing_listing_rows,
            )
            timings["detail_enrichment_seconds"] = elapsed_seconds(detail_started_at)
            timings["total_seconds"] = elapsed_seconds(scrape_started_at)

            logging.info(
                "Detail scraping summary: %s attempted, %s succeeded, %s failed",
                detail_attempted,
                detail_succeeded,
                len(failed_detail_urls),
            )
            if failed_detail_urls:
                logging.warning("Failed detail URLs: %s", failed_detail_urls)
            logging.info("Scrape timings: %s", timings)

            await context.close()
            return {
                "listing_summaries": summaries,
                "listings": merged_listings,
                "results_count": results_count,
                "summary_count": len(summaries),
                "detail_attempted": detail_attempted,
                "detail_succeeded": detail_succeeded,
                "failed_detail_urls": failed_detail_urls,
                "timings": timings,
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
        load_dotenv()
        args = parse_args()
        criteria = collect_search_criteria(args)
        limits = collect_scrape_limits(args)
        supabase_config = get_supabase_config(args)
        run_started_at = datetime.utcnow().isoformat(timespec="seconds") + "Z"
        scrape_result = await scrape_listings(criteria, limits)
        run_finished_at = datetime.utcnow().isoformat(timespec="seconds") + "Z"
        payload = build_run_payload(
            criteria,
            limits,
            scrape_result,
            run_started_at=run_started_at,
            run_finished_at=run_finished_at,
        )
        output_path = save_results(payload)
        if supabase_config is not None:
            save_to_supabase(supabase_config, payload)
        logging.info("Scrape completed successfully")
        print(f"\nSaved JSON: {output_path}")
        if not args.no_print_listings:
            print_listings(scrape_result["listings"])
        return 0
    except ValueError as error:
        logging.error("%s", error)
        return 1
    except KeyboardInterrupt:
        logging.error("Scrape cancelled by user")
        return 0
    except Exception as error:
        logging.error("Scrape finished with errors: %s", error)
        return 1


def main() -> int:
    return asyncio.run(async_main())


if __name__ == "__main__":
    sys.exit(main())
