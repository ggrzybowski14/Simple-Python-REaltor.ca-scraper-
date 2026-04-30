from __future__ import annotations

import json
import os
from typing import Any
from urllib import error, request

OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"


def get_openai_research_model() -> str:
    return os.getenv("OPENAI_RESEARCH_MODEL") or os.getenv("OPENAI_UNDERWRITING_MODEL", "gpt-5.4-mini")


def extract_response_text(response_payload: dict[str, Any]) -> str:
    output_text = response_payload.get("output_text")
    if isinstance(output_text, str) and output_text.strip():
        return output_text
    text_parts: list[str] = []
    for item in response_payload.get("output", []):
        if not isinstance(item, dict) or item.get("type") != "message":
            continue
        for content_item in item.get("content", []):
            if not isinstance(content_item, dict):
                continue
            text = content_item.get("text")
            if isinstance(text, str):
                text_parts.append(text)
    return "\n".join(text_parts).strip()


def extract_web_sources(response_payload: dict[str, Any]) -> list[dict[str, str]]:
    sources: list[dict[str, str]] = []
    seen_urls: set[str] = set()

    def add_source(candidate: dict[str, Any]) -> None:
        url = candidate.get("url")
        if not isinstance(url, str) or not url or url in seen_urls:
            return
        seen_urls.add(url)
        sources.append(
            {
                "url": url,
                "title": str(candidate.get("title") or candidate.get("source") or url),
            }
        )

    for item in response_payload.get("output", []):
        if not isinstance(item, dict):
            continue
        action = item.get("action")
        if isinstance(action, dict):
            for source in action.get("sources", []):
                if isinstance(source, dict):
                    add_source(source)
        if item.get("type") == "message":
            for content_item in item.get("content", []):
                if not isinstance(content_item, dict):
                    continue
                for annotation in content_item.get("annotations", []):
                    if isinstance(annotation, dict):
                        add_source(annotation)
    return sources


def merge_response_sources(parsed: dict[str, Any], sources: list[dict[str, str]]) -> dict[str, Any]:
    if not sources:
        return parsed
    existing_urls = [
        url for url in parsed.get("source_urls", [])
        if isinstance(url, str) and url
    ]
    existing_names = [
        name for name in parsed.get("source_names", [])
        if isinstance(name, str) and name
    ]
    for source in sources:
        if source["url"] not in existing_urls:
            existing_urls.append(source["url"])
        if source["title"] not in existing_names:
            existing_names.append(source["title"])
    parsed["source_urls"] = existing_urls
    parsed["source_names"] = existing_names
    return parsed


def call_openai_researched_json(
    *,
    system_text: str,
    prompt_text: str,
    payload: dict[str, Any],
    schema_name: str,
    schema: dict[str, Any],
    timeout: int = 120,
) -> dict[str, Any]:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not configured.")

    model = get_openai_research_model()
    body = {
        "model": model,
        "input": [
            {
                "role": "system",
                "content": [{"type": "input_text", "text": system_text}],
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": f"{prompt_text}\n\nJSON payload:\n{json.dumps(payload)}",
                    }
                ],
            },
        ],
        "tools": [{"type": "web_search"}],
        "tool_choice": "auto",
        "include": ["web_search_call.action.sources"],
        "text": {
            "format": {
                "type": "json_schema",
                "name": schema_name,
                "strict": True,
                "schema": schema,
            }
        },
    }

    req = request.Request(
        OPENAI_RESPONSES_URL,
        data=json.dumps(body).encode("utf-8"),
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )
    try:
        with request.urlopen(req, timeout=timeout) as response:
            raw = response.read().decode("utf-8", errors="replace")
    except error.HTTPError as exc:
        details = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"OpenAI request failed with status {exc.code}: {details}") from exc
    except error.URLError as exc:
        raise RuntimeError(f"OpenAI request failed: {exc.reason}") from exc

    response_payload = json.loads(raw)
    content = extract_response_text(response_payload)
    if not content:
        raise RuntimeError("OpenAI response did not include JSON text output.")
    parsed = json.loads(content)
    if isinstance(parsed, dict):
        parsed = merge_response_sources(parsed, extract_web_sources(response_payload))
    return {
        "raw_response_text": content,
        "parsed_response": parsed,
        "model": model,
        "web_sources": extract_web_sources(response_payload),
    }


