from __future__ import annotations

import app as webapp


def test_market_context_route_renders_seeded_metrics(monkeypatch) -> None:
    monkeypatch.setattr(
        webapp,
        "get_supabase_read_config",
        lambda: webapp.SupabaseReadConfig(url="https://example.supabase.co", key="test-key"),
    )
    monkeypatch.setattr(
        webapp,
        "fetch_saved_search",
        lambda config, saved_search_id: {
            "id": saved_search_id,
            "name": "Victoria Houses",
            "location": "Victoria",
            "property_type": "house",
            "beds_min": 2,
            "search_snapshot": {},
        },
    )
    monkeypatch.setattr(
        webapp,
        "fetch_saved_searches",
        lambda config: [
            {
                "id": 7,
                "name": "Victoria Houses",
                "location": "Victoria",
                "property_type": "house",
                "beds_min": 2,
            }
        ],
    )
    monkeypatch.setattr(
        webapp,
        "fetch_market_profile",
        lambda config, market_key: {
            "market_key": market_key,
            "market_name": "Victoria",
            "province": "BC",
            "status": "active",
        },
    )
    monkeypatch.setattr(
        webapp,
        "fetch_market_metrics",
        lambda config, market_key: [
            {
                "metric_key": "population",
                "value_numeric": 397237,
                "source_name": "Statistics Canada 2021 Census",
                "confidence": "high",
                "notes": "Victoria CMA population in the 2021 Census.",
            },
            {
                "metric_key": "population_growth_percent",
                "value_numeric": 8.0,
                "source_name": "Statistics Canada 2021 Census",
                "confidence": "high",
                "notes": "Population change from 2016 to 2021 for Victoria CMA.",
            },
            {
                "metric_key": "unemployment_rate_percent",
                "value_numeric": 6.9,
                "source_name": "Statistics Canada 2021 Census",
                "confidence": "medium",
                "notes": "Census unemployment rate.",
            },
            {
                "metric_key": "median_household_income",
                "value_numeric": 75500,
                "source_name": "Statistics Canada 2021 Census",
                "confidence": "high",
                "notes": "Median after-tax household income in 2020.",
            },
        ],
    )
    monkeypatch.setattr(
        webapp,
        "build_market_housing_summary",
        lambda config, market_profile: {
            "rent_display": "$2,327",
            "vacancy_display": "3.1%",
            "match_label": "CMHC Exact",
            "matched_market_name": "Victoria",
            "notes": "Exact market reference match found.",
            "source_url": "https://example.com/cmhc",
            "source_date": "2025-12-11",
            "confidence": "high",
        },
    )
    monkeypatch.setattr(
        webapp,
        "fetch_market_metric_series",
        lambda config, market_key, series_key: [
            {"point_date": "2017-01-01", "value_numeric": 95.1, "source_name": "Statistics Canada RPPI", "source_url": "https://example.com/rppi", "confidence": "high", "notes": "RPPI series."},
            {"point_date": "2020-10-01", "value_numeric": 118.3, "source_name": "Statistics Canada RPPI", "source_url": "https://example.com/rppi", "confidence": "high", "notes": "RPPI series."},
        ],
    )

    client = webapp.app.test_client()
    response = client.get("/saved-searches/7/market-context")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Victoria Market Context" in body
    assert "$75,500" in body
    assert "397,237" in body
    assert "CMHC Exact" in body
    assert "Appreciation history" in body


def test_market_context_by_key_route_renders_without_saved_search_id_in_url(monkeypatch) -> None:
    monkeypatch.setattr(
        webapp,
        "get_supabase_read_config",
        lambda: webapp.SupabaseReadConfig(url="https://example.supabase.co", key="test-key"),
    )
    monkeypatch.setattr(
        webapp,
        "fetch_saved_searches",
        lambda config: [
            {
                "id": 7,
                "name": "Duncan Houses",
                "location": "Duncan",
                "property_type": "house",
                "beds_min": 3,
                "search_snapshot": {},
            }
        ],
    )
    monkeypatch.setattr(
        webapp,
        "fetch_market_profile",
        lambda config, market_key: {
            "market_key": market_key,
            "market_name": "Duncan",
            "province": "BC",
            "status": "active",
        },
    )
    monkeypatch.setattr(webapp, "fetch_market_metrics", lambda config, market_key: [])
    monkeypatch.setattr(
        webapp,
        "build_market_housing_summary",
        lambda config, market_profile: {
            "rent_display": "$1,629",
            "vacancy_display": "3.0%",
            "match_label": "CMHC Exact",
            "matched_market_name": "Duncan",
            "notes": "Exact market reference match found.",
            "source_url": "https://example.com/cmhc",
            "source_date": "2025-12-11",
            "confidence": "high",
        },
    )
    monkeypatch.setattr(
        webapp,
        "build_preferred_appreciation_context",
        lambda config, market_key, property_type_slug="composite", allow_proxy=False: {
            "title": "Benchmark price history",
            "metric_cards": [],
            "available": False,
            "empty_message": "No official appreciation series is available for this market yet.",
            "notes": "CREA HPI is the primary appreciation source for supported markets.",
            "proxy_available": True,
            "proxy_active": False,
            "proxy_label": "Vancouver Island proxy",
            "proxy_market_name": "Vancouver Island",
            "source_name": None,
            "ai_estimate_available": True,
        },
    )

    client = webapp.app.test_client()
    response = client.get("/markets/duncan_bc")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Duncan Market Context" in body
    assert "$1,629" in body
    assert "Use Vancouver Island proxy" in body


