from __future__ import annotations

import re
from copy import deepcopy
from typing import Any


PROXY_MARKET_BY_LOCATION = {
    "duncan": {
        "proxy_market_key": "victoria_bc",
        "proxy_market_name": "Victoria, BC",
        "confidence": "low",
        "notes": "Duncan currently falls back to Victoria as an explicit proxy market for CMHC-style defaults.",
    }
}


def normalize_market_key(location: str | None, province: str | None = None) -> str:
    location_part = re.sub(r"[^a-z0-9]+", "_", (location or "").strip().lower()).strip("_")
    province_part = re.sub(r"[^a-z0-9]+", "_", (province or "").strip().lower()).strip("_")
    if location_part and province_part:
        return f"{location_part}_{province_part}"
    return location_part or province_part or "unknown_market"


def infer_province(saved_search: dict[str, Any]) -> str | None:
    location = (saved_search.get("location") or "").lower()
    if any(token in location for token in ["bc", "british columbia", "victoria", "duncan", "nanaimo"]):
        return "BC"
    return None


def find_market_reference_match(
    saved_search: dict[str, Any],
    market_rows: list[dict[str, Any]],
) -> dict[str, Any] | None:
    if not market_rows:
        return None

    province = infer_province(saved_search)
    location = saved_search.get("location") or ""
    target_market_key = normalize_market_key(location, province)
    property_type = (saved_search.get("property_type") or "").strip().lower() or None
    beds_min = saved_search.get("beds_min")

    def row_score(row: dict[str, Any]) -> tuple[int, int]:
        score = 0
        if row.get("market_key") == target_market_key:
            score += 100
        if property_type and (row.get("property_type") or "").strip().lower() == property_type:
            score += 10
        if isinstance(beds_min, int) and row.get("bedroom_count") == beds_min:
            score += 5
        return (score, int(row.get("id") or 0))

    exact_candidates = [row for row in market_rows if row.get("market_key") == target_market_key]
    if exact_candidates:
        best = sorted(exact_candidates, key=row_score, reverse=True)[0]
        property_type_mismatch = bool(
            property_type
            and best.get("property_type")
            and (best.get("property_type") or "").strip().lower() != property_type
        )
        return {
            "match_type": "exact",
            "confidence": "medium" if property_type_mismatch else "high",
            "market_reference": best,
            "matched_market_name": best.get("market_name"),
            "notes": (
                "Exact market match found, but the CMHC baseline is apartment-based and may run low for detached-house underwriting."
                if property_type_mismatch
                else "Exact market reference match found."
            ),
            "property_type_mismatch": property_type_mismatch,
        }

    proxy = PROXY_MARKET_BY_LOCATION.get(location.strip().lower())
    if proxy:
        proxy_candidates = [row for row in market_rows if row.get("market_key") == proxy["proxy_market_key"]]
        if proxy_candidates:
            best = sorted(proxy_candidates, key=row_score, reverse=True)[0]
            property_type_mismatch = bool(
                property_type
                and best.get("property_type")
                and (best.get("property_type") or "").strip().lower() != property_type
            )
            return {
                "match_type": "proxy",
                "confidence": proxy["confidence"],
                "market_reference": best,
                "matched_market_name": proxy["proxy_market_name"],
                "notes": (
                    f"{proxy['notes']} The CMHC baseline is apartment-based and may run low for detached-house underwriting."
                    if property_type_mismatch
                    else proxy["notes"]
                ),
                "property_type_mismatch": property_type_mismatch,
            }

    return None


def hydrate_defaults_with_market_data(
    defaults_snapshot: dict[str, dict[str, Any]],
    market_match: dict[str, Any] | None,
) -> dict[str, dict[str, Any]]:
    hydrated = deepcopy(defaults_snapshot)
    if not market_match:
        return hydrated
    reference = market_match.get("market_reference") or {}
    match_type = market_match.get("match_type")
    source_label = "cmhc_exact" if match_type == "exact" else "cmhc_proxy"
    confidence = "high" if match_type == "exact" else "medium"

    average_rent = reference.get("average_rent_monthly")
    vacancy_rate = reference.get("vacancy_rate_percent")
    if hydrated["market_rent_monthly"].get("value") is None and average_rent is not None:
        hydrated["market_rent_monthly"]["value"] = float(average_rent)
        hydrated["market_rent_monthly"]["source"] = source_label
        hydrated["market_rent_monthly"]["confidence"] = confidence
        hydrated["market_rent_monthly"]["help_text"] = (
            f"Hydrated from CMHC market reference for {market_match.get('matched_market_name')}."
        )
        hydrated["market_rent_monthly"]["help_url"] = reference.get("source_url")
    if hydrated["vacancy_percent"].get("value") in {None, 4.0} and vacancy_rate is not None:
        hydrated["vacancy_percent"]["value"] = float(vacancy_rate)
        hydrated["vacancy_percent"]["source"] = source_label
        hydrated["vacancy_percent"]["confidence"] = confidence
        hydrated["vacancy_percent"]["help_text"] = (
            f"Hydrated from CMHC market reference for {market_match.get('matched_market_name')}."
        )
        hydrated["vacancy_percent"]["help_url"] = reference.get("source_url")
    return hydrated
