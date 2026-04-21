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
