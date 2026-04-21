from __future__ import annotations

import app as webapp


def test_build_buy_box_criteria_uses_saved_settings_when_query_not_applied() -> None:
    saved_search = {
        "max_price": 900000,
        "beds_min": 2,
        "property_type": "house",
        "search_snapshot": {
            "buy_box": {
                "applied": True,
                "max_price": 800000,
                "beds_min": 3,
                "property_type": "condo",
                "required_keywords_raw": "suite, income",
                "ai_goal_raw": "secondary suite potential",
            }
        },
    }

    criteria = webapp.build_buy_box_criteria({}, saved_search)

    assert criteria["applied"] is True
    assert criteria["max_price"] == 800000
    assert criteria["beds_min"] == 3
    assert criteria["property_type"] == "condo"
    assert criteria["required_keywords"] == ["suite", "income"]
    assert criteria["ai_enabled"] is True


def test_analyze_listing_against_buy_box_rejects_non_house_building_types() -> None:
    criteria = {
        "max_price": 900000,
        "beds_min": 3,
        "property_type": "house",
        "required_keywords": [],
    }
    listing = {
        "price": "$799,000",
        "bedrooms": 3,
        "property_type": "single family",
        "building_type": "Row / Townhouse",
        "listing_description": "Well-kept home with updated kitchen.",
    }

    analysis = webapp.analyze_listing_against_buy_box(listing, criteria)

    assert analysis["matched"] is False
    assert "Building type is Row / Townhouse" in analysis["reasons"]


def test_build_buy_box_result_lookup_returns_bucket_labels() -> None:
    saved_search = {
        "search_snapshot": {
            "buy_box": {
                "applied": True,
                "max_price": 800000,
                "beds_min": 3,
                "property_type": "house",
                "required_keywords_raw": "",
                "ai_goal_raw": "",
            }
        }
    }
    criteria = webapp.build_buy_box_criteria({}, saved_search)
    listings = [
        {
            "listing_id": 1,
            "price": "$750,000",
            "bedrooms": 3,
            "property_type": "single family",
            "building_type": "House",
            "listing_description": "Detached house.",
        },
        {
            "listing_id": 2,
            "price": "$925,000",
            "bedrooms": 3,
            "property_type": "single family",
            "building_type": "House",
            "listing_description": "Detached house.",
        },
    ]

    lookup = webapp.build_buy_box_result_lookup(listings, criteria)

    assert lookup[1]["bucket"] == "matched"
    assert lookup[1]["label"] == "Matched"
    assert lookup[2]["bucket"] == "unmatched"
    assert lookup[2]["label"] == "Unmatched"

