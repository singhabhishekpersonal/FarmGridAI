"""Regression tests for equipment operating-cost P0 fixes.

- The estimator previously required a ``diesel_price_range`` tuple as the
  first positional argument and the operating-cost endpoint passed the
  equipment object instead: both the service init and the endpoint call are
  now correct.
- Electric/solar equipment must report zero direct fuel cost.
- The endpoint contract must always carry confirmation/verification flags.
"""

import pytest
from rest_framework.test import APIClient

from apps.equipment.models import EquipmentCategory, FarmerEquipment
from apps.equipment.services import EquipmentOperatingCostEstimator
from apps.farms.models import FarmService


@pytest.fixture
def user(db):
    from django.contrib.auth import get_user_model

    return get_user_model().objects.create_user(username="costram", password="Str0ng!", phone="9876500101")


@pytest.fixture
def farm(user, db):
    return FarmService.create_farm(user, "Cost Farm", area=2, unit="acre", state="Uttar Pradesh")


@pytest.fixture
def tractor_category(db):
    return EquipmentCategory.objects.create(code="tractor", name="Tractor")


def test_electric_equipment_has_zero_fuel_cost(farm, tractor_category):
    item = FarmerEquipment.objects.create(
        farm=farm, category=tractor_category, fuel_type="electric", horsepower=20, purchase_price=400000, is_owned=True
    )
    estimator = EquipmentOperatingCostEstimator()
    fuel = estimator.fuel_cost(item)
    assert (fuel.minimum, fuel.maximum, fuel.expected) == (0, 0, 0)


def test_solar_equipment_has_zero_fuel_cost(farm, tractor_category):
    item = FarmerEquipment.objects.create(
        farm=farm, category=tractor_category, fuel_type="solar", horsepower=20, purchase_price=400000, is_owned=True
    )
    estimator = EquipmentOperatingCostEstimator()
    fuel = estimator.fuel_cost(item)
    assert (fuel.minimum, fuel.maximum, fuel.expected) == (0, 0, 0)


def test_operating_cost_estimate_contract_shape(farm, tractor_category):
    item = FarmerEquipment.objects.create(
        farm=farm,
        category=tractor_category,
        fuel_type="diesel",
        horsepower=35,
        purchase_price=500000,
        usage_hours_per_year=700,
        is_owned=True,
    )
    estimator = EquipmentOperatingCostEstimator()
    result = estimator.operating_cost_estimate(item)
    assert result["equipment_id"] == str(item.id)
    assert result["annual_ownership_cost"]["minimum"] >= 0
    for part in ("fuel", "maintenance", "depreciation", "insurance"):
        assert part in result["breakdown"]
    assert result["cost_per_hour"]["minimum"] >= 0
    assert result["requires_farmer_confirmation"] is True
    assert "Operating-cost figures are benchmark estimates only" in result["warnings"][0]


def test_operating_cost_endpoint_returns_200(user, farm, tractor_category):
    item = FarmerEquipment.objects.create(farm=farm, category=tractor_category, fuel_type="electric", purchase_price=300000, is_owned=True)
    client = APIClient()
    client.force_authenticate(user=user)
    resp = client.post(f"/api/v1/farms/{farm.id}/equipment/{item.id}/operating-cost")
    assert resp.status_code == 200, resp.content
    body = resp.json()
    assert body["success"] is True
    # Electric pump: zero fuel, estimate still complete.
    assert body["data"]["breakdown"]["fuel"]["minimum"] == 0
    assert body["data"]["breakdown"]["fuel"]["maximum"] == 0


def test_operating_cost_endpoint_404_for_other_farmer(user, farm, tractor_category):
    from django.contrib.auth import get_user_model

    other = get_user_model().objects.create_user(username="othercost", password="Str0ng!", phone="9876500102")
    item = FarmerEquipment.objects.create(farm=farm, category=tractor_category, fuel_type="diesel", is_owned=True)
    client = APIClient()
    client.force_authenticate(user=other)
    resp = client.post(f"/api/v1/farms/{farm.id}/equipment/{item.id}/operating-cost")
    assert resp.status_code == 404