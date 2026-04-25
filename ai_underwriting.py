from __future__ import annotations

import json
import os
from typing import Any
from urllib import error, request


def build_rent_ai_prompt_text() -> str:
    return (
        "Estimate monthly market rent for each listing in this saved search.\n\n"
        "Use the provided market baseline when present. If a listing appears stronger or weaker than the baseline "
        "because of size, age, condition, bedrooms, bathrooms, square footage, suite potential, or other meaningful "
        "details, adjust the rent estimate accordingly.\n\n"
        "For each listing, return:\n"
        "- listing_id\n"
        "- suggested_rent_monthly\n"
        "- confidence\n"
        "- reasoning\n"
        "- baseline_used\n"
        "- adjustment_direction\n\n"
        "Confidence must be one of: high, medium, low.\n"
        "Adjustment direction must be one of: above_baseline, near_baseline, below_baseline.\n"
        "Return structured JSON only."
    )


def build_rent_ai_payload(
    saved_search: dict[str, Any],
    listings: list[dict[str, Any]],
    market_match: dict[str, Any] | None,
    investment_defaults: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    reference = (market_match or {}).get("market_reference") or {}
    return {
        "saved_search": {
            "saved_search_id": saved_search.get("id"),
            "name": saved_search.get("name"),
            "location": saved_search.get("location"),
            "property_type": saved_search.get("property_type"),
            "beds_min": saved_search.get("beds_min"),
            "max_price": saved_search.get("max_price"),
        },
        "market_reference": {
            "source": reference.get("source"),
            "source_dataset": reference.get("source_dataset"),
            "matched_market_name": (market_match or {}).get("matched_market_name"),
            "match_type": (market_match or {}).get("match_type"),
            "confidence": (market_match or {}).get("confidence"),
            "average_rent_monthly": reference.get("average_rent_monthly"),
            "vacancy_rate_percent": reference.get("vacancy_rate_percent"),
            "source_url": reference.get("source_url"),
        },
        "current_defaults": {
            "saved_search_market_rent_monthly": investment_defaults["market_rent_monthly"].get("value"),
            "vacancy_percent": investment_defaults["vacancy_percent"].get("value"),
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
                "annual_taxes": listing.get("annual_taxes"),
                "listing_description": listing.get("listing_description"),
                "current_market_rent_default": investment_defaults["market_rent_monthly"].get("value"),
            }
            for listing in listings
        ],
    }


def call_openai_rent_suggestions(prompt_text: str, payload: dict[str, Any]) -> dict[str, Any]:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not configured.")

    model = os.getenv("OPENAI_UNDERWRITING_MODEL", "gpt-5.4-mini")
    body = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are assisting with buy-and-hold rental underwriting for Canadian residential listings. "
                    "Treat official market baseline data as the starting anchor when present. "
                    "Return only structured JSON."
                ),
            },
            {
                "role": "user",
                "content": f"{prompt_text}\n\nJSON payload:\n{json.dumps(payload)}",
            },
        ],
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "rent_suggestions",
                "strict": True,
                "schema": {
                    "type": "object",
                    "properties": {
                        "suggestions": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "listing_id": {"type": "integer"},
                                    "suggested_rent_monthly": {"type": "integer"},
                                    "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
                                    "reasoning": {"type": "string"},
                                    "baseline_used": {"type": ["integer", "null"]},
                                    "adjustment_direction": {
                                        "type": "string",
                                        "enum": ["above_baseline", "near_baseline", "below_baseline"],
                                    },
                                },
                                "required": [
                                    "listing_id",
                                    "suggested_rent_monthly",
                                    "confidence",
                                    "reasoning",
                                    "baseline_used",
                                    "adjustment_direction",
                                ],
                                "additionalProperties": False,
                            },
                        }
                    },
                    "required": ["suggestions"],
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

    payload_raw = json.loads(raw)
    content = payload_raw["choices"][0]["message"]["content"]
    parsed = json.loads(content)
    return {
        "raw_response_text": content,
        "parsed_response": parsed,
        "model": model,
    }


def build_market_rental_gap_prompt_text() -> str:
    return (
        "Estimate a missing Canadian market rental benchmark for one residential property type and bedroom count.\n\n"
        "Use the supplied official CMHC rows as anchors when they exist, then reason from comparable rental-market "
        "sources such as Rentals.ca, Zumper, Craigslist, Facebook Marketplace, PadMapper, liv.rent, local property "
        "management listings, and nearby official benchmarks. If you cannot verify live listings, be explicit that "
        "the estimate is a low-confidence synthesis rather than an official observed average.\n\n"
        "Return a clean benchmark estimate, a vacancy estimate when defensible, confidence, short reasoning, and "
        "source names or URLs a user should review manually. Return structured JSON only."
    )