def build_rent_ai_prompt_text() -> str:
    return (
        "Estimate monthly market rent for each listing in this saved search.\n\n"
        "First research current rental context for the saved-search market and buy-box profile using web search. "
        "For example, if the search is Nanaimo 4+ bedroom houses, establish a current market rent range for that "
        "profile from reputable rental-market sources before adjusting individual listings. Prioritize whole-property "
        "rental comps matching the saved-search property type and bedroom count. Exclude room rentals, shared "
        "accommodation, basement-suite-only rentals, short-term/vacation rentals, and mismatched apartment/townhouse "
        "evidence unless you clearly label it as fallback context.\n\n"
        "The market_research_summary must start with the direct whole-property comparable evidence and the resulting "
        "rent range. Only after that should it mention official baselines such as CMHC, affordability limits, apartment "
        "data, room data, or other fallback evidence. Do not open the summary with CMHC or affordability data unless "
        "zero direct whole-property comps were found.\n\n"
        "Treat the provided official market baseline as optional context, not the primary answer. If direct comps are "
        "thin, expand to nearby bedroom counts for the same property type, then nearby comparable municipalities, then "
        "official market baselines as a floor or broad context. If a listing appears stronger or weaker than the "
        "researched range because of size, age, condition, bedrooms, bathrooms, square footage, suite potential, or "
        "other meaningful details, adjust the rent estimate accordingly.\n\n"
        "When a listing clearly has multiple rentable units, estimate the total rent for the full listing and include "
        "a small rent_components breakdown such as main_unit plus basement_suite or carriage_suite. Do not invent a "
        "suite component when the listing only hints vaguely at potential; use an empty rent_components array unless "
        "the component is supported by listing facts or clearly labeled low-confidence reasoning.\n\n"
        "For each listing, return:\n"
        "- listing_id\n"
        "- suggested_rent_monthly\n"
        "- rent_components\n"
        "- confidence\n"
        "- reasoning\n"
        "- baseline_used\n"
        "- adjustment_direction\n\n"
        "Also return a market research summary, direct comp count, fallback comp count, fallback strategy, and the "
        "source names/URLs used for the market rent context.\n\n"
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
    schema = {
        "type": "object",
        "properties": {
            "market_research_summary": {"type": "string"},
            "direct_comps_found": {"type": "integer"},
            "fallback_comps_found": {"type": "integer"},
            "fallback_strategy": {"type": "string"},
            "source_names": {"type": "array", "items": {"type": "string"}},
            "source_urls": {"type": "array", "items": {"type": "string"}},
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
                        "rent_components": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "component_type": {
                                        "type": "string",
                                        "enum": [
                                            "main_unit",
                                            "basement_suite",
                                            "secondary_suite",
                                            "carriage_suite",
                                            "other_unit",
                                        ],
                                    },
                                    "estimated_rent_monthly": {"type": "integer"},
                                    "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
                                    "reasoning": {"type": "string"},
                                },
                                "required": [
                                    "component_type",
                                    "estimated_rent_monthly",
                                    "confidence",
                                    "reasoning",
                                ],
                                "additionalProperties": False,
                            },
                        },
                    },
                    "required": [
                        "listing_id",
                        "suggested_rent_monthly",
                        "confidence",
                        "reasoning",
                        "baseline_used",
                        "adjustment_direction",
                        "rent_components",
                    ],
                    "additionalProperties": False,
                },
            },
        },
        "required": [
            "market_research_summary",
            "direct_comps_found",
            "fallback_comps_found",
            "fallback_strategy",
            "source_names",
            "source_urls",
            "suggestions",
        ],
        "additionalProperties": False,
    }
    return call_openai_researched_json(
        system_text=(
            "You are assisting with buy-and-hold rental underwriting for Canadian residential listings. "
            "Use web search once to establish current, segment-specific market rent context for the saved-search "
            "profile, then apply that context across the provided listings. Treat supplied official market baseline "
            "data as optional context and fallback evidence, not as the primary source when direct comparable rents "
            "are available. Return only structured JSON."
        ),
        prompt_text=prompt_text,
        payload=payload,
        schema_name="rent_suggestions",
        schema=schema,
    )


