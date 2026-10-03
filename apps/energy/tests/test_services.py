"""Regression tests for the energy comparison service fixes.

The audit found the 10-year NPV and breakeven previously compared solar only
against the grid and produced phantom breakevens when the farmer used zero
grid/diesel energy. These tests lock in:
- references only include options actually used (no phantom breakeven);
- NPV = -upfront + PV(annual savings);
- the summary always reflects the "expected" scenario;
- a zero-usage farm gets a "gather more information" recommendation.
"""

from apps.energy.services import (
    _project,
    compare_energy_options,
    generate_solar_recommendation,
)


def _default_inputs(**overrides):
    inputs = {
        "annual_kwh": 0.0,
        "rapayee_kwh": 0.0,
        "litres_per_year": 0.0,
        "system_cost_inr": 0.0,
        "subsidy_inr": 0.0,
        "upfront_install_inr": 0.0,
        "annual_maintenance_inr": 5000.0,
    }
    inputs.update(overrides)
    return inputs


def test_project_applies_year_one_factor_and_degradation():
    series = _project(100, 0.10, 3, degradation=0.50, year_one_factor=0.5)
    assert series == [50.0, 27.5, 15.13]


def test_zero_usage_produces_no_phantom_breakeven():
    comparison = compare_energy_options(
        _default_inputs(system_cost_inr=400000, upfront_install_inr=20000)
    )
    assert comparison["break_even_year"] is None
    assert comparison["npv_inr"] < 0
    recommendation = generate_solar_recommendation(comparison, _default_inputs())
    assert recommendation["solar_recommended"] is False
    assert recommendation["recommendation"] == "gather_more_information"


def test_diesel_only_uses_diesel_reference_not_grid():
    comparison = compare_energy_options(
        _default_inputs(litres_per_year=4000, diesel_price=92.0, system_cost_inr=300000)
    )
    for scenario in comparison["scenarios"]:
        assert scenario["grid_cumulative_10y"] == 0
        assert scenario["diesel_cumulative_10y"] > 0
    expected = next(p for p in comparison["scenarios"] if p["scenario"] == "expected")
    assert comparison["npv_inr"] == expected["npv_inr"]
    assert comparison["break_even_year"] == expected["break_even_year"]
    if comparison["break_even_year"] is not None:
        assert comparison["break_even_year"] >= 1


def test_expected_scenario_drives_the_summary():
    inputs = _default_inputs(
        annual_kwh=6000,
        tariff_kwh=8.5,
        litres_per_year=1000,
        diesel_price=92.0,
        system_cost_inr=400000,
        subsidy_inr=100000,
        upfront_install_inr=20000,
    )
    comparison = compare_energy_options(inputs)
    expected = next(p for p in comparison["scenarios"] if p["scenario"] == "expected")
    assert comparison["npv_inr"] == expected["npv_inr"]
    assert comparison["break_even_year"] == expected["break_even_year"]
    assert comparison["payback_years"] == expected["payback_years"]
    assert comparison["requires_farmer_confirmation"] is True
    assert comparison["requires_official_verification"] is True


def test_basic_diesel_scenario_solar_saves_money_within_ten_years():
    inputs = _default_inputs(
        litres_per_year=4000,
        diesel_price=92.0,
        system_cost_inr=300000,
        subsidy_inr=0,
        upfront_install_inr=0,
    )
    comparison = compare_energy_options(inputs)
    expected = next(p for p in comparison["scenarios"] if p["scenario"] == "expected")
    assert expected["solar_cumulative_10y"] < expected["diesel_cumulative_10y"]
    assert comparison["break_even_year"] is not None