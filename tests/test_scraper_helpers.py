from __future__ import annotations

import argparse

import pytest

import scraper as scraper_module
from scraper import (
    address_matches_requested_location,
    build_proxy_config_from_webshare_proxy,
    collect_scrape_limits,
    describe_proxy_config,
    get_scraper_proxy_config,
    normalize_proxy_server,
    ProxyConfig,
    should_block_detail_request,
    text_has_security_challenge,
)


def test_address_matches_requested_location_accepts_bc_alias() -> None:
    assert address_matches_requested_location(
        "549 Weber St, Nanaimo, British Columbia",
        "Nanaimo, BC",
    )


def test_address_matches_requested_location_rejects_nearby_city() -> None:
    assert not address_matches_requested_location(
        "2395 Collins Cres, Nanoose Bay, British Columbia",
        "Nanaimo, BC",
    )


def test_normalize_proxy_server_adds_http_scheme() -> None:
    assert normalize_proxy_server("p.webshare.io:80") == "http://p.webshare.io:80"


def test_should_block_detail_request_blocks_heavy_assets() -> None:
    assert should_block_detail_request("image", "https://cdn.example.com/listing.jpg")
    assert should_block_detail_request("font", "https://cdn.example.com/font.woff2")
    assert should_block_detail_request("media", "https://cdn.example.com/tour.mp4")


def test_should_block_detail_request_blocks_common_tracking() -> None:
    assert should_block_detail_request("script", "https://www.googletagmanager.com/gtm.js")
    assert should_block_detail_request("xhr", "https://stats.g.doubleclick.net/collect")


def test_should_block_detail_request_allows_document_and_xhr() -> None:
    assert not should_block_detail_request("document", "https://www.realtor.ca/real-estate/123/example")
    assert not should_block_detail_request("xhr", "https://api2.realtor.ca/Listing.svc/PropertyDetails")


def test_text_has_security_challenge_detects_realtor_challenge() -> None:
    assert text_has_security_challenge("www.realtor.ca Additional security check is required")
    assert text_has_security_challenge("Just click the I'm not a robot checkbox to pass the security check. Click to verify")


def test_text_has_security_challenge_ignores_normal_listing_text() -> None:
    assert not text_has_security_challenge("Property Summary MLS Number Listing Description")


def test_collect_scrape_limits_accepts_detail_pause_settings() -> None:
    limits = collect_scrape_limits(
        argparse.Namespace(
            max_pages=1,
            max_listings=3,
            detail_limit=1,
            detail_concurrency=2,
            detail_pause_min=0.1,
            detail_pause_max=0.4,
            block_detail_assets=True,
        )
    )

    assert limits.detail_pause_min == 0.1
    assert limits.detail_pause_max == 0.4
    assert limits.block_detail_assets is True


def test_collect_scrape_limits_rejects_invalid_detail_pause_range() -> None:
    with pytest.raises(ValueError, match="--detail-pause-max"):
        collect_scrape_limits(
            argparse.Namespace(
                max_pages=1,
                max_listings=3,
                detail_limit=1,
                detail_concurrency=2,
                detail_pause_min=0.8,
                detail_pause_max=0.2,
                block_detail_assets=False,
            )
        )


def test_get_scraper_proxy_config_reads_authenticated_env(monkeypatch) -> None:
    monkeypatch.delenv("WEBSHARE_API_KEY", raising=False)
    monkeypatch.setenv("SCRAPER_PROXY_ENABLED", "true")
    monkeypatch.setenv("SCRAPER_PROXY_SERVER", "p.webshare.io:80")
    monkeypatch.setenv("SCRAPER_PROXY_USERNAME", "user")
    monkeypatch.setenv("SCRAPER_PROXY_PASSWORD", "secret")

    proxy_config = get_scraper_proxy_config()

    assert proxy_config is not None
    assert proxy_config.server == "http://p.webshare.io:80"
    assert proxy_config.username == "user"
    assert proxy_config.password == "secret"


