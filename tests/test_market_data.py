from __future__ import annotations

from investment import merge_investment_defaults
from market_data import (
    build_market_profile_from_saved_search,
    find_market_reference_match,
    get_market_seed_bootstrap_payload,
    hydrate_defaults_with_market_data,
    infer_province,
)


def test_find_market_reference_match_prefers_exact_market_and_matching_shape() -> None:
    saved_search = {
        "location": "Victoria",
        "property_type": "apartment",
        "beds_min": 2,
    }
    market_rows = [
        {
            "id": 1,
            "market_key": "victoria_bc",
            "market_name": "Victoria",
            "property_type": "apartment",
            "bedroom_count": 1,
            "average_rent_monthly": 1900,
            "vacancy_rate_percent": 2.8,
        },
        {
            "id": 2,
            "market_key": "victoria_bc",
            "market_name": "Victoria",
            "property_type": "apartment",
            "bedroom_count": 2,
            "average_rent_monthly": 2300,
            "vacancy_rate_percent": 3.1,
        },
    ]

    match = find_market_reference_match(saved_search, market_rows)

    assert match is not None
    assert match["match_type"] == "exact"
    assert match["confidence"] == "high"
    assert match["market_reference"]["id"] == 2
    assert match["property_type_mismatch"] is False


def test_find_market_reference_match_uses_proxy_for_duncan() -> None:
    saved_search = {
        "location": "Duncan",
        "property_type": "house",
        "beds_min": 2,
    }
    market_rows = [
        {
            "id": 11,
            "market_key": "victoria_bc",
            "market_name": "Victoria",
            "property_type": "apartment",
            "bedroom_count": 2,
            "average_rent_monthly": 2200,
            "vacancy_rate_percent": 3.0,
        }
    ]

    match = find_market_reference_match(saved_search, market_rows)

    assert match is not None
    assert match["match_type"] == "proxy"
    assert match["matched_market_name"] == "Victoria, BC"
    assert match["property_type_mismatch"] is True
    assert "apartment-based" in match["notes"]


def test_hydrate_defaults_with_market_data_sets_missing_rent_and_vacancy() -> None:
    defaults = merge_investment_defaults({"market_rent_monthly": {"value": None}})
    market_match = {
        "match_type": "exact",
        "matched_market_name": "Victoria",
        "market_reference": {
            "average_rent_monthly": 2350,
            "vacancy_rate_percent": 3.2,
            "source_url": "https://example.com/cmhc",
        },
    }

    hydrated = hydrate_defaults_with_market_data(defaults, market_match)

    assert hydrated["market_rent_monthly"]["value"] == 2350.0
    assert hydrated["market_rent_monthly"]["source"] == "cmhc_exact"
    assert hydrated["vacancy_percent"]["value"] == 3.2
    assert hydrated["vacancy_percent"]["source"] == "cmhc_exact"


def test_infer_province_recognizes_sidney_as_bc() -> None:
    assert infer_province({"location": "Sidney"}) == "BC"


def test_build_market_profile_from_saved_search_creates_bc_market_key() -> None:
    profile = build_market_profile_from_saved_search({"location": "Sidney"}, status="discovered")

    assert profile["market_key"] == "sidney_bc"
    assert profile["province"] == "BC"
    assert profile["status"] == "discovered"


def test_get_market_seed_bootstrap_payload_returns_seed_bundle_for_victoria() -> None:
    bundle = get_market_seed_bootstrap_payload({"location": "Victoria"})

    assert bundle is not None
    assert bundle["profile"]["market_key"] == "victoria_bc"
    assert len(bundle["metrics"]) == 4
    assert len(bundle["series"]) >= 2


def test_get_market_seed_bootstrap_payload_returns_none_for_unknown_market() -> None:
    bundle = get_market_seed_bootstrap_payload({"location": "Kelowna"})

    assert bundle is None


def test_get_market_seed_bootstrap_payload_returns_seed_bundle_for_vancouver() -> None:
    bundle = get_market_seed_bootstrap_payload({"location": "Vancouver"})

    assert bundle is not None
    assert bundle["profile"]["market_key"] == "vancouver_bc"
    assert len(bundle["metrics"]) == 4


def test_get_market_seed_bootstrap_payload_returns_seed_bundle_for_sidney() -> None:
    bundle = get_market_seed_bootstrap_payload({"location": "Sidney"})

    assert bundle is not None
    assert bundle["profile"]["market_key"] == "sidney_bc"
    assert len(bundle["metrics"]) == 4
    assert bundle["series"] == []
