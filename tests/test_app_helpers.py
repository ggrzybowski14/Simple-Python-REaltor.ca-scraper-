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
    assert criteria["ai_screens"][0]["goal"] == "secondary suite potential"
    assert criteria["ai_screens"][0]["enabled"] is True


def test_parse_market_bedroom_filter_accepts_larger_bedroom_options() -> None:
    assert webapp.parse_market_bedroom_filter("4") == 4
    assert webapp.parse_market_bedroom_filter("5+") == 5
    assert webapp.format_bedroom_option_label(5) == "5+"


def test_format_display_timestamp_uses_readable_local_time() -> None:
    assert (
        webapp.format_display_timestamp("2026-04-30T03:04:42+00:00")
        == "Apr 29, 2026 at 8:04 PM"
    )
    assert webapp.format_display_timestamp(None) == "Never"


def test_build_buy_box_criteria_uses_two_ai_screens_from_form() -> None:
    saved_search = {"search_snapshot": {}}

    criteria = webapp.build_buy_box_criteria(
        MultiDict(
            {
                "apply_buy_box": "1",
                "buy_box_ai_screen_1_enabled": "1",
                "buy_box_ai_screen_1_goal": "Find suite potential",
                "buy_box_ai_screen_2_enabled": "1",
                "buy_box_ai_screen_2_goal": "Find subdivision potential",
            }
        ),
        saved_search,
    )

    assert criteria["applied"] is True
    assert criteria["ai_enabled"] is True
    assert criteria["ai_screens"][0]["name"] == "AI Prompt 1"
    assert criteria["ai_screens"][0]["enabled"] is True
    assert criteria["ai_screens"][1]["name"] == "AI Prompt 2"
    assert criteria["ai_screens"][1]["enabled"] is True


def test_analyze_active_listings_splits_partial_ai_screen_matches(monkeypatch) -> None:
    criteria = {
        "applied": True,
        "max_price": None,
        "beds_min": None,
        "property_type": "",
        "required_keywords": [],
        "ai_screens": [
            {"key": "screen_1", "name": "AI Prompt 1", "goal": "suite", "enabled": True},
            {"key": "screen_2", "name": "AI Prompt 2", "goal": "subdivide", "enabled": True},
        ],
    }
    listings = [
        {
            "listing_id": 1,
            "price": "$750,000",
            "bedrooms": 3,
            "property_type": "single family",
            "building_type": "House",
            "listing_description": "Large home with suite and big lot.",
        }
    ]

    def fake_apply(goal, active_listings, **kwargs):
        if goal == "suite":
            return {1: {"verdict": "likely", "reason": "Mentions suite."}}, None
        return {1: {"verdict": "no", "reason": "No subdivision language."}}, None

    monkeypatch.setattr(webapp, "apply_ai_buy_box", fake_apply)

    analysis = webapp.analyze_active_listings(listings, criteria)

    assert analysis["matched"] == []
    assert len(analysis["maybe"]) == 1
    maybe_listing = analysis["maybe"][0]
    assert maybe_listing["ai_screen_likely_count"] == 1
    assert maybe_listing["ai_screen_total"] == 2
    assert [result["verdict"] for result in maybe_listing["ai_screen_results"]] == ["likely", "no"]


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


def test_buy_box_goal_needs_research_for_neighborhood_and_rules_questions() -> None:
    assert webapp.buy_box_goal_needs_research("Is this in a safe nice neighborhood?")
    assert webapp.buy_box_goal_needs_research("Does zoning allow subdivision?")
    assert not webapp.buy_box_goal_needs_research("Mentions a separate entrance suite")


def test_apply_ai_buy_box_uses_researched_batch_for_research_prompts(monkeypatch) -> None:
    webapp.AI_BUY_BOX_CACHE.clear()
    calls: dict[str, object] = {}
    listings = [
        {
            "listing_id": 1,
            "address": "123 Example St, Nanaimo, BC",
            "listing_description": "Large family home.",
        },
        {
            "listing_id": 2,
            "address": "456 Example Ave, Nanaimo, BC",
            "listing_description": "Updated home near amenities.",
        },
    ]
    saved_search = {"id": 36, "location": "Nanaimo", "property_type": "house", "beds_min": 4}

    def fake_researched(goal, active_listings, saved_search_arg=None):
        calls["goal"] = goal
        calls["listing_count"] = len(active_listings)
        calls["saved_search"] = saved_search_arg
        return {
            1: {"verdict": "maybe", "reason": "Market-level research is mixed."},
            2: {"verdict": "likely", "reason": "Area context is favorable."},
        }

    def fail_description_only(goal, active_listings):
        raise AssertionError("research prompts should use the researched buy-box path")

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(webapp, "call_openai_researched_buy_box_assessment", fake_researched)
    monkeypatch.setattr(webapp, "call_openai_buy_box_assessment", fail_description_only)

    results, error = webapp.apply_ai_buy_box(
        "Is this in a safe nice neighborhood?",
        listings,
        saved_search=saved_search,
    )

    assert error is None
    assert calls["listing_count"] == 2
    assert calls["saved_search"] == saved_search
    assert results[1]["verdict"] == "maybe"
    assert results[2]["verdict"] == "likely"