def test_market_context_by_key_route_offers_proxy_action_when_available(monkeypatch) -> None:
    monkeypatch.setattr(
        webapp,
        "get_supabase_read_config",
        lambda: webapp.SupabaseReadConfig(url="https://example.supabase.co", key="test-key"),
    )
    monkeypatch.setattr(webapp, "fetch_saved_searches", lambda config: [])
    monkeypatch.setattr(
        webapp,
        "fetch_market_profile",
        lambda config, market_key: {
            "market_key": market_key,
            "market_name": "Duncan",
            "province": "BC",
            "status": "active",
        },
    )
    monkeypatch.setattr(webapp, "fetch_market_metrics", lambda config, market_key: [])
    monkeypatch.setattr(
        webapp,
        "build_market_housing_summary",
        lambda config, market_profile: {
            "rent_display": "$1,629",
            "vacancy_display": "3.0%",
            "match_label": "CMHC Exact",
            "matched_market_name": "Duncan",
            "notes": None,
            "source_url": None,
            "source_date": None,
            "confidence": "high",
        },
    )
    monkeypatch.setattr(
        webapp,
        "build_preferred_appreciation_context",
        lambda config, market_key, property_type_slug="composite", allow_proxy=False: {
            "title": "Benchmark price history",
            "metric_cards": [],
            "available": False,
            "empty_message": "No official appreciation series is available for this market yet.",
            "notes": None,
            "proxy_available": True,
            "proxy_active": False,
            "proxy_label": "Vancouver Island proxy",
            "proxy_market_name": "Vancouver Island",
            "source_name": None,
            "ai_estimate_available": True,
        },
    )

    client = webapp.app.test_client()
    response = client.get("/markets/duncan_bc")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Use Vancouver Island proxy" in body


def test_market_appreciation_api_returns_proxy_metadata(monkeypatch) -> None:
    monkeypatch.setattr(
        webapp,
        "get_supabase_read_config",
        lambda: webapp.SupabaseReadConfig(url="https://example.supabase.co", key="test-key"),
    )
    monkeypatch.setattr(
        webapp,
        "build_preferred_appreciation_context",
        lambda config, market_key, property_type_slug="composite", allow_proxy=False: {
            "source_key": "crea_hpi_proxy",
            "source_name": "CREA MLS HPI",
            "property_type_label": "Composite",
            "available": True,
            "latest_benchmark_price": 700000,
            "latest_benchmark_price_display": "$700,000",
            "latest_date": "2026-03-01",
            "trend_direction": "mixed_market",
            "trend_label": "Mixed Market",
            "data_quality_flag": "low",
            "empty_message": None,
            "notes": None,
            "proxy_available": True,
            "proxy_active": True,
            "proxy_label": "Vancouver Island proxy",
            "proxy_market_name": "Vancouver Island",
            "metric_cards": [
                {"label": "12-Month Change", "value": "1.2%"},
                {"label": "1-Month Change", "value": "0.2%"},
                {"label": "5-Year Annualized", "value": "4.1%"},
                {"label": "10-Year Annualized", "value": "4.8%"},
            ],
        },
    )

    client = webapp.app.test_client()
    response = client.get("/api/markets/duncan_bc/appreciation?use_proxy=1")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["proxy_available"] is True
    assert payload["proxy_active"] is True
    assert payload["proxy_label"] == "Vancouver Island proxy"


def test_market_context_route_renders_crea_metric_cards(monkeypatch) -> None:
    monkeypatch.setattr(
        webapp,
        "get_supabase_read_config",
        lambda: webapp.SupabaseReadConfig(url="https://example.supabase.co", key="test-key"),
    )
    monkeypatch.setattr(
        webapp,
        "fetch_saved_search",
        lambda config, saved_search_id: {
            "id": saved_search_id,
            "name": "Victoria Houses",
            "location": "Victoria",
            "property_type": "house",
            "beds_min": 2,
            "search_snapshot": {},
        },
    )
    monkeypatch.setattr(webapp, "fetch_saved_searches", lambda config: [])
    monkeypatch.setattr(
        webapp,
        "fetch_market_profile",
        lambda config, market_key: {
            "market_key": market_key,
            "market_name": "Victoria",
            "province": "BC",
            "status": "active",
        },
    )
    monkeypatch.setattr(webapp, "fetch_market_metrics", lambda config, market_key: [])
    monkeypatch.setattr(
        webapp,
        "build_market_housing_summary",
        lambda config, market_profile: {
            "rent_display": "$2,327",
            "vacancy_display": "3.1%",
            "match_label": "CMHC Exact",
            "matched_market_name": "Victoria",
            "notes": None,
            "source_url": None,
            "source_date": None,
            "confidence": "high",
        },
    )
    monkeypatch.setattr(
        webapp,
        "build_preferred_appreciation_context",
        lambda config, market_key, property_type_slug="composite", allow_proxy=False: {
            "available": True,
            "title": "Appreciation history",
            "total_change_display": "44.0%",
            "start_label": "2016-01-01",
            "end_label": "2026-01-01",
            "start_value": "100.0",
            "end_value": "144.0",
            "source_name": "CREA MLS HPI",
            "confidence": "high",
            "source_url": None,
            "chart_path": "0,0 1,1",
            "series_points": [],
            "metric_cards": [
                {"label": "Benchmark Price", "value": "$890,000"},
                {"label": "5-Year Annualized", "value": "6.2%"},
            ],
            "property_type_label": "Composite",
            "data_quality_flag": "high",
            "trend_label": "Strong Long Term Growth",
            "latest_benchmark_price_display": "$890,000",
            "latest_date": "2026-01-01",
            "method_notes": None,
        },
    )

    client = webapp.app.test_client()
    response = client.get("/saved-searches/7/market-context")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Benchmark Price" in body
    assert "$890,000" in body
    assert "5-Year Annualized" in body
    assert "CREA MLS HPI" in body


