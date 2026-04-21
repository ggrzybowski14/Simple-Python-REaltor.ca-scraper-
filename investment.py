from __future__ import annotations

import math
from copy import deepcopy
from typing import Any


DEFAULT_INVESTMENT_ASSUMPTIONS: dict[str, dict[str, Any]] = {
    "down_payment_percent": {
        "value": 20.0,
        "source": "product_default",
        "confidence": "high",
        "help_text": "Standard investor down payment assumption for V1.",
        "help_url": None,
        "label": "Down Payment %",
        "input_step": "0.5",
    },
    "interest_rate_percent": {
        "value": 4.5,
        "source": "manual",
        "confidence": "medium",
        "help_text": "Editable financing estimate for this saved search.",
        "help_url": "https://www.ratehub.ca/mortgages",
        "label": "Interest Rate %",
        "input_step": "0.05",
    },
    "amortization_years": {
        "value": 30,
        "source": "product_default",
        "confidence": "high",
        "help_text": "Longer amortization reduces the monthly payment.",
        "help_url": None,
        "label": "Amortization (Years)",
        "input_step": "1",
    },
    "closing_cost_percent": {
        "value": 2.0,
        "source": "product_default",
        "confidence": "medium",
        "help_text": "Closing costs are often estimated around 1.5% to 4% of purchase price.",
        "help_url": "https://www.cmhc-schl.gc.ca/professionals/industry-innovation-and-leadership/industry-expertise/resources-for-mortgage-professionals/10-words-to-know-when-buying-home",
        "label": "Closing Costs %",
        "input_step": "0.1",
    },
    "vacancy_percent": {
        "value": 4.0,
        "source": "manual",
        "confidence": "medium",
        "help_text": "Editable saved-search vacancy assumption for this market.",
        "help_url": None,
        "label": "Vacancy %",
        "input_step": "0.1",
    },
    "maintenance_percent_of_rent": {
        "value": 8.0,
        "source": "product_default",
        "confidence": "medium",
        "help_text": "Modeled as a percent of rent in V1, not property value.",
        "help_url": None,
        "label": "Maintenance % Of Rent",
        "input_step": "0.1",
    },
    "capex_percent_of_rent": {
        "value": 5.0,
        "source": "product_default",
        "confidence": "medium",
        "help_text": "Capital reserve modeled as a percent of rent in V1.",
        "help_url": None,
        "label": "CapEx % Of Rent",
        "input_step": "0.1",
    },
    "management_percent_of_rent": {
        "value": 0.0,
        "source": "manual",
        "confidence": "high",
        "help_text": "Set to 0% for self-management in V1.",
        "help_url": None,
        "label": "Management % Of Rent",
        "input_step": "0.1",
    },
    "insurance_monthly": {
        "value": None,
        "source": "manual",
        "confidence": "low",
        "help_text": "Monthly insurance estimate if known.",
        "help_url": None,
        "label": "Insurance Monthly",
        "input_step": "1",
    },
    "utilities_monthly": {
        "value": None,
        "source": "manual",
        "confidence": "low",
        "help_text": "Only include landlord-paid utilities.",
        "help_url": None,
        "label": "Utilities Monthly",
        "input_step": "1",
    },
    "other_monthly": {
        "value": None,
        "source": "manual",
        "confidence": "low",
        "help_text": "Any recurring monthly cost not covered elsewhere.",
        "help_url": None,
        "label": "Other Monthly",
        "input_step": "1",
    },
    "market_rent_monthly": {
        "value": None,
        "source": "manual",
        "confidence": "low",
        "help_text": "Single rent estimate for this saved search in V1.",
        "help_url": None,
        "label": "Market Rent Monthly",
        "input_step": "1",
    },
}


def get_default_investment_assumptions() -> dict[str, dict[str, Any]]:
    return deepcopy(DEFAULT_INVESTMENT_ASSUMPTIONS)


def merge_investment_defaults(
    saved_defaults: dict[str, Any] | None,
) -> dict[str, dict[str, Any]]:
    merged = get_default_investment_assumptions()
    if not isinstance(saved_defaults, dict):
        return merged
    for key, definition in merged.items():
        candidate = saved_defaults.get(key)
        if isinstance(candidate, dict):
            definition.update(
                {
                    "value": candidate.get("value"),
                    "source": candidate.get("source") or definition["source"],
                    "confidence": candidate.get("confidence") or definition["confidence"],
                    "help_text": candidate.get("help_text") or definition["help_text"],
                    "help_url": candidate.get("help_url") or definition["help_url"],
                }
            )
    return merged


def parse_form_number(value: str | None) -> float | None:
    if value is None:
        return None
    cleaned = value.strip().replace(",", "")
    if not cleaned:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def build_defaults_snapshot_from_form(
    form_data,
    existing_defaults: dict[str, dict[str, Any]] | None = None,
) -> dict[str, dict[str, Any]]:
    defaults = merge_investment_defaults(existing_defaults)
    for key, definition in defaults.items():
        previous_value = definition.get("value")
        value = parse_form_number(form_data.get(key))
        definition["value"] = value
        if value != previous_value:
            definition["source"] = "manual"
            definition["confidence"] = "medium"
            if key == "market_rent_monthly":
                definition["help_text"] = "Manual saved-search rent value."
            elif key == "vacancy_percent":
                definition["help_text"] = "Manual saved-search vacancy value."
    return defaults


