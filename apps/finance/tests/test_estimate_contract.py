"""Regression tests for the finance estimate contract.

Every decision endpoint must carry explicit assumptions, limitations,
warnings, data confidence and honest verification flags. This locks in
the audit fix that added ``limitations`` and ``requires_official_verification``
(especially when a subsidy input is involved).
"""
from apps.finance.services import (
    calculate_buy_vs_rent,
    calculate_machine_affordability,
    calculate_repair_vs_replace,
    generate_machinery_recommendation,
)

REQUIRED_KEYS = {"assumptions", "warnings", "limitations", "data_confidence", "requires_farmer_confirmation", "requires_official_verification"}


def test_buy_vs_rent_carries_full_contract():
    result = calculate_buy_vs_rent(500000, 600, 400, subsidy=100000)
    assert REQUIRED_KEYS <= result.keys()
    assert isinstance(result["limitations"], list) and result["limitations"]


def test_buy_vs_rent_requires_official_verification_when_subsidised():
    with_subsidy = calculate_buy_vs_rent(500000, 600, 400, subsidy=100000)
    without_subsidy = calculate_buy_vs_rent(500000, 600, 400, subsidy=0)
    assert with_subsidy["requires_official_verification"] is True
    assert without_subsidy["requires_official_verification"] is False


def test_repair_vs_replace_carries_full_contract():
    result = calculate_repair_vs_replace(20000, 500000, 150000, 800)
    assert REQUIRED_KEYS <= result.keys()
    assert result["requires_official_verification"] is True


def test_affordability_carries_full_contract():
    result = calculate_machine_affordability(200000, 8000, existing_emi_total=2000)
    assert REQUIRED_KEYS <= result.keys()
    assert result["requires_official_verification"] is True


def test_machinery_recommendation_flag_with_and_without_subsidy():
    with_subsidy = generate_machinery_recommendation(800, True, 10000, 200000, 500000, 200000, 8000, subsidy=150000)
    without_subsidy = generate_machinery_recommendation(800, True, 10000, 200000, 500000, 200000, 8000, subsidy=0)
    assert with_subsidy["requires_official_verification"] is True
    assert without_subsidy["requires_official_verification"] is False


def test_machinery_recommendation_handles_missing_usage_safely():
    result = generate_machinery_recommendation(None, True, 0, 0, None, 200000, 8000)
    assert result["suggested_option"] == "gather_more_information"
    assert result["requires_official_verification"] is True


def test_machinery_recommendation_normal_path_carries_contract():
    result = generate_machinery_recommendation(800, True, 10000, 200000, 500000, 200000, 8000)
    assert REQUIRED_KEYS <= result.keys()
    assert isinstance(result["limitations"], list) and result["limitations"]