def test_market_appreciation_api_returns_preferred_payload(monkeypatch) -> None:
    monkeypatch.setattr(
        webapp,
        "get_supabase_read_config",
        lambda: webapp.SupabaseReadConfig(url="https://example.supabase.co", key="test-key"),
    )
    monkeypatch.setattr(
        webapp,
        "build_preferred_appreciation_context",
        lambda config, market_key, property_type_slug="composite", allow_proxy=False: {
            "source_key": "crea_hpi",
            "source_name": "CREA MLS HPI",
            "property_type_label": "Composite",
            "available": True,
            "latest_benchmark_price": 890000,
            "latest_benchmark_price_display": "$890,000",
            "latest_date": "2026-01-01",
            "trend_direction": "strong_long_term_growth",
            "trend_label": "Strong Long Term Growth",
            "data_quality_flag": "high",
            "empty_message": None,
            "notes": None,
            "metric_cards": [
                {"label": "12-Month Change", "value": "8.5%"},
                {"label": "1-Month Change", "value": "0.6%"},
                {"label": "5-Year Annualized", "value": "6.2%"},
                {"label": "10-Year Annualized", "value": "5.4%"},
            ],
        },
    )

    client = webapp.app.test_client()
    response = client.get("/api/markets/victoria_bc/appreciation")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["source_key"] == "crea_hpi"
    assert payload["latest_benchmark_price_display"] == "$890,000"
    assert payload["appreciation_5y_cagr"] == "6.2%"
    assert payload["trend_label"] == "Strong Long Term Growth"


def test_investment_analyzer_route_renders_with_stubbed_dependencies(monkeypatch) -> None:
    webapp.LISTING_ANALYSIS_RUNS.clear()
    monkeypatch.setattr(
        webapp,
        "get_supabase_read_config",
        lambda: webapp.SupabaseReadConfig(url="https://example.supabase.co", key="test-key"),
    )
    monkeypatch.setattr(
        webapp,
        "fetch_saved_search",
        lambda config, saved_search_id: {
            "id": saved_search_id,
            "name": "Victoria Houses",
            "location": "Victoria",
            "property_type": "house",
            "beds_min": 2,
            "max_price": 900000,
            "search_snapshot": {},
        },
    )
    monkeypatch.setattr(
        webapp,
        "fetch_active_listings",
        lambda config, saved_search_id: [
            {
                "listing_id": 101,
                "address": "123 Example St",
                "price": "$500,000",
                "bedrooms": 3,
                "bathrooms": 2,
                "property_type": "house",
                "building_type": "House",
                "annual_taxes": "$3,600",
                "hoa_fees": "$0",
                "listing_description": "Detached house with suite potential.",
            }
        ],
    )
    monkeypatch.setattr(
        webapp,
        "hydrate_defaults_for_saved_search",
        lambda config, saved_search: (
            {
                **webapp.merge_investment_defaults({"market_rent_monthly": {"value": 3000}}),
            },
            {
                "match_type": "exact",
                "confidence": "high",
                "matched_market_name": "Victoria",
                "notes": "Exact market reference match found.",
                "market_reference": {
                    "source": "cmhc",
                    "vacancy_rate_percent": 3.1,
                    "source_url": "https://example.com/cmhc",
                },
            },
        ),
    )
    monkeypatch.setattr(webapp, "fetch_listing_investment_overrides", lambda config, saved_search_id, listing_ids: {})
    monkeypatch.setattr(webapp, "persist_saved_search_investment_defaults", lambda config, saved_search_id, defaults_snapshot: None)
    monkeypatch.setattr(webapp, "persist_saved_buy_box", lambda config, saved_search, buy_box: None)

    client = webapp.app.test_client()
    response = client.get("/saved-searches/7/investment-analyzer")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Victoria Houses" in body
    assert "Listing Analysis" in body
    assert "Ready to run" in body
    assert "Confirm the buy box and saved-search defaults above, then run analysis to fill this table." in body

    response = client.post(
        "/saved-searches/7/investment-analyzer/run",
        data={
            "apply_buy_box": "1",
            "buy_box_max_price": "900000",
            "buy_box_beds_min": "2",
            "buy_box_property_type": "house",
        },
        follow_redirects=True,
    )

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Buy box plus underwriting" in body
    assert "Rerun analysis" in body
    assert "123 Example St" in body


def test_investment_analyzer_uses_persisted_buy_box_results_on_page_load(monkeypatch) -> None:
    monkeypatch.setattr(
        webapp,
        "get_supabase_read_config",
        lambda: webapp.SupabaseReadConfig(url="https://example.supabase.co", key="test-key"),
    )
    monkeypatch.setattr(
        webapp,
        "fetch_saved_search",
        lambda config, saved_search_id: {
            "id": saved_search_id,
            "name": "Nanaimo Houses",
            "location": "Nanaimo",
            "property_type": "house",
            "beds_min": 4,
            "max_price": 2500000,
            "search_snapshot": {
                "latest_listing_analysis": {
                    "ran_at": "2026-04-28T22:27:51Z",
                    "buy_box": {
                        "applied": True,
                        "max_price": 2495000,
                        "beds_min": 4,
                        "property_type": "house",
                        "ai_screens": [
                            {
                                "key": "screen_1",
                                "name": "AI Prompt 1",
                                "goal": "Is this in a safe nice neighborhood?",
                                "enabled": True,
                            }
                        ],
                    },
                    "defaults_snapshot": webapp.merge_investment_defaults(
                        {"market_rent_monthly": {"value": 3500}}
                    ),
                    "overrides_by_listing_id": {},
                    "buy_box_results_by_listing_id": {
                        "101": {
                            "bucket": "maybe",
                            "label": "Maybe",
                            "reasons": ["AI Prompt 1: maybe - Needs review."],
                            "ai_verdict": "maybe",
                            "ai_screen_results": [
                                {
                                    "key": "screen_1",
                                    "name": "AI Prompt 1",
                                    "verdict": "maybe",
                                    "reason": "Needs review.",
                                    "research_summary": "Shared market context was researched.",
                                    "source_urls": ["https://example.com/source"],
                                }
                            ],
                            "ai_screen_likely_count": 0,
                            "ai_screen_total": 1,
                        }
                    },
                }
            },
        },
    )
    monkeypatch.setattr(
        webapp,
        "fetch_active_listings",
        lambda config, saved_search_id: [
            {
                "listing_id": 101,
                "address": "123 Example St",
                "price": "$1,200,000",
                "bedrooms": 4,
                "bathrooms": 3,
                "property_type": "house",
                "building_type": "House",
                "annual_taxes": "$5,000",
                "hoa_fees": "$0",
                "listing_description": "Large detached house.",
            }
        ],
    )
    monkeypatch.setattr(
        webapp,
        "hydrate_defaults_for_saved_search",
        lambda config, saved_search: (webapp.merge_investment_defaults({"market_rent_monthly": {"value": 3500}}), None),
    )
    monkeypatch.setattr(webapp, "fetch_listing_investment_overrides", lambda config, saved_search_id, listing_ids: {})

    def fail_if_called(*args, **kwargs):
        raise AssertionError("page load should render persisted buy-box results without rebuilding AI analysis")

    monkeypatch.setattr(webapp, "build_buy_box_result_lookup", fail_if_called)

    response = webapp.app.test_client().get("/saved-searches/36/investment-analyzer")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Nanaimo Houses" in body
    assert "source 1" in body


