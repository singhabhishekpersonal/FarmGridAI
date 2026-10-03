"""Contract tests for the profile read endpoints.

The audit found pump-profile, solar-configuration and income-profile were
POST-only, so the frontend could never tell an empty profile from a saved one
and the analytics silently fell back to zeroed defaults. These tests lock in
that GET is available, returns the same row the analytics read, and reports an
empty profile as ``{}`` rather than inventing data.
"""
import pytest
from rest_framework.test import APIClient

from apps.farms.models import FarmService


@pytest.fixture
def user(db):
    from django.contrib.auth import get_user_model

    return get_user_model().objects.create_user(username="readram", password="Str0ng!", phone="9876500201")


@pytest.fixture
def farm(user):
    return FarmService.create_farm(user, "Read Farm", area=2, unit="acre", state="Uttar Pradesh")


@pytest.fixture
def client(user):
    api = APIClient()
    api.force_authenticate(user=user)
    return api


def test_pump_profile_get_empty_then_saved(client, farm):
    url = f"/api/v1/farms/{farm.id}/pump-profile"
    empty = client.get(url)
    assert empty.status_code == 200, empty.content
    assert empty.json()["data"] == {}

    saved = client.post(url, {"pump_type": "diesel", "horsepower": "10.0", "irrigation_days_per_year": 120})
    assert saved.status_code == 201, saved.content

    got = client.get(url)
    assert got.status_code == 200
    assert got.json()["data"]["pump_type"] == "diesel"


def test_solar_configuration_get_empty_then_saved(client, farm):
    url = f"/api/v1/farms/{farm.id}/solar-configuration"
    assert client.get(url).json()["data"] == {}

    saved = client.post(url, {"system_kw": "5.0", "pump_cost_inr": 200000, "installation_cost_inr": 50000})
    assert saved.status_code == 201, saved.content

    got = client.get(url).json()["data"]
    assert float(got["system_kw"]) == 5.0
    assert got["total_upfront"] == 250000


def test_income_profile_get_empty_then_saved(client, farm):
    url = f"/api/v1/farms/{farm.id}/income-profile"
    assert client.get(url).json()["data"] == {}

    saved = client.post(url, {"year": 2025, "crop_income": 100000, "off_farm_income": 50000})
    assert saved.status_code == 201, saved.content

    got = client.get(url).json()["data"]
    assert got["year"] == 2025
    assert got["total_income"] == 150000


def test_profile_get_is_scoped_to_owner(user, farm):
    from django.contrib.auth import get_user_model

    other = get_user_model().objects.create_user(username="readother", password="Str0ng!", phone="9876500202")
    api = APIClient()
    api.force_authenticate(user=other)
    for suffix in ("pump-profile", "solar-configuration", "income-profile"):
        resp = api.get(f"/api/v1/farms/{farm.id}/{suffix}")
        assert resp.status_code == 404, (suffix, resp.content)
