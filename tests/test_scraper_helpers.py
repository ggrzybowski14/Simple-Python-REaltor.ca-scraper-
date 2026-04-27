from __future__ import annotations

from scraper import address_matches_requested_location


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