def test_saved_search_detail_does_not_run_buy_box_analysis_on_page_load(monkeypatch) -> None:
    monkeypatch.setattr(
        webapp,
        "get_supabase_read_config",
        lambda: webapp.SupabaseReadConfig(url="https://example.supabase.co", key="test-key"),
    )
    monkeypatch.setattr(
        webapp,
        "fetch_saved_search",
        lambda config, saved_search_id: {
            "id": saved_search_id,
            "name": "Nanaimo Houses",
            "location": "Nanaimo",
            "property_type": "house",
            "beds_min": 4,
            "max_price": 2500000,
            "last_scraped_at": "2026-04-28T15:40:32+00:00",
            "search_snapshot": {
                "buy_box": {
                    "applied": True,
                    "max_price": 2495000,
                    "beds_min": 4,
                    "property_type": "house",
                    "ai_screens": [
                        {
                            "key": "screen_1",
                            "name": "AI Prompt 1",
                            "goal": "subdivision potential",
                            "enabled": True,
                        }
                    ],
                }
            },
        },
    )
    monkeypatch.setattr(
        webapp,
        "fetch_active_listings",
        lambda config, saved_search_id: [
            {
                "listing_id": 101,
                "address": "123 Example St",
                "price": "$1,200,000",
                "bedrooms": 4,
                "bathrooms": 3,
                "property_type": "house",
                "building_type": "House",
                "listing_description": "Large detached house.",
                "is_new_in_run": False,
            }
        ],
    )
    monkeypatch.setattr(webapp, "fetch_listing_investment_overrides", lambda config, saved_search_id, listing_ids: {})
    monkeypatch.setattr(webapp, "fetch_recent_runs", lambda config, saved_search_id=None: [])

    def fail_if_called(active_listings, criteria):
        raise AssertionError("saved-search detail should not run buy-box analysis during page load")

    monkeypatch.setattr(webapp, "analyze_active_listings", fail_if_called)

    response = webapp.app.test_client().get("/saved-searches/36")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Nanaimo Houses" in body
    assert "AI Prompt 1" in body


def test_dashboard_renders_started_listing_search_status(monkeypatch) -> None:
    monkeypatch.setattr(
        webapp,
        "get_supabase_read_config",
        lambda: webapp.SupabaseReadConfig(url="https://example.supabase.co", key="test-key"),
    )
    monkeypatch.setattr(webapp, "fetch_saved_searches", lambda config: [])
    monkeypatch.setattr(webapp, "fetch_recent_runs", lambda config, saved_search_id=None: [])
    monkeypatch.setattr(webapp, "build_market_index", lambda config, saved_searches: [])
    monkeypatch.setattr(
        webapp,
        "list_scrape_jobs",
        lambda: [
            {
                "id": "job123",
                "status": "failed",
                "return_code": 1,
                "started_at": "2026-04-22T20:34:09Z",
            }
        ],
    )
    monkeypatch.setattr(
        webapp,
        "get_scrape_job",
        lambda job_id: {
            "id": job_id,
            "status": "failed",
            "return_code": 1,
            "started_at": "2026-04-22T20:34:09Z",
        },
    )

    client = webapp.app.test_client()
    response = client.get("/?started=job123")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Your listing search is running" in body
    assert "We are fetching matching listings now" in body
    assert "View progress" in body


