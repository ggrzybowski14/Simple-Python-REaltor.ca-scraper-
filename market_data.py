from __future__ import annotations

import re
from copy import deepcopy
from typing import Any

from market_seed_data import get_market_seed_bundle


PROXY_MARKET_BY_LOCATION = {
    "duncan": {
        "proxy_market_key": "victoria_bc",
        "proxy_market_name": "Victoria, BC",
        "confidence": "low",
        "notes": "Duncan currently falls back to Victoria as an explicit proxy market for CMHC-style defaults.",
    }
}

KNOWN_BC_LOCATIONS = {
    "burnaby",
    "campbell river",
    "central saanich",
    "chilliwack",
    "colwood",
    "comox",
    "courtenay",
    "duncan",
    "esquimalt",
    "langford",
    "maple ridge",
    "nanaimo",
    "north saanich",
    "parksville",
    "penticton",
    "port alberni",
    "richmond",
    "saanich",
    "sidney",
    "surrey",
    "victoria",
    "vancouver",
    "vernon",
    "west kelowna",
}

VANCOUVER_ISLAND_PROXY_MARKETS = {
    "duncan_bc",
    "nanaimo_bc",
    "sidney_bc",
}

RENTAL_PROPERTY_TYPE_LABELS = {
    "apartment": "Apartment",
    "condo_apartment": "Condo apartment",
    "single_family": "Detached house",
    "semi_detached": "Semi-detached / duplex",
    "townhouse": "Townhouse",
}

PROPERTY_TYPE_MATCH_RULES = {
    "apartment": {
        "preferred": ["apartment", "condo_apartment"],
        "acceptable": {"apartment", "condo_apartment"},
    },
    "condo": {
        "preferred": ["condo_apartment", "apartment"],
        "acceptable": {"condo_apartment", "apartment"},
    },
    "house": {
        "preferred": ["single_family", "semi_detached", "townhouse", "apartment"],
        "acceptable": {"single_family", "semi_detached", "townhouse"},
    },
}


def normalize_market_key(location: str | None, province: str | None = None) -> str:
    location_part = re.sub(r"[^a-z0-9]+", "_", (location or "").strip().lower()).strip("_")
    province_part = re.sub(r"[^a-z0-9]+", "_", (province or "").strip().lower()).strip("_")
    if location_part and province_part:
        return f"{location_part}_{province_part}"
    return location_part or province_part or "unknown_market"


def infer_province(saved_search: dict[str, Any]) -> str | None:
    province = (saved_search.get("province") or "").strip().upper()
    if province:
        return province

    snapshot = saved_search.get("search_snapshot")
    if isinstance(snapshot, dict):
        snapshot_province = (snapshot.get("province") or "").strip().upper()
        if snapshot_province:
            return snapshot_province

    location = (saved_search.get("location") or "").strip().lower()
    if not location and isinstance(snapshot, dict):
        location = (snapshot.get("location") or "").strip().lower()

    if any(token in location for token in ["bc", "british columbia"]):
        return "BC"

    normalized_location = re.sub(r"[^a-z0-9, ]+", " ", location)
    parts = [part.strip() for part in normalized_location.split(",") if part.strip()]
    candidate_tokens = set(parts)
    candidate_tokens.update(token for token in re.split(r"\s+", normalized_location) if token)
    if candidate_tokens & KNOWN_BC_LOCATIONS:
        return "BC"
    return None


def get_appreciation_proxy_market(market_key: str) -> dict[str, str] | None:
    if market_key not in VANCOUVER_ISLAND_PROXY_MARKETS:
        return None
    return {
        "proxy_key": "vancouver_island_bc",
        "proxy_name": "Vancouver Island",
        "label": "Vancouver Island proxy",
        "confidence": "low",
        "notes": "This market does not have direct CREA HPI coverage, so the Vancouver Island CREA series is being used as an explicit proxy after user acceptance.",
    }


def get_rental_property_type_label(property_type: str | None) -> str:
    normalized = (property_type or "").strip().lower()
    return RENTAL_PROPERTY_TYPE_LABELS.get(normalized, normalized.replace("_", " ").title() or "Unknown")


