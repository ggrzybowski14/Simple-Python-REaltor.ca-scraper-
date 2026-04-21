from __future__ import annotations

import app as webapp


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