def test_listing_detail_renders_smart_reserve_reasoning(monkeypatch) -> None:
    monkeypatch.setattr(
        webapp,
        "get_supabase_read_config",
        lambda: webapp.SupabaseReadConfig(url="https://example.supabase.co", key="test-key"),
    )
    monkeypatch.setattr(
        webapp,
        "fetch_saved_search",
        lambda config, saved_search_id: {
            "id": saved_search_id,
            "name": "Sidney Houses",
            "location": "Sidney",
            "property_type": "house",
            "beds_min": 3,
            "search_snapshot": {},
        },
    )
    monkeypatch.setattr(
        webapp,
        "fetch_active_listing_detail",
        lambda config, saved_search_id, listing_id: {
            "listing_id": listing_id,
            "address": "123 Example St",
            "price": "$500,000",
            "bedrooms": 3,
            "bathrooms": 2,
            "property_type": "house",
            "building_type": "House",
            "annual_taxes": "$3,600",
            "hoa_fees": "$0",
            "listing_description": "Updated home with recent renovations.",
            "last_seen_at": "2026-04-22T20:00:00Z",
            "source_listing_key": "abc123",
            "url": "https://example.com/listing",
        },
    )
    monkeypatch.setattr(webapp, "build_buy_box_criteria", lambda args, saved_search: {})
    monkeypatch.setattr(webapp, "analyze_listing_for_detail", lambda listing, buy_box: None)
    monkeypatch.setattr(
        webapp,
        "hydrate_defaults_for_saved_search",
        lambda config, saved_search: (
            {
                **webapp.merge_investment_defaults(
                    {
                        "market_rent_monthly": {"value": 2800},
                    }
                ),
            },
            None,
        ),
    )
    monkeypatch.setattr(
        webapp,
        "fetch_listing_investment_overrides",
        lambda config, saved_search_id, listing_ids: {
            listing_ids[0]: {
                "maintenance_percent_of_rent": 8.0,
                "maintenance_percent_source": "smart_listing_estimate",
                "maintenance_percent_confidence": "medium",
                "maintenance_percent_help_text": "Smart listing estimate based on older property vintage, single-family profile.",
                "capex_percent_of_rent": 10.0,
                "capex_percent_source": "smart_listing_estimate",
                "capex_percent_confidence": "medium",
                "capex_percent_help_text": "Smart listing estimate based on older property vintage, single-family profile.",
            }
        },
    )
    monkeypatch.setattr(
        webapp,
        "fetch_latest_ai_underwriting_suggestion",
        lambda config, saved_search_id, listing_id, suggestion_type: None,
    )

    client = webapp.app.test_client()
    response = client.get("/saved-searches/7/listings/101")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Smart listing estimate based on older property vintage, single-family profile." in body
    assert 'href="https://example.com/listing"' in body
    assert "Save listing underwriting" in body


def test_listing_detail_uses_persisted_buy_box_result(monkeypatch) -> None:
    monkeypatch.setattr(
        webapp,
        "get_supabase_read_config",
        lambda: webapp.SupabaseReadConfig(url="https://example.supabase.co", key="test-key"),
    )
    monkeypatch.setattr(
        webapp,
        "fetch_saved_search",
        lambda config, saved_search_id: {
            "id": saved_search_id,
            "name": "Victoria Apartments",
            "location": "Victoria",
            "property_type": "apartment",
            "beds_min": 2,
            "search_snapshot": {
                "latest_listing_analysis": {
                    "buy_box": {"applied": True},
                    "defaults_snapshot": webapp.merge_investment_defaults(
                        {"market_rent_monthly": {"value": 2400}}
                    ),
                    "overrides_by_listing_id": {},
                    "buy_box_results_by_listing_id": {
                        "101": {
                            "bucket": "maybe",
                            "label": "Maybe",
                            "reasons": ["AI Prompt 1: maybe - Saved result from prior run."],
                            "ai_verdict": "maybe",
                            "ai_screen_results": [],
                        }
                    },
                }
            },
        },
    )
    monkeypatch.setattr(
        webapp,
        "fetch_active_listing_detail",
        lambda config, saved_search_id, listing_id: {
            "listing_id": listing_id,
            "address": "123 Example Ave",
            "price": "$500,000",
            "bedrooms": 2,
            "bathrooms": 2,
            "property_type": "apartment",
            "building_type": "Apartment",
            "annual_taxes": "$2,400",
            "hoa_fees": "$400",
            "listing_description": "Downtown apartment.",
            "last_seen_at": "2026-04-22T20:00:00Z",
            "source_listing_key": "abc123",
            "url": "https://example.com/listing",
        },
    )
    monkeypatch.setattr(
        webapp,
        "hydrate_defaults_for_saved_search",
        lambda config, saved_search: (
            webapp.merge_investment_defaults({"market_rent_monthly": {"value": 2400}}),
            None,
        ),
    )
    monkeypatch.setattr(webapp, "fetch_listing_investment_overrides", lambda config, saved_search_id, listing_ids: {})
    monkeypatch.setattr(
        webapp,
        "fetch_latest_ai_underwriting_suggestion",
        lambda config, saved_search_id, listing_id, suggestion_type: {
            "accepted_value": 2400,
            "model": "gpt-test",
            "created_at": "2026-04-30T16:00:00Z",
            "parsed_suggestion": {
                "confidence": "medium",
                "adjustment_direction": "near_baseline",
                "reasoning": "Comparable apartment rent.",
                "rent_components": [],
            },
        },
    )

    def fail_if_called(*args, **kwargs):
        raise AssertionError("listing detail should use the persisted buy-box result")

    monkeypatch.setattr(webapp, "analyze_listing_for_detail", fail_if_called)

    response = webapp.app.test_client().get("/saved-searches/7/listings/101")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Saved result from prior run." in body
    assert "Maybe" in body
    assert "Rent reasoning" in body


