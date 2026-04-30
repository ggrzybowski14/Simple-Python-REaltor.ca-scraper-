from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import uuid
import hashlib
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from threading import Lock, Thread
from typing import Any
from urllib import error, parse, request

from flask import Flask, abort, jsonify, redirect, render_template, request as flask_request, url_for

from ai_underwriting import (
    build_market_appreciation_gap_payload,
    build_market_appreciation_gap_prompt_text,
    build_market_rental_gap_payload,
    build_market_rental_gap_prompt_text,
    build_rent_ai_payload,
    build_rent_ai_prompt_text,
    call_openai_market_appreciation_gap_estimate,
    call_openai_market_rental_gap_estimate,
    call_openai_researched_json,
    call_openai_rent_suggestions,
)
from crea_hpi import SERIES_KEY_BY_PROPERTY_TYPE, format_signal_label
from investment import (
    build_defaults_snapshot_from_form,
    calculate_underwriting,
    estimate_rule_based_insurance_monthly,
    estimate_rule_based_utilities_monthly,
    estimate_smart_reserve_percentages,
    format_currency,
    format_percent,
    get_listing_override_metadata_keys,
    merge_investment_defaults,
    parse_form_number,
)
from market_data import (
    build_market_profile_from_saved_search,
    find_market_reference_match,
    get_appreciation_proxy_market,
    get_market_seed_bootstrap_payload,
    get_rental_property_type_label,
    hydrate_defaults_with_market_data,
    infer_province,
    normalize_market_key,
)
from scraper import load_dotenv


APP_ROOT = Path(__file__).parent
LOCAL_JOB_LOG_DIR = APP_ROOT / "artifacts" / "web_jobs"
DEFAULT_MAX_PAGES = 10
DEFAULT_MAX_LISTINGS = 100
DEFAULT_DETAIL_LIMIT = DEFAULT_MAX_LISTINGS
DEFAULT_DETAIL_CONCURRENCY = 6
DEFAULT_DETAIL_PAUSE_MIN = 0.2
DEFAULT_DETAIL_PAUSE_MAX = 0.5
DEFAULT_BLOCK_DETAIL_ASSETS = True
PROPERTY_TYPE_OPTIONS = ["house", "apartment", "condo"]
SCRAPE_JOBS: dict[str, dict[str, Any]] = {}
SCRAPE_JOBS_LOCK = Lock()
AI_BUY_BOX_CACHE: dict[str, dict[str, str]] = {}
AI_RENT_PREVIEWS: dict[int, dict[str, Any]] = {}
LISTING_ANALYSIS_RUNS: dict[int, dict[str, Any]] = {}
DEFAULT_BUY_BOX_AI_SCREENS = [
    {"key": "screen_1", "name": "AI Prompt 1", "goal": "", "enabled": False},
    {"key": "screen_2", "name": "AI Prompt 2", "goal": "", "enabled": False},
]
BUY_BOX_RESEARCH_TERMS = (
    "allowed",
    "bylaw",
    "by-law",
    "carriage",
    "crime",
    "flood",
    "legal",
    "neighborhood",
    "neighbourhood",
    "nice area",
    "permit",
    "safe",
    "safety",
    "school",
    "subdiv",
    "transit",
    "walkable",
    "walkability",
    "wildfire",
    "zoning",
)

LISTING_UNDERWRITING_OVERRIDE_KEYS = [
    "market_rent_monthly",
    "down_payment_percent",
    "interest_rate_percent",
    "amortization_years",
    "closing_cost_percent",
    "vacancy_percent",
    "maintenance_percent_of_rent",
    "capex_percent_of_rent",
    "management_percent_of_rent",
    "insurance_monthly",
    "utilities_monthly",
    "other_monthly",
]


def build_listing_underwriting_override_updates(form_data: Any) -> dict[str, Any]:
    updates: dict[str, Any] = {}
    for key in LISTING_UNDERWRITING_OVERRIDE_KEYS:
        value = parse_form_number(form_data.get(key))
        source_key, confidence_key, help_text_key = get_listing_override_metadata_keys(key)
        if value is None:
            updates[key] = None
            updates[source_key] = None
            updates[confidence_key] = None
            updates[help_text_key] = None
            continue
        updates[key] = value
        updates[source_key] = "listing_override"
        updates[confidence_key] = "medium"
        updates[help_text_key] = "Saved listing-specific underwriting override."
    return updates


def annotate_listing_favorites(
    listings: list[dict[str, Any]],
    overrides_by_listing_id: dict[int, dict[str, Any]],
) -> list[dict[str, Any]]:
    for listing in listings:
        listing_id = normalize_listing_id(listing.get("listing_id"))
        overrides = overrides_by_listing_id.get(listing_id or -1, {})
        listing["is_favorite"] = bool(overrides.get("favorite"))
    return listings

MARKET_METRIC_DEFINITIONS = {
    "population": {"label": "Population", "format": "integer"},
    "population_growth_percent": {"label": "Population Growth", "format": "percent1"},
    "unemployment_rate_percent": {"label": "Unemployment Rate", "format": "percent1"},
    "median_household_income": {"label": "Median Household Income", "format": "currency0"},
}

MARKET_RENTAL_CARD_TYPES = ["apartment", "townhouse", "condo_apartment", "single_family"]
MARKET_RENTAL_BEDROOM_OPTIONS = [1, 2, 3, 4, 5]


@dataclass
class SupabaseReadConfig:
    url: str
    key: str


def parse_optional_int(value: Any) -> int | None:
    if value is None:
        return None
    cleaned = str(value).strip()
    if not cleaned:
        return None
    try:
        return int(cleaned.replace(",", ""))
    except ValueError:
        return None


def parse_market_bedroom_filter(value: Any, *, default: int | None = 2) -> int | None:
    if value is None or str(value).strip() == "":
        return default
    cleaned = str(value).strip().lower()
    if cleaned in {"all", "average", "avg"}:
        return None
    if cleaned in {"5+", "5 plus", "5plus", "5_plus"}:
        return 5
    parsed = parse_optional_int(cleaned)
    if parsed in MARKET_RENTAL_BEDROOM_OPTIONS:
        return parsed
    return default


def format_bedroom_option_label(bedroom_count: int | None) -> str:
    if bedroom_count is None:
        return "Avg"
    if bedroom_count >= 5:
        return "5+"
    return str(bedroom_count)


def build_market_rental_review_links(
    market_profile: dict[str, Any],
    property_type: str,
    bedroom_count: int | None,
) -> list[dict[str, str]]:
    market_name = market_profile.get("market_name") or market_profile.get("market_key") or ""
    province = market_profile.get("province") or ""
    property_label = get_rental_property_type_label(property_type)
    bedroom_label = f"{bedroom_count} bedroom" if isinstance(bedroom_count, int) else "rental"
    base_query = " ".join(part for part in [market_name, province, bedroom_label, property_label, "rent"] if part)
    source_queries = [
        ("Craigslist", f"site:craigslist.org {base_query}"),
        ("Rentals.ca", f"site:rentals.ca {base_query}"),
        ("Zumper", f"site:zumper.com {base_query}"),
        ("PadMapper", f"site:padmapper.com {base_query}"),
        ("liv.rent", f"site:liv.rent {base_query}"),
        ("Kijiji", f"site:kijiji.ca {base_query}"),
        ("Local property managers", f"{base_query} property management rentals"),
    ]
    return [
        {
            "name": name,
            "url": f"https://www.google.com/search?{parse.urlencode({'q': query})}",
        }
        for name, query in source_queries
    ]


def parse_iso_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    normalized = value.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        return None


def parse_price_amount(value: str | None) -> int | None:
    if not value:
        return None
    digits = "".join(ch for ch in value if ch.isdigit())
    return int(digits) if digits else None


def normalize_listing_id(value: Any) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def normalize_keyword_list(value: str | None) -> list[str]:
    if not value:
        return []
    raw_parts = [part.strip().lower() for part in value.replace("\n", ",").split(",")]
    return [part for part in raw_parts if part]


def humanize_market_name(value: str | None) -> str:
    return (value or "Unknown market").strip()


def derive_market_profile_from_saved_search(saved_search: dict[str, Any]) -> dict[str, Any]:
    return build_market_profile_from_saved_search(saved_search, status="placeholder", notes=None)


def ensure_market_profile(config: SupabaseReadConfig, saved_search: dict[str, Any]) -> dict[str, Any]:
    profile = build_market_profile_from_saved_search(
        saved_search,
        status="discovered",
        notes=(
            "Auto-created from a scraped saved search. Structured metrics, rent growth, and appreciation "
            "series can be populated later as market-context coverage expands."
        ),
    )
    try:
        result = supabase_post(
            config,
            "market_profiles",
            query={"on_conflict": "market_key"},
            payload=[profile],
            prefer="resolution=merge-duplicates,return=representation",
        )
    except RuntimeError:
        return profile
    if isinstance(result, list) and result:
        persisted = result[0]
    else:
        persisted = profile
    return bootstrap_market_context(config, saved_search, fallback_profile=persisted)


def bootstrap_market_context(
    config: SupabaseReadConfig,
    saved_search: dict[str, Any],
    *,
    fallback_profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    bundle = get_market_seed_bootstrap_payload(saved_search)
    if bundle is None:
        return fallback_profile or build_market_profile_from_saved_search(saved_search, status="discovered", notes=None)

    profile_payload = bundle["profile"]
    try:
        profile_result = supabase_post(
            config,
            "market_profiles",
            query={"on_conflict": "market_key"},
            payload=[profile_payload],
            prefer="resolution=merge-duplicates,return=representation",
        )
        if bundle["metrics"]:
            supabase_post(
                config,
                "market_metrics",
                query={"on_conflict": "market_key,metric_key"},
                payload=bundle["metrics"],
                prefer="resolution=merge-duplicates,return=representation",
            )
        if bundle["series"]:
            supabase_post(
                config,
                "market_metric_series",
                query={"on_conflict": "market_key,series_key,point_date"},
                payload=bundle["series"],
                prefer="resolution=merge-duplicates,return=representation",
            )
    except RuntimeError:
        return fallback_profile or profile_payload

    if isinstance(profile_result, list) and profile_result:
        return profile_result[0]
    return profile_payload


def build_market_index(
    config: SupabaseReadConfig,
    saved_searches: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    markets_by_key: dict[str, dict[str, Any]] = {}
    for search in saved_searches:
        derived_profile = derive_market_profile_from_saved_search(search)
        market_key = derived_profile["market_key"]
        market = markets_by_key.get(market_key)
        if market is None:
            persisted_profile = fetch_market_profile(config, market_key)
            if persisted_profile and persisted_profile.get("status") == "discovered":
                market = bootstrap_market_context(config, search, fallback_profile=persisted_profile)
            else:
                market = persisted_profile or ensure_market_profile(config, search)
            market = {
                **market,
                "saved_searches": [],
                "representative_saved_search_id": search["id"],
            }
            markets_by_key[market_key] = market
        market["saved_searches"].append(search)
    return sorted(markets_by_key.values(), key=lambda market: market["market_name"].lower())


def format_market_metric_value(metric: dict[str, Any]) -> str:
    value = metric.get("value_numeric")
    format_name = metric.get("format")
    if value is None:
        return metric.get("value_text") or "—"
    numeric_value = float(value)
    if format_name == "currency0":
        return format_currency(numeric_value)
    if format_name == "percent1":
        return format_percent(numeric_value, digits=1)
    if format_name == "integer":
        return f"{int(round(numeric_value)):,}"
    return str(value)


def get_saved_buy_box_settings(saved_search: dict[str, Any]) -> dict[str, Any]:
    snapshot = saved_search.get("search_snapshot")
    if not isinstance(snapshot, dict):
        return {}
    saved_buy_box = snapshot.get("buy_box")
    return saved_buy_box if isinstance(saved_buy_box, dict) else {}


def has_saved_buy_box_settings(saved_buy_box: dict[str, Any]) -> bool:
    if not saved_buy_box:
        return False
    saved_ai_screens = saved_buy_box.get("ai_screens")
    has_ai_screen = any(
        bool((screen.get("goal") or "").strip())
        for screen in saved_ai_screens
        if isinstance(screen, dict)
    ) if isinstance(saved_ai_screens, list) else False
    return any(
        [
            saved_buy_box.get("applied"),
            saved_buy_box.get("max_price") is not None,
            saved_buy_box.get("beds_min") is not None,
            bool((saved_buy_box.get("property_type") or "").strip()),
            bool((saved_buy_box.get("required_keywords_raw") or "").strip()),
            bool((saved_buy_box.get("ai_goal_raw") or "").strip()),
            has_ai_screen,
        ]
    )


def normalize_ai_screen(raw_screen: dict[str, Any], index: int) -> dict[str, Any]:
    fallback = DEFAULT_BUY_BOX_AI_SCREENS[index]
    goal = (raw_screen.get("goal") or "").strip()
    return {
        "key": fallback["key"],
        "name": fallback["name"],
        "goal": goal,
        "enabled": bool(raw_screen.get("enabled")) and bool(goal),
    }


def get_saved_ai_screens(saved_buy_box: dict[str, Any]) -> list[dict[str, Any]]:
    raw_screens = saved_buy_box.get("ai_screens")
    if isinstance(raw_screens, list):
        normalized = [
            normalize_ai_screen(raw_screen if isinstance(raw_screen, dict) else {}, index)
            for index, raw_screen in enumerate(raw_screens[:2])
        ]
        while len(normalized) < 2:
            normalized.append(dict(DEFAULT_BUY_BOX_AI_SCREENS[len(normalized)]))
        return normalized
    legacy_goal = (saved_buy_box.get("ai_goal_raw") or "").strip()
    screens = [dict(screen) for screen in DEFAULT_BUY_BOX_AI_SCREENS]
    if legacy_goal:
        screens[0]["goal"] = legacy_goal
        screens[0]["enabled"] = True
    return screens


def build_ai_screens_from_args(args, saved_buy_box: dict[str, Any], query_applied: bool) -> list[dict[str, Any]]:
    if not query_applied:
        return get_saved_ai_screens(saved_buy_box)
    screens: list[dict[str, Any]] = []
    for index, fallback in enumerate(DEFAULT_BUY_BOX_AI_SCREENS, start=1):
        goal = (args.get(f"buy_box_ai_screen_{index}_goal") or "").strip()
        screens.append(
            {
                "key": fallback["key"],
                "name": fallback["name"],
                "goal": goal,
                "enabled": bool(args.get(f"buy_box_ai_screen_{index}_enabled")) and bool(goal),
            }
        )
    return screens


def build_buy_box_criteria(args, saved_search: dict[str, Any]) -> dict[str, Any]:
    saved_buy_box = get_saved_buy_box_settings(saved_search)
    query_applied = bool(args.get("apply_buy_box"))
    persisted_applied = has_saved_buy_box_settings(saved_buy_box)
    ai_screens = build_ai_screens_from_args(args, saved_buy_box, query_applied)
    criteria = {
        "max_price": (
            parse_optional_int(args.get("buy_box_max_price"))
            if query_applied
            else saved_buy_box.get("max_price")
        ),
        "beds_min": (
            parse_optional_int(args.get("buy_box_beds_min"))
            if query_applied
            else saved_buy_box.get("beds_min")
        ),
        "property_type": (
            (args.get("buy_box_property_type") or "").strip().lower()
            if query_applied
            else (saved_buy_box.get("property_type") or "")
        ),
        "required_keywords_raw": (
            (args.get("buy_box_keywords") or "").strip()
            if query_applied
            else (saved_buy_box.get("required_keywords_raw") or "")
        ),
        "required_keywords": (
            normalize_keyword_list(args.get("buy_box_keywords") or "")
            if query_applied
            else normalize_keyword_list(saved_buy_box.get("required_keywords_raw"))
        ),
        "ai_goal_raw": (
            (args.get("buy_box_ai_goal") or "").strip()
            if query_applied
            else (saved_buy_box.get("ai_goal_raw") or "")
        ),
        "ai_screens": ai_screens,
        "ai_enabled": any(screen["enabled"] for screen in ai_screens),
        "applied": persisted_applied if not query_applied else False,
    }
    criteria["applied"] = bool(
        criteria["applied"]
        or criteria.get("max_price") is not None
        or criteria.get("beds_min") is not None
        or criteria.get("property_type")
        or criteria.get("required_keywords")
        or criteria.get("ai_enabled")
    )
    return criteria


def analyze_listing_against_buy_box(listing: dict[str, Any], criteria: dict[str, Any]) -> dict[str, Any]:
    reasons: list[str] = []
    listing_price = parse_price_amount(listing.get("price"))
    listing_beds = listing.get("bedrooms")
    listing_type_parts = [
        (listing.get("property_type") or "").strip().lower(),
        (listing.get("building_type") or "").strip().lower(),
    ]
    listing_type = " ".join(part for part in listing_type_parts if part)
    description = (listing.get("listing_description") or "").lower()

    if criteria.get("max_price") is not None:
        if listing_price is None:
            reasons.append("Missing price")
        elif listing_price > criteria["max_price"]:
            reasons.append(f"Price exceeds ${criteria['max_price']:,}")

    if criteria.get("beds_min") is not None:
        if listing_beds is None:
            reasons.append("Missing bedroom count")
        elif listing_beds < criteria["beds_min"]:
            reasons.append(f"Fewer than {criteria['beds_min']} beds")

    if criteria.get("property_type"):
        expected_type = criteria["property_type"]
        property_type_aliases = {
            "house": ["house", "single family"],
            "apartment": ["apartment"],
            "condo": ["condo", "apartment"],
        }
        if expected_type == "house":
            building_type = (listing.get("building_type") or "").strip().lower()
            excluded_house_types = [
                "duplex",
                "triplex",
                "row / townhouse",
                "row/townhouse",
                "townhouse",
                "half duplex",
                "fourplex",
            ]
            if any(label in building_type for label in excluded_house_types):
                reasons.append(f"Building type is {listing.get('building_type')}")
        aliases = property_type_aliases.get(expected_type, [expected_type])
        if not any(alias in listing_type for alias in aliases):
            reasons.append(f"Type is not {expected_type}")

    missing_keywords = [
        keyword for keyword in criteria.get("required_keywords", [])
        if keyword not in description
    ]
    if missing_keywords:
        reasons.append(f"Missing keywords: {', '.join(missing_keywords)}")

    return {
        "matched": not reasons,
        "reasons": reasons or ["Matches all buy-box rules"],
    }


def buy_box_goal_needs_research(goal: str) -> bool:
    normalized = goal.strip().lower()
    return any(term in normalized for term in BUY_BOX_RESEARCH_TERMS)


def build_ai_buy_box_cache_key(goal: str, listing: dict[str, Any], *, mode: str = "description") -> str:
    payload = "\n".join(
        [
            mode,
            goal.strip(),
            str(listing.get("listing_id") or ""),
            listing.get("address") or "",
            listing.get("listing_description") or "",
        ]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def build_researched_buy_box_payload(
    goal: str,
    listings: list[dict[str, Any]],
    saved_search: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "goal": goal,
        "saved_search": {
            "saved_search_id": (saved_search or {}).get("id"),
            "name": (saved_search or {}).get("name"),
            "location": (saved_search or {}).get("location"),
            "property_type": (saved_search or {}).get("property_type"),
            "beds_min": (saved_search or {}).get("beds_min"),
            "max_price": (saved_search or {}).get("max_price"),
        },
        "listings": [
            {
                "listing_id": listing.get("listing_id"),
                "address": listing.get("address"),
                "url": listing.get("url"),
                "price": listing.get("price"),
                "bedrooms": listing.get("bedrooms"),
                "bathrooms": listing.get("bathrooms"),
                "property_type": listing.get("property_type"),
                "building_type": listing.get("building_type"),
                "square_feet": listing.get("square_feet"),
                "land_size": listing.get("land_size"),
                "built_in": listing.get("built_in"),
                "zoning_type": listing.get("zoning_type"),
                "listing_description": listing.get("listing_description") or "",
            }
            for listing in listings
        ],
    }


def call_openai_buy_box_assessment(goal: str, listings: list[dict[str, Any]]) -> dict[int, dict[str, str]]:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key or not listings:
        return {}

    model = os.getenv("OPENAI_BUY_BOX_MODEL", "gpt-5.4-mini")
    user_payload = {
        "goal": goal,
        "listings": [
            {
                "listing_id": listing["listing_id"],
                "address": listing.get("address"),
                "description": listing.get("listing_description") or "",
            }
            for listing in listings
        ],
    }
    body = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You analyze scraped real-estate listing descriptions for investment screening. "
                    "Assess whether each listing satisfies the user's qualitative criterion. "
                    "Return only structured JSON."
                ),
            },
            {
                "role": "user",
                "content": json.dumps(user_payload),
            },
        ],
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "buy_box_ai_assessment",
                "strict": True,
                "schema": {
                    "type": "object",
                    "properties": {
                        "assessments": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "listing_id": {"type": "integer"},
                                    "verdict": {"type": "string", "enum": ["likely", "maybe", "no"]},
                                    "reason": {"type": "string"},
                                },
                                "required": ["listing_id", "verdict", "reason"],
                                "additionalProperties": False,
                            },
                        }
                    },
                    "required": ["assessments"],
                    "additionalProperties": False,
                },
            },
        },
    }

    req = request.Request(
        "https://api.openai.com/v1/chat/completions",
        data=json.dumps(body).encode("utf-8"),
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )
    try:
        with request.urlopen(req, timeout=60) as response:
            raw = response.read().decode("utf-8", errors="replace")
    except error.HTTPError as exc:
        details = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"OpenAI request failed with status {exc.code}: {details}") from exc
    except error.URLError as exc:
        raise RuntimeError(f"OpenAI request failed: {exc.reason}") from exc

    payload = json.loads(raw)
    content = payload["choices"][0]["message"]["content"]
    parsed = json.loads(content)
    assessment_by_listing_id: dict[int, dict[str, str]] = {}
    for item in parsed.get("assessments", []):
        listing_id = item.get("listing_id")
        verdict = item.get("verdict")
        reason = item.get("reason")
        if isinstance(listing_id, int) and isinstance(verdict, str) and isinstance(reason, str):
            assessment_by_listing_id[listing_id] = {"verdict": verdict, "reason": reason}
    return assessment_by_listing_id