def get_property_type_match_rule(property_type: str | None) -> dict[str, Any]:
    normalized = (property_type or "").strip().lower()
    return PROPERTY_TYPE_MATCH_RULES.get(normalized, {"preferred": [normalized] if normalized else [], "acceptable": {normalized} if normalized else set()})


def build_market_profile_from_saved_search(
    saved_search: dict[str, Any],
    *,
    status: str = "placeholder",
    notes: str | None = None,
) -> dict[str, Any]:
    location = (saved_search.get("location") or "Unknown market").strip()
    province = infer_province(saved_search)
    return {
        "market_key": normalize_market_key(location, province),
        "market_name": location,
        "province": province,
        "geography_type": "market",
        "status": status,
        "notes": notes,
    }


def get_market_seed_bootstrap_payload(saved_search: dict[str, Any]) -> dict[str, Any] | None:
    profile = build_market_profile_from_saved_search(saved_search)
    return get_market_seed_bundle(profile["market_key"])


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
    property_type_rule = get_property_type_match_rule(property_type)
    property_type_preference = property_type_rule["preferred"]
    acceptable_property_types = property_type_rule["acceptable"]

    def row_score(row: dict[str, Any]) -> tuple[int, int]:
        score = 0
        row_property_type = (row.get("property_type") or "").strip().lower()
        if row.get("market_key") == target_market_key:
            score += 100
        if property_type and row_property_type:
            if row_property_type in property_type_preference:
                score += 20 - (property_type_preference.index(row_property_type) * 4)
            elif row_property_type in acceptable_property_types:
                score += 6
            else:
                score -= 2
        if isinstance(beds_min, int) and row.get("bedroom_count") == beds_min:
            score += 5
        return (score, int(row.get("id") or 0))

    exact_candidates = [row for row in market_rows if row.get("market_key") == target_market_key]
    if exact_candidates:
        best = sorted(exact_candidates, key=row_score, reverse=True)[0]
        best_property_type = (best.get("property_type") or "").strip().lower()
        property_type_mismatch = bool(
            property_type
            and best_property_type
            and best_property_type not in acceptable_property_types
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
            best_property_type = (best.get("property_type") or "").strip().lower()
            property_type_mismatch = bool(
                property_type
                and best_property_type
                and best_property_type not in acceptable_property_types
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
    rent_source = hydrated["market_rent_monthly"].get("source")
    rent_value = hydrated["market_rent_monthly"].get("value")
    rent_help_text = hydrated["market_rent_monthly"].get("help_text")
    should_hydrate_rent = (
        rent_value is None
        and rent_source == "manual"
        and rent_help_text == "Single rent estimate for this saved search in V1."
    )
    if should_hydrate_rent and average_rent is not None:
        hydrated["market_rent_monthly"]["value"] = float(average_rent)
        hydrated["market_rent_monthly"]["source"] = source_label
        hydrated["market_rent_monthly"]["confidence"] = confidence
        hydrated["market_rent_monthly"]["help_text"] = (
            f"Hydrated from CMHC market reference for {market_match.get('matched_market_name')}."
        )
        hydrated["market_rent_monthly"]["help_url"] = reference.get("source_url")
    vacancy_source = hydrated["vacancy_percent"].get("source")
    vacancy_value = hydrated["vacancy_percent"].get("value")
    vacancy_help_text = hydrated["vacancy_percent"].get("help_text")
    should_hydrate_vacancy = (
        vacancy_value is None
        or (
            vacancy_value == 4.0
            and vacancy_source == "manual"
            and vacancy_help_text == "Editable saved-search vacancy assumption for this market."
        )
    )
    if should_hydrate_vacancy and vacancy_rate is not None:
        hydrated["vacancy_percent"]["value"] = float(vacancy_rate)
        hydrated["vacancy_percent"]["source"] = source_label
        hydrated["vacancy_percent"]["confidence"] = confidence
        hydrated["vacancy_percent"]["help_text"] = (
            f"Hydrated from CMHC market reference for {market_match.get('matched_market_name')}."
        )
        hydrated["vacancy_percent"]["help_url"] = reference.get("source_url")
    return hydrated