def test_listing_detail_shows_persisted_buy_box_research_sources(monkeypatch) -> None:
    monkeypatch.setattr(
        webapp,
        "get_supabase_read_config",
        lambda: webapp.SupabaseReadConfig(url="https://example.supabase.co", key="test-key"),
    )
    monkeypatch.setattr(
        webapp,
        "fetch_saved_search",
        lambda config, saved_search_id: {
            "id": saved_search_id,
            "name": "Victoria Apartments",
            "location": "Victoria",
            "property_type": "apartment",
            "beds_min": 2,
            "search_snapshot": {
                "latest_listing_analysis": {
                    "buy_box": {"applied": True},
                    "defaults_snapshot": webapp.merge_investment_defaults(
                        {"market_rent_monthly": {"value": 2400}}
                    ),
                    "overrides_by_listing_id": {},
                    "buy_box_results_by_listing_id": {
                        "101": {
                            "bucket": "maybe",
                            "label": "Maybe",
                            "reasons": ["AI Prompt 1: maybe - Saved result."],
                            "ai_verdict": "maybe",
                            "ai_screen_results": [
                                {
                                    "key": "screen_1",
                                    "name": "AI Prompt 1",
                                    "verdict": "maybe",
                                    "reason": "Needs review.",
                                    "research_summary": "Saanich neighbourhood context was researched.",
                                    "source_urls": ["https://example.com/source"],
                                }
                            ],
                        }
                    },
                }
            },
        },
    )
    monkeypatch.setattr(
        webapp,
        "fetch_active_listing_detail",
        lambda config, saved_search_id, listing_id: {
            "listing_id": listing_id,
            "address": "304 3133 Tillicum Rd",
            "price": "$299,900",
            "bedrooms": 2,
            "bathrooms": 1,
            "property_type": "apartment",
            "building_type": "Apartment",
            "annual_taxes": "$1,800",
            "hoa_fees": "$400",
            "listing_description": "Apartment near parks and transit.",
            "last_seen_at": "2026-04-28T22:47:34Z",
            "source_listing_key": "abc123",
            "url": "https://example.com/listing",
        },
    )
    monkeypatch.setattr(
        webapp,
        "hydrate_defaults_for_saved_search",
        lambda config, saved_search: (
            webapp.merge_investment_defaults({"market_rent_monthly": {"value": 2400}}),
            None,
        ),
    )
    monkeypatch.setattr(webapp, "fetch_listing_investment_overrides", lambda config, saved_search_id, listing_ids: {})
    monkeypatch.setattr(
        webapp,
        "fetch_latest_ai_underwriting_suggestion",
        lambda config, saved_search_id, listing_id, suggestion_type: None,
    )

    response = webapp.app.test_client().get("/saved-searches/7/listings/101")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Research trail" in body
    assert "compact-research-trail" in body
    assert "Saanich neighbourhood context was researched." in body
    assert "https://example.com/source" in body


def test_listing_detail_underwriting_override_route_persists_values(monkeypatch) -> None:
    captured: dict[str, object] = {}
    monkeypatch.setattr(
        webapp,
        "get_supabase_read_config",
        lambda: webapp.SupabaseReadConfig(url="https://example.supabase.co", key="test-key"),
    )
    monkeypatch.setattr(
        webapp,
        "fetch_saved_search",
        lambda config, saved_search_id: {
            "id": saved_search_id,
            "name": "Nanaimo Houses",
            "location": "Nanaimo",
            "property_type": "house",
            "beds_min": 4,
            "search_snapshot": {},
        },
    )
    monkeypatch.setattr(
        webapp,
        "fetch_active_listing_detail",
        lambda config, saved_search_id, listing_id: {
            "listing_id": listing_id,
            "address": "123 Example St",
            "price": "$500,000",
            "annual_taxes": "$3,600",
            "hoa_fees": "$0",
        },
    )

    def fake_persist(config, saved_search_id, listing_id, override_updates):
        captured["saved_search_id"] = saved_search_id
        captured["listing_id"] = listing_id
        captured["override_updates"] = override_updates

    monkeypatch.setattr(webapp, "persist_listing_investment_override", fake_persist)

    client = webapp.app.test_client()
    response = client.post(
        "/saved-searches/7/listings/101/underwriting",
        data={
            "return_to": "investment_analyzer",
            "market_rent_monthly": "3200",
            "down_payment_percent": "25",
            "interest_rate_percent": "5.25",
            "amortization_years": "30",
            "closing_cost_percent": "2",
            "vacancy_percent": "4",
            "maintenance_percent_of_rent": "8",
            "capex_percent_of_rent": "5",
            "management_percent_of_rent": "0",
            "insurance_monthly": "125",
            "utilities_monthly": "0",
            "other_monthly": "",
        },
    )

    assert response.status_code == 302
    assert response.headers["Location"].endswith(
        "/saved-searches/7/listings/101?underwriting_saved=1&return_to=investment_analyzer"
    )
    updates = captured["override_updates"]
    assert updates["market_rent_monthly"] == 3200
    assert updates["market_rent_source"] == "listing_override"
    assert updates["down_payment_percent"] == 25
    assert updates["down_payment_percent_source"] == "listing_override"
    assert updates["interest_rate_percent"] == 5.25
    assert updates["interest_rate_percent_source"] == "listing_override"
    assert updates["other_monthly"] is None


def test_toggle_listing_favorite_persists_flag(monkeypatch) -> None:
    captured: dict[str, object] = {}
    monkeypatch.setattr(
        webapp,
        "get_supabase_read_config",
        lambda: webapp.SupabaseReadConfig(url="https://example.supabase.co", key="test-key"),
    )
    monkeypatch.setattr(webapp, "fetch_saved_search", lambda config, saved_search_id: {"id": saved_search_id})
    monkeypatch.setattr(
        webapp,
        "fetch_active_listing_detail",
        lambda config, saved_search_id, listing_id: {"listing_id": listing_id, "address": "123 Example St"},
    )

    def fake_persist(config, saved_search_id, listing_id, override_updates):
        captured["saved_search_id"] = saved_search_id
        captured["listing_id"] = listing_id
        captured["override_updates"] = override_updates

    monkeypatch.setattr(webapp, "persist_listing_investment_override", fake_persist)

    client = webapp.app.test_client()
    response = client.post(
        "/saved-searches/7/listings/101/favorite",
        data={"favorite": "1", "redirect_target": "listing_detail"},
    )

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/saved-searches/7/listings/101")
    assert captured["override_updates"] == {"favorite": True}


