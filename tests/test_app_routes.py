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
    assert "24.4%" in body


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
        "fetch_market_metric_series",
        lambda config, market_key, series_key: [],
    )

    client = webapp.app.test_client()
    response = client.get("/markets/duncan_bc")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Duncan Market Context" in body
    assert "$1,629" in body
    assert "Series pending" in body


def test_investment_analyzer_route_renders_with_stubbed_dependencies(monkeypatch) -> None:
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

    client = webapp.app.test_client()
    response = client.get("/saved-searches/7/investment-analyzer")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Victoria Houses" in body
    assert "Investment Analyzer" in body
    assert "123 Example St" in body


def test_dashboard_renders_local_background_jobs(monkeypatch) -> None:
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
    assert "Background job job123" in body
    assert "Background job history" in body
    assert "Open local job log" in body


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
