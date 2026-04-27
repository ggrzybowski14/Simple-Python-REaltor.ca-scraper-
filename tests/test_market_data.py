from __future__ import annotations

from investment import merge_investment_defaults
from market_data import (
    build_market_profile_from_saved_search,
    find_market_reference_match,
    get_appreciation_proxy_market,
    get_market_seed_bootstrap_payload,
    get_rental_property_type_label,
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
    assert "closest available row" in match["notes"]


def test_find_market_reference_match_treats_townhouse_as_valid_house_like_baseline() -> None:
    saved_search = {
        "location": "Victoria",
        "property_type": "house",
        "beds_min": 2,
    }
    market_rows = [
        {
            "id": 21,
            "market_key": "victoria_bc",
            "market_name": "Victoria",
            "property_type": "apartment",
            "bedroom_count": 2,
            "average_rent_monthly": 2300,
        },
        {
            "id": 22,
            "market_key": "victoria_bc",
            "market_name": "Victoria",
            "property_type": "townhouse",
            "bedroom_count": 2,
            "average_rent_monthly": 2600,
        },
    ]

    match = find_market_reference_match(saved_search, market_rows)

    assert match is not None
    assert match["market_reference"]["id"] == 22
    assert match["property_type_mismatch"] is False
    assert match["reference_label"] == "2-Bedroom Townhouse closest match"
    assert "closest available property-type match" in match["notes"]


def test_find_market_reference_match_accepts_condo_apartment_for_condo_search() -> None:
    saved_search = {
        "location": "Victoria",
        "property_type": "condo",
        "beds_min": 2,
    }
    market_rows = [
        {
            "id": 31,
            "market_key": "victoria_bc",
            "market_name": "Victoria",
            "property_type": "condo_apartment",
            "bedroom_count": 2,
            "average_rent_monthly": 2550,
        }
    ]

    match = find_market_reference_match(saved_search, market_rows)

    assert match is not None
    assert match["market_reference"]["id"] == 31
    assert match["property_type_mismatch"] is False


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


def test_hydrate_defaults_with_market_data_preserves_manual_vacancy_even_when_value_matches_default() -> None:
    defaults = merge_investment_defaults(
        {
            "vacancy_percent": {
                "value": 4.0,
                "source": "manual",
                "help_text": "Manual saved-search vacancy value.",
            }
        }
    )
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

    assert hydrated["vacancy_percent"]["value"] == 4.0
    assert hydrated["vacancy_percent"]["source"] == "manual"


def test_hydrate_defaults_with_market_data_preserves_manual_rent_even_when_blank() -> None:
    defaults = merge_investment_defaults(
        {
            "market_rent_monthly": {
                "value": None,
                "source": "manual",
                "help_text": "Manual saved-search rent value.",
            }
        }
    )
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

    assert hydrated["market_rent_monthly"]["value"] is None
    assert hydrated["market_rent_monthly"]["source"] == "manual"


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


def test_get_appreciation_proxy_market_returns_curated_vancouver_island_proxy() -> None:
    proxy = get_appreciation_proxy_market("duncan_bc")

    assert proxy is not None
    assert proxy["proxy_key"] == "vancouver_island_bc"
    assert proxy["confidence"] == "low"


def test_get_appreciation_proxy_market_supports_legacy_tofino_key() -> None:
    proxy = get_appreciation_proxy_market("tofino")

    assert proxy is not None
    assert proxy["proxy_key"] == "vancouver_island_bc"


def test_get_appreciation_proxy_market_returns_none_for_unlisted_market() -> None:
    assert get_appreciation_proxy_market("courtenay_bc") is None


def test_get_rental_property_type_label_returns_friendly_labels() -> None:
    assert get_rental_property_type_label("semi_detached") == "Semi-detached / duplex"