def parse_money_amount(value: str | None) -> float | None:
    if not value:
        return None
    cleaned = "".join(ch for ch in value if ch.isdigit() or ch in {".", "-"})
    if not cleaned or cleaned in {".", "-", "-."}:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def monthly_mortgage_payment(principal: float, annual_rate_percent: float, amortization_years: float) -> float | None:
    if principal <= 0 or annual_rate_percent < 0 or amortization_years <= 0:
        return None
    monthly_rate = annual_rate_percent / 100 / 12
    periods = int(amortization_years * 12)
    if periods <= 0:
        return None
    if monthly_rate == 0:
        return principal / periods
    factor = (1 + monthly_rate) ** periods
    return principal * (monthly_rate * factor) / (factor - 1)


def build_effective_assumptions(
    listing: dict[str, Any],
    merged_defaults: dict[str, dict[str, Any]],
    listing_overrides: dict[str, Any] | None = None,
) -> dict[str, dict[str, Any]]:
    effective = deepcopy(merged_defaults)
    normalized_overrides = listing_overrides if isinstance(listing_overrides, dict) else {}
    annual_taxes = parse_money_amount(listing.get("annual_taxes"))
    hoa_monthly = parse_money_amount(listing.get("hoa_fees"))
    rent_override = parse_form_number(str(normalized_overrides.get("market_rent_monthly"))) if normalized_overrides.get("market_rent_monthly") is not None else None
    if rent_override is not None:
        rent_override_source = str(normalized_overrides.get("market_rent_source") or "listing_override")
        effective["market_rent_monthly"]["value"] = rent_override
        effective["market_rent_monthly"]["source"] = rent_override_source
        effective["market_rent_monthly"]["confidence"] = "medium"
        effective["market_rent_monthly"]["help_text"] = (
            "Saved AI listing rent value." if rent_override_source.startswith("ai_") else "Saved listing-specific rent override."
        )
    if annual_taxes is not None:
        effective["property_tax_annual"] = {
            "value": annual_taxes,
            "source": "scraped",
            "confidence": "high",
            "help_text": "Scraped from the listing where available.",
            "help_url": None,
            "label": "Property Tax Annual",
        }
    else:
        effective["property_tax_annual"] = {
            "value": None,
            "source": "missing",
            "confidence": "low",
            "help_text": "Tax amount was not available in the scraped listing.",
            "help_url": None,
            "label": "Property Tax Annual",
        }
    if hoa_monthly is not None:
        effective["hoa_monthly"] = {
            "value": hoa_monthly,
            "source": "scraped",
            "confidence": "high",
            "help_text": "Scraped from the listing where available.",
            "help_url": None,
            "label": "HOA Monthly",
        }
    else:
        effective["hoa_monthly"] = {
            "value": None,
            "source": "missing",
            "confidence": "low",
            "help_text": "HOA or strata fee was not available in the scraped listing.",
            "help_url": None,
            "label": "HOA Monthly",
        }
    return effective


def calculate_listing_verdict(metrics: dict[str, Any], warnings: list[str]) -> dict[str, str]:
    monthly_cash_flow = metrics.get("monthly_cash_flow")
    cap_rate = metrics.get("cap_rate")
    if metrics.get("gross_monthly_rent") is None or metrics.get("purchase_price") is None:
        return {"label": "Borderline", "slug": "borderline"}
    if warnings:
        if monthly_cash_flow is not None and monthly_cash_flow > 0 and cap_rate is not None and cap_rate >= 4.5:
            return {"label": "Promising", "slug": "promising"}
        return {"label": "Borderline", "slug": "borderline"}
    if monthly_cash_flow is not None and monthly_cash_flow > 0 and cap_rate is not None and cap_rate >= 5.0:
        return {"label": "Promising", "slug": "promising"}
    if monthly_cash_flow is not None and monthly_cash_flow < -150:
        return {"label": "Weak", "slug": "weak"}
    return {"label": "Borderline", "slug": "borderline"}