def test_favorites_page_groups_favorites_by_location(monkeypatch) -> None:
    monkeypatch.setattr(
        webapp,
        "get_supabase_read_config",
        lambda: webapp.SupabaseReadConfig(url="https://example.supabase.co", key="test-key"),
    )
    monkeypatch.setattr(
        webapp,
        "fetch_saved_searches",
        lambda config: [
            {"id": 7, "name": "Nanaimo Houses", "location": "Nanaimo"},
            {"id": 8, "name": "Victoria Houses", "location": "Victoria"},
        ],
    )
    monkeypatch.setattr(
        webapp,
        "fetch_active_listings",
        lambda config, saved_search_id: [
            {
                "saved_search_id": saved_search_id,
                "listing_id": 101 if saved_search_id == 7 else 201,
                "address": "Favorite Example" if saved_search_id == 7 else "Other Example",
                "price": "$500,000",
            }
        ],
    )
    monkeypatch.setattr(
        webapp,
        "fetch_listing_investment_overrides",
        lambda config, saved_search_id, listing_ids: {101: {"favorite": True}} if saved_search_id == 7 else {},
    )
    monkeypatch.setattr(webapp, "merge_listing_media", lambda config, listings: None)

    client = webapp.app.test_client()
    response = client.get("/favorites")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Nanaimo" in body
    assert "Favorite Example" in body
    assert "Other Example" not in body


def test_use_cmhc_vacancy_default_persists_updated_value(monkeypatch) -> None:
    captured: dict[str, object] = {}
    monkeypatch.setattr(
        webapp,
        "get_supabase_read_config",
        lambda: webapp.SupabaseReadConfig(url="https://example.supabase.co", key="test-key"),
    )
    monkeypatch.setattr(
        webapp,
        "fetch_saved_search",
        lambda config, saved_search_id: {
            "id": saved_search_id,
            "location": "Victoria",
            "property_type": "house",
            "beds_min": 2,
            "search_snapshot": {},
        },
    )
    monkeypatch.setattr(
        webapp,
        "fetch_saved_search_investment_defaults",
        lambda config, saved_search_id: {"vacancy_percent": {"value": 4.0, "source": "manual"}},
    )
    monkeypatch.setattr(
        webapp,
        "hydrate_defaults_for_saved_search",
        lambda config, saved_search: (
            {},
            {
                "match_type": "exact",
                "confidence": "high",
                "notes": "Exact market reference match found.",
                "market_reference": {
                    "vacancy_rate_percent": 3.1,
                    "source_url": "https://example.com/cmhc",
                },
            },
        ),
    )

    def fake_persist(config, saved_search_id, defaults_snapshot):
        captured["saved_search_id"] = saved_search_id
        captured["defaults_snapshot"] = defaults_snapshot

    monkeypatch.setattr(webapp, "persist_saved_search_investment_defaults", fake_persist)

    client = webapp.app.test_client()
    response = client.post("/saved-searches/7/investment-analyzer/use-cmhc-vacancy")

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/saved-searches/7/investment-analyzer?cmhc_vacancy_used=1")
    assert captured["saved_search_id"] == 7
    defaults_snapshot = captured["defaults_snapshot"]
    assert defaults_snapshot["vacancy_percent"]["value"] == 3.1
    assert defaults_snapshot["vacancy_percent"]["source"] == "cmhc_exact"


def test_use_manual_vacancy_default_persists_manual_source_even_when_value_matches_cmhc(monkeypatch) -> None:
    captured: dict[str, object] = {}
    monkeypatch.setattr(
        webapp,
        "get_supabase_read_config",
        lambda: webapp.SupabaseReadConfig(url="https://example.supabase.co", key="test-key"),
    )
    monkeypatch.setattr(
        webapp,
        "fetch_saved_search",
        lambda config, saved_search_id: {
            "id": saved_search_id,
            "location": "Victoria",
            "property_type": "house",
            "beds_min": 2,
            "search_snapshot": {},
        },
    )
    monkeypatch.setattr(
        webapp,
        "fetch_saved_search_investment_defaults",
        lambda config, saved_search_id: {"vacancy_percent": {"value": 3.0, "source": "cmhc_exact"}},
    )

    def fake_persist(config, saved_search_id, defaults_snapshot):
        captured["saved_search_id"] = saved_search_id
        captured["defaults_snapshot"] = defaults_snapshot

    monkeypatch.setattr(webapp, "persist_saved_search_investment_defaults", fake_persist)

    client = webapp.app.test_client()
    response = client.post("/saved-searches/7/investment-analyzer/use-manual-vacancy", data={"vacancy_percent": "3.0"})

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/saved-searches/7/investment-analyzer?manual_vacancy_used=1")
    defaults_snapshot = captured["defaults_snapshot"]
    assert defaults_snapshot["vacancy_percent"]["value"] == 3.0
    assert defaults_snapshot["vacancy_percent"]["source"] == "manual"


def test_use_cmhc_rent_preserves_entered_manual_rent_value(monkeypatch) -> None:
    captured: dict[str, object] = {}
    monkeypatch.setattr(
        webapp,
        "get_supabase_read_config",
        lambda: webapp.SupabaseReadConfig(url="https://example.supabase.co", key="test-key"),
    )
    monkeypatch.setattr(
        webapp,
        "fetch_saved_search",
        lambda config, saved_search_id: {
            "id": saved_search_id,
            "location": "Duncan",
            "property_type": "house",
            "beds_min": 3,
            "search_snapshot": {},
        },
    )
    monkeypatch.setattr(webapp, "fetch_saved_search_investment_defaults", lambda config, saved_search_id: {})
    monkeypatch.setattr(
        webapp,
        "hydrate_defaults_for_saved_search",
        lambda config, saved_search: (
            {},
            {
                "match_type": "exact",
                "confidence": "high",
                "notes": "Exact market reference match found.",
                "market_reference": {
                    "average_rent_monthly": 1822,
                    "source_url": "https://example.com/cmhc",
                },
            },
        ),
    )

    def fake_persist(config, saved_search_id, defaults_snapshot):
        captured["defaults_snapshot"] = defaults_snapshot

    monkeypatch.setattr(webapp, "persist_saved_search_investment_defaults", fake_persist)
    monkeypatch.setattr(webapp, "clear_listing_rent_overrides_for_saved_search", lambda config, saved_search_id: None)

    client = webapp.app.test_client()
    response = client.post("/saved-searches/7/investment-analyzer/use-cmhc-rent", data={"market_rent_monthly": "2000"})

    assert response.status_code == 302
    defaults_snapshot = captured["defaults_snapshot"]
    assert defaults_snapshot["market_rent_monthly"]["value"] == 1822.0
    assert defaults_snapshot["market_rent_monthly"]["manual_value"] == 2000.0
    assert defaults_snapshot["market_rent_monthly"]["source"] == "cmhc_exact"