def test_get_scraper_proxy_config_requires_server_when_enabled(monkeypatch) -> None:
    monkeypatch.delenv("WEBSHARE_API_KEY", raising=False)
    monkeypatch.setenv("SCRAPER_PROXY_ENABLED", "true")
    monkeypatch.delenv("SCRAPER_PROXY_SERVER", raising=False)

    with pytest.raises(ValueError, match="SCRAPER_PROXY_SERVER is required"):
        get_scraper_proxy_config()


def test_get_scraper_proxy_config_requires_username_password_pair(monkeypatch) -> None:
    monkeypatch.delenv("WEBSHARE_API_KEY", raising=False)
    monkeypatch.setenv("SCRAPER_PROXY_SERVER", "http://p.webshare.io:80")
    monkeypatch.setenv("SCRAPER_PROXY_USERNAME", "user")
    monkeypatch.delenv("SCRAPER_PROXY_PASSWORD", raising=False)

    with pytest.raises(ValueError, match="must be set together"):
        get_scraper_proxy_config()


def test_describe_proxy_config_hides_credentials(monkeypatch) -> None:
    monkeypatch.delenv("WEBSHARE_API_KEY", raising=False)
    monkeypatch.setenv("SCRAPER_PROXY_SERVER", "http://p.webshare.io:80")
    monkeypatch.setenv("SCRAPER_PROXY_USERNAME", "user")
    monkeypatch.setenv("SCRAPER_PROXY_PASSWORD", "secret")

    proxy_config = get_scraper_proxy_config()

    assert proxy_config is not None
    description = describe_proxy_config(proxy_config)
    assert description == "http://p.webshare.io:80 (authenticated)"
    assert "user" not in description
    assert "secret" not in description


def test_build_proxy_config_from_webshare_direct_proxy() -> None:
    proxy_config = build_proxy_config_from_webshare_proxy(
        {
            "proxy_address": "104.239.107.47",
            "port": 5699,
            "username": "user",
            "password": "secret",
            "valid": True,
        },
        mode="direct",
    )

    assert proxy_config is not None
    assert proxy_config.server == "http://104.239.107.47:5699"
    assert proxy_config.username == "user"
    assert proxy_config.password == "secret"


def test_build_proxy_config_from_webshare_backbone_proxy() -> None:
    proxy_config = build_proxy_config_from_webshare_proxy(
        {
            "proxy_address": "104.239.107.47",
            "port": 80,
            "username": "user",
            "password": "secret",
            "valid": True,
        },
        mode="backbone",
    )

    assert proxy_config is not None
    assert proxy_config.server == "http://p.webshare.io:80"


def test_build_proxy_config_from_webshare_proxy_rejects_invalid_proxy() -> None:
    assert (
        build_proxy_config_from_webshare_proxy(
            {
                "proxy_address": "104.239.107.47",
                "port": 5699,
                "username": "user",
                "password": "secret",
                "valid": False,
            }
        )
        is None
    )


def test_get_scraper_proxy_config_uses_webshare_api(monkeypatch) -> None:
    selected = ProxyConfig(
        server="http://104.239.107.47:5699",
        username="api-user",
        password="api-secret",
    )

    def fake_fetch(api_key: str, *, mode: str, country_codes: str | None = None) -> list[ProxyConfig]:
        assert api_key == "test-key"
        assert mode == "direct"
        assert country_codes == "US,CA"
        return [selected]

    monkeypatch.setenv("WEBSHARE_API_KEY", "test-key")
    monkeypatch.setenv("WEBSHARE_PROXY_MODE", "direct")
    monkeypatch.setenv("WEBSHARE_PROXY_COUNTRY_CODES", "US,CA")
    monkeypatch.setattr(scraper_module, "fetch_webshare_proxy_configs", fake_fetch)

    assert get_scraper_proxy_config() == selected
