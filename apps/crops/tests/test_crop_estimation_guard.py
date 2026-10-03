"""Regression tests for the crop-estimation error-dict guard.

``estimate_farm_crops`` previously crashed with a KeyError whenever one
``estimate_farm_crop`` call returned an error dict (zero-area crop): it
unconditionally read ``result["total"]``. The guard now skips such results
instead of crashing, while still returning the healthy rows.
"""

import pytest

from apps.crops.models import Crop, CropCostBenchmark, FarmCrop
from apps.crops.services import estimate_farm_crops
from apps.farms.models import FarmService


@pytest.fixture
def user(db):
    from django.contrib.auth import get_user_model

    return get_user_model().objects.create_user(username="cropper", password="Str0ng!", phone="9876500501")


@pytest.fixture
def farm(user, db):
    return FarmService.create_farm(user, "Crop Farm", area=3, unit="acre", state="Uttar Pradesh")


def test_zero_area_crop_does_not_crash_aggregate(farm):
    crop = Crop.objects.create(name="Wheat", slug="wheat")
    FarmCrop.objects.create(farm=farm, crop=crop, season="kharif", year=2025, area=0)

    result = estimate_farm_crops(farm.id)
    assert result["totals"] == {"minimum": 0, "maximum": 0, "expected": 0}
    assert result["crop_estimates"] == [{"error": "Area must be positive."}]


def test_healthy_crops_still_aggregate(farm):
    crop = Crop.objects.create(name="Rice", slug="rice")
    FarmCrop.objects.create(farm=farm, crop=crop, season="kharif", year=2025, area=2)
    CropCostBenchmark.objects.create(
        crop=crop,
        input_type="seed",
        unit="per_acre",
        min_cost=2000,
        max_cost=2600,
        expected_cost=2300,
        is_verified=True,
    )

    result = estimate_farm_crops(farm.id)
    assert result["totals"]["expected"] > 0
    assert len(result["crop_estimates"]) == 1
    assert "total" in result["crop_estimates"][0]