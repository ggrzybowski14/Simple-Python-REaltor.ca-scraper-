from __future__ import annotations

import pytest

from investment import (
    build_defaults_snapshot_from_form,
    calculate_underwriting,
    estimate_rule_based_insurance_monthly,
    estimate_rule_based_utilities_monthly,
    estimate_smart_reserve_percentages,
    merge_investment_defaults,
)


def build_defaults(overrides: dict[str, dict[str, float]] | None = None) -> dict[str, dict[str, object]]:
    return merge_investment_defaults(overrides or {})


def test_build_defaults_snapshot_from_form_preserves_non_manual_blank_source_mode() -> None:
    defaults = build_defaults(
        {
            "market_rent_monthly": {
                "value": 2420,
                "source": "cmhc_exact",
                "confidence": "high",
            }
        }
    )

    snapshot = build_defaults_snapshot_from_form({"market_rent_monthly": ""}, existing_defaults=defaults)

    assert snapshot["market_rent_monthly"]["value"] == 2420
    assert snapshot["market_rent_monthly"]["source"] == "cmhc_exact"


def test_build_defaults_snapshot_from_form_allows_manual_blank_value() -> None:
    defaults = build_defaults({"market_rent_monthly": {"value": 2420, "source": "manual"}})

    snapshot = build_defaults_snapshot_from_form({"market_rent_monthly": ""}, existing_defaults=defaults)

    assert snapshot["market_rent_monthly"]["value"] is None
    assert snapshot["market_rent_monthly"]["source"] == "manual"


def test_calculate_underwriting_returns_expected_metrics() -> None:
    listing = {
        "price": "$500,000",
        "annual_taxes": "$3,600",
        "hoa_fees": "$0",
    }
    defaults = build_defaults(
        {
            "market_rent_monthly": {"value": 3000},
            "vacancy_percent": {"value": 4.0},
            "maintenance_percent_of_rent": {"value": 8.0},
            "capex_percent_of_rent": {"value": 5.0},
            "management_percent_of_rent": {"value": 0.0},
            "interest_rate_percent": {"value": 4.5},
            "down_payment_percent": {"value": 20.0},
            "closing_cost_percent": {"value": 2.0},
            "amortization_years": {"value": 30},
            "insurance_monthly": {"value": 100},
            "utilities_monthly": {"value": 0},
            "other_monthly": {"value": 0},
        }
    )

    result = calculate_underwriting(listing, defaults)
    metrics = result["metrics"]

    assert metrics["monthly_mortgage"] == pytest.approx(2026.74, abs=0.01)
    assert metrics["monthly_cash_flow"] == pytest.approx(63.26, abs=0.01)
    assert metrics["annual_noi"] == pytest.approx(26880.0, abs=0.01)
    assert metrics["cap_rate"] == pytest.approx(5.376, abs=0.001)
    assert metrics["cash_on_cash_return"] == pytest.approx(0.6901, abs=0.001)
    assert metrics["rent_to_price_ratio"] == pytest.approx(0.6, abs=0.001)
    assert result["warnings"] == []
    assert result["verdict"]["slug"] == "promising"


def test_calculate_underwriting_warns_when_rent_and_taxes_are_missing() -> None:
    listing = {
        "price": "$500,000",
        "annual_taxes": None,
        "hoa_fees": None,
    }
    defaults = build_defaults({"market_rent_monthly": {"value": None}})

    result = calculate_underwriting(listing, defaults)

    assert "Missing market rent default" in result["warnings"]
    assert "Missing scraped taxes" in result["warnings"]
    assert result["metrics"]["monthly_cash_flow"] is None
    assert result["metrics"]["cap_rate"] is None
    assert result["verdict"]["slug"] == "borderline"


def test_calculate_underwriting_uses_listing_level_rent_override() -> None:
    listing = {
        "price": "$500,000",
        "annual_taxes": "$3,600",
        "hoa_fees": "$0",
    }
    defaults = build_defaults({"market_rent_monthly": {"value": 2400}})

    result = calculate_underwriting(
        listing,
        defaults,
        listing_overrides={
            "market_rent_monthly": 3100,
            "market_rent_source": "ai_listing_suggestion",
        },
    )

    effective_rent = result["effective_assumptions"]["market_rent_monthly"]
    assert effective_rent["value"] == 3100
    assert effective_rent["source"] == "ai_listing_suggestion"
    assert result["metrics"]["gross_monthly_rent"] == 3100


def test_estimate_rule_based_utilities_monthly_uses_bc_property_heuristics() -> None:
    estimate = estimate_rule_based_utilities_monthly(
        {
            "location": "Victoria",
            "property_type": "house",
            "beds_min": 3,
        }
    )

    assert estimate["value"] == 205.0
    assert estimate["source"] == "rule_based_bc"
    assert estimate["confidence"] == "low"


def test_estimate_rule_based_insurance_monthly_uses_bc_property_heuristics() -> None:
    estimate = estimate_rule_based_insurance_monthly(
        {
            "location": "Victoria",
            "property_type": "condo",
            "beds_min": 2,
        }
    )

    assert estimate["value"] == 40.0
    assert estimate["source"] == "rule_based_bc"
    assert estimate["confidence"] == "low"


def test_estimate_smart_reserve_percentages_responds_to_age_and_updates() -> None:
    estimate = estimate_smart_reserve_percentages(
        {
            "property_type": "condo",
            "building_type": "Apartment",
            "built_in": "2018",
            "hoa_fees": "$420",
            "listing_description": "Recently updated condo with new windows and modernized kitchen.",
        }
    )

    assert estimate["maintenance_percent_of_rent"]["value"] == 3.0
    assert estimate["capex_percent_of_rent"]["value"] == 3.0
    assert estimate["maintenance_percent_of_rent"]["source"] == "smart_listing_estimate"
    assert estimate["capex_percent_of_rent"]["source"] == "smart_listing_estimate"
