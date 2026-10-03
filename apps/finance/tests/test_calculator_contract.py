"""Contract tests for the four finance calculators and their markup.

All four calculators on /farms/<id>/finance/ were dead: the JavaScript looked up
``#form-<kind>`` and ``[data-ks-out-<kind>]``, and neither existed in the
template, so every click returned early. The endpoint map was also keyed on
names (``buy-rent``) that the template's ``data-ks-calc`` values (``buy-vs-rent``)
never produced, so three of the four would have posted to a ``undefined`` path.

These tests pin both ends:
- the page markup carries the hooks the controller looks for;
- each endpoint accepts exactly the field names the form sends, and returns the
  keys the renderer reads.
"""
import pytest
from django.test import Client
from rest_framework.test import APIClient

from apps.farms.models import FarmService


@pytest.fixture
def user(db):
    from django.contrib.auth import get_user_model

    return get_user_model().objects.create_user(username="calcuser", password="Str0ng!", phone="9876500301")


@pytest.fixture
def farm(user):
    return FarmService.create_farm(user, "Calc Farm", area=3, unit="acre", state="Uttar Pradesh")


@pytest.fixture
def client(user):
    api = APIClient()
    api.force_authenticate(user=user)
    return api


# The exact payloads templates/finance/machinery_decision.html submits.
CALC_PAYLOADS = {
    "buy-vs-rent": (
        {
            "purchase_price_inr": 500000,
            "usage_hours_per_year": 600,
            "rental_rate_per_hour_inr": 400,
            "subsidy_inr": 100000,
            "loan_years": 5,
            "interest_rate_pct": 12,
        },
        ["suggested_option", "buy", "rent_annual", "net_purchase_price", "utilization_score", "data_confidence"],
    ),
    "repair-vs-replace": (
        {
            "estimated_repair_cost_inr": 20000,
            "replacement_price_inr": 500000,
            "residual_value_inr": 150000,
            "annual_usage_hours": 700,
            "repair_frequency_per_year": 1,
        },
        ["suggested_option", "expected_annual_repair", "replacement_annual_cost_equivalent", "remaining_life_years_estimate", "financial_risk_level"],
    ),
    "affordability": (
        {
            "annual_income_inr": 200000,
            "proposed_emi_inr": 8000,
            "existing_emi_total_inr": 2000,
            "safe_burden_pct": 25,
        },
        ["income_burden_pct", "safe_burden_pct", "affordable", "financial_risk_level", "data_confidence"],
    ),
    "machinery-decision": (
        {
            "usage_hours_per_year": 800,
            "purchase_price": 500000,
            "annual_repair_spend": 10000,
            "residual_value": 200000,
            "annual_income": 200000,
            "proposed_emi": 8000,
            "existing_emi": 0,
            "subsidy": 0,
            "rental_available": True,
        },
        ["suggested_option", "financial_risk_level", "alternatives", "key_calculations"],
    ),
}

# The controller's CALCS map: data-ks-calc-form value -> (form id, out mount).
CALC_HOOKS = {
    "buy-vs-rent": ("form-buy-rent", "buy-rent"),
    "repair-vs-replace": ("form-repair-replace", "repair-replace"),
    "affordability": ("form-affordability", "affordability"),
    "machinery-decision": ("form-machinery", "machinery"),
}


@pytest.mark.parametrize("calc", sorted(CALC_PAYLOADS))
def test_calculator_endpoint_accepts_form_payload(client, farm, calc):
    payload, expected_keys = CALC_PAYLOADS[calc]
    resp = client.post(f"/api/v1/farms/{farm.id}/finance/{calc}", payload, format="json")
    assert resp.status_code == 200, (calc, resp.content)
    data = resp.json()["data"]
    for key in expected_keys:
        assert key in data, (calc, key, sorted(data.keys()))


def test_machinery_decision_unchecked_rental_still_accepted(client, farm):
    """forms.read sends rental_available=false for an unticked box; the view
    must read that as false rather than falling back to its True default."""
    payload = dict(CALC_PAYLOADS["machinery-decision"][0], rental_available=False)
    resp = client.post(f"/api/v1/farms/{farm.id}/finance/machinery-decision", payload, format="json")
    assert resp.status_code == 200, resp.content
    assert resp.json()["data"]["suggested_option"]


def test_finance_page_carries_every_calculator_hook(user, farm):
    """The dead-UI regression: without these hooks the controller early-returns."""
    page = Client()
    page.force_login(user)
    resp = page.get(f"/farms/{farm.id}/finance/")
    assert resp.status_code == 200
    html = resp.content.decode()
    for calc, (form_id, out_key) in CALC_HOOKS.items():
        assert f'data-ks-calc-form="{calc}"' in html, calc
        assert f'id="{form_id}"' in html, form_id
        assert f"data-ks-out-{out_key}" in html, out_key
    assert "data-ks-income-profile" in html