def build_market_rental_gap_prompt_text() -> str:
    return (
        "Estimate a missing Canadian market rental benchmark for one residential property type and bedroom count.\n\n"
        "Prioritize current external comparable-rent evidence for the exact target segment before using any supplied "
        "official rows. Search for whole-property rental comps that match the target market, property type, and bedroom "
        "count. For single-family or detached homes, exclude room rentals, shared accommodation, basement suites, "
        "short-term/vacation rentals, and apartment/townhouse rows unless you clearly label them as fallback context.\n\n"
        "The market_research_summary and reasoning must start with direct whole-property comps and the rent range they "
        "support. Mention CMHC, affordability limits, apartment data, room data, or other fallback evidence only after "
        "summarizing direct comps. Do not lead with CMHC unless zero direct whole-property comps were found.\n\n"
        "If fewer than three direct comps are found, expand in this order: same-market nearby bedroom counts for the "
        "same property type, nearby comparable municipalities, then official CMHC or other structured rows as a floor "
        "or broad context. Do not let CMHC apartment or townhouse data drive a detached-house estimate unless no "
        "better evidence exists, and say so explicitly.\n\n"
        "Return a clean benchmark estimate, a vacancy estimate when defensible, confidence, short reasoning, and "
        "source names or URLs a user should review manually. Include how many direct comps were found, how many "
        "fallback comps were used, and the fallback strategy. Return structured JSON only."
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
    schema = {
        "type": "object",
        "properties": {
            "average_rent_monthly": {"type": "integer"},
            "vacancy_rate_percent": {"type": ["number", "null"]},
            "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
            "market_research_summary": {"type": "string"},
            "direct_comps_found": {"type": "integer"},
            "fallback_comps_found": {"type": "integer"},
            "fallback_strategy": {"type": "string"},
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
            "market_research_summary",
            "direct_comps_found",
            "fallback_comps_found",
            "fallback_strategy",
            "reasoning",
            "source_names",
            "source_urls",
        ],
        "additionalProperties": False,
    }
    return call_openai_researched_json(
        system_text=(
            "You assist with Canadian residential rental-market underwriting. Use web search to find current, "
            "segment-specific comparable rental evidence first. Treat supplied official rows as optional context, "
            "not as the primary source unless they directly match the requested segment. Do not present estimates "
            "as official data unless supplied or researched official data supports that. Return only structured JSON."
        ),
        prompt_text=prompt_text,
        payload=payload,
        schema_name="market_rental_gap_estimate",
        schema=schema,
    )


def build_market_appreciation_gap_prompt_text() -> str:
    return (
        "Estimate the target market's appreciation context for buy-and-hold real estate analysis.\n\n"
        "The supplied data may include official HPI data, proxy-market HPI data, census metrics, rent metrics, and "
        "other context. Treat this data as reference material, not necessarily as the final answer. Your task is to "
        "estimate the target market itself. Prioritize current web research on target-market sale prices, market "
        "reports, board statistics, assessed-value trends, and local inventory conditions before leaning on supplied "
        "proxy rows. Proxy HPI is fallback context, not the answer.\n\n"
        "For the target market, estimate best-effort numeric values for:\n"
        "- latest market-wide benchmark home price\n"
        "- 1-month change\n"
        "- 12-month change\n"
        "- 5-year annualized appreciation\n"
        "- 10-year annualized appreciation\n"
        "- trend label\n"
        "- confidence\n"
        "- concise reasoning\n"
        "- source names or URLs a user should review\n\n"
        "If direct official data is missing, infer from target-market evidence first, then nearby markets, regional "
        "trend data, population growth, household income, labour market strength, market size, liquidity, and any "
        "supplied proxy data. Do not simply copy proxy values unless you believe the proxy is truly representative; "
        "if you use proxy values, explain why and identify what target-market evidence supports the adjustment.\n\n"
        "Do not return null for the numeric fields. If evidence is thin, provide a low-confidence directional estimate "
        "and clearly explain the uncertainty in the reasoning. Return structured JSON only. Percentage values should "
        "be plain percentages, not ratios."
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
    schema = {
        "type": "object",
        "properties": {
            "latest_benchmark_price": {"type": "integer"},
            "change_1m_percent": {"type": "number"},
            "change_12m_percent": {"type": "number"},
            "appreciation_5y_cagr_percent": {"type": "number"},
            "appreciation_10y_cagr_percent": {"type": "number"},
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
    }
    return call_openai_researched_json(
        system_text=(
            "You assist with Canadian residential market analysis. Use web search to find current and reputable "
            "target-market appreciation context first. Treat supplied HPI/proxy/market metric data as optional "
            "context and fallback evidence, not as the primary answer when target-market evidence is available. "
            "Do not present estimates as official data unless supplied or researched source data supports that. "
            "Return only structured JSON."
        ),
        prompt_text=prompt_text,
        payload=payload,
        schema_name="market_appreciation_gap_estimate",
        schema=schema,
    )