def call_openai_researched_buy_box_assessment(
    goal: str,
    listings: list[dict[str, Any]],
    saved_search: dict[str, Any] | None = None,
) -> dict[int, dict[str, Any]]:
    if not listings:
        return {}
    schema = {
        "type": "object",
        "properties": {
            "research_summary": {"type": "string"},
            "source_names": {"type": "array", "items": {"type": "string"}},
            "source_urls": {"type": "array", "items": {"type": "string"}},
            "assessments": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "listing_id": {"type": "integer"},
                        "verdict": {"type": "string", "enum": ["likely", "maybe", "no"]},
                        "reason": {"type": "string"},
                    },
                    "required": ["listing_id", "verdict", "reason"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["research_summary", "source_names", "source_urls", "assessments"],
        "additionalProperties": False,
    }
    ai_result = call_openai_researched_json(
        system_text=(
            "You screen Canadian residential real-estate listings against a user's buy-box criterion. "
            "Use web search to research the saved-search market and criterion once, then apply that shared "
            "market context across the provided listings. Do not perform parcel-specific due diligence or claim "
            "exact zoning, crime, school-catchment, floodplain, or permit conclusions for a specific address. "
            "For property-specific unknowns, use maybe and say what should be verified in listing-detail chat "
            "or manual due diligence. Return only structured JSON."
        ),
        prompt_text=(
            "Research the market-level context needed for this buy-box screen, then classify each listing as "
            "likely, maybe, or no. Keep reasons short and cite the shared sources in source_names/source_urls."
        ),
        payload=build_researched_buy_box_payload(goal, listings, saved_search),
        schema_name="researched_buy_box_assessment",
        schema=schema,
    )
    parsed = ai_result["parsed_response"]
    source_names = parsed.get("source_names", []) if isinstance(parsed, dict) else []
    source_urls = parsed.get("source_urls", []) if isinstance(parsed, dict) else []
    assessment_by_listing_id: dict[int, dict[str, Any]] = {}
    for item in parsed.get("assessments", []) if isinstance(parsed, dict) else []:
        listing_id = item.get("listing_id")
        verdict = item.get("verdict")
        reason = item.get("reason")
        if isinstance(listing_id, int) and isinstance(verdict, str) and isinstance(reason, str):
            assessment_by_listing_id[listing_id] = {
                "verdict": verdict,
                "reason": reason,
                "source_names": source_names,
                "source_urls": source_urls,
                "research_summary": parsed.get("research_summary", ""),
                "research_mode": "market_context",
            }
    return assessment_by_listing_id


def apply_ai_buy_box(
    goal: str,
    listings: list[dict[str, Any]],
    *,
    saved_search: dict[str, Any] | None = None,
    allow_research: bool = True,
) -> tuple[dict[int, dict[str, Any]], str | None]:
    if not goal.strip():
        return {}, None
    if not os.getenv("OPENAI_API_KEY"):
        return {}, "OPENAI_API_KEY is not configured for AI buy-box analysis."

    mode = "research" if allow_research and buy_box_goal_needs_research(goal) else "description"
    cached_results: dict[int, dict[str, str]] = {}
    uncached_listings: list[dict[str, Any]] = []
    uncached_keys: dict[int, str] = {}

    for listing in listings:
        cache_key = build_ai_buy_box_cache_key(goal, listing, mode=mode)
        cached = AI_BUY_BOX_CACHE.get(cache_key)
        if cached:
            cached_results[listing["listing_id"]] = cached
        else:
            uncached_listings.append(listing)
            uncached_keys[listing["listing_id"]] = cache_key

    if uncached_listings:
        if mode == "research":
            fresh_results = call_openai_researched_buy_box_assessment(goal, uncached_listings, saved_search)
        else:
            fresh_results = call_openai_buy_box_assessment(goal, uncached_listings)
        for listing_id, result in fresh_results.items():
            cache_key = uncached_keys.get(listing_id)
            if cache_key:
                AI_BUY_BOX_CACHE[cache_key] = result
        cached_results.update(fresh_results)

    return cached_results, None


def analyze_active_listings(
    active_listings: list[dict[str, Any]],
    criteria: dict[str, Any],
    *,
    saved_search: dict[str, Any] | None = None,
    allow_research: bool = True,
) -> dict[str, Any]:
    structured_matches: list[dict[str, Any]] = []
    structured_unmatched: list[dict[str, Any]] = []

    for listing in active_listings:
        result = analyze_listing_against_buy_box(listing, criteria)
        enriched_listing = dict(listing)
        enriched_listing["buy_box_match"] = result["matched"]
        enriched_listing["buy_box_reasons"] = result["reasons"]
        if result["matched"]:
            structured_matches.append(enriched_listing)
        else:
            structured_unmatched.append(enriched_listing)

    enabled_ai_screens = [
        screen for screen in criteria.get("ai_screens", [])
        if isinstance(screen, dict) and screen.get("enabled") and (screen.get("goal") or "").strip()
    ]
    ai_results_by_screen: dict[str, dict[int, dict[str, str]]] = {}
    ai_error: str | None = None
    if criteria.get("applied"):
        for screen in enabled_ai_screens:
            try:
                screen_results, screen_error = apply_ai_buy_box(
                    screen["goal"],
                    structured_matches,
                    saved_search=saved_search,
                    allow_research=allow_research,
                )
                if screen_error:
                    ai_error = screen_error
                ai_results_by_screen[screen["key"]] = screen_results
            except Exception as exc:
                ai_error = str(exc)
                ai_results_by_screen[screen["key"]] = {}

    matched: list[dict[str, Any]] = []
    maybe: list[dict[str, Any]] = []
    unmatched: list[dict[str, Any]] = list(structured_unmatched)

    for listing in structured_matches:
        if enabled_ai_screens:
            screen_results: list[dict[str, str]] = []
            for screen in enabled_ai_screens:
                ai_result = ai_results_by_screen.get(screen["key"], {}).get(listing["listing_id"])
                if ai_result:
                    normalized_verdict = (ai_result.get("verdict") or "no").strip().lower()
                    screen_result = {
                        "key": screen["key"],
                        "name": screen["name"],
                        "verdict": normalized_verdict,
                        "reason": ai_result.get("reason") or "",
                        "source_names": ai_result.get("source_names", []),
                        "source_urls": ai_result.get("source_urls", []),
                        "research_summary": ai_result.get("research_summary", ""),
                        "research_mode": ai_result.get("research_mode", ""),
                    }
                    screen_results.append(screen_result)
                    listing["buy_box_reasons"] = listing["buy_box_reasons"] + [
                        f"{screen['name']}: {normalized_verdict} - {screen_result['reason']}"
                    ]
                elif ai_error:
                    screen_results.append(
                        {
                            "key": screen["key"],
                            "name": screen["name"],
                            "verdict": "maybe",
                            "reason": f"AI unavailable: {ai_error}",
                        }
                    )
                    listing["buy_box_reasons"] = listing["buy_box_reasons"] + [
                        f"{screen['name']}: AI unavailable - {ai_error}"
                    ]
                else:
                    screen_results.append(
                        {
                            "key": screen["key"],
                            "name": screen["name"],
                            "verdict": "no",
                            "reason": "AI analysis unavailable",
                        }
                    )
                    listing["buy_box_reasons"] = listing["buy_box_reasons"] + [
                        f"{screen['name']}: AI analysis unavailable"
                    ]
            likely_count = sum(1 for result in screen_results if result["verdict"] == "likely")
            maybe_count = sum(1 for result in screen_results if result["verdict"] == "maybe")
            listing["ai_screen_results"] = screen_results
            listing["ai_screen_likely_count"] = likely_count
            listing["ai_screen_total"] = len(screen_results)
            if likely_count == len(screen_results):
                listing["ai_buy_box_verdict"] = "likely"
                listing["ai_buy_box_reason"] = "All enabled AI screens matched."
                matched.append(listing)
            elif likely_count > 0 or maybe_count > 0:
                listing["buy_box_match"] = False
                listing["ai_buy_box_verdict"] = "maybe"
                listing["ai_buy_box_reason"] = f"{likely_count} of {len(screen_results)} enabled AI screens matched."
                maybe.append(listing)
            else:
                listing["buy_box_match"] = False
                listing["ai_buy_box_verdict"] = "no"
                listing["ai_buy_box_reason"] = "No enabled AI screens matched."
                unmatched.append(listing)
        else:
            matched.append(listing)

    return {
        "matched": matched,
        "maybe": maybe,
        "unmatched": unmatched,
        "ai_error": ai_error,
    }


def analyze_listing_for_detail(listing: dict[str, Any], criteria: dict[str, Any]) -> dict[str, Any] | None:
    if not criteria.get("applied"):
        return None
    analysis = analyze_active_listings([listing], criteria, allow_research=False)
    for bucket_name in ("matched", "maybe", "unmatched"):
        bucket = analysis[bucket_name]
        if bucket:
            analyzed_listing = bucket[0]
            return {
                "bucket": bucket_name,
                "label": bucket_name.title(),
                "reasons": analyzed_listing.get("buy_box_reasons", []),
                "ai_verdict": analyzed_listing.get("ai_buy_box_verdict"),
                "ai_reason": analyzed_listing.get("ai_buy_box_reason"),
                "ai_screen_results": analyzed_listing.get("ai_screen_results", []),
                "ai_screen_likely_count": analyzed_listing.get("ai_screen_likely_count"),
                "ai_screen_total": analyzed_listing.get("ai_screen_total"),
                "ai_error": analysis.get("ai_error"),
            }
    return None


def serialize_buy_box_criteria(criteria: dict[str, Any]) -> dict[str, Any]:
    return {
        "applied": bool(criteria.get("applied")),
        "max_price": criteria.get("max_price"),
        "beds_min": criteria.get("beds_min"),
        "property_type": criteria.get("property_type") or "",
        "required_keywords_raw": criteria.get("required_keywords_raw") or "",
        "ai_goal_raw": criteria.get("ai_goal_raw") or "",
        "ai_screens": [
            {
                "key": screen.get("key"),
                "name": screen.get("name") or "",
                "goal": screen.get("goal") or "",
                "enabled": bool(screen.get("enabled")),
            }
            for screen in criteria.get("ai_screens", [])
            if isinstance(screen, dict)
        ],
    }


def build_combined_analysis_verdict(
    buy_box: dict[str, Any] | None,
    underwriting_verdict: dict[str, str],
) -> dict[str, str]:
    buy_box_label = (buy_box or {}).get("label")
    underwriting_slug = underwriting_verdict.get("slug")

    if underwriting_slug == "weak":
        return {
            "label": "Reject",
            "slug": "reject",
            "reason": "Fails the underwriting floor.",
        }
    if buy_box_label == "Unlikely" and underwriting_slug == "promising":
        return {
            "label": "Review",
            "slug": "review",
            "reason": "Strong underwriting, but outside the buy box.",
        }
    if buy_box_label == "Unlikely":
        return {
            "label": "Reject",
            "slug": "reject",
            "reason": "Fails the buy box.",
        }
    if buy_box_label == "Maybe" or underwriting_slug == "borderline":
        return {
            "label": "Review",
            "slug": "review",
            "reason": "One analysis layer needs a closer look.",
        }
    if buy_box_label == "Likely" and underwriting_slug == "promising":
        return {
            "label": "Strong",
            "slug": "strong",
            "reason": "Passes both buy-box and underwriting checks.",
        }
    if buy_box is None and underwriting_slug == "promising":
        return {
            "label": "Strong",
            "slug": "strong",
            "reason": "Promising underwriting; no buy box is active.",
        }
    return {
        "label": "Review",
        "slug": "review",
        "reason": "Analysis is incomplete or mixed.",
    }


def build_underwriting_rows(
    active_listings: list[dict[str, Any]],
    defaults_snapshot: dict[str, dict[str, Any]],
    overrides_by_listing_id: dict[int, dict[str, Any]] | None = None,
    buy_box_results_by_listing_id: dict[int, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for listing in active_listings:
        listing_id = normalize_listing_id(listing.get("listing_id"))
        listing_overrides = (overrides_by_listing_id or {}).get(listing_id or -1, {})
        analysis = calculate_underwriting(listing, defaults_snapshot, listing_overrides=listing_overrides)
        listing_buy_box = (buy_box_results_by_listing_id or {}).get(listing["listing_id"])
        normalized_buy_box = normalize_buy_box_bucket(listing_buy_box)
        rows.append(
            {
                "listing": listing,
                "metrics": analysis["metrics"],
                "warnings": analysis["warnings"],
                "verdict": analysis["verdict"],
                "effective_assumptions": analysis["effective_assumptions"],
                "buy_box": normalized_buy_box,
                "combined_verdict": build_combined_analysis_verdict(normalized_buy_box, analysis["verdict"]),
                "overrides": listing_overrides,
            }
        )
    combined_rank = {"Strong": 0, "Review": 1, "Reject": 2}
    bucket_rank = {"Likely": 0, "Maybe": 1, "Unlikely": 2, "All Listings": 3}
    return sorted(
        rows,
        key=lambda row: (
            combined_rank.get(row.get("combined_verdict", {}).get("label", "Review"), 9),
            bucket_rank.get((row.get("buy_box") or {}).get("label", "All Listings"), 9),
            999999999 if row["metrics"].get("monthly_cash_flow") is None else -row["metrics"]["monthly_cash_flow"],
            999999999 if row["metrics"].get("rent_to_price_ratio") is None else -row["metrics"]["rent_to_price_ratio"],
            999999999 if row["metrics"].get("cap_rate") is None else -row["metrics"]["cap_rate"],
            row["listing"].get("address") or "",
        ),
    )


def get_saved_listing_analysis_state(saved_search: dict[str, Any]) -> dict[str, Any] | None:
    snapshot = saved_search.get("search_snapshot")
    if not isinstance(snapshot, dict):
        return None
    state = snapshot.get("latest_listing_analysis")
    return state if isinstance(state, dict) else None


def build_listing_analysis_state(
    saved_search_id: int,
    *,
    buy_box: dict[str, Any],
    defaults_snapshot: dict[str, dict[str, Any]],
    overrides_by_listing_id: dict[int, dict[str, Any]],
    buy_box_results_by_listing_id: dict[int, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "buy_box": buy_box,
        "defaults_snapshot": defaults_snapshot,
        "overrides_by_listing_id": {
            str(listing_id): overrides
            for listing_id, overrides in overrides_by_listing_id.items()
        },
        "buy_box_results_by_listing_id": {
            str(listing_id): result
            for listing_id, result in (buy_box_results_by_listing_id or {}).items()
        },
        "ran_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
    }


def set_listing_analysis_state(
    saved_search_id: int,
    *,
    buy_box: dict[str, Any],
    defaults_snapshot: dict[str, dict[str, Any]],
    overrides_by_listing_id: dict[int, dict[str, Any]],
    buy_box_results_by_listing_id: dict[int, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    state = build_listing_analysis_state(
        saved_search_id,
        buy_box=buy_box,
        defaults_snapshot=defaults_snapshot,
        overrides_by_listing_id=overrides_by_listing_id,
        buy_box_results_by_listing_id=buy_box_results_by_listing_id,
    )
    LISTING_ANALYSIS_RUNS[saved_search_id] = state
    return state


def clear_listing_analysis_state(saved_search_id: int) -> None:
    LISTING_ANALYSIS_RUNS.pop(saved_search_id, None)


def normalize_analysis_state_overrides(state: dict[str, Any] | None) -> dict[int, dict[str, Any]]:
    raw_overrides = (state or {}).get("overrides_by_listing_id")
    if not isinstance(raw_overrides, dict):
        return {}
    normalized: dict[int, dict[str, Any]] = {}
    for listing_id, overrides in raw_overrides.items():
        normalized_listing_id = normalize_listing_id(listing_id)
        if normalized_listing_id is None or not isinstance(overrides, dict):
            continue
        normalized[normalized_listing_id] = overrides
    return normalized


def normalize_analysis_state_buy_box_results(state: dict[str, Any] | None) -> dict[int, dict[str, Any]]:
    raw_results = (state or {}).get("buy_box_results_by_listing_id")
    if not isinstance(raw_results, dict):
        return {}
    normalized: dict[int, dict[str, Any]] = {}
    for listing_id, result in raw_results.items():
        normalized_listing_id = normalize_listing_id(listing_id)
        if normalized_listing_id is None or not isinstance(result, dict):
            continue
        normalized[normalized_listing_id] = result
    return normalized


def get_saved_listing_buy_box_result(saved_search: dict[str, Any], listing_id: int) -> dict[str, Any] | None:
    analysis_state = get_saved_listing_analysis_state(saved_search) or LISTING_ANALYSIS_RUNS.get(int(saved_search["id"]))
    saved_results = normalize_analysis_state_buy_box_results(analysis_state)
    return normalize_buy_box_bucket(saved_results.get(listing_id))


def buy_box_has_enabled_ai(buy_box: dict[str, Any] | None) -> bool:
    screens = (buy_box or {}).get("ai_screens")
    if not isinstance(screens, list):
        return False
    return any(
        isinstance(screen, dict)
        and bool(screen.get("enabled"))
        and bool((screen.get("goal") or "").strip())
        for screen in screens
    )


def hydrate_defaults_for_saved_search(
    config: SupabaseReadConfig,
    saved_search: dict[str, Any],
) -> tuple[dict[str, dict[str, Any]], dict[str, Any] | None]:
    base_defaults = fetch_saved_search_investment_defaults(config, int(saved_search["id"]))
    market_rows = fetch_market_reference_rows(config)
    market_match = find_market_reference_match(saved_search, market_rows)
    hydrated_defaults = hydrate_defaults_with_market_data(base_defaults, market_match)
    return hydrated_defaults, market_match


def build_buy_box_result_lookup(
    active_listings: list[dict[str, Any]],
    buy_box: dict[str, Any],
    *,
    saved_search: dict[str, Any] | None = None,
) -> dict[int, dict[str, Any]]:
    if not buy_box.get("applied"):
        return {}
    analysis = analyze_active_listings(active_listings, buy_box, saved_search=saved_search)
    lookup: dict[int, dict[str, Any]] = {}
    for bucket_name in ("matched", "maybe", "unmatched"):
        label = bucket_name.title()
        for listing in analysis[bucket_name]:
            listing_id = normalize_listing_id(listing.get("listing_id"))
            if listing_id is None:
                continue
            lookup[listing_id] = {
                "bucket": bucket_name,
                "label": label,
                "reasons": listing.get("buy_box_reasons", []),
                "ai_verdict": listing.get("ai_buy_box_verdict"),
                "ai_screen_results": listing.get("ai_screen_results", []),
                "ai_screen_likely_count": listing.get("ai_screen_likely_count"),
                "ai_screen_total": listing.get("ai_screen_total"),
            }
    return lookup


def normalize_buy_box_bucket(listing_buy_box: dict[str, Any] | None) -> dict[str, Any] | None:
    if not listing_buy_box:
        return None
    ai_verdict = (listing_buy_box.get("ai_verdict") or "").strip().lower()
    bucket = listing_buy_box.get("bucket")
    normalized = dict(listing_buy_box)
    if ai_verdict == "likely":
        normalized["label"] = "Likely"
    elif ai_verdict == "maybe":
        normalized["label"] = "Maybe"
    elif ai_verdict == "no":
        normalized["label"] = "Unlikely"
    elif bucket == "matched":
        normalized["label"] = "Likely"
    elif bucket == "maybe":
        normalized["label"] = "Maybe"
    else:
        normalized["label"] = "Unlikely"
    return normalized


def create_app() -> Flask:
    load_dotenv()
    app = Flask(__name__)
    app.config["SECRET_KEY"] = os.getenv("FLASK_SECRET_KEY", "local-real-estate-analyzer")

    @app.template_filter("currency")
    def currency_filter(value: float | None) -> str:
        return format_currency(value)

    @app.template_filter("percent1")
    def percent_filter(value: float | None) -> str:
        return format_percent(value, digits=1)

    @app.context_processor
    def inject_now() -> dict[str, Any]:
        return {"now": datetime.utcnow()}

    @app.route("/")
    def dashboard() -> str:
        config = get_supabase_read_config()
        saved_searches = fetch_saved_searches(config)
        recent_runs = fetch_recent_runs(config)
        local_jobs = list_scrape_jobs()
        started_job = None
        started_job_id = (flask_request.args.get("started") or "").strip()
        if started_job_id:
            started_job = get_scrape_job(started_job_id)
        latest_run = recent_runs[0] if recent_runs else None
        runs_by_saved_search = {}
        for run in recent_runs:
            runs_by_saved_search.setdefault(run["saved_search_id"], run)
        for search in saved_searches:
            search["latest_run"] = runs_by_saved_search.get(search["id"])
            search["updated_in_latest_run"] = bool(
                latest_run and latest_run.get("saved_search_id") == search["id"]
            )
            search["market_profile"] = derive_market_profile_from_saved_search(search)
        analyzed_markets = build_market_index(config, saved_searches)
        return render_template(
            "dashboard.html",
            saved_searches=saved_searches,
            recent_runs=recent_runs,
            local_jobs=local_jobs,
            started_job=started_job,
            analyzed_markets=analyzed_markets,
            property_type_options=PROPERTY_TYPE_OPTIONS,
        )

    @app.route("/favorites")
    def favorites() -> str:
        config = get_supabase_read_config()
        saved_searches = fetch_saved_searches(config)
        grouped_favorites: list[dict[str, Any]] = []
        for saved_search in saved_searches:
            active_listings = fetch_active_listings(config, int(saved_search["id"]))
            listing_ids = [
                listing_id
                for listing_id in (normalize_listing_id(listing.get("listing_id")) for listing in active_listings)
                if listing_id is not None
            ]
            overrides_by_listing_id = fetch_listing_investment_overrides(config, int(saved_search["id"]), listing_ids)
            favorite_listings = [
                listing for listing in annotate_listing_favorites(active_listings, overrides_by_listing_id)
                if listing.get("is_favorite")
            ]
            if favorite_listings:
                grouped_favorites.append(
                    {
                        "saved_search": saved_search,
                        "location": saved_search.get("location") or saved_search.get("name") or "Unknown location",
                        "listings": favorite_listings,
                    }
                )
        grouped_favorites.sort(key=lambda group: str(group["location"]).lower())
        return render_template("favorites.html", grouped_favorites=grouped_favorites)

    @app.route("/markets/<market_key>")
    def market_context_by_key(market_key: str) -> str:
        config = get_supabase_read_config()
        allow_proxy = flask_request.args.get("use_proxy") == "1"
        saved_searches = fetch_saved_searches(config)
        matching_saved_searches = [
            search for search in saved_searches
            if derive_market_profile_from_saved_search(search)["market_key"] == market_key
        ]
        market_profile = fetch_market_profile(config, market_key)
        if market_profile is None and not matching_saved_searches:
            abort(404)
        representative_saved_search = matching_saved_searches[0] if matching_saved_searches else None
        if market_profile is None and representative_saved_search:
            market_profile = ensure_market_profile(config, representative_saved_search)
        elif market_profile is not None and representative_saved_search and market_profile.get("status") == "discovered":
            market_profile = bootstrap_market_context(config, representative_saved_search, fallback_profile=market_profile)
        if market_profile is None and matching_saved_searches:
            market_profile = derive_market_profile_from_saved_search(matching_saved_searches[0])
        selected_bedroom_count = parse_market_bedroom_filter(
            flask_request.args.get("beds"),
            default=(
                representative_saved_search.get("beds_min")
                if representative_saved_search
                and representative_saved_search.get("beds_min") in MARKET_RENTAL_BEDROOM_OPTIONS
                else 2
            ),
        )
        market_profile["_selected_bedroom_count"] = selected_bedroom_count
        market_metrics = fetch_market_metrics(config, market_profile["market_key"])
        housing_summary = build_market_housing_summary(config, market_profile)
        appreciation_chart = build_preferred_appreciation_context(
            config,
            market_profile["market_key"],
            allow_proxy=allow_proxy,
        )
        return render_template(
            "market_context.html",
            saved_search=representative_saved_search,
            market_profile=market_profile,
            housing_summary=housing_summary,
            selected_bedroom_count=selected_bedroom_count,
            bedroom_options=MARKET_RENTAL_BEDROOM_OPTIONS,
            market_metric_cards=build_market_metric_cards(market_metrics),
            appreciation_chart=appreciation_chart,
            related_saved_searches=matching_saved_searches,
        )

    @app.route("/saved-searches/<int:saved_search_id>")
    def saved_search_detail(saved_search_id: int) -> str:
        config = get_supabase_read_config()
        saved_search = fetch_saved_search(config, saved_search_id)
        if saved_search is None:
            abort(404)
        saved_search["market_profile"] = derive_market_profile_from_saved_search(saved_search)
        if flask_request.args.get("clear_buy_box"):
            clear_saved_buy_box(config, saved_search)
            return redirect(url_for("saved_search_detail", saved_search_id=saved_search_id))
        active_listings = fetch_active_listings(config, saved_search_id)
        active_listing_ids = [
            listing_id
            for listing_id in (normalize_listing_id(listing.get("listing_id")) for listing in active_listings)
            if listing_id is not None
        ]
        favorite_overrides = fetch_listing_investment_overrides(config, saved_search_id, active_listing_ids)
        annotate_listing_favorites(active_listings, favorite_overrides)
        buy_box = build_buy_box_criteria(flask_request.args, saved_search)
        if flask_request.args.get("apply_buy_box"):
            persist_saved_buy_box(config, saved_search, buy_box)
            return redirect(url_for("saved_search_detail", saved_search_id=saved_search_id))
        scrape_runs = fetch_recent_runs(config, saved_search_id=saved_search_id)
        latest_run = scrape_runs[0] if scrape_runs else None
        return render_template(
            "saved_search.html",
            saved_search=saved_search,
            active_listings=active_listings,
            buy_box=buy_box,
            matched_listings=[],
            maybe_listings=[],
            unmatched_listings=[],
            buy_box_ai_error=None,
            scrape_runs=scrape_runs,
            latest_run=latest_run,
            new_listing_count=sum(1 for listing in active_listings if listing.get("is_new_in_run")),
            sparse_listing_count=count_sparse_listings(active_listings),
            property_type_options=PROPERTY_TYPE_OPTIONS,
            current_query=flask_request.query_string.decode("utf-8"),
        )

    @app.route("/saved-searches/<int:saved_search_id>/market-context")
    def market_context(saved_search_id: int) -> str:
        config = get_supabase_read_config()
        allow_proxy = flask_request.args.get("use_proxy") == "1"
        saved_search = fetch_saved_search(config, saved_search_id)
        if saved_search is None:
            abort(404)
        selected_bedroom_count = parse_market_bedroom_filter(
            flask_request.args.get("beds"),
            default=saved_search.get("beds_min") if saved_search.get("beds_min") in MARKET_RENTAL_BEDROOM_OPTIONS else 2,
        )
        derived_profile = derive_market_profile_from_saved_search(saved_search)
        market_profile = fetch_market_profile(config, derived_profile["market_key"])
        if market_profile is None:
            market_profile = ensure_market_profile(config, saved_search)
        elif market_profile.get("status") == "discovered":
            market_profile = bootstrap_market_context(config, saved_search, fallback_profile=market_profile)
        market_profile["_selected_bedroom_count"] = selected_bedroom_count
        market_metrics = fetch_market_metrics(config, market_profile["market_key"])
        housing_summary = build_market_housing_summary(config, market_profile)
        appreciation_chart = build_preferred_appreciation_context(
            config,
            market_profile["market_key"],
            allow_proxy=allow_proxy,
        )
        related_saved_searches = [
            search
            for search in fetch_saved_searches(config)
            if derive_market_profile_from_saved_search(search)["market_key"] == market_profile["market_key"]
        ]
        return render_template(
            "market_context.html",
            saved_search=saved_search,
            market_profile=market_profile,
            housing_summary=housing_summary,
            selected_bedroom_count=selected_bedroom_count,
            bedroom_options=MARKET_RENTAL_BEDROOM_OPTIONS,
            market_metric_cards=build_market_metric_cards(market_metrics),
            appreciation_chart=appreciation_chart,
            related_saved_searches=related_saved_searches,
        )

    @app.route("/markets/<market_key>/rental-ai-estimate", methods=["POST"])
    def generate_market_rental_ai_estimate(market_key: str) -> Any:
        config = get_supabase_read_config()
        property_type = (flask_request.form.get("property_type") or "").strip().lower()
        if property_type not in MARKET_RENTAL_CARD_TYPES:
            abort(400)
        selected_bedroom_count = parse_market_bedroom_filter(flask_request.form.get("beds"), default=2)
        saved_searches = fetch_saved_searches(config)
        matching_saved_searches = [
            search for search in saved_searches
            if derive_market_profile_from_saved_search(search)["market_key"] == market_key
        ]
        representative_saved_search = matching_saved_searches[0] if matching_saved_searches else None
        if representative_saved_search is None:
            abort(400)
        market_profile = fetch_market_profile(config, market_key)
        if market_profile is None:
            market_profile = ensure_market_profile(config, representative_saved_search)
        market_rows = fetch_market_reference_rows(config)
        prompt_text = build_market_rental_gap_prompt_text()
        payload = build_market_rental_gap_payload(
            market_profile,
            property_type,
            selected_bedroom_count,
            market_rows,
        )
        result = call_openai_market_rental_gap_estimate(prompt_text, payload)
        parsed_response = result.get("parsed_response")
        if not isinstance(parsed_response, dict):
            abort(502)
        persist_market_rental_ai_estimate(
            config,
            saved_search_id=int(representative_saved_search["id"]),
            market_profile=market_profile,
            property_type=property_type,
            bedroom_count=selected_bedroom_count,
            prompt_text=prompt_text,
            input_context=payload,
            raw_response_text=str(result.get("raw_response_text") or ""),
            parsed_suggestion=parsed_response,
            model=result.get("model"),
        )
        redirect_args: dict[str, Any] = {"market_key": market_key, "ai_rental_estimated": property_type}
        if selected_bedroom_count is None:
            redirect_args["beds"] = "all"
        else:
            redirect_args["beds"] = selected_bedroom_count
        return redirect(url_for("market_context_by_key", **redirect_args))

    @app.route("/markets/<market_key>/appreciation-ai-estimate", methods=["POST"])
    def generate_market_appreciation_ai_estimate(market_key: str) -> Any:
        config = get_supabase_read_config()
        saved_searches = fetch_saved_searches(config)
        matching_saved_searches = [
            search for search in saved_searches
            if derive_market_profile_from_saved_search(search)["market_key"] == market_key
        ]
        representative_saved_search = matching_saved_searches[0] if matching_saved_searches else None
        if representative_saved_search is None:
            abort(400)
        market_profile = fetch_market_profile(config, market_key)
        if market_profile is None:
            market_profile = ensure_market_profile(config, representative_saved_search)
        property_type_slug = (flask_request.form.get("property_type") or "composite").strip().lower()
        direct_snapshot = fetch_hpi_market_metric_snapshot(
            config,
            market_key,
            property_type_slug=property_type_slug,
        )
        proxy_market = get_appreciation_proxy_market(market_key)
        proxy_snapshot = (
            fetch_hpi_market_metric_snapshot(
                config,
                proxy_market["proxy_key"],
                property_type_slug=property_type_slug,
            )
            if proxy_market is not None
            else None
        )
        market_metrics = fetch_market_metrics(config, market_key)
        prompt_text = build_market_appreciation_gap_prompt_text()
        payload = build_market_appreciation_gap_payload(
            market_profile,
            direct_snapshot=direct_snapshot,
            proxy_snapshot=proxy_snapshot,
            proxy_market=proxy_market,
            market_metrics=market_metrics,
        )
        result = call_openai_market_appreciation_gap_estimate(prompt_text, payload)
        parsed_response = result.get("parsed_response")
        if not isinstance(parsed_response, dict):
            abort(502)
        persist_market_appreciation_ai_estimate(
            config,
            saved_search_id=int(representative_saved_search["id"]),
            market_profile=market_profile,
            property_type_slug=property_type_slug,
            prompt_text=prompt_text,
            input_context=payload,
            raw_response_text=str(result.get("raw_response_text") or ""),
            parsed_suggestion=parsed_response,
            model=result.get("model"),
        )
        selected_bedroom_count = parse_market_bedroom_filter(flask_request.form.get("beds"), default=2)
        redirect_args: dict[str, Any] = {"market_key": market_key, "ai_appreciation_estimated": 1}
        if selected_bedroom_count is None:
            redirect_args["beds"] = "all"
        else:
            redirect_args["beds"] = selected_bedroom_count
        return redirect(url_for("market_context_by_key", **redirect_args))

    @app.route("/api/markets/<market_key>/appreciation")
    def api_market_appreciation(market_key: str) -> Any:
        config = get_supabase_read_config()
        property_type_slug = (flask_request.args.get("property_type") or "composite").strip().lower()
        allow_proxy = flask_request.args.get("use_proxy") == "1"
        appreciation = build_preferred_appreciation_context(
            config,
            market_key,
            property_type_slug=property_type_slug,
            allow_proxy=allow_proxy,
        )
        return jsonify(
            {
                "market_key": market_key,
                "property_type_slug": property_type_slug,
                "proxy_available": appreciation.get("proxy_available"),
                "proxy_active": appreciation.get("proxy_active"),
                "proxy_label": appreciation.get("proxy_label"),
                "proxy_market_name": appreciation.get("proxy_market_name"),
                "source_key": appreciation.get("source_key"),
                "source_name": appreciation.get("source_name"),
                "property_type_label": appreciation.get("property_type_label"),
                "available": appreciation.get("available"),
                "latest_benchmark_price": appreciation.get("latest_benchmark_price"),
                "latest_benchmark_price_display": appreciation.get("latest_benchmark_price_display"),
                "latest_date": appreciation.get("latest_date"),
                "change_12m": next((card["value"] for card in appreciation.get("metric_cards", []) if card["label"] == "12-Month Change"), None),
                "change_1m": next((card["value"] for card in appreciation.get("metric_cards", []) if card["label"] == "1-Month Change"), None),
                "appreciation_5y_cagr": next((card["value"] for card in appreciation.get("metric_cards", []) if card["label"] == "5-Year Annualized"), None),
                "appreciation_10y_cagr": next((card["value"] for card in appreciation.get("metric_cards", []) if card["label"] == "10-Year Annualized"), None),
                "trend_direction": appreciation.get("trend_direction"),
                "trend_label": appreciation.get("trend_label"),
                "data_quality_flag": appreciation.get("data_quality_flag"),
                "empty_message": appreciation.get("empty_message"),
                "notes": appreciation.get("notes"),
                "metric_cards": appreciation.get("metric_cards", []),
            }
        )

    @app.route("/saved-searches/<int:saved_search_id>/investment-analyzer")
    def investment_analyzer(saved_search_id: int) -> str:
        config = get_supabase_read_config()
        saved_search = fetch_saved_search(config, saved_search_id)
        if saved_search is None:
            abort(404)
        saved_search["market_profile"] = derive_market_profile_from_saved_search(saved_search)
        if flask_request.args.get("clear_buy_box"):
            clear_saved_buy_box(config, saved_search)
            clear_listing_analysis_state(saved_search_id)
            return redirect(url_for("investment_analyzer", saved_search_id=saved_search_id))
        active_listings = fetch_active_listings(config, saved_search_id)
        defaults_snapshot, market_match = hydrate_defaults_for_saved_search(config, saved_search)
        overrides_by_listing_id = fetch_listing_investment_overrides(
            config,
            saved_search_id,
            [listing["listing_id"] for listing in active_listings],
        )
        annotate_listing_favorites(active_listings, overrides_by_listing_id)
        buy_box = build_buy_box_criteria(flask_request.args, saved_search)
        analysis_state = get_saved_listing_analysis_state(saved_search) or LISTING_ANALYSIS_RUNS.get(saved_search_id)
        analysis_has_run = analysis_state is not None
        analysis_buy_box = analysis_state.get("buy_box", {}) if analysis_state else {}
        analysis_defaults = analysis_state.get("defaults_snapshot", {}) if analysis_state else {}
        analysis_overrides_by_listing_id = normalize_analysis_state_overrides(analysis_state)
        buy_box_results_by_listing_id = normalize_analysis_state_buy_box_results(analysis_state)
        if analysis_has_run and not buy_box_results_by_listing_id and not buy_box_has_enabled_ai(analysis_buy_box):
            buy_box_results_by_listing_id = build_buy_box_result_lookup(active_listings, analysis_buy_box, saved_search=saved_search)
        smart_maintenance_active = any(
            isinstance(snapshot, dict) and snapshot.get("maintenance_percent_source") == "smart_listing_estimate"
            for snapshot in overrides_by_listing_id.values()
        )
        smart_capex_active = any(
            isinstance(snapshot, dict) and snapshot.get("capex_percent_source") == "smart_listing_estimate"
            for snapshot in overrides_by_listing_id.values()
        )
        underwriting_rows = (
            build_underwriting_rows(
                active_listings,
                analysis_defaults,
                overrides_by_listing_id=analysis_overrides_by_listing_id,
                buy_box_results_by_listing_id=buy_box_results_by_listing_id,
            )
            if analysis_has_run
            else []
        )
        utilities_rule_based_estimate = estimate_rule_based_utilities_monthly(saved_search)
        insurance_rule_based_estimate = estimate_rule_based_insurance_monthly(saved_search)
        return render_template(
            "investment_analyzer.html",
            saved_search=saved_search,
            active_listings=active_listings,
            underwriting_rows=underwriting_rows,
            investment_defaults=defaults_snapshot,
            buy_box=buy_box,
            analysis_has_run=analysis_has_run,
            analysis_ran_at=analysis_state.get("ran_at") if analysis_state else None,
            analysis_buy_box=analysis_buy_box,
            market_match=market_match,
            default_rent_ai_prompt=build_rent_ai_prompt_text(),
            ai_rent_preview=AI_RENT_PREVIEWS.get(saved_search_id),
            smart_maintenance_active=smart_maintenance_active,
            smart_capex_active=smart_capex_active,
            utilities_rule_based_estimate=utilities_rule_based_estimate,
            insurance_rule_based_estimate=insurance_rule_based_estimate,
            property_type_options=PROPERTY_TYPE_OPTIONS,
            ai_preview_listing_lookup={
                normalize_listing_id(listing.get("listing_id")): listing
                for listing in active_listings
                if normalize_listing_id(listing.get("listing_id")) is not None
            },
        )

    @app.route("/saved-searches/<int:saved_search_id>/investment-analyzer/run", methods=["POST"])
    def run_listing_analysis(saved_search_id: int) -> Any:
        config = get_supabase_read_config()
        saved_search = fetch_saved_search(config, saved_search_id)
        if saved_search is None:
            abort(404)
        existing_defaults, _market_match = hydrate_defaults_for_saved_search(config, saved_search)
        defaults_snapshot = build_defaults_snapshot_from_form(flask_request.form, existing_defaults=existing_defaults)
        persist_saved_search_investment_defaults(config, saved_search_id, defaults_snapshot)
        buy_box = build_buy_box_criteria(flask_request.form, saved_search)
        persist_saved_buy_box(config, saved_search, buy_box)
        active_listings = fetch_active_listings(config, saved_search_id)
        overrides_by_listing_id = fetch_listing_investment_overrides(
            config,
            saved_search_id,
            [listing["listing_id"] for listing in active_listings],
        )
        buy_box_results_by_listing_id = build_buy_box_result_lookup(
            active_listings,
            buy_box,
            saved_search=saved_search,
        )
        analysis_state = set_listing_analysis_state(
            saved_search_id,
            buy_box=buy_box,
            defaults_snapshot=defaults_snapshot,
            overrides_by_listing_id=overrides_by_listing_id,
            buy_box_results_by_listing_id=buy_box_results_by_listing_id,
        )
        persist_latest_listing_analysis(config, saved_search, analysis_state)
        return redirect(url_for("investment_analyzer", saved_search_id=saved_search_id, analyzed=1))

    @app.route("/saved-searches/<int:saved_search_id>/investment-analyzer/defaults", methods=["POST"])
    def save_investment_analyzer_defaults(saved_search_id: int) -> Any:
        config = get_supabase_read_config()
        saved_search = fetch_saved_search(config, saved_search_id)
        if saved_search is None:
            abort(404)
        existing_defaults, _market_match = hydrate_defaults_for_saved_search(config, saved_search)
        defaults_snapshot = build_defaults_snapshot_from_form(flask_request.form, existing_defaults=existing_defaults)
        persist_saved_search_investment_defaults(config, saved_search_id, defaults_snapshot)
        return redirect(url_for("investment_analyzer", saved_search_id=saved_search_id, saved=1))

    @app.route("/saved-searches/<int:saved_search_id>/investment-analyzer/use-manual-rent", methods=["POST"])
    def use_manual_rent_default(saved_search_id: int) -> Any:
        config = get_supabase_read_config()
        saved_search = fetch_saved_search(config, saved_search_id)
        if saved_search is None:
            abort(404)
        manual_rent = parse_optional_int(flask_request.form.get("market_rent_monthly"))
        existing_defaults = fetch_saved_search_investment_defaults(config, saved_search_id)
        updated_defaults = merge_investment_defaults(existing_defaults)
        updated_defaults["market_rent_monthly"]["value"] = float(manual_rent) if manual_rent is not None else None
        updated_defaults["market_rent_monthly"]["manual_value"] = float(manual_rent) if manual_rent is not None else None
        updated_defaults["market_rent_monthly"]["source"] = "manual"
        updated_defaults["market_rent_monthly"]["confidence"] = "medium"
        updated_defaults["market_rent_monthly"]["help_text"] = "Manual saved-search rent value."
        persist_saved_search_investment_defaults(config, saved_search_id, updated_defaults)
        clear_listing_rent_overrides_for_saved_search(config, saved_search_id)
        return redirect(url_for("investment_analyzer", saved_search_id=saved_search_id, manual_rent_used=1))

    @app.route("/saved-searches/<int:saved_search_id>/investment-analyzer/use-cmhc-rent", methods=["POST"])
    def use_cmhc_rent_default(saved_search_id: int) -> Any:
        config = get_supabase_read_config()
        saved_search = fetch_saved_search(config, saved_search_id)
        if saved_search is None:
            abort(404)
        existing_defaults = fetch_saved_search_investment_defaults(config, saved_search_id)
        _hydrated_defaults, market_match = hydrate_defaults_for_saved_search(config, saved_search)
        if not market_match:
            return redirect(url_for("investment_analyzer", saved_search_id=saved_search_id, cmhc_missing=1))
        reference = market_match.get("market_reference") or {}
        average_rent = reference.get("average_rent_monthly")
        if average_rent is None:
            return redirect(url_for("investment_analyzer", saved_search_id=saved_search_id, cmhc_missing=1))
        updated_defaults = merge_investment_defaults(existing_defaults)
        manual_rent = parse_optional_int(flask_request.form.get("market_rent_monthly"))
        if manual_rent is not None:
            updated_defaults["market_rent_monthly"]["manual_value"] = float(manual_rent)
        updated_defaults["market_rent_monthly"]["value"] = float(average_rent)
        updated_defaults["market_rent_monthly"]["source"] = (
            "cmhc_apartment_proxy" if market_match.get("property_type_mismatch") else f"cmhc_{market_match.get('match_type')}"
        )
        updated_defaults["market_rent_monthly"]["confidence"] = market_match.get("confidence", "medium")
        updated_defaults["market_rent_monthly"]["help_text"] = market_match.get("notes") or updated_defaults["market_rent_monthly"]["help_text"]
        updated_defaults["market_rent_monthly"]["help_url"] = reference.get("source_url")
        persist_saved_search_investment_defaults(config, saved_search_id, updated_defaults)
        clear_listing_rent_overrides_for_saved_search(config, saved_search_id)
        return redirect(url_for("investment_analyzer", saved_search_id=saved_search_id, cmhc_used=1))

    @app.route("/saved-searches/<int:saved_search_id>/investment-analyzer/use-cmhc-vacancy", methods=["POST"])
    def use_cmhc_vacancy_default(saved_search_id: int) -> Any:
        config = get_supabase_read_config()
        saved_search = fetch_saved_search(config, saved_search_id)
        if saved_search is None:
            abort(404)
        existing_defaults = fetch_saved_search_investment_defaults(config, saved_search_id)
        _hydrated_defaults, market_match = hydrate_defaults_for_saved_search(config, saved_search)
        if not market_match:
            return redirect(url_for("investment_analyzer", saved_search_id=saved_search_id, cmhc_missing=1))
        reference = market_match.get("market_reference") or {}
        vacancy_rate = reference.get("vacancy_rate_percent")
        if vacancy_rate is None:
            return redirect(url_for("investment_analyzer", saved_search_id=saved_search_id, cmhc_missing=1))
        updated_defaults = merge_investment_defaults(existing_defaults)
        updated_defaults["vacancy_percent"]["value"] = float(vacancy_rate)
        updated_defaults["vacancy_percent"]["source"] = f"cmhc_{market_match.get('match_type')}"
        updated_defaults["vacancy_percent"]["confidence"] = market_match.get("confidence", "medium")
        updated_defaults["vacancy_percent"]["help_text"] = market_match.get("notes") or updated_defaults["vacancy_percent"]["help_text"]
        updated_defaults["vacancy_percent"]["help_url"] = reference.get("source_url")
        persist_saved_search_investment_defaults(config, saved_search_id, updated_defaults)
        return redirect(url_for("investment_analyzer", saved_search_id=saved_search_id, cmhc_vacancy_used=1))

    @app.route("/saved-searches/<int:saved_search_id>/investment-analyzer/use-manual-vacancy", methods=["POST"])
    def use_manual_vacancy_default(saved_search_id: int) -> Any:
        config = get_supabase_read_config()
        saved_search = fetch_saved_search(config, saved_search_id)
        if saved_search is None:
            abort(404)
        manual_vacancy = parse_form_number(flask_request.form.get("vacancy_percent"))
        existing_defaults = fetch_saved_search_investment_defaults(config, saved_search_id)
        updated_defaults = merge_investment_defaults(existing_defaults)
        updated_defaults["vacancy_percent"]["value"] = manual_vacancy
        updated_defaults["vacancy_percent"]["source"] = "manual"
        updated_defaults["vacancy_percent"]["confidence"] = "medium"
        updated_defaults["vacancy_percent"]["help_text"] = "Manual saved-search vacancy value."
        updated_defaults["vacancy_percent"]["help_url"] = None
        persist_saved_search_investment_defaults(config, saved_search_id, updated_defaults)
        return redirect(url_for("investment_analyzer", saved_search_id=saved_search_id, manual_vacancy_used=1))

    @app.route("/saved-searches/<int:saved_search_id>/investment-analyzer/use-manual-utilities", methods=["POST"])
    def use_manual_utilities_default(saved_search_id: int) -> Any:
        config = get_supabase_read_config()
        saved_search = fetch_saved_search(config, saved_search_id)
        if saved_search is None:
            abort(404)
        manual_utilities = parse_optional_int(flask_request.form.get("utilities_monthly"))
        existing_defaults = fetch_saved_search_investment_defaults(config, saved_search_id)
        updated_defaults = merge_investment_defaults(existing_defaults)
        updated_defaults["utilities_monthly"]["value"] = float(manual_utilities) if manual_utilities is not None else None
        updated_defaults["utilities_monthly"]["source"] = "manual"
        updated_defaults["utilities_monthly"]["confidence"] = "medium"
        updated_defaults["utilities_monthly"]["help_text"] = "Manual landlord-paid utilities estimate."
        updated_defaults["utilities_monthly"]["help_url"] = None
        persist_saved_search_investment_defaults(config, saved_search_id, updated_defaults)
        return redirect(url_for("investment_analyzer", saved_search_id=saved_search_id, manual_utilities_used=1))

    @app.route("/saved-searches/<int:saved_search_id>/investment-analyzer/use-off-utilities", methods=["POST"])
    def use_off_utilities_default(saved_search_id: int) -> Any:
        config = get_supabase_read_config()
        saved_search = fetch_saved_search(config, saved_search_id)
        if saved_search is None:
            abort(404)
        existing_defaults = fetch_saved_search_investment_defaults(config, saved_search_id)
        updated_defaults = merge_investment_defaults(existing_defaults)
        updated_defaults["utilities_monthly"]["value"] = 0.0
        updated_defaults["utilities_monthly"]["source"] = "off"
        updated_defaults["utilities_monthly"]["confidence"] = "high"
        updated_defaults["utilities_monthly"]["help_text"] = "Landlord-paid utilities assumed to be zero for this underwriting view."
        updated_defaults["utilities_monthly"]["help_url"] = None
        persist_saved_search_investment_defaults(config, saved_search_id, updated_defaults)
        return redirect(url_for("investment_analyzer", saved_search_id=saved_search_id, utilities_off=1))

    @app.route("/saved-searches/<int:saved_search_id>/investment-analyzer/use-rule-based-utilities", methods=["POST"])
    def use_rule_based_utilities_default(saved_search_id: int) -> Any:
        config = get_supabase_read_config()
        saved_search = fetch_saved_search(config, saved_search_id)
        if saved_search is None:
            abort(404)
        existing_defaults = fetch_saved_search_investment_defaults(config, saved_search_id)
        updated_defaults = merge_investment_defaults(existing_defaults)
        estimate = estimate_rule_based_utilities_monthly(saved_search)
        updated_defaults["utilities_monthly"].update(estimate)
        persist_saved_search_investment_defaults(config, saved_search_id, updated_defaults)
        return redirect(url_for("investment_analyzer", saved_search_id=saved_search_id, utilities_rule_based=1))

    @app.route("/saved-searches/<int:saved_search_id>/investment-analyzer/use-manual-insurance", methods=["POST"])
    def use_manual_insurance_default(saved_search_id: int) -> Any:
        config = get_supabase_read_config()
        saved_search = fetch_saved_search(config, saved_search_id)
        if saved_search is None:
            abort(404)
        manual_insurance = parse_optional_int(flask_request.form.get("insurance_monthly"))
        existing_defaults = fetch_saved_search_investment_defaults(config, saved_search_id)
        updated_defaults = merge_investment_defaults(existing_defaults)
        updated_defaults["insurance_monthly"]["value"] = float(manual_insurance) if manual_insurance is not None else None
        updated_defaults["insurance_monthly"]["source"] = "manual"
        updated_defaults["insurance_monthly"]["confidence"] = "medium"
        updated_defaults["insurance_monthly"]["help_text"] = "Manual insurance estimate."
        updated_defaults["insurance_monthly"]["help_url"] = None
        persist_saved_search_investment_defaults(config, saved_search_id, updated_defaults)
        return redirect(url_for("investment_analyzer", saved_search_id=saved_search_id, manual_insurance_used=1))

    @app.route("/saved-searches/<int:saved_search_id>/investment-analyzer/use-rule-based-insurance", methods=["POST"])
    def use_rule_based_insurance_default(saved_search_id: int) -> Any:
        config = get_supabase_read_config()
        saved_search = fetch_saved_search(config, saved_search_id)
        if saved_search is None:
            abort(404)
        existing_defaults = fetch_saved_search_investment_defaults(config, saved_search_id)
        updated_defaults = merge_investment_defaults(existing_defaults)
        estimate = estimate_rule_based_insurance_monthly(saved_search)
        updated_defaults["insurance_monthly"].update(estimate)
        persist_saved_search_investment_defaults(config, saved_search_id, updated_defaults)
        return redirect(url_for("investment_analyzer", saved_search_id=saved_search_id, insurance_rule_based=1))

    @app.route("/saved-searches/<int:saved_search_id>/investment-analyzer/apply-smart-maintenance", methods=["POST"])
    def apply_smart_maintenance_estimates(saved_search_id: int) -> Any:
        config = get_supabase_read_config()
        saved_search = fetch_saved_search(config, saved_search_id)
        if saved_search is None:
            abort(404)
        active_listings = fetch_active_listings(config, saved_search_id)
        applied_count = 0
        for listing in active_listings:
            listing_id = normalize_listing_id(listing.get("listing_id"))
            if listing_id is None:
                continue
            estimate = estimate_smart_reserve_percentages(listing)
            persist_listing_investment_override(
                config,
                saved_search_id,
                listing_id,
                {
                    "maintenance_percent_of_rent": estimate["maintenance_percent_of_rent"]["value"],
                    "maintenance_percent_source": estimate["maintenance_percent_of_rent"]["source"],
                    "maintenance_percent_confidence": estimate["maintenance_percent_of_rent"]["confidence"],
                    "maintenance_percent_help_text": estimate["maintenance_percent_of_rent"]["help_text"],
                },
            )
            applied_count += 1
        return redirect(url_for("investment_analyzer", saved_search_id=saved_search_id, smart_maintenance_applied=applied_count))

    @app.route("/saved-searches/<int:saved_search_id>/investment-analyzer/apply-smart-capex", methods=["POST"])
    def apply_smart_capex_estimates(saved_search_id: int) -> Any:
        config = get_supabase_read_config()
        saved_search = fetch_saved_search(config, saved_search_id)
        if saved_search is None:
            abort(404)
        active_listings = fetch_active_listings(config, saved_search_id)
        applied_count = 0
        for listing in active_listings:
            listing_id = normalize_listing_id(listing.get("listing_id"))
            if listing_id is None:
                continue
            estimate = estimate_smart_reserve_percentages(listing)
            persist_listing_investment_override(
                config,
                saved_search_id,
                listing_id,
                {
                    "capex_percent_of_rent": estimate["capex_percent_of_rent"]["value"],
                    "capex_percent_source": estimate["capex_percent_of_rent"]["source"],
                    "capex_percent_confidence": estimate["capex_percent_of_rent"]["confidence"],
                    "capex_percent_help_text": estimate["capex_percent_of_rent"]["help_text"],
                },
            )
            applied_count += 1
        return redirect(url_for("investment_analyzer", saved_search_id=saved_search_id, smart_capex_applied=applied_count))

    @app.route("/saved-searches/<int:saved_search_id>/investment-analyzer/use-shared-maintenance", methods=["POST"])
    def use_shared_maintenance_default(saved_search_id: int) -> Any:
        config = get_supabase_read_config()
        saved_search = fetch_saved_search(config, saved_search_id)
        if saved_search is None:
            abort(404)
        clear_listing_override_keys_for_saved_search(
            config,
            saved_search_id,
            [
                "maintenance_percent_of_rent",
                "maintenance_percent_source",
                "maintenance_percent_confidence",
                "maintenance_percent_help_text",
            ],
        )
        return redirect(url_for("investment_analyzer", saved_search_id=saved_search_id, shared_maintenance_used=1))

    @app.route("/saved-searches/<int:saved_search_id>/investment-analyzer/use-shared-capex", methods=["POST"])
    def use_shared_capex_default(saved_search_id: int) -> Any:
        config = get_supabase_read_config()
        saved_search = fetch_saved_search(config, saved_search_id)
        if saved_search is None:
            abort(404)
        clear_listing_override_keys_for_saved_search(
            config,
            saved_search_id,
            [
                "capex_percent_of_rent",
                "capex_percent_source",
                "capex_percent_confidence",
                "capex_percent_help_text",
            ],
        )
        return redirect(url_for("investment_analyzer", saved_search_id=saved_search_id, shared_capex_used=1))

    @app.route("/saved-searches/<int:saved_search_id>/investment-analyzer/ai-rent-preview", methods=["POST"])
    def preview_ai_rent_suggestions(saved_search_id: int) -> Any:
        config = get_supabase_read_config()
        saved_search = fetch_saved_search(config, saved_search_id)
        if saved_search is None:
            abort(404)
        active_listings = fetch_active_listings(config, saved_search_id)
        investment_defaults, market_match = hydrate_defaults_for_saved_search(config, saved_search)
        prompt_text = (flask_request.form.get("prompt_text") or "").strip() or build_rent_ai_prompt_text()
        payload = build_rent_ai_payload(saved_search, active_listings, market_match, investment_defaults)
        try:
            ai_result = call_openai_rent_suggestions(prompt_text, payload)
            AI_RENT_PREVIEWS[saved_search_id] = {
                "prompt_text": prompt_text,
                "payload": payload,
                "raw_response_text": ai_result["raw_response_text"],
                "parsed_response": ai_result["parsed_response"],
                "model": ai_result["model"],
                "error": None,
            }
        except Exception as exc:
            AI_RENT_PREVIEWS[saved_search_id] = {
                "prompt_text": prompt_text,
                "payload": payload,
                "raw_response_text": "",
                "parsed_response": {},
                "model": None,
                "error": str(exc),
            }
        return redirect(url_for("investment_analyzer", saved_search_id=saved_search_id, ai_preview=1))

    @app.route("/saved-searches/<int:saved_search_id>/investment-analyzer/ai-rent-accept", methods=["POST"])
    def accept_ai_rent_suggestion(saved_search_id: int) -> Any:
        config = get_supabase_read_config()
        listing_id = parse_optional_int(flask_request.form.get("listing_id"))
        suggested_rent = parse_optional_int(flask_request.form.get("suggested_rent_monthly"))
        if listing_id is None or suggested_rent is None:
            abort(400, "Listing and suggested rent are required")
        persist_listing_investment_override(
            config,
            saved_search_id,
            listing_id,
            {
                "market_rent_monthly": suggested_rent,
                "market_rent_source": "ai_listing_suggestion",
            },
        )
        preview = AI_RENT_PREVIEWS.get(saved_search_id) or {}
        suggestion_lookup = {
            item.get("listing_id"): item
            for item in (preview.get("parsed_response") or {}).get("suggestions", [])
            if isinstance(item, dict)
        }
        parsed_suggestion = suggestion_lookup.get(listing_id, {})
        persist_ai_underwriting_suggestion(
            config,
            saved_search_id=saved_search_id,
            listing_id=listing_id,
            suggestion_type="listing_rent",
            status="accepted",
            prompt_text=preview.get("prompt_text", build_rent_ai_prompt_text()),
            model=preview.get("model"),
            input_context=preview.get("payload", {}),
            raw_response_text=preview.get("raw_response_text", ""),
            parsed_suggestion=parsed_suggestion if isinstance(parsed_suggestion, dict) else {},
            accepted_value=suggested_rent,
        )
        return redirect(url_for("investment_analyzer", saved_search_id=saved_search_id, ai_accepted=listing_id))

    @app.route("/saved-searches/<int:saved_search_id>/investment-analyzer/ai-rent-accept-all", methods=["POST"])
    def accept_all_ai_rent_suggestions(saved_search_id: int) -> Any:
        config = get_supabase_read_config()
        preview = AI_RENT_PREVIEWS.get(saved_search_id) or {}
        suggestions = (preview.get("parsed_response") or {}).get("suggestions", [])
        valid_suggestions: list[dict[str, Any]] = []
        for item in suggestions:
            if not isinstance(item, dict):
                continue
            listing_id = normalize_listing_id(item.get("listing_id"))
            suggested_rent = parse_optional_int(str(item.get("suggested_rent_monthly")))
            if listing_id is None or suggested_rent is None:
                continue
            normalized_item = dict(item)
            normalized_item["listing_id"] = listing_id
            normalized_item["suggested_rent_monthly"] = suggested_rent
            valid_suggestions.append(normalized_item)
        if not valid_suggestions:
            return redirect(url_for("investment_analyzer", saved_search_id=saved_search_id, ai_missing=1))

        saved_search = fetch_saved_search(config, saved_search_id)
        if saved_search is None:
            abort(404)

        clear_listing_rent_overrides_for_saved_search(config, saved_search_id)
        for item in valid_suggestions:
            listing_id = item["listing_id"]
            suggested_rent = item["suggested_rent_monthly"]
            persist_listing_investment_override(
                config,
                saved_search_id,
                listing_id,
                {
                    "market_rent_monthly": suggested_rent,
                    "market_rent_source": "ai_listing_suggestion",
                },
            )
            persist_ai_underwriting_suggestion(
                config,
                saved_search_id=saved_search_id,
                listing_id=listing_id,
                suggestion_type="listing_rent",
                status="accepted",
                prompt_text=preview.get("prompt_text", build_rent_ai_prompt_text()),
                model=preview.get("model"),
                input_context=preview.get("payload", {}),
                raw_response_text=preview.get("raw_response_text", ""),
                parsed_suggestion=item,
                accepted_value=suggested_rent,
            )

        average_rent = round(sum(item["suggested_rent_monthly"] for item in valid_suggestions) / len(valid_suggestions))
        existing_defaults = fetch_saved_search_investment_defaults(config, saved_search_id)
        updated_defaults = merge_investment_defaults(existing_defaults)
        updated_defaults["market_rent_monthly"]["value"] = float(average_rent)
        updated_defaults["market_rent_monthly"]["source"] = "ai_listing_suggestions"
        updated_defaults["market_rent_monthly"]["confidence"] = "medium"
        updated_defaults["market_rent_monthly"]["help_text"] = (
            "AI listing rent suggestions applied across the active table. "
            "This shared value is the average of the accepted listing-level AI rents."
        )
        persist_saved_search_investment_defaults(config, saved_search_id, updated_defaults)

        buy_box = build_buy_box_criteria(flask_request.form, saved_search)
        persist_saved_buy_box(config, saved_search, buy_box)
        active_listings = fetch_active_listings(config, saved_search_id)
        overrides_by_listing_id = fetch_listing_investment_overrides(
            config,
            saved_search_id,
            [listing["listing_id"] for listing in active_listings],
        )
        buy_box_results_by_listing_id = build_buy_box_result_lookup(
            active_listings,
            buy_box,
            saved_search=saved_search,
        )
        analysis_state = set_listing_analysis_state(
            saved_search_id,
            buy_box=buy_box,
            defaults_snapshot=updated_defaults,
            overrides_by_listing_id=overrides_by_listing_id,
            buy_box_results_by_listing_id=buy_box_results_by_listing_id,
        )
        persist_latest_listing_analysis(config, saved_search, analysis_state)
        return redirect(
            url_for(
                "investment_analyzer",
                saved_search_id=saved_search_id,
                ai_applied=len(valid_suggestions),
                analyzed=1,
            )
        )

    @app.route("/saved-searches/<int:saved_search_id>/investment-analyzer/listings/<int:listing_id>/rent", methods=["POST"])
    def save_listing_rent_override(saved_search_id: int, listing_id: int) -> Any:
        config = get_supabase_read_config()
        saved_search = fetch_saved_search(config, saved_search_id)
        if saved_search is None:
            abort(404)
        rent_override = flask_request.form.get("market_rent_monthly")
        persist_listing_investment_override(
            config,
            saved_search_id,
            listing_id,
            {
                "market_rent_monthly": parse_optional_int(rent_override),
                "market_rent_source": "listing_override",
            },
        )
        redirect_target = (flask_request.form.get("redirect_target") or "").strip()
        return_to = (flask_request.form.get("return_to") or "").strip()
        if redirect_target == "listing_detail":
            redirect_kwargs: dict[str, Any] = {
                "saved_search_id": saved_search_id,
                "listing_id": listing_id,
                "rent_saved": 1,
            }
            if return_to:
                redirect_kwargs["return_to"] = return_to
            return redirect(url_for("listing_detail", **redirect_kwargs))
        return redirect(url_for("investment_analyzer", saved_search_id=saved_search_id, rent_saved=listing_id))

    @app.route("/saved-searches/<int:saved_search_id>/listings/<int:listing_id>/underwriting", methods=["POST"])
    def save_listing_underwriting_overrides(saved_search_id: int, listing_id: int) -> Any:
        config = get_supabase_read_config()
        saved_search = fetch_saved_search(config, saved_search_id)
        if saved_search is None:
            abort(404)
        listing = fetch_active_listing_detail(config, saved_search_id, listing_id)
        if listing is None:
            abort(404)
        persist_listing_investment_override(
            config,
            saved_search_id,
            listing_id,
            build_listing_underwriting_override_updates(flask_request.form),
        )
        redirect_kwargs: dict[str, Any] = {
            "saved_search_id": saved_search_id,
            "listing_id": listing_id,
            "underwriting_saved": 1,
        }
        return_to = (flask_request.form.get("return_to") or "").strip()
        if return_to:
            redirect_kwargs["return_to"] = return_to
        return redirect(url_for("listing_detail", **redirect_kwargs))

    @app.route("/saved-searches/<int:saved_search_id>/listings/<int:listing_id>/favorite", methods=["POST"])
    def toggle_listing_favorite(saved_search_id: int, listing_id: int) -> Any:
        config = get_supabase_read_config()
        saved_search = fetch_saved_search(config, saved_search_id)
        if saved_search is None:
            abort(404)
        listing = fetch_active_listing_detail(config, saved_search_id, listing_id)
        if listing is None:
            abort(404)
        should_favorite = flask_request.form.get("favorite") == "1"
        persist_listing_investment_override(
            config,
            saved_search_id,
            listing_id,
            {"favorite": True if should_favorite else None},
        )
        redirect_target = (flask_request.form.get("redirect_target") or "").strip()
        return_to = (flask_request.form.get("return_to") or "").strip()
        if redirect_target == "listing_detail":
            redirect_kwargs: dict[str, Any] = {"saved_search_id": saved_search_id, "listing_id": listing_id}
            if return_to:
                redirect_kwargs["return_to"] = return_to
            return redirect(url_for("listing_detail", **redirect_kwargs))
        if redirect_target == "investment_analyzer":
            return redirect(url_for("investment_analyzer", saved_search_id=saved_search_id))
        if redirect_target == "favorites":
            return redirect(url_for("favorites"))
        return redirect(url_for("saved_search_detail", saved_search_id=saved_search_id))

    @app.route("/saved-searches/<int:saved_search_id>/listings/<int:listing_id>")
    def listing_detail(saved_search_id: int, listing_id: int) -> str:
        config = get_supabase_read_config()
        saved_search = fetch_saved_search(config, saved_search_id)
        if saved_search is None:
            abort(404)
        listing = fetch_active_listing_detail(config, saved_search_id, listing_id)
        if listing is None:
            abort(404)
        buy_box = build_buy_box_criteria(flask_request.args, saved_search)
        listing_buy_box = None
        if not flask_request.args.get("apply_buy_box"):
            listing_buy_box = get_saved_listing_buy_box_result(saved_search, listing_id)
        if listing_buy_box is None:
            listing_buy_box = analyze_listing_for_detail(listing, buy_box)
        investment_defaults, _market_match = hydrate_defaults_for_saved_search(config, saved_search)
        listing_overrides = fetch_listing_investment_overrides(config, saved_search_id, [listing_id]).get(listing_id, {})
        listing["is_favorite"] = bool(listing_overrides.get("favorite"))
        underwriting = calculate_underwriting(listing, investment_defaults, listing_overrides=listing_overrides)
        latest_ai_rent_suggestion = fetch_latest_ai_underwriting_suggestion(
            config,
            saved_search_id=saved_search_id,
            listing_id=listing_id,
            suggestion_type="listing_rent",
        )
        return render_template(
            "listing_detail.html",
            saved_search=saved_search,
            listing=listing,
            buy_box=buy_box,
            listing_buy_box=listing_buy_box,
            investment_defaults=investment_defaults,
            underwriting=underwriting,
            listing_overrides=listing_overrides,
            editable_assumption_keys=LISTING_UNDERWRITING_OVERRIDE_KEYS,
            latest_ai_rent_suggestion=latest_ai_rent_suggestion,
            return_to=flask_request.args.get("return_to"),
            back_query=flask_request.query_string.decode("utf-8"),
        )

    @app.route("/scrapes", methods=["POST"])
    def create_scrape() -> Any:
        location = (flask_request.form.get("location") or "").strip()
        if not location:
            abort(400, "Location is required")

        args = build_scrape_args(flask_request.form)
        job = start_scrape_job(args)
        return redirect(url_for("dashboard", started=job["id"]))

    @app.route("/saved-searches/<int:saved_search_id>/scrapes", methods=["POST"])
    def update_saved_search(saved_search_id: int) -> Any:
        config = get_supabase_read_config()
        saved_search = fetch_saved_search(config, saved_search_id)
        if saved_search is None:
            abort(404)

        args = build_scrape_args_from_saved_search(saved_search, flask_request.form)
        job = start_scrape_job(args)
        return redirect(url_for("saved_search_detail", saved_search_id=saved_search_id, started=job["id"]))

    @app.route("/saved-searches/<int:saved_search_id>/retry-sparse-details", methods=["POST"])
    def retry_sparse_details(saved_search_id: int) -> Any:
        config = get_supabase_read_config()
        saved_search = fetch_saved_search(config, saved_search_id)
        if saved_search is None:
            abort(404)
        args = build_retry_sparse_args(saved_search_id)
        job = start_scrape_job(args)
        return redirect(url_for("saved_search_detail", saved_search_id=saved_search_id, started=job["id"]))

    @app.route("/jobs/<job_id>")
    def job_detail(job_id: str) -> str:
        job = get_scrape_job(job_id)
        if job is None:
            abort(404)
        return render_template("job_detail.html", job=job)

    @app.route("/jobs/<job_id>/cancel", methods=["POST"])
    def cancel_job(job_id: str) -> Any:
        job = get_scrape_job(job_id)
        if job is None:
            abort(404)
        cancel_scrape_job(job)
        return redirect(url_for("job_detail", job_id=job_id))

    return app


def get_supabase_read_config() -> SupabaseReadConfig:
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_KEY")
    if not url or not key:
        raise RuntimeError("SUPABASE_URL and SUPABASE_KEY must be configured for the local website")
    return SupabaseReadConfig(url=url.rstrip("/"), key=key)


def supabase_get(config: SupabaseReadConfig, path: str, *, query: dict[str, Any] | None = None) -> Any:
    endpoint = f"{config.url}/rest/v1/{path}"
    if query:
        endpoint = f"{endpoint}?{parse.urlencode(query, doseq=True)}"

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
        raise RuntimeError(f"Supabase read failed with status {exc.code}: {details}") from exc
    except error.URLError as exc:
        raise RuntimeError(f"Supabase read failed: {exc.reason}") from exc


def supabase_patch(
    config: SupabaseReadConfig,
    path: str,
    *,
    query: dict[str, Any] | None = None,
    payload: dict[str, Any],
) -> Any:
    endpoint = f"{config.url}/rest/v1/{path}"
    if query:
        endpoint = f"{endpoint}?{parse.urlencode(query, doseq=True)}"

    req = request.Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        method="PATCH",
        headers={
            "apikey": config.key,
            "Authorization": f"Bearer {config.key}",
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Prefer": "return=representation",
        },
    )
    try:
        with request.urlopen(req, timeout=30) as response:
            raw = response.read().decode("utf-8", errors="replace")
            return json.loads(raw) if raw else None
    except error.HTTPError as exc:
        details = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Supabase write failed with status {exc.code}: {details}") from exc
    except error.URLError as exc:
        raise RuntimeError(f"Supabase write failed: {exc.reason}") from exc


def supabase_post(
    config: SupabaseReadConfig,
    path: str,
    *,
    query: dict[str, Any] | None = None,
    payload: Any,
    prefer: str | None = None,
) -> Any:
    endpoint = f"{config.url}/rest/v1/{path}"
    if query:
        endpoint = f"{endpoint}?{parse.urlencode(query, doseq=True)}"

    headers = {
        "apikey": config.key,
        "Authorization": f"Bearer {config.key}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    if prefer:
        headers["Prefer"] = prefer

    req = request.Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers=headers,
    )
    try:
        with request.urlopen(req, timeout=30) as response:
            raw = response.read().decode("utf-8", errors="replace")
            return json.loads(raw) if raw else None
    except error.HTTPError as exc:
        details = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Supabase write failed with status {exc.code}: {details}") from exc
    except error.URLError as exc:
        raise RuntimeError(f"Supabase write failed: {exc.reason}") from exc


def fetch_saved_searches(config: SupabaseReadConfig) -> list[dict[str, Any]]:
    result = supabase_get(
        config,
        "saved_searches",
        query={
            "select": "id,search_key,name,location,min_price,max_price,beds_min,property_type,last_scraped_at",
            "order": "last_scraped_at.desc.nullslast,id.desc",
        },
    )
    searches = result if isinstance(result, list) else []
    now = datetime.utcnow().astimezone()
    for search in searches:
        last_scraped_at = parse_iso_timestamp(search.get("last_scraped_at"))
        search["updated_recently"] = bool(
            last_scraped_at and (now - last_scraped_at.astimezone()).total_seconds() <= 15 * 60
        )
    return searches


def fetch_saved_search(config: SupabaseReadConfig, saved_search_id: int) -> dict[str, Any] | None:
    result = supabase_get(
        config,
        "saved_searches",
        query={
            "id": f"eq.{saved_search_id}",
            "select": "id,search_key,name,location,min_price,max_price,beds_min,property_type,last_scraped_at,search_snapshot",
            "limit": 1,
        },
    )
    if isinstance(result, list) and result:
        return result[0]
    return None


def fetch_recent_runs(config: SupabaseReadConfig, *, saved_search_id: int | None = None) -> list[dict[str, Any]]:
    query: dict[str, Any] = {
        "select": "id,saved_search_id,status,results_count,summary_count,detail_attempted,detail_succeeded,started_at,finished_at",
        "order": "id.desc",
        "limit": 20,
    }
    if saved_search_id is not None:
        query["saved_search_id"] = f"eq.{saved_search_id}"
    result = supabase_get(config, "scrape_runs", query=query)
    return result if isinstance(result, list) else []


def fetch_active_listings(config: SupabaseReadConfig, saved_search_id: int) -> list[dict[str, Any]]:
    result = supabase_get(
        config,
        "current_active_saved_search_listings",
        query={
            "saved_search_id": f"eq.{saved_search_id}",
            "select": (
                "saved_search_id,listing_id,address,price,bedrooms,bathrooms,property_type,"
                "building_type,square_feet,land_size,built_in,annual_taxes,hoa_fees,"
                "listing_description,"
                "time_on_realtor,zoning_type,url,results_page,is_new_in_run,last_seen_at"
            ),
            "order": "is_new_in_run.desc,price.asc.nullslast,listing_id.asc",
        },
    )
    listings = result if isinstance(result, list) else []
    merge_listing_media(config, listings)
    return listings


def fetch_saved_search_investment_defaults(
    config: SupabaseReadConfig,
    saved_search_id: int,
) -> dict[str, dict[str, Any]]:
    try:
        result = supabase_get(
            config,
            "saved_search_investment_defaults",
            query={
                "saved_search_id": f"eq.{saved_search_id}",
                "select": "defaults_snapshot",
                "limit": 1,
            },
        )
    except RuntimeError:
        return merge_investment_defaults(None)
    if isinstance(result, list) and result:
        defaults_snapshot = result[0].get("defaults_snapshot")
        return merge_investment_defaults(defaults_snapshot if isinstance(defaults_snapshot, dict) else None)
    return merge_investment_defaults(None)


def fetch_market_reference_rows(config: SupabaseReadConfig) -> list[dict[str, Any]]:
    try:
        result = supabase_get(
            config,
            "market_reference_data",
            query={
                "select": (
                    "id,source,source_dataset,market_name,province,market_key,geography_type,"
                    "property_type,bedroom_count,average_rent_monthly,vacancy_rate_percent,source_url,source_date"
                ),
                "limit": 2000,
            },
        )
    except RuntimeError:
        return []
    return result if isinstance(result, list) else []


def fetch_market_rental_ai_estimates(
    config: SupabaseReadConfig,
    market_key: str,
) -> dict[tuple[str, int | None], dict[str, Any]]:
    if not market_key:
        return {}
    try:
        result = supabase_get(
            config,
            "ai_underwriting_suggestions",
            query={
                "suggestion_type": "eq.market_rental_gap",
                "status": "eq.generated",
                "input_context->market->>market_key": f"eq.{market_key}",
                "select": "id,input_context,parsed_suggestion,model,created_at",
                "order": "created_at.desc",
                "limit": 100,
            },
        )
    except RuntimeError:
        return {}
    rows = result if isinstance(result, list) else []
    estimates: dict[tuple[str, int | None], dict[str, Any]] = {}
    for row in rows:
        context = row.get("input_context")
        suggestion = row.get("parsed_suggestion")
        if not isinstance(context, dict) or not isinstance(suggestion, dict):
            continue
        benchmark = context.get("missing_benchmark")
        if not isinstance(benchmark, dict):
            continue
        property_type = str(benchmark.get("property_type") or "").strip().lower()
        bedroom_count = benchmark.get("bedroom_count")
        if not property_type or (bedroom_count is not None and not isinstance(bedroom_count, int)):
            continue
        key = (property_type, bedroom_count)
        if key not in estimates:
            estimates[key] = {
                **suggestion,
                "model": row.get("model"),
                "created_at": row.get("created_at"),
            }
    return estimates


def persist_market_rental_ai_estimate(
    config: SupabaseReadConfig,
    *,
    saved_search_id: int,
    market_profile: dict[str, Any],
    property_type: str,
    bedroom_count: int | None,
    prompt_text: str,
    input_context: dict[str, Any],
    raw_response_text: str,
    parsed_suggestion: dict[str, Any],
    model: str | None,
) -> None:
    supabase_post(
        config,
        "ai_underwriting_suggestions",
        payload=[
            {
                "saved_search_id": saved_search_id,
                "listing_id": None,
                "suggestion_type": "market_rental_gap",
                "status": "generated",
                "prompt_text": prompt_text,
                "model": model,
                "input_context": input_context,
                "raw_response_text": raw_response_text,
                "parsed_suggestion": {
                    **parsed_suggestion,
                    "market_key": market_profile.get("market_key"),
                    "property_type": property_type,
                    "bedroom_count": bedroom_count,
                },
                "accepted_value": parsed_suggestion.get("average_rent_monthly"),
            }
        ],
        prefer="return=representation",
    )


def fetch_market_appreciation_ai_estimate(
    config: SupabaseReadConfig,
    market_key: str,
    *,
    property_type_slug: str = "composite",
) -> dict[str, Any] | None:
    if not market_key:
        return None
    try:
        result = supabase_get(
            config,
            "ai_underwriting_suggestions",
            query={
                "suggestion_type": "eq.market_appreciation_gap",
                "status": "eq.generated",
                "input_context->market->>market_key": f"eq.{market_key}",
                "input_context->>property_type_slug": f"eq.{property_type_slug}",
                "select": "id,input_context,parsed_suggestion,model,created_at",
                "order": "created_at.desc",
                "limit": 1,
            },
        )
    except RuntimeError:
        return None
    rows = result if isinstance(result, list) else []
    if not rows:
        return None
    row = rows[0]
    suggestion = row.get("parsed_suggestion")
    if not isinstance(suggestion, dict):
        return None
    return {
        **suggestion,
        "model": row.get("model"),
        "created_at": row.get("created_at"),
    }


def persist_market_appreciation_ai_estimate(
    config: SupabaseReadConfig,
    *,
    saved_search_id: int,
    market_profile: dict[str, Any],
    property_type_slug: str,
    prompt_text: str,
    input_context: dict[str, Any],
    raw_response_text: str,
    parsed_suggestion: dict[str, Any],
    model: str | None,
) -> None:
    normalized_context = {
        **input_context,
        "property_type_slug": property_type_slug,
    }
    supabase_post(
        config,
        "ai_underwriting_suggestions",
        payload=[
            {
                "saved_search_id": saved_search_id,
                "listing_id": None,
                "suggestion_type": "market_appreciation_gap",
                "status": "generated",
                "prompt_text": prompt_text,
                "model": model,
                "input_context": normalized_context,
                "raw_response_text": raw_response_text,
                "parsed_suggestion": {
                    **parsed_suggestion,
                    "market_key": market_profile.get("market_key"),
                    "property_type_slug": property_type_slug,
                },
                "accepted_value": parsed_suggestion.get("latest_benchmark_price"),
            }
        ],
        prefer="return=representation",
    )


def fetch_market_profile(config: SupabaseReadConfig, market_key: str) -> dict[str, Any] | None:
    try:
        result = supabase_get(
            config,
            "market_profiles",
            query={
                "market_key": f"eq.{market_key}",
                "select": "id,market_key,market_name,province,geography_type,status,notes",
                "limit": 1,
            },
        )
    except RuntimeError:
        return None
    rows = result if isinstance(result, list) else []
    return rows[0] if rows else None


def fetch_market_metrics(config: SupabaseReadConfig, market_key: str) -> list[dict[str, Any]]:
    try:
        result = supabase_get(
            config,
            "market_metrics",
            query={
                "market_key": f"eq.{market_key}",
                "select": (
                    "metric_key,value_numeric,value_text,unit,source_name,source_url,"
                    "source_date,confidence,notes"
                ),
                "order": "metric_key.asc",
            },
        )
    except RuntimeError:
        return []
    return result if isinstance(result, list) else []


def build_market_metric_cards(metrics: list[dict[str, Any]]) -> list[dict[str, Any]]:
    cards: list[dict[str, Any]] = []
    for metric_key in ("population", "population_growth_percent", "unemployment_rate_percent", "median_household_income"):
        definition = MARKET_METRIC_DEFINITIONS[metric_key]
        raw_metric = next((metric for metric in metrics if metric.get("metric_key") == metric_key), None)
        if raw_metric is None:
            cards.append(
                {
                    "key": metric_key,
                    "label": definition["label"],
                    "display_value": "—",
                    "source_name": None,
                    "source_url": None,
                    "source_date": None,
                    "confidence": None,
                    "notes": None,
                }
            )
            continue
        enriched_metric = {
            **raw_metric,
            "format": definition["format"],
        }
        cards.append(
            {
                "key": metric_key,
                "label": definition["label"],
                "display_value": format_market_metric_value(enriched_metric),
                "source_name": raw_metric.get("source_name"),
                "source_url": raw_metric.get("source_url"),
                "source_date": raw_metric.get("source_date"),
                "confidence": raw_metric.get("confidence"),
                "notes": raw_metric.get("notes"),
            }
        )
    return cards


def fetch_market_metric_series(
    config: SupabaseReadConfig,
    market_key: str,
    *,
    series_key: str,
) -> list[dict[str, Any]]:
    try:
        result = supabase_get(
            config,
            "market_metric_series",
            query={
                "market_key": f"eq.{market_key}",
                "series_key": f"eq.{series_key}",
                "select": (
                    "point_date,value_numeric,unit,source_name,source_url,"
                    "source_date,confidence,notes"
                ),
                "order": "point_date.asc",
            },
        )
    except RuntimeError:
        return []
    return result if isinstance(result, list) else []


def fetch_hpi_market_metric_snapshot(
    config: SupabaseReadConfig,
    market_key: str,
    *,
    property_type_slug: str = "composite",
) -> dict[str, Any] | None:
    try:
        result = supabase_get(
            config,
            "hpi_market_metrics",
            query={
                "source": "eq.crea_hpi",
                "market_key": f"eq.{market_key}",
                "property_type_slug": f"eq.{property_type_slug}",
                "select": (
                    "market_key,market_name,province,property_type_slug,property_type_label,"
                    "latest_date,latest_index_value,latest_benchmark_price,"
                    "appreciation_5y_total_pct,appreciation_5y_cagr,"
                    "appreciation_10y_total_pct,appreciation_10y_cagr,"
                    "change_12m_pct,change_3m_pct,change_3m_annualized_pct,change_1m_pct,"
                    "trend_direction,data_quality_flag,observation_count,method_notes"
                ),
                "limit": 1,
            },
        )
    except RuntimeError:
        return None
    rows = result if isinstance(result, list) else []
    return rows[0] if rows else None


def fetch_hpi_observation_series(
    config: SupabaseReadConfig,
    market_key: str,
    *,
    property_type_slug: str = "composite",
) -> list[dict[str, Any]]:
    try:
        result = supabase_get(
            config,
            "hpi_observations",
            query={
                "source": "eq.crea_hpi",
                "market_key": f"eq.{market_key}",
                "property_type_slug": f"eq.{property_type_slug}",
                "seasonal_adjustment": "eq.seasonally_adjusted",
                "select": "point_date,index_value,benchmark_price,property_type_label",
                "order": "point_date.asc",
            },
        )
    except RuntimeError:
        return []
    return result if isinstance(result, list) else []


def build_appreciation_metric_cards(snapshot: dict[str, Any] | None) -> list[dict[str, str]]:
    if not snapshot:
        return []

    def format_ratio_percent(value: Any) -> str:
        if value is None:
            return "—"
        return format_percent(float(value) * 100.0, digits=1)

    return [
        {
            "label": "Latest Market-Wide Benchmark Home Price",
            "value": format_currency(float(snapshot["latest_benchmark_price"])) if snapshot.get("latest_benchmark_price") is not None else "—",
            "meta": f"As of {snapshot['latest_date']}" if snapshot.get("latest_date") else None,
        },
        {
            "label": "5-Year Annualized",
            "value": format_ratio_percent(snapshot.get("appreciation_5y_cagr")),
            "meta": "Calculated from the HPI index",
        },
        {
            "label": "10-Year Annualized",
            "value": format_ratio_percent(snapshot.get("appreciation_10y_cagr")),
            "meta": "Calculated from the HPI index",
        },
        {
            "label": "12-Month Change",
            "value": format_ratio_percent(snapshot.get("change_12m_pct")),
            "meta": "Calculated from the HPI index",
        },
        {
            "label": "1-Month Change",
            "value": format_ratio_percent(snapshot.get("change_1m_pct")),
            "meta": "Calculated from the HPI index",
        },
    ]


def build_empty_appreciation_metric_cards() -> list[dict[str, str | None]]:
    return [
        {
            "label": "Latest Market-Wide Benchmark Home Price",
            "value": "—",
            "meta": "No data",
        },
        {
            "label": "5-Year Annualized",
            "value": "—",
            "meta": "No data",
        },
        {
            "label": "10-Year Annualized",
            "value": "—",
            "meta": "No data",
        },
        {
            "label": "12-Month Change",
            "value": "—",
            "meta": "No data",
        },
        {
            "label": "1-Month Change",
            "value": "—",
            "meta": "No data",
        },
    ]


def build_ai_appreciation_metric_cards(estimate: dict[str, Any]) -> list[dict[str, str | None]]:
    def format_optional_percent(value: Any) -> str:
        if value is None:
            return "—"
        return format_percent(float(value), digits=1)

    return [
        {
            "label": "Latest Market-Wide Benchmark Home Price",
            "value": format_currency(float(estimate["latest_benchmark_price"])) if estimate.get("latest_benchmark_price") is not None else "—",
            "meta": "AI estimate",
        },
        {
            "label": "5-Year Annualized",
            "value": format_optional_percent(estimate.get("appreciation_5y_cagr_percent")),
            "meta": "AI estimate",
        },
        {
            "label": "10-Year Annualized",
            "value": format_optional_percent(estimate.get("appreciation_10y_cagr_percent")),
            "meta": "AI estimate",
        },
        {
            "label": "12-Month Change",
            "value": format_optional_percent(estimate.get("change_12m_percent")),
            "meta": "AI estimate",
        },
        {
            "label": "1-Month Change",
            "value": format_optional_percent(estimate.get("change_1m_percent")),
            "meta": "AI estimate",
        },
    ]


def format_axis_currency(value: float) -> str:
    if value >= 1_000_000:
        return f"${value / 1_000_000:.1f}M"
    if value >= 1_000:
        return f"${value / 1_000:.0f}k"
    return f"${value:,.0f}"


def build_appreciation_chart(
    series_rows: list[dict[str, Any]],
    *,
    chart_title: str = "Appreciation history",
    y_axis_label: str = "Index value",
    start_at_zero: bool = False,
    value_key: str = "value_numeric",
    total_change_label: str = "Total change",
    value_summary_label: str = "Value moved from",
    value_label_formatter=None,
) -> dict[str, Any]:
    if len(series_rows) < 2:
        return {
            "available": False,
            "title": chart_title,
            "empty_message": "No official appreciation series is available for this market yet.",
            "notes": "Victoria can use Statistics Canada RPPI data. Smaller markets may need a separate source later.",
            "chart_path": "",
            "series_points": [],
        }

    values = [float(row[value_key]) for row in series_rows if row.get(value_key) is not None]
    if len(values) < 2:
        return {
            "available": False,
            "title": chart_title,
            "empty_message": "No official appreciation series is available for this market yet.",
            "notes": "Victoria can use Statistics Canada RPPI data. Smaller markets may need a separate source later.",
            "chart_path": "",
            "series_points": [],
        }

    width = 760
    height = 280
    padding_left = 94
    padding_right = 18
    padding_top = 18
    padding_bottom = 36
    min_value = 0.0 if start_at_zero else min(values)
    max_value = max(values)
    value_span = max(max_value - min_value, 1.0)
    chart_width = width - padding_left - padding_right
    chart_height = height - padding_top - padding_bottom
    step_x = chart_width / max(len(values) - 1, 1)

    point_pairs: list[str] = []
    series_points: list[dict[str, Any]] = []
    for index, row in enumerate(series_rows):
        raw_value = row.get(value_key)
        if raw_value is None:
            continue
        value = float(raw_value)
        x = padding_left + index * step_x
        normalized_y = (value - min_value) / value_span
        y = height - padding_bottom - normalized_y * chart_height
        point_pairs.append(f"{x:.1f},{y:.1f}")
        series_points.append(
            {
                "label": row.get("point_date"),
                "display_value": value_label_formatter(value) if value_label_formatter else f"{value:.1f}",
                "x": round(x, 1),
                "y": round(y, 1),
            }
        )

    y_tick_count = 4
    y_axis_ticks: list[dict[str, Any]] = []
    for tick_index in range(y_tick_count + 1):
        ratio = tick_index / y_tick_count
        tick_value = min_value + (value_span * (1.0 - ratio))
        y = padding_top + chart_height * ratio
        y_axis_ticks.append(
            {
                "label": value_label_formatter(tick_value) if value_label_formatter else f"{tick_value:.0f}",
                "x": padding_left,
                "y": round(y, 1),
                "line_x2": width - padding_right,
            }
        )

    candidate_indices = sorted({0, len(series_rows) // 2, len(series_rows) - 1})
    x_axis_ticks: list[dict[str, Any]] = []
    for index in candidate_indices:
        row = series_rows[index]
        x_axis_ticks.append(
            {
                "label": row.get("point_date"),
                "x": round(padding_left + index * step_x, 1),
                "y": height - padding_bottom,
            }
        )

    first_value = float(series_rows[0][value_key])
    last_value = float(series_rows[-1][value_key])
    total_change_percent = ((last_value / first_value) - 1.0) * 100 if first_value else None
    return {
        "available": True,
        "title": chart_title,
        "total_change_label": total_change_label,
        "value_summary_label": value_summary_label,
        "empty_message": None,
        "notes": series_rows[-1].get("notes"),
        "y_axis_label": y_axis_label,
        "chart_width": width,
        "chart_height": height,
        "plot_left": padding_left,
        "plot_right": width - padding_right,
        "plot_top": padding_top,
        "plot_bottom": height - padding_bottom,
        "chart_path": " ".join(point_pairs),
        "series_points": series_points,
        "y_axis_ticks": y_axis_ticks,
        "x_axis_ticks": x_axis_ticks,
        "start_label": series_rows[0].get("point_date"),
        "end_label": series_rows[-1].get("point_date"),
        "start_value": value_label_formatter(first_value) if value_label_formatter else f"{first_value:.1f}",
        "end_value": value_label_formatter(last_value) if value_label_formatter else f"{last_value:.1f}",
        "total_change_display": format_percent(total_change_percent, digits=1) if total_change_percent is not None else "—",
        "source_name": series_rows[-1].get("source_name"),
        "source_url": series_rows[-1].get("source_url"),
        "confidence": series_rows[-1].get("confidence"),
    }


def build_preferred_appreciation_context(
    config: SupabaseReadConfig,
    market_key: str,
    *,
    property_type_slug: str = "composite",
    allow_proxy: bool = False,
) -> dict[str, Any]:
    hpi_snapshot = fetch_hpi_market_metric_snapshot(config, market_key, property_type_slug=property_type_slug)
    if hpi_snapshot is not None:
        observation_rows = fetch_hpi_observation_series(
            config,
            market_key,
            property_type_slug=property_type_slug,
        )
        chart = build_appreciation_chart(
            observation_rows,
            chart_title="Benchmark price history",
            y_axis_label="Benchmark price (CAD)",
            start_at_zero=True,
            value_key="benchmark_price",
            total_change_label="Long-term benchmark change",
            value_summary_label="Benchmark moved from",
            value_label_formatter=format_axis_currency,
        )
        chart.update(
            {
                "source_key": "crea_hpi",
                "source_name": "CREA MLS HPI",
                "property_type_label": hpi_snapshot.get("property_type_label") or property_type_slug.replace("_", " ").title(),
                "latest_date": hpi_snapshot.get("latest_date"),
                "latest_benchmark_price": hpi_snapshot.get("latest_benchmark_price"),
                "latest_benchmark_price_display": (
                    format_currency(float(hpi_snapshot["latest_benchmark_price"]))
                    if hpi_snapshot.get("latest_benchmark_price") is not None
                    else "—"
                ),
                "metric_cards": build_appreciation_metric_cards(hpi_snapshot),
                "trend_direction": hpi_snapshot.get("trend_direction"),
                "trend_label": format_signal_label(hpi_snapshot.get("trend_direction") or "insufficient_data"),
                "data_quality_flag": hpi_snapshot.get("data_quality_flag"),
                "method_notes": hpi_snapshot.get("method_notes"),
                "benchmark_explainer": (
                    f"The latest benchmark shown is the CREA {hpi_snapshot.get('property_type_label', 'Composite')} "
                    f"market-wide benchmark home price for {hpi_snapshot.get('market_name', market_key)} as of {hpi_snapshot.get('latest_date')}."
                ),
                "proxy_active": False,
                "proxy_available": get_appreciation_proxy_market(market_key) is not None,
                "ai_estimate_available": True,
            }
        )
        if not chart["available"]:
            chart["empty_message"] = "CREA HPI metrics exist, but the series points have not been published yet."
            chart["notes"] = hpi_snapshot.get("method_notes")
        return chart

    proxy_market = get_appreciation_proxy_market(market_key)
    if allow_proxy and proxy_market is not None:
        proxy_snapshot = fetch_hpi_market_metric_snapshot(
            config,
            proxy_market["proxy_key"],
            property_type_slug=property_type_slug,
        )
        if proxy_snapshot is not None:
            proxy_observation_rows = fetch_hpi_observation_series(
                config,
                proxy_market["proxy_key"],
                property_type_slug=property_type_slug,
            )
            chart = build_appreciation_chart(
                proxy_observation_rows,
                chart_title="Benchmark price history",
                y_axis_label="Benchmark price (CAD)",
                start_at_zero=True,
                value_key="benchmark_price",
                total_change_label="Long-term benchmark change",
                value_summary_label="Benchmark moved from",
                value_label_formatter=format_axis_currency,
            )
            chart.update(
                {
                    "source_key": "crea_hpi_proxy",
                    "source_name": "CREA MLS HPI",
                    "property_type_label": proxy_snapshot.get("property_type_label") or property_type_slug.replace("_", " ").title(),
                    "latest_date": proxy_snapshot.get("latest_date"),
                    "latest_benchmark_price": proxy_snapshot.get("latest_benchmark_price"),
                    "latest_benchmark_price_display": (
                        format_currency(float(proxy_snapshot["latest_benchmark_price"]))
                        if proxy_snapshot.get("latest_benchmark_price") is not None
                        else "—"
                    ),
                    "metric_cards": build_appreciation_metric_cards(proxy_snapshot),
                    "trend_direction": proxy_snapshot.get("trend_direction"),
                    "trend_label": format_signal_label(proxy_snapshot.get("trend_direction") or "insufficient_data"),
                    "data_quality_flag": proxy_market["confidence"],
                    "method_notes": None,
                    "benchmark_explainer": proxy_market["notes"],
                    "proxy_label": proxy_market["label"],
                    "proxy_market_name": proxy_market["proxy_name"],
                    "proxy_active": True,
                    "proxy_available": True,
                    "ai_estimate_available": True,
                }
            )
            return chart

    ai_estimate = fetch_market_appreciation_ai_estimate(
        config,
        market_key,
        property_type_slug=property_type_slug,
    )
    fallback_chart = build_appreciation_chart(
        fetch_market_metric_series(config, market_key, series_key="residential_property_price_index_total")
    )
    metric_cards = build_empty_appreciation_metric_cards()
    source_key = "fallback_series"
    source_name = fallback_chart.get("source_name")
    trend_label = None
    data_quality_flag = None
    notes = fallback_chart.get("notes")
    latest_benchmark_price = None
    latest_benchmark_price_display = "—"
    latest_date = None
    if ai_estimate is not None:
        metric_cards = build_ai_appreciation_metric_cards(ai_estimate)
        source_key = "ai_appreciation_estimate"
        source_name = "AI estimate"
        trend_label = ai_estimate.get("trend_label")
        data_quality_flag = ai_estimate.get("confidence")
        notes = ai_estimate.get("reasoning")
        latest_benchmark_price = ai_estimate.get("latest_benchmark_price")
        latest_benchmark_price_display = (
            format_currency(float(latest_benchmark_price)) if latest_benchmark_price is not None else "—"
        )
    fallback_chart.update(
        {
            "source_key": source_key,
            "property_type_label": None,
            "latest_date": latest_date,
            "latest_benchmark_price": latest_benchmark_price,
            "latest_benchmark_price_display": latest_benchmark_price_display,
            "metric_cards": metric_cards,
            "trend_direction": None,
            "trend_label": trend_label,
            "data_quality_flag": data_quality_flag,
            "method_notes": None,
            "benchmark_explainer": None,
            "proxy_label": proxy_market["label"] if proxy_market else None,
            "proxy_market_name": proxy_market["proxy_name"] if proxy_market else None,
            "proxy_active": False,
            "proxy_available": proxy_market is not None,
            "ai_estimate_available": True,
            "ai_estimate_active": ai_estimate is not None,
            "ai_source_names": ai_estimate.get("source_names", []) if ai_estimate is not None else [],
            "ai_source_urls": ai_estimate.get("source_urls", []) if ai_estimate is not None else [],
        }
    )
    if not fallback_chart["available"]:
        fallback_chart["notes"] = notes or (
            "CREA HPI is the primary appreciation source for supported markets. "
            "Markets without official coverage continue to show a clean empty state for now."
        )
    return fallback_chart


def build_market_housing_summary(
    config: SupabaseReadConfig,
    market_profile: dict[str, Any],
    *,
    bedroom_count: int | None = 2,
) -> dict[str, Any]:
    if "_selected_bedroom_count" in market_profile:
        bedroom_count = market_profile.get("_selected_bedroom_count")
    market_rows = fetch_market_reference_rows(config)
    exact_market_key = market_profile.get("market_key")
    exact_rows = [row for row in market_rows if row.get("market_key") == exact_market_key]
    ai_estimates = fetch_market_rental_ai_estimates(config, str(exact_market_key or ""))

    grouped_rows: dict[str, list[dict[str, Any]]] = {}
    for row in exact_rows:
        property_type = (row.get("property_type") or "").strip().lower()
        if property_type:
            grouped_rows.setdefault(property_type, []).append(row)

    rental_cards: list[dict[str, Any]] = []
    for property_type in MARKET_RENTAL_CARD_TYPES:
        rows = grouped_rows.get(property_type) or []
        if bedroom_count is None:
            rent_row = next((row for row in rows if row.get("bedroom_count") is None and row.get("average_rent_monthly") is not None), None)
        else:
            rent_row = next((row for row in rows if row.get("bedroom_count") == bedroom_count and row.get("average_rent_monthly") is not None), None)
        if rent_row is None:
            rent_row = next((row for row in rows if row.get("average_rent_monthly") is not None), None)
        if bedroom_count is None:
            vacancy_row = next((row for row in rows if row.get("bedroom_count") is None and row.get("vacancy_rate_percent") is not None), None)
        else:
            vacancy_row = next((row for row in rows if row.get("bedroom_count") == bedroom_count and row.get("vacancy_rate_percent") is not None), None)
        if vacancy_row is None:
            vacancy_row = next((row for row in rows if row.get("bedroom_count") is None and row.get("vacancy_rate_percent") is not None), None)
        if vacancy_row is None:
            vacancy_row = next((row for row in rows if row.get("vacancy_rate_percent") is not None), None)
        estimate_key = (property_type, bedroom_count)
        ai_estimate = ai_estimates.get(estimate_key) or ai_estimates.get((property_type, None))
        source_row = rent_row or vacancy_row or (rows[0] if rows else {})
        average_rent = rent_row.get("average_rent_monthly") if rent_row else None
        vacancy_rate = vacancy_row.get("vacancy_rate_percent") if vacancy_row else None
        value_source = "cmhc" if average_rent is not None or vacancy_rate is not None else "missing"
        if average_rent is None and isinstance(ai_estimate, dict):
            average_rent = ai_estimate.get("average_rent_monthly")
            value_source = "ai_estimate"
        if vacancy_rate is None and isinstance(ai_estimate, dict):
            vacancy_rate = ai_estimate.get("vacancy_rate_percent")
        displayed_bedroom_count = bedroom_count if bedroom_count is not None else (rent_row.get("bedroom_count") if rent_row else None)
        source_names = ai_estimate.get("source_names", []) if isinstance(ai_estimate, dict) else []
        source_urls = ai_estimate.get("source_urls", []) if isinstance(ai_estimate, dict) else []
        review_links = build_market_rental_review_links(market_profile, property_type, bedroom_count)
        direct_comps_found = ai_estimate.get("direct_comps_found") if isinstance(ai_estimate, dict) else None
        fallback_comps_found = ai_estimate.get("fallback_comps_found") if isinstance(ai_estimate, dict) else None
        rental_cards.append(
            {
                "property_type": property_type,
                "property_type_label": get_rental_property_type_label(property_type),
                "rent_display": format_currency(float(average_rent)) if average_rent is not None else "—",
                "vacancy_display": format_percent(float(vacancy_rate), digits=1) if vacancy_rate is not None else "—",
                "rent_label": (
                    f"{format_bedroom_option_label(displayed_bedroom_count)}-bedroom rent"
                    if isinstance(displayed_bedroom_count, int)
                    else "Average rent"
                ),
                "source_url": source_row.get("source_url"),
                "source_date": source_row.get("source_date"),
                "market_research_summary": (
                    ai_estimate.get("market_research_summary")
                    if value_source == "ai_estimate" and isinstance(ai_estimate, dict)
                    else None
                ),
                "direct_comps_found": direct_comps_found,
                "fallback_comps_found": fallback_comps_found,
                "fallback_strategy": ai_estimate.get("fallback_strategy") if isinstance(ai_estimate, dict) else None,
                "notes": ai_estimate.get("reasoning") if value_source == "ai_estimate" and isinstance(ai_estimate, dict) else None,
                "value_source": value_source,
                "confidence": ai_estimate.get("confidence") if value_source == "ai_estimate" and isinstance(ai_estimate, dict) else None,
                "ai_source_names": source_names,
                "ai_source_urls": source_urls,
                "review_links": review_links,
                "bedroom_count": bedroom_count,
                "missing_value": value_source == "missing",
            }
        )

    market_match = find_market_reference_match(
        {
            "location": market_profile.get("market_name"),
            "property_type": "apartment",
            "beds_min": 2,
        },
        market_rows,
    )
    if not market_match:
        return {
            "available": False,
            "rent_display": "—",
            "vacancy_display": "—",
            "rental_cards": rental_cards,
            "match_label": "No CMHC match",
            "notes": "No CMHC rental-market baseline is currently available for this market.",
            "source_url": None,
            "source_date": None,
            "confidence": None,
            "selected_bedroom_count": bedroom_count,
        }

    reference = market_match.get("market_reference") or {}
    average_rent = reference.get("average_rent_monthly")
    vacancy_rate = reference.get("vacancy_rate_percent")
    if not rental_cards and (average_rent is not None or vacancy_rate is not None):
        fallback_property_type = reference.get("property_type")
        fallback_bedroom_count = reference.get("bedroom_count")
        rental_cards.append(
            {
                "property_type": fallback_property_type,
                "property_type_label": get_rental_property_type_label(fallback_property_type),
                "rent_display": format_currency(float(average_rent)) if average_rent is not None else "—",
                "vacancy_display": format_percent(float(vacancy_rate), digits=1) if vacancy_rate is not None else "—",
                "rent_label": (
                    f"{format_bedroom_option_label(fallback_bedroom_count)}-bedroom rent"
                    if isinstance(fallback_bedroom_count, int)
                    else "Average rent"
                ),
                "source_url": reference.get("source_url"),
                "source_date": reference.get("source_date"),
                "notes": market_match.get("notes"),
            }
        )
    return {
        "available": average_rent is not None or vacancy_rate is not None,
        "rent_display": format_currency(float(average_rent)) if average_rent is not None else "—",
        "vacancy_display": format_percent(float(vacancy_rate), digits=1) if vacancy_rate is not None else "—",
        "rental_cards": rental_cards,
        "match_label": f"CMHC {market_match.get('reference_label') or market_match.get('match_type', 'reference').title()}",
        "matched_market_name": market_match.get("matched_market_name"),
        "notes": market_match.get("notes"),
        "source_url": reference.get("source_url"),
        "source_date": reference.get("source_date"),
        "confidence": market_match.get("confidence"),
        "selected_bedroom_count": bedroom_count,
    }


def persist_saved_search_investment_defaults(
    config: SupabaseReadConfig,
    saved_search_id: int,
    defaults_snapshot: dict[str, dict[str, Any]],
) -> None:
    supabase_post(
        config,
        "saved_search_investment_defaults",
        query={"on_conflict": "saved_search_id"},
        payload=[
            {
                "saved_search_id": saved_search_id,
                "defaults_snapshot": defaults_snapshot,
            }
        ],
        prefer="resolution=merge-duplicates,return=representation",
    )


def fetch_listing_investment_overrides(
    config: SupabaseReadConfig,
    saved_search_id: int,
    listing_ids: list[int],
) -> dict[int, dict[str, Any]]:
    normalized_ids = sorted({listing_id for listing_id in listing_ids if isinstance(listing_id, int)})
    if not normalized_ids:
        return {}
    try:
        result = supabase_get(
            config,
            "listing_investment_overrides",
            query={
                "saved_search_id": f"eq.{saved_search_id}",
                "listing_id": f"in.({','.join(str(listing_id) for listing_id in normalized_ids)})",
                "select": "listing_id,overrides_snapshot",
            },
        )
    except RuntimeError:
        return {}
    rows = result if isinstance(result, list) else []
    overrides_by_listing_id: dict[int, dict[str, Any]] = {}
    for row in rows:
        listing_id = row.get("listing_id")
        snapshot = row.get("overrides_snapshot")
        if isinstance(listing_id, int) and isinstance(snapshot, dict):
            overrides_by_listing_id[listing_id] = snapshot
    return overrides_by_listing_id


def persist_listing_investment_override(
    config: SupabaseReadConfig,
    saved_search_id: int,
    listing_id: int,
    override_updates: dict[str, Any],
) -> None:
    current_snapshot = fetch_listing_investment_overrides(config, saved_search_id, [listing_id]).get(listing_id, {})
    normalized_snapshot = dict(current_snapshot) if isinstance(current_snapshot, dict) else {}
    for key, value in override_updates.items():
        if value is None:
            normalized_snapshot.pop(key, None)
        else:
            normalized_snapshot[key] = value
    supabase_post(
        config,
        "listing_investment_overrides",
        query={"on_conflict": "saved_search_id,listing_id"},
        payload=[
            {
                "saved_search_id": saved_search_id,
                "listing_id": listing_id,
                "overrides_snapshot": normalized_snapshot,
            }
        ],
        prefer="resolution=merge-duplicates,return=representation",
    )


def clear_listing_rent_overrides_for_saved_search(
    config: SupabaseReadConfig,
    saved_search_id: int,
) -> None:
    try:
        result = supabase_get(
            config,
            "listing_investment_overrides",
            query={
                "saved_search_id": f"eq.{saved_search_id}",
                "select": "id,listing_id,overrides_snapshot",
            },
        )
    except RuntimeError:
        return
    rows = result if isinstance(result, list) else []
    for row in rows:
        listing_id = row.get("listing_id")
        snapshot = row.get("overrides_snapshot")
        if not isinstance(listing_id, int) or not isinstance(snapshot, dict):
            continue
        if "market_rent_monthly" not in snapshot and "market_rent_source" not in snapshot:
            continue
        updated_snapshot = dict(snapshot)
        updated_snapshot.pop("market_rent_monthly", None)
        updated_snapshot.pop("market_rent_source", None)
        supabase_patch(
            config,
            "listing_investment_overrides",
            query={"saved_search_id": f"eq.{saved_search_id}", "listing_id": f"eq.{listing_id}"},
            payload={"overrides_snapshot": updated_snapshot},
        )


def clear_listing_override_keys_for_saved_search(
    config: SupabaseReadConfig,
    saved_search_id: int,
    keys: list[str],
) -> None:
    try:
        result = supabase_get(
            config,
            "listing_investment_overrides",
            query={
                "saved_search_id": f"eq.{saved_search_id}",
                "select": "listing_id,overrides_snapshot",
            },
        )
    except RuntimeError:
        return
    rows = result if isinstance(result, list) else []
    for row in rows:
        listing_id = row.get("listing_id")
        snapshot = row.get("overrides_snapshot")
        if not isinstance(listing_id, int) or not isinstance(snapshot, dict):
            continue
        if not any(key in snapshot for key in keys):
            continue
        updated_snapshot = dict(snapshot)
        for key in keys:
            updated_snapshot.pop(key, None)
        supabase_patch(
            config,
            "listing_investment_overrides",
            query={"saved_search_id": f"eq.{saved_search_id}", "listing_id": f"eq.{listing_id}"},
            payload={"overrides_snapshot": updated_snapshot},
        )


def persist_ai_underwriting_suggestion(
    config: SupabaseReadConfig,
    *,
    saved_search_id: int,
    listing_id: int | None,
    suggestion_type: str,
    status: str,
    prompt_text: str,
    model: str | None,
    input_context: dict[str, Any],
    raw_response_text: str,
    parsed_suggestion: dict[str, Any],
    accepted_value: int | None = None,
) -> None:
    try:
        supabase_post(
            config,
            "ai_underwriting_suggestions",
            payload=[
                {
                    "saved_search_id": saved_search_id,
                    "listing_id": listing_id,
                    "suggestion_type": suggestion_type,
                    "status": status,
                    "prompt_text": prompt_text,
                    "model": model,
                    "input_context": input_context,
                    "raw_response_text": raw_response_text,
                    "parsed_suggestion": parsed_suggestion,
                    "accepted_value": accepted_value,
                    "accepted_at": datetime.utcnow().isoformat(timespec="seconds") + "Z" if accepted_value is not None else None,
                }
            ],
            prefer="return=minimal",
        )
    except RuntimeError:
        return


def fetch_latest_ai_underwriting_suggestion(
    config: SupabaseReadConfig,
    *,
    saved_search_id: int,
    listing_id: int,
    suggestion_type: str,
) -> dict[str, Any] | None:
    try:
        result = supabase_get(
            config,
            "ai_underwriting_suggestions",
            query={
                "saved_search_id": f"eq.{saved_search_id}",
                "listing_id": f"eq.{listing_id}",
                "suggestion_type": f"eq.{suggestion_type}",
                "status": "eq.accepted",
                "select": "accepted_value,model,parsed_suggestion,created_at",
                "order": "created_at.desc",
                "limit": 1,
            },
        )
    except RuntimeError:
        return None
    rows = result if isinstance(result, list) else []
    return rows[0] if rows else None


def count_sparse_listings(listings: list[dict[str, Any]]) -> int:
    required_fields = [
        "listing_description",
        "property_type",
        "building_type",
        "square_feet",
        "built_in",
    ]
    sparse_count = 0
    for listing in listings:
        if any(not listing.get(field) for field in required_fields):
            sparse_count += 1
    return sparse_count


def persist_saved_buy_box(
    config: SupabaseReadConfig,
    saved_search: dict[str, Any],
    criteria: dict[str, Any],
) -> None:
    snapshot = saved_search.get("search_snapshot")
    normalized_snapshot = dict(snapshot) if isinstance(snapshot, dict) else {}
    normalized_snapshot["buy_box"] = serialize_buy_box_criteria(criteria)
    supabase_patch(
        config,
        "saved_searches",
        query={"id": f"eq.{saved_search['id']}"},
        payload={"search_snapshot": normalized_snapshot},
    )
    saved_search["search_snapshot"] = normalized_snapshot


def persist_latest_listing_analysis(
    config: SupabaseReadConfig,
    saved_search: dict[str, Any],
    state: dict[str, Any],
) -> None:
    snapshot = saved_search.get("search_snapshot")
    normalized_snapshot = dict(snapshot) if isinstance(snapshot, dict) else {}
    normalized_snapshot["latest_listing_analysis"] = state
    try:
        supabase_patch(
            config,
            "saved_searches",
            query={"id": f"eq.{saved_search['id']}"},
            payload={"search_snapshot": normalized_snapshot},
        )
    except RuntimeError:
        return
    saved_search["search_snapshot"] = normalized_snapshot


def clear_saved_buy_box(config: SupabaseReadConfig, saved_search: dict[str, Any]) -> None:
    snapshot = saved_search.get("search_snapshot")
    normalized_snapshot = dict(snapshot) if isinstance(snapshot, dict) else {}
    normalized_snapshot.pop("buy_box", None)
    normalized_snapshot.pop("latest_listing_analysis", None)
    supabase_patch(
        config,
        "saved_searches",
        query={"id": f"eq.{saved_search['id']}"},
        payload={"search_snapshot": normalized_snapshot},
    )
    saved_search["search_snapshot"] = normalized_snapshot


def fetch_active_listing_detail(
    config: SupabaseReadConfig,
    saved_search_id: int,
    listing_id: int,
) -> dict[str, Any] | None:
    result = supabase_get(
        config,
        "current_active_saved_search_listings",
        query={
            "saved_search_id": f"eq.{saved_search_id}",
            "listing_id": f"eq.{listing_id}",
            "select": (
                "saved_search_id,listing_id,address,price,bedrooms,bathrooms,property_type,building_type,"
                "square_feet,land_size,built_in,annual_taxes,hoa_fees,time_on_realtor,zoning_type,url,"
                "results_page,is_new_in_run,last_seen_at,listing_description,source_listing_key,source"
            ),
            "limit": 1,
        },
    )
    if isinstance(result, list) and result:
        listing = result[0]
        merge_listing_media(config, [listing])
        return listing
    return None


def fetch_listing_media(config: SupabaseReadConfig, listing_ids: list[int]) -> dict[int, dict[str, Any]]:
    unique_ids = sorted({listing_id for listing_id in listing_ids if listing_id})
    if not unique_ids:
        return {}

    result = supabase_get(
        config,
        "listings",
        query={
            "id": f"in.({','.join(str(listing_id) for listing_id in unique_ids)})",
            "select": "id,property_type,building_type,raw_listing",
        },
    )
    rows = result if isinstance(result, list) else []
    media_by_id: dict[int, dict[str, Any]] = {}
    for row in rows:
        raw_listing = row.get("raw_listing") if isinstance(row, dict) else None
        photo_urls = raw_listing.get("photo_urls") if isinstance(raw_listing, dict) else None
        if not isinstance(photo_urls, list):
            photo_urls = []
        cleaned_urls = [url for url in photo_urls if isinstance(url, str) and url.strip()]
        primary_photo_url = raw_listing.get("primary_photo_url") if isinstance(raw_listing, dict) else None
        if not primary_photo_url and cleaned_urls:
            primary_photo_url = cleaned_urls[0]
        property_type = row.get("property_type") if isinstance(row, dict) else None
        building_type = row.get("building_type") if isinstance(row, dict) else None
        if isinstance(raw_listing, dict):
            property_type = property_type or raw_listing.get("property_type")
            building_type = building_type or raw_listing.get("building_type")
        media_by_id[row["id"]] = {
            "photo_urls": cleaned_urls[:6],
            "primary_photo_url": primary_photo_url,
            "property_type": property_type,
            "building_type": building_type,
            "listing_description": raw_listing.get("listing_description") if isinstance(raw_listing, dict) else None,
            "square_feet": raw_listing.get("square_feet") if isinstance(raw_listing, dict) else None,
            "land_size": raw_listing.get("land_size") if isinstance(raw_listing, dict) else None,
            "built_in": raw_listing.get("built_in") if isinstance(raw_listing, dict) else None,
            "annual_taxes": raw_listing.get("annual_taxes") if isinstance(raw_listing, dict) else None,
            "hoa_fees": raw_listing.get("hoa_fees") if isinstance(raw_listing, dict) else None,
            "time_on_realtor": raw_listing.get("time_on_realtor") if isinstance(raw_listing, dict) else None,
            "zoning_type": raw_listing.get("zoning_type") if isinstance(raw_listing, dict) else None,
        }
    return media_by_id


def merge_listing_media(config: SupabaseReadConfig, listings: list[dict[str, Any]]) -> None:
    media_by_id = fetch_listing_media(
        config,
        [
            normalize_listing_id(listing.get("listing_id"))
            for listing in listings
            if isinstance(listing, dict)
        ],
    )
    for listing in listings:
        media = media_by_id.get(normalize_listing_id(listing.get("listing_id")), {})
        listing["photo_urls"] = media.get("photo_urls", [])
        listing["primary_photo_url"] = media.get("primary_photo_url")
        listing["property_type"] = listing.get("property_type") or media.get("property_type")
        listing["building_type"] = listing.get("building_type") or media.get("building_type")
        listing["listing_description"] = listing.get("listing_description") or media.get("listing_description")
        listing["square_feet"] = listing.get("square_feet") or media.get("square_feet")
        listing["land_size"] = listing.get("land_size") or media.get("land_size")
        listing["built_in"] = listing.get("built_in") or media.get("built_in")
        listing["annual_taxes"] = listing.get("annual_taxes") or media.get("annual_taxes")
        listing["hoa_fees"] = listing.get("hoa_fees") or media.get("hoa_fees")
        listing["time_on_realtor"] = listing.get("time_on_realtor") or media.get("time_on_realtor")
        listing["zoning_type"] = listing.get("zoning_type") or media.get("zoning_type")


def form_value(form_data, key: str, default: Any = None) -> Any:
    if form_data is None:
        return default
    value = form_data.get(key)
    if value is None or str(value).strip() == "":
        return default
    return value


def form_flag_enabled(form_data, key: str, default: bool = False) -> bool:
    if form_data is None:
        return default
    if key not in form_data:
        return False
    value = str(form_data.get(key) or "").strip().lower()
    return value not in {"", "0", "false", "off", "no"}


def parse_price_form_value(value: Any) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip().lower().replace(",", "")
    if not cleaned:
        return None
    multiplier = 1
    if "million" in cleaned:
        multiplier = 1_000_000
        cleaned = cleaned.replace("million", "")
    elif cleaned.endswith("m"):
        multiplier = 1_000_000
        cleaned = cleaned[:-1]
    elif cleaned.endswith("k"):
        multiplier = 1_000
        cleaned = cleaned[:-1]
    cleaned = cleaned.replace("$", "").strip()
    try:
        parsed_amount = float(cleaned)
    except ValueError:
        return str(value).strip()
    if multiplier == 1 and "." in cleaned and 0 < parsed_amount < 1000:
        multiplier = 1_000_000
    amount = parsed_amount * multiplier
    if amount <= 0:
        return None
    return str(int(round(amount)))


def build_scrape_args(form_data) -> list[str]:
    args = [str(resolve_scraper_python()), "scraper.py"]

    def append_value(flag: str, value: str | None) -> None:
        if value is None:
            return
        cleaned = value.strip()
        if cleaned:
            args.extend([flag, cleaned])

    beds_min = parse_optional_int(form_data.get("beds_min"))
    append_value("--location", form_data.get("location"))
    if beds_min is not None and beds_min > 0:
        append_value("--beds-min", str(beds_min))
    append_value("--property-type", form_data.get("property_type"))
    append_value("--min-price", parse_price_form_value(form_data.get("min_price")))
    append_value("--max-price", parse_price_form_value(form_data.get("max_price")))
    append_value("--max-pages", form_value(form_data, "max_pages", str(DEFAULT_MAX_PAGES)))
    append_value("--max-listings", form_value(form_data, "max_listings", str(DEFAULT_MAX_LISTINGS)))
    append_value("--detail-limit", form_value(form_data, "detail_limit", str(DEFAULT_DETAIL_LIMIT)))
    append_value("--detail-concurrency", form_value(form_data, "detail_concurrency", str(DEFAULT_DETAIL_CONCURRENCY)))
    append_value("--detail-pause-min", form_value(form_data, "detail_pause_min", str(DEFAULT_DETAIL_PAUSE_MIN)))
    append_value("--detail-pause-max", form_value(form_data, "detail_pause_max", str(DEFAULT_DETAIL_PAUSE_MAX)))
    if form_flag_enabled(form_data, "block_detail_assets", DEFAULT_BLOCK_DETAIL_ASSETS):
        args.append("--block-detail-assets")
    return args


def build_scrape_args_from_saved_search(saved_search: dict[str, Any], form_data=None) -> list[str]:
    args = [str(resolve_scraper_python()), "scraper.py"]

    def append_value(flag: str, value: Any) -> None:
        if value is None:
            return
        cleaned = str(value).strip()
        if cleaned:
            args.extend([flag, cleaned])

    beds_min = parse_optional_int(saved_search.get("beds_min"))
    append_value("--location", saved_search.get("location"))
    if beds_min is not None and beds_min > 0:
        append_value("--beds-min", str(beds_min))
    append_value("--property-type", saved_search.get("property_type"))
    append_value("--min-price", saved_search.get("min_price"))
    append_value("--max-price", saved_search.get("max_price"))
    append_value("--max-pages", form_value(form_data, "max_pages", DEFAULT_MAX_PAGES))
    append_value("--max-listings", form_value(form_data, "max_listings", DEFAULT_MAX_LISTINGS))
    append_value("--detail-limit", form_value(form_data, "detail_limit", DEFAULT_DETAIL_LIMIT))
    append_value("--detail-concurrency", form_value(form_data, "detail_concurrency", DEFAULT_DETAIL_CONCURRENCY))
    append_value("--detail-pause-min", form_value(form_data, "detail_pause_min", DEFAULT_DETAIL_PAUSE_MIN))
    append_value("--detail-pause-max", form_value(form_data, "detail_pause_max", DEFAULT_DETAIL_PAUSE_MAX))
    if form_flag_enabled(form_data, "block_detail_assets", DEFAULT_BLOCK_DETAIL_ASSETS):
        args.append("--block-detail-assets")
    return args


def build_retry_sparse_args(saved_search_id: int) -> list[str]:
    return [
        str(resolve_scraper_python()),
        "scripts/retry_sparse_listing_details.py",
        "--saved-search-id",
        str(saved_search_id),
        "--limit",
        "10",
        "--concurrency",
        str(DEFAULT_DETAIL_CONCURRENCY),
    ]


def resolve_scraper_python() -> Path:
    venv_python = APP_ROOT / ".venv" / "bin" / "python"
    return venv_python if venv_python.exists() else Path(sys.executable)


def start_scrape_job(args: list[str]) -> dict[str, Any]:
    LOCAL_JOB_LOG_DIR.mkdir(parents=True, exist_ok=True)
    job_id = uuid.uuid4().hex[:12]
    started_at = datetime.utcnow().isoformat(timespec="seconds") + "Z"
    log_path = LOCAL_JOB_LOG_DIR / f"{job_id}.log"
    log_handle = log_path.open("w", encoding="utf-8")
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    process = subprocess.Popen(
        args,
        cwd=APP_ROOT,
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        text=True,
        env=env,
        start_new_session=True,
    )
    log_handle.close()

    job = {
        "id": job_id,
        "args": args[1:],
        "pid": process.pid,
        "started_at": started_at,
        "log_path": str(log_path),
        "status_path": str(LOCAL_JOB_LOG_DIR / f"{job_id}.status.json"),
    }
    with SCRAPE_JOBS_LOCK:
        SCRAPE_JOBS[job_id] = job
    write_job_status(job, status="running", return_code=None)
    watcher = Thread(target=watch_scrape_job, args=(job, process), daemon=True)
    watcher.start()
    return job


def watch_scrape_job(job: dict[str, Any], process: subprocess.Popen[str]) -> None:
    return_code = process.wait()
    current_status = read_job_status(job).get("status")
    if current_status == "cancelled":
        status = "cancelled"
    else:
        status = "succeeded" if return_code == 0 else "failed"
    write_job_status(job, status=status, return_code=return_code)


def cancel_scrape_job(job: dict[str, Any]) -> None:
    if job.get("status") not in {"running", "unknown"}:
        return
    pid = int(job["pid"])
    try:
        os.killpg(pid, signal.SIGTERM)
    except ProcessLookupError:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    except PermissionError:
        os.kill(pid, signal.SIGTERM)
    write_job_status(job, status="cancelled", return_code=None)


def list_scrape_jobs() -> list[dict[str, Any]]:
    with SCRAPE_JOBS_LOCK:
        jobs = [augment_job_snapshot(job) for job in SCRAPE_JOBS.values()]
    return sorted(jobs, key=lambda item: item["started_at"], reverse=True)


def get_scrape_job(job_id: str) -> dict[str, Any] | None:
    with SCRAPE_JOBS_LOCK:
        job = SCRAPE_JOBS.get(job_id)
    return augment_job_snapshot(job) if job else None


def augment_job_snapshot(job: dict[str, Any] | None) -> dict[str, Any]:
    if job is None:
        return {}

    pid = job["pid"]
    status_payload = read_job_status(job)
    return_code = status_payload.get("return_code")
    status_label = status_payload.get("status", "running")

    if status_label == "running":
        try:
            os.kill(pid, 0)
        except OSError:
            if return_code is None:
                status_label = "unknown"
        else:
            status_label = "running"

    log_path = Path(job["log_path"])
    log_tail = ""
    if log_path.exists():
        lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
        log_tail = "\n".join(lines[-20:])

    snapshot = dict(job)
    snapshot["status"] = status_label
    snapshot["return_code"] = return_code
    snapshot["log_tail"] = log_tail
    return snapshot


def write_job_status(job: dict[str, Any], *, status: str, return_code: int | None) -> None:
    status_path = Path(job["status_path"])
    payload = {
        "status": status,
        "return_code": return_code,
        "updated_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
    }
    status_path.write_text(json.dumps(payload), encoding="utf-8")


def read_job_status(job: dict[str, Any]) -> dict[str, Any]:
    status_path = Path(job["status_path"])
    if not status_path.exists():
        return {"status": "running", "return_code": None}
    try:
        return json.loads(status_path.read_text(encoding="utf-8"))
    except Exception:
        return {"status": "unknown", "return_code": None}


app = create_app()


if __name__ == "__main__":
    app.run(debug=True, use_reloader=False, port=int(os.getenv("PORT", "5000")))