def calculate_underwriting(
    listing: dict[str, Any],
    merged_defaults: dict[str, dict[str, Any]],
    listing_overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    effective = build_effective_assumptions(listing, merged_defaults, listing_overrides=listing_overrides)
    purchase_price = parse_money_amount(listing.get("price"))
    gross_monthly_rent = effective["market_rent_monthly"]["value"]
    down_payment_percent = effective["down_payment_percent"]["value"] or 0
    interest_rate_percent = effective["interest_rate_percent"]["value"] or 0
    amortization_years = effective["amortization_years"]["value"] or 0
    closing_cost_percent = effective["closing_cost_percent"]["value"] or 0
    vacancy_percent = effective["vacancy_percent"]["value"] or 0
    maintenance_percent = effective["maintenance_percent_of_rent"]["value"] or 0
    capex_percent = effective["capex_percent_of_rent"]["value"] or 0
    management_percent = effective["management_percent_of_rent"]["value"] or 0
    property_tax_annual = effective["property_tax_annual"]["value"]
    hoa_monthly = effective["hoa_monthly"]["value"] or 0
    insurance_monthly = effective["insurance_monthly"]["value"] or 0
    utilities_monthly = effective["utilities_monthly"]["value"] or 0
    other_monthly = effective["other_monthly"]["value"] or 0

    warnings: list[str] = []
    if purchase_price is None:
        warnings.append("Missing listing price")
    if gross_monthly_rent is None:
        warnings.append("Missing market rent default")
    if property_tax_annual is None:
        warnings.append("Missing scraped taxes")

    down_payment_amount = None
    loan_amount = None
    closing_cost_amount = None
    cash_invested_total = None
    monthly_mortgage = None

    if purchase_price is not None:
        down_payment_amount = purchase_price * down_payment_percent / 100
        loan_amount = purchase_price - down_payment_amount
        closing_cost_amount = purchase_price * closing_cost_percent / 100
        cash_invested_total = down_payment_amount + closing_cost_amount
        if loan_amount is not None:
            monthly_mortgage = monthly_mortgage_payment(loan_amount, interest_rate_percent, amortization_years)

    monthly_property_tax = property_tax_annual / 12 if property_tax_annual is not None else None
    monthly_vacancy = (
        gross_monthly_rent * vacancy_percent / 100 if gross_monthly_rent is not None else None
    )
    monthly_maintenance = (
        gross_monthly_rent * maintenance_percent / 100 if gross_monthly_rent is not None else None
    )
    monthly_capex = gross_monthly_rent * capex_percent / 100 if gross_monthly_rent is not None else None
    monthly_management = (
        gross_monthly_rent * management_percent / 100 if gross_monthly_rent is not None else None
    )

    operating_components = [
        monthly_property_tax,
        insurance_monthly,
        hoa_monthly,
        utilities_monthly,
        other_monthly,
        monthly_vacancy,
        monthly_maintenance,
        monthly_management,
    ]
    monthly_operating_expenses_ex_mortgage = None
    if gross_monthly_rent is not None and all(component is not None for component in operating_components):
        monthly_operating_expenses_ex_mortgage = float(sum(operating_components))

    annual_noi = None
    if gross_monthly_rent is not None and monthly_operating_expenses_ex_mortgage is not None:
        annual_noi = (gross_monthly_rent - monthly_operating_expenses_ex_mortgage) * 12

    monthly_cash_flow = None
    cash_flow_components = [
        monthly_property_tax,
        insurance_monthly,
        hoa_monthly,
        utilities_monthly,
        other_monthly,
        monthly_vacancy,
        monthly_maintenance,
        monthly_management,
        monthly_capex,
        monthly_mortgage,
    ]
    if gross_monthly_rent is not None and all(component is not None for component in cash_flow_components):
        monthly_cash_flow = gross_monthly_rent - float(sum(cash_flow_components))

    cap_rate = annual_noi / purchase_price * 100 if annual_noi is not None and purchase_price else None
    cash_on_cash_return = (
        (monthly_cash_flow * 12) / cash_invested_total * 100
        if monthly_cash_flow is not None and cash_invested_total not in {None, 0}
        else None
    )
    rent_to_price_ratio = (
        gross_monthly_rent / purchase_price * 100 if gross_monthly_rent is not None and purchase_price else None
    )

    metrics = {
        "purchase_price": purchase_price,
        "gross_monthly_rent": gross_monthly_rent,
        "down_payment_amount": down_payment_amount,
        "loan_amount": loan_amount,
        "closing_cost_amount": closing_cost_amount,
        "cash_invested_total": cash_invested_total,
        "monthly_mortgage": monthly_mortgage,
        "monthly_property_tax": monthly_property_tax,
        "monthly_insurance": insurance_monthly,
        "monthly_hoa": hoa_monthly if hoa_monthly else None,
        "monthly_utilities": utilities_monthly if utilities_monthly else None,
        "monthly_other": other_monthly if other_monthly else None,
        "monthly_vacancy_reserve": monthly_vacancy,
        "monthly_maintenance_reserve": monthly_maintenance,
        "monthly_capex_reserve": monthly_capex,
        "monthly_management": monthly_management,
        "monthly_operating_expenses_ex_mortgage": monthly_operating_expenses_ex_mortgage,
        "monthly_cash_flow": monthly_cash_flow,
        "annual_noi": annual_noi,
        "cap_rate": cap_rate,
        "cash_on_cash_return": cash_on_cash_return,
        "rent_to_price_ratio": rent_to_price_ratio,
    }
    verdict = calculate_listing_verdict(metrics, warnings)
    return {
        "effective_assumptions": effective,
        "metrics": metrics,
        "warnings": warnings,
        "verdict": verdict,
    }


def format_currency(value: float | None) -> str:
    if value is None or math.isnan(value):
        return "—"
    return f"${value:,.0f}"


def format_percent(value: float | None, digits: int = 1) -> str:
    if value is None or math.isnan(value):
        return "—"
    return f"{value:.{digits}f}%"
