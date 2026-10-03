import pytest

from apps.core.constants import LandUnit
from apps.core.units import BighaRuleProvider, UnitConversionService
from apps.farms.models import BighaConversionRule


def test_acre_to_hectares_uses_standard_factor():
    result = UnitConversionService().to_hectares(1.0, LandUnit.ACRE)
    assert result["value_ha"] == pytest.approx(0.40468564224)
    assert result["requires_confirmation"] is False


def test_square_feet_to_hectares_small_area():
    result = UnitConversionService().to_hectares(27000, LandUnit.SQUARE_FOOT)
    assert result["value_ha"] == pytest.approx(0.2508382656)


def test_kaththa_and_cent_convert():
    svc = UnitConversionService()
    assert svc.to_hectares(1, LandUnit.CENT)["value_ha"] == pytest.approx(0.0040468564224)
    assert svc.to_hectares(1, LandUnit.GUNTHA)["value_ha"] == pytest.approx(0.010117141056)


@pytest.mark.django_db
def test_bigha_with_regional_rule(db):
    rule = BighaConversionRule.objects.create(state="Uttar Pradesh", district="", label="UP", sq_meters_per_bigha=2508.0)
    result = UnitConversionService().to_hectares(2.5, LandUnit.BIGHA, rule=rule)
    assert result["value"] == pytest.approx(2.5 * 2508.0)
    assert result["requires_confirmation"] is False
    assert "regional bigha rule" in result["method"]


@pytest.mark.django_db
def test_bigha_from_model_resolver(db):
    rule = BighaConversionRule.objects.create(state="Bihar", district="", label="Bihar", sq_meters_per_bigha=2529.0)
    data = BighaRuleProvider.from_model(rule)
    assert BighaRuleProvider.resolve_factor(data) == pytest.approx(2529.0)


def test_bigha_without_rule_requires_confirmation():
    result = UnitConversionService().to_hectares(5, LandUnit.BIGHA)
    assert result["value_ha"] is None
    assert result["requires_confirmation"] is True


def test_unsupported_unit_raises():
    with pytest.raises(ValueError):
        UnitConversionService().to_hectares(1, "parsec")