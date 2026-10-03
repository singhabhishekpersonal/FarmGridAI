import pytest

from apps.farms.models import Farm, FarmService


@pytest.fixture
def user(db):
    from django.contrib.auth import get_user_model

    return get_user_model().objects.create_user(username="ram", password="Str0ng!", phone="9876543210")


def test_create_farm_sets_default_for_first_farm(user):
    farm = FarmService.create_farm(user, "My Farm", area=2.5, unit="acre", state="Uttar Pradesh")
    assert farm.is_default is True
    assert float(farm.total_hectares) > 0
    assert farm.location.state == "Uttar Pradesh"
    assert farm.land_parcels.count() == 1
    assert farm.land_parcels.first().area_requires_confirmation is False


def test_second_farm_not_default_until_requested(user):
    first = FarmService.create_farm(user, "Farm A", area=1, unit="acre")
    second = FarmService.create_farm(user, "Farm B", area=2, unit="acre")
    assert first.is_default is True
    assert second.is_default is False
    assert sum(f.is_default for f in user.farms.filter(deleted_at__isnull=True)) == 1


def test_total_hectares_sums_parcels(user):
    farm = FarmService.create_farm(user, "Combined", area=1, unit="acre")
    FarmService.add_parcel(farm, name="Second", area=1, unit="acre")
    assert float(farm.total_hectares) == pytest.approx(0.8094, abs=1e-3)


def test_land_parcel_bigha_conversion_uses_rule(user, db):
    from apps.farms.models import BighaConversionRule

    BighaConversionRule.objects.create(state="Uttar Pradesh", district="", label="UP", sq_meters_per_bigha=2508.0)
    farm = FarmService.create_farm(user, "UP Farm", area=1, unit="bigha", state="Uttar Pradesh")
    parcel = farm.land_parcels.first()
    assert float(parcel.area_hectares) == pytest.approx(0.2508, rel=1e-3)
    assert parcel.area_requires_confirmation is False