def test_use_off_utilities_default_persists_zero_value(monkeypatch) -> None:
    captured: dict[str, object] = {}
    monkeypatch.setattr(
        webapp,
        "get_supabase_read_config",
        lambda: webapp.SupabaseReadConfig(url="https://example.supabase.co", key="test-key"),
    )
    monkeypatch.setattr(
        webapp,
        "fetch_saved_search",
        lambda config, saved_search_id: {
            "id": saved_search_id,
            "location": "Victoria",
            "property_type": "apartment",
            "beds_min": 2,
            "search_snapshot": {},
        },
    )
    monkeypatch.setattr(webapp, "fetch_saved_search_investment_defaults", lambda config, saved_search_id: {})

    def fake_persist(config, saved_search_id, defaults_snapshot):
        captured["saved_search_id"] = saved_search_id
        captured["defaults_snapshot"] = defaults_snapshot

    monkeypatch.setattr(webapp, "persist_saved_search_investment_defaults", fake_persist)

    client = webapp.app.test_client()
    response = client.post("/saved-searches/7/investment-analyzer/use-off-utilities")

    assert response.status_code == 302
    defaults_snapshot = captured["defaults_snapshot"]
    assert defaults_snapshot["utilities_monthly"]["value"] == 0.0
    assert defaults_snapshot["utilities_monthly"]["source"] == "off"


def test_use_rule_based_insurance_default_persists_bc_rule_based_value(monkeypatch) -> None:
    captured: dict[str, object] = {}
    monkeypatch.setattr(
        webapp,
        "get_supabase_read_config",
        lambda: webapp.SupabaseReadConfig(url="https://example.supabase.co", key="test-key"),
    )
    monkeypatch.setattr(
        webapp,
        "fetch_saved_search",
        lambda config, saved_search_id: {
            "id": saved_search_id,
            "location": "Victoria",
            "property_type": "house",
            "beds_min": 3,
            "search_snapshot": {},
        },
    )
    monkeypatch.setattr(webapp, "fetch_saved_search_investment_defaults", lambda config, saved_search_id: {})

    def fake_persist(config, saved_search_id, defaults_snapshot):
        captured["saved_search_id"] = saved_search_id
        captured["defaults_snapshot"] = defaults_snapshot

    monkeypatch.setattr(webapp, "persist_saved_search_investment_defaults", fake_persist)

    client = webapp.app.test_client()
    response = client.post("/saved-searches/7/investment-analyzer/use-rule-based-insurance")

    assert response.status_code == 302
    defaults_snapshot = captured["defaults_snapshot"]
    assert defaults_snapshot["insurance_monthly"]["value"] == 135.0
    assert defaults_snapshot["insurance_monthly"]["source"] == "rule_based_bc"


def test_apply_smart_maintenance_persists_listing_level_estimates(monkeypatch) -> None:
    captured: list[tuple[int, dict[str, object]]] = []
    monkeypatch.setattr(
        webapp,
        "get_supabase_read_config",
        lambda: webapp.SupabaseReadConfig(url="https://example.supabase.co", key="test-key"),
    )
    monkeypatch.setattr(
        webapp,
        "fetch_saved_search",
        lambda config, saved_search_id: {"id": saved_search_id, "name": "Victoria Houses", "search_snapshot": {}},
    )
    monkeypatch.setattr(
        webapp,
        "fetch_active_listings",
        lambda config, saved_search_id: [
            {
                "listing_id": 101,
                "property_type": "house",
                "building_type": "House",
                "built_in": "1965",
                "hoa_fees": None,
                "listing_description": "Older house with original condition and needs work.",
            }
        ],
    )

    def fake_persist(config, saved_search_id, listing_id, override_updates):
        captured.append((listing_id, override_updates))

    monkeypatch.setattr(webapp, "persist_listing_investment_override", fake_persist)

    client = webapp.app.test_client()
    response = client.post("/saved-searches/7/investment-analyzer/apply-smart-maintenance")

    assert response.status_code == 302
    assert len(captured) == 1
    listing_id, override_updates = captured[0]
    assert listing_id == 101
    assert override_updates["maintenance_percent_source"] == "smart_listing_estimate"
    assert override_updates["maintenance_percent_of_rent"] >= 9.0
    assert "capex_percent_of_rent" not in override_updates


def test_use_shared_maintenance_clears_listing_level_keys(monkeypatch) -> None:
    cleared: dict[str, object] = {}
    monkeypatch.setattr(
        webapp,
        "get_supabase_read_config",
        lambda: webapp.SupabaseReadConfig(url="https://example.supabase.co", key="test-key"),
    )
    monkeypatch.setattr(
        webapp,
        "fetch_saved_search",
        lambda config, saved_search_id: {"id": saved_search_id, "search_snapshot": {}},
    )

    def fake_clear(config, saved_search_id, keys):
        cleared["saved_search_id"] = saved_search_id
        cleared["keys"] = keys

    monkeypatch.setattr(webapp, "clear_listing_override_keys_for_saved_search", fake_clear)

    client = webapp.app.test_client()
    response = client.post("/saved-searches/7/investment-analyzer/use-shared-maintenance")

    assert response.status_code == 302
    assert cleared["saved_search_id"] == 7
    assert "maintenance_percent_of_rent" in cleared["keys"]