def build_market_rental_gap_payload(
    market_profile: dict[str, Any],
    property_type: str,
    bedroom_count: int | None,
    reference_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    market_key = market_profile.get("market_key")
    nearby_rows = [
        {
            "market_key": row.get("market_key"),
            "market_name": row.get("market_name"),
            "property_type": row.get("property_type"),
            "bedroom_count": row.get("bedroom_count"),
            "average_rent_monthly": row.get("average_rent_monthly"),
            "vacancy_rate_percent": row.get("vacancy_rate_percent"),
            "source_dataset": row.get("source_dataset"),
            "source_date": row.get("source_date"),
        }
        for row in reference_rows
        if row.get("market_key") == market_key
    ]
    return {
        "market": {
            "market_key": market_key,
            "market_name": market_profile.get("market_name"),
            "province": market_profile.get("province"),
        },
        "missing_benchmark": {
            "property_type": property_type,
            "bedroom_count": bedroom_count,
        },
        "official_rows_for_this_market": nearby_rows,
    }


def call_openai_market_rental_gap_estimate(prompt_text: str, payload: dict[str, Any]) -> dict[str, Any]:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not configured.")

    model = os.getenv("OPENAI_UNDERWRITING_MODEL", "gpt-5.4-mini")
    body = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You assist with Canadian residential rental-market underwriting. "
                    "Do not present estimates as official data unless the supplied official rows support that. "
                    "Return only structured JSON."
                ),
            },
            {
                "role": "user",
                "content": f"{prompt_text}\n\nJSON payload:\n{json.dumps(payload)}",
            },
        ],
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "market_rental_gap_estimate",
                "strict": True,
                "schema": {
                    "type": "object",
                    "properties": {
                        "average_rent_monthly": {"type": "integer"},
                        "vacancy_rate_percent": {"type": ["number", "null"]},
                        "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
                        "reasoning": {"type": "string"},
                        "source_names": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "source_urls": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                    },
                    "required": [
                        "average_rent_monthly",
                        "vacancy_rate_percent",
                        "confidence",
                        "reasoning",
                        "source_names",
                        "source_urls",
                    ],
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

    payload_raw = json.loads(raw)
    content = payload_raw["choices"][0]["message"]["content"]
    parsed = json.loads(content)
    return {
        "raw_response_text": content,
        "parsed_response": parsed,
        "model": model,
    }


def build_market_appreciation_gap_prompt_text() -> str:
    return (
        "Estimate the target market's appreciation context for buy-and-hold real estate analysis.\n\n"
        "The supplied data may include official HPI data, proxy-market HPI data, census metrics, rent metrics, and "
        "other context. Treat this data as reference material, not necessarily as the final answer. Your task is to "
        "estimate the target market itself.\n\n"
        "For the target market, estimate:\n"
        "- latest market-wide benchmark home price\n"
        "- 1-month change\n"
        "- 12-month change\n"
        "- 5-year annualized appreciation\n"
        "- 10-year annualized appreciation\n"
        "- trend label\n"
        "- confidence\n"
        "- concise reasoning\n"
        "- source names or URLs a user should review\n\n"
        "If direct official data is missing, infer from nearby markets, regional trend data, population growth, "
        "household income, labour market strength, market size, liquidity, and any supplied proxy data. Do not simply "
        "copy proxy values unless you believe the proxy is truly representative; if you use proxy values, explain why.\n\n"
        "Return structured JSON only. Percentage values should be plain percentages, not ratios."
    )


def build_market_appreciation_gap_payload(
    market_profile: dict[str, Any],
    *,
    direct_snapshot: dict[str, Any] | None = None,
    proxy_snapshot: dict[str, Any] | None = None,
    proxy_market: dict[str, str] | None = None,
    market_metrics: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "market": {
            "market_key": market_profile.get("market_key"),
            "market_name": market_profile.get("market_name"),
            "province": market_profile.get("province"),
        },
        "direct_hpi_snapshot": direct_snapshot,
        "proxy_market": proxy_market,
        "proxy_hpi_snapshot": proxy_snapshot,
        "estimation_instruction": (
            "Estimate the target market directly. Do not simply return proxy values when proxy_market differs from "
            "market. Use the proxy as an anchor and apply a target-market adjustment."
        ),
        "structured_market_metrics": market_metrics or [],
    }


def call_openai_market_appreciation_gap_estimate(prompt_text: str, payload: dict[str, Any]) -> dict[str, Any]:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not configured.")

    model = os.getenv("OPENAI_UNDERWRITING_MODEL", "gpt-5.4-mini")
    body = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You assist with Canadian residential market analysis. "
                    "Do not present estimates as official data unless supplied source data supports that. "
                    "Return only structured JSON."
                ),
            },
            {
                "role": "user",
                "content": f"{prompt_text}\n\nJSON payload:\n{json.dumps(payload)}",
            },
        ],
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "market_appreciation_gap_estimate",
                "strict": True,
                "schema": {
                    "type": "object",
                    "properties": {
                        "latest_benchmark_price": {"type": ["integer", "null"]},
                        "change_1m_percent": {"type": ["number", "null"]},
                        "change_12m_percent": {"type": ["number", "null"]},
                        "appreciation_5y_cagr_percent": {"type": ["number", "null"]},
                        "appreciation_10y_cagr_percent": {"type": ["number", "null"]},
                        "trend_label": {"type": "string"},
                        "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
                        "reasoning": {"type": "string"},
                        "source_names": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "source_urls": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                    },
                    "required": [
                        "latest_benchmark_price",
                        "change_1m_percent",
                        "change_12m_percent",
                        "appreciation_5y_cagr_percent",
                        "appreciation_10y_cagr_percent",
                        "trend_label",
                        "confidence",
                        "reasoning",
                        "source_names",
                        "source_urls",
                    ],
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

    payload_raw = json.loads(raw)
    content = payload_raw["choices"][0]["message"]["content"]
    parsed = json.loads(content)
    return {
        "raw_response_text": content,
        "parsed_response": parsed,
        "model": model,
    }
