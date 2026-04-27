from __future__ import annotations

import app as webapp
from ai_underwriting import build_market_appreciation_gap_prompt_text
from werkzeug.datastructures import MultiDict


def test_market_appreciation_gap_prompt_requires_best_effort_numeric_estimate() -> None:
    prompt = build_market_appreciation_gap_prompt_text()

    assert "Do not return null for the numeric fields" in prompt
    assert "low-confidence directional estimate" in prompt


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


def test_build_combined_analysis_verdict_uses_buy_box_and_underwriting() -> None:
    assert webapp.build_combined_analysis_verdict(
        {"label": "Likely"},
        {"label": "Promising", "slug": "promising"},
    )["label"] == "Strong"
    assert webapp.build_combined_analysis_verdict(
        {"label": "Maybe"},
        {"label": "Promising", "slug": "promising"},
    )["label"] == "Review"
    assert webapp.build_combined_analysis_verdict(
        {"label": "Likely"},
        {"label": "Weak", "slug": "weak"},
    )["label"] == "Reject"
    assert webapp.build_combined_analysis_verdict(
        {"label": "Unlikely"},
        {"label": "Promising", "slug": "promising"},
    )["label"] == "Review"


def test_persist_latest_listing_analysis_stores_state_in_saved_search_snapshot(monkeypatch) -> None:
    patched_payloads = []
    saved_search = {"id": 7, "search_snapshot": {"buy_box": {"applied": True}}}
    state = {
        "buy_box": {"applied": True},
        "defaults_snapshot": {"market_rent_monthly": {"value": 3000}},
        "overrides_by_listing_id": {"101": {"market_rent_monthly": 3200}},
        "ran_at": "2026-04-26T16:00:00Z",
    }

    def fake_patch(config, path, *, query, payload):
        patched_payloads.append({"path": path, "query": query, "payload": payload})

    monkeypatch.setattr(webapp, "supabase_patch", fake_patch)

    webapp.persist_latest_listing_analysis(
        webapp.SupabaseReadConfig(url="https://example.supabase.co", key="test-key"),
        saved_search,
        state,
    )

    assert saved_search["search_snapshot"]["buy_box"]["applied"] is True
    assert saved_search["search_snapshot"]["latest_listing_analysis"] == state
    assert patched_payloads[0]["path"] == "saved_searches"
    assert patched_payloads[0]["payload"]["search_snapshot"]["latest_listing_analysis"] == state


def test_get_saved_listing_analysis_state_reads_snapshot() -> None:
    state = {
        "buy_box": {"applied": True},
        "defaults_snapshot": {},
        "overrides_by_listing_id": {},
        "ran_at": "2026-04-26T16:00:00Z",
    }

    assert webapp.get_saved_listing_analysis_state(
        {"search_snapshot": {"latest_listing_analysis": state}}
    ) == state


def test_build_scrape_args_omits_zero_beds_filter() -> None:
    args = webapp.build_scrape_args(
        MultiDict(
            {
                "location": "Sidney",
                "beds_min": "0",
                "max_pages": "3",
                "max_listings": "25",
                "detail_limit": "25",
                "detail_concurrency": "2",
            }
        )
    )

    assert "--beds-min" not in args


def test_build_scrape_args_from_saved_search_omits_zero_beds_filter() -> None:
    args = webapp.build_scrape_args_from_saved_search(
        {
            "location": "Sidney",
            "beds_min": 0,
            "max_price": 750000,
        }
    )

    assert "--beds-min" not in args
