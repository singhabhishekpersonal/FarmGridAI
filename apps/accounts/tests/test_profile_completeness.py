"""Regression tests for ProfileCompleteness (fixes the bogus
``FarmerProfile.crops`` reference that crashed and was silently swallowed,
downgrading every recommendation's profile-completeness signal to the
``score=0.0`` fallback)."""
import pytest

from apps.accounts.models import FarmerProfile
from apps.accounts.services import ProfileCompleteness
from apps.crops.models import Crop, FarmCrop
from apps.farms.models import FarmService


@pytest.fixture
def user(db):
    from django.contrib.auth import get_user_model

    return get_user_model().objects.create_user(username="netram", password="Str0ng!", phone="9876500005")


def _profile(user):
    return FarmerProfile.objects.create(user=user, full_name="")


def test_score_runs_without_error_and_counts_crops(user):
    farm = FarmService.create_farm(user, "Crop Farm", area=2, unit="acre", state="Uttar Pradesh", district="Lucknow")
    crop = Crop.objects.create(name="Wheat", slug="wheat", category="rabi")
    FarmCrop.objects.create(farm=farm, crop=crop, area=1.0, year=2026)

    result = ProfileCompleteness.score(_profile(user))

    assert "score" in result and "missing_fields" in result
    assert result["score"] > 0.0


def test_score_zero_when_profile_empty(user):
    result = ProfileCompleteness.score(_profile(user))
    assert "full_name" in result["missing_fields"]
    assert result["score"] <= 0.1


def test_score_weighs_farm_flag_when_farm_exists(user):
    FarmService.create_farm(user, "Empty Farm", area=1, unit="acre", state="Uttar Pradesh", district="Lucknow")
    result = ProfileCompleteness.score(_profile(user))
    assert result["score"] >= 0.10