def test_apply_ai_buy_box_keeps_description_path_for_listing_description_prompts(monkeypatch) -> None:
    webapp.AI_BUY_BOX_CACHE.clear()
    calls: dict[str, object] = {}
    listings = [
        {
            "listing_id": 1,
            "address": "123 Example St",
            "listing_description": "Includes a suite with separate entrance.",
        }
    ]

    def fail_researched(goal, active_listings, saved_search_arg=None):
        raise AssertionError("description-only prompts should not use web research")

    def fake_description_only(goal, active_listings):
        calls["goal"] = goal
        calls["listing_count"] = len(active_listings)
        return {1: {"verdict": "likely", "reason": "Mentions suite."}}

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(webapp, "call_openai_researched_buy_box_assessment", fail_researched)
    monkeypatch.setattr(webapp, "call_openai_buy_box_assessment", fake_description_only)

    results, error = webapp.apply_ai_buy_box("Mentions a separate entrance suite", listings)

    assert error is None
    assert calls["listing_count"] == 1
    assert results[1]["reason"] == "Mentions suite."


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


def test_listing_analysis_state_stores_buy_box_results_with_string_keys() -> None:
    state = webapp.build_listing_analysis_state(
        7,
        buy_box={"applied": True},
        defaults_snapshot={},
        overrides_by_listing_id={101: {"favorite": True}},
        buy_box_results_by_listing_id={
            101: {
                "bucket": "matched",
                "label": "Matched",
                "ai_screen_results": [{"verdict": "likely", "reason": "Fits."}],
            }
        },
    )

    assert state["overrides_by_listing_id"]["101"]["favorite"] is True
    assert state["buy_box_results_by_listing_id"]["101"]["bucket"] == "matched"
    assert webapp.normalize_analysis_state_buy_box_results(state)[101]["label"] == "Matched"


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
                "block_detail_assets": "1",
            }
        )
    )

    assert "--beds-min" not in args
    assert "--block-detail-assets" in args


def test_build_scrape_args_uses_bulk_safe_speed_defaults_when_form_values_are_blank() -> None:
    args = webapp.build_scrape_args(
        MultiDict(
            {
                "location": "Victoria",
                "max_pages": "",
                "max_listings": "",
                "detail_limit": "",
                "detail_concurrency": "",
                "detail_pause_min": "",
                "detail_pause_max": "",
                "block_detail_assets": "1",
            }
        )
    )

    assert args[args.index("--detail-concurrency") + 1] == "6"
    assert args[args.index("--detail-pause-min") + 1] == "0.2"
    assert args[args.index("--detail-pause-max") + 1] == "0.5"
    assert "--block-detail-assets" in args


def test_build_scrape_args_accepts_human_price_input() -> None:
    args = webapp.build_scrape_args(
        MultiDict(
            {
                "location": "Nanaimo",
                "max_price": "2.5m",
            }
        )
    )

    assert args[args.index("--max-price") + 1] == "2500000"


def test_build_scrape_args_treats_decimal_price_shorthand_as_millions() -> None:
    args = webapp.build_scrape_args(
        MultiDict(
            {
                "location": "Nanaimo",
                "max_price": "2.5",
            }
        )
    )

    assert args[args.index("--max-price") + 1] == "2500000"


def test_build_scrape_args_from_saved_search_accepts_editable_limits() -> None:
    args = webapp.build_scrape_args_from_saved_search(
        {
            "location": "Victoria",
            "beds_min": 2,
            "property_type": "house",
            "max_price": 1000000,
        },
        MultiDict(
            {
                "max_pages": "2",
                "max_listings": "10",
                "detail_limit": "10",
                "detail_concurrency": "12",
                "detail_pause_min": "0.2",
                "detail_pause_max": "0.5",
                "block_detail_assets": "1",
            }
        ),
    )

    assert args[args.index("--max-pages") + 1] == "2"
    assert args[args.index("--max-listings") + 1] == "10"
    assert args[args.index("--detail-limit") + 1] == "10"
    assert args[args.index("--detail-concurrency") + 1] == "12"
    assert "--block-detail-assets" in args


def test_build_scrape_args_from_saved_search_omits_zero_beds_filter() -> None:
    args = webapp.build_scrape_args_from_saved_search(
        {
            "location": "Sidney",
            "beds_min": 0,
            "max_price": 750000,
        }
    )

    assert "--beds-min" not in args
