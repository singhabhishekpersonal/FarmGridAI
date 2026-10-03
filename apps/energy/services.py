"""Solar versus grid/diesel 10-year financial calculators.

All functions are deterministic and explainable: they return ranges with
assumptions and limitations. Results must never be presented as guarantees.
"""
from dataclasses import dataclass, field
from typing import List, Optional

DISCOUNT_RATE = 0.10
DEFAULT_GRID_ESCALATION = 0.05
DEFAULT_DIESEL_ESCALATION = 0.04
DEFAULT_PUMP_DEGRADATION = 0.005
SYSTEM_LIFETIME = 10


@dataclass
class EnergyScenario:
    label: str
    tariff_kwh: float
    diesel_price: float
    grid_escalation: float
    diesel_escalation: float


DEFAULT_SCENARIOS = [
    EnergyScenario(label="best", tariff_kwh=6.0, diesel_price=84.0, grid_escalation=0.02, diesel_escalation=0.02),
    EnergyScenario(label="expected", tariff_kwh=8.5, diesel_price=92.0, grid_escalation=0.05, diesel_escalation=0.05),
    EnergyScenario(label="worst", tariff_kwh=12.0, diesel_price=105.0, grid_escalation=0.09, diesel_escalation=0.09),
]


def _project(value, escalation, years, degradation=0.0, year_one_factor=1.0):
    """Yearly series of a recurring cost with annual escalation + degradation.

    ``year_one_factor`` scales the first year (e.g. partial first-year usage);
    ``degradation`` reduces production (so the effective recurring cost grows
    slower than raw escalation). Values are floored at zero.
    """
    series = []
    current = float(value) * max(0.0, float(year_one_factor))
    for _ in range(years):
        series.append(current)
        current = current * (1 + escalation) * max(0.0, 1 - degradation)
        current = max(0.0, current)
    return [round(v, 2) for v in series]


def calculate_grid_cost_projection(annual_kwh, tariff, years=SYSTEM_LIFETIME, escalation=DEFAULT_GRID_ESCALATION):
    if annual_kwh <= 0 or tariff <= 0:
        return {"years": [], "annual": [0] * years, "cumulative": [0] * years, "assumptions": ["No grid usage."]}
    annual = _project(annual_kwh * tariff, escalation, years)
    cum = []
    total = 0
    for a in annual:
        total += a
        cum.append(total)
    return {
        "years": list(range(1, years + 1)),
        "annual": [round(x, 2) for x in annual],
        "cumulative": [round(x, 2) for x in cum],
        "assumptions": [
            f"Grid consumption assumed {annual_kwh:.0f} kWh/year",
            f"Tariff Rs {tariff}/kWh escalating {escalation*100:.0f}%/year",
        ],
    }


def calculate_diesel_cost_projection(litres_per_year, diesel_price, years=SYSTEM_LIFETIME, escalation=DEFAULT_DIESEL_ESCALATION):
    if litres_per_year <= 0 or diesel_price <= 0:
        return {"years": [], "annual": [0] * years, "cumulative": [0] * years, "assumptions": ["No diesel usage."]}
    annual = _project(litres_per_year * diesel_price, escalation, years)
    cum = []
    total = 0
    for a in annual:
        total += a
        cum.append(total)
    return {
        "years": list(range(1, years + 1)),
        "annual": [round(x, 2) for x in annual],
        "cumulative": [round(x, 2) for x in cum],
        "assumptions": [
            f"Diesel consumption assumed {litres_per_year:.0f} L/year",
            f"Diesel price Rs {diesel_price}/L escalating {escalation*100:.0f}%/year",
        ],
    }


def calculate_solar_cost_projection(
    upfront_cost,
    annual_maintenance=5000,
    years=SYSTEM_LIFETIME,
    degradation=DEFAULT_PUMP_DEGRADATION,
):
    """Solar running cost series: maintenance from year 2 onward + upfront."""
    annual = [annual_maintenance if i > 1 else 0 for i in range(1, years + 1)]
    cum = []
    total = upfront_cost
    for a in annual:
        total += a
        cum.append(total)
    return {
        "years": list(range(1, years + 1)),
        "upfront": round(upfront_cost, 2),
        "annual": [round(x, 2) for x in annual],
        "cumulative": [round(x, 2) for x in cum],
        "assumptions": [
            f"Upfront cost (after subsidy) Rs {upfront_cost:,.0f}",
            f"Annual maintenance Rs {annual_maintenance:,.0f} from year 2",
            f"System degradation factor {degradation*100:.1f}%/year",
        ],
    }


def calculate_break_even_year(grid_projection, solar_projection, diesel_projection=None):
    best_reference = grid_projection["cumulative"]
    if diesel_projection and diesel_projection["cumulative"]:
        best_reference = [min(g, d) for g, d in zip(grid_projection["cumulative"], diesel_projection["cumulative"])]
    for i, (ref, sol) in enumerate(zip(best_reference, solar_projection["cumulative"])):
        if sol <= ref:
            return i + 1
    return None


def calculate_npv(cash_flows, discount_rate=DISCOUNT_RATE):
    return sum(cf / ((1 + discount_rate) ** (i + 1)) for i, cf in enumerate(cash_flows))


def calculate_payback_period(upfront_cost, annual_savings_series, years=SYSTEM_LIFETIME, discount_rate=DISCOUNT_RATE):
    cum = 0.0
    for i, saving in enumerate(annual_savings_series, start=1):
        cum += saving / ((1 + discount_rate) ** i)
        if cum >= upfront_cost:
            exact = i - (cum - upfront_cost) / max(1e-9, saving / ((1 + discount_rate) ** i))
            return round(exact, 2)
    return None


def compare_energy_options(inputs: dict, scenarios: Optional[List[EnergyScenario]] = None):
    """Compare grid vs diesel vs solar under best/expected/worst scenarios.

    ``inputs`` expected keys: annual_kwh, tariff_kwh, litres_per_year,
    diesel_price, system_kw, system_cost_inr, subsidy_inr, upfront_install_inr,
    annual_maintenance_inr, grid_escalation, diesel_escalation,
    solar_degradation.

    NPV is computed as ``-upfront + PV(annual savings)`` where annual savings
    are the avoided reference (grid/diesel) cost minus solar running cost.
    References only include options the farmer actually uses, so a zero-usage
    input can never produce a phantom breakeven.
    """
    scenarios = scenarios or DEFAULT_SCENARIOS
    annual_kwh = float(inputs.get("annual_kwh", 0))
    litres = float(inputs.get("litres_per_year", 0))
    system_cost = float(inputs.get("system_cost_inr", 0))
    subsidy = float(inputs.get("subsidy_inr", 0))
    install = float(inputs.get("upfront_install_inr", 0))
    maint = float(inputs.get("annual_maintenance_inr", 5000))
    upfront = system_cost + install - subsidy
    degradation = float(inputs.get("solar_degradation", DEFAULT_PUMP_DEGRADATION))

    has_grid = annual_kwh > 0
    has_diesel = litres > 0

    per_scenario = []
    for s in scenarios:
        grid = calculate_grid_cost_projection(annual_kwh, s.tariff_kwh, escalation=s.grid_escalation)
        diesel = calculate_diesel_cost_projection(litres, s.diesel_price, escalation=s.diesel_escalation)
        solar = calculate_solar_cost_projection(upfront, maint, degradation=degradation)

        if has_grid and has_diesel:
            ref_annual = [min(g, d) for g, d in zip(grid["annual"], diesel["annual"])]
            ref_cum = [min(gc, dc) for gc, dc in zip(grid["cumulative"], diesel["cumulative"])]
        elif has_diesel:
            ref_annual, ref_cum = diesel["annual"], diesel["cumulative"]
        elif has_grid:
            ref_annual, ref_cum = grid["annual"], grid["cumulative"]
        else:
            ref_annual, ref_cum = [0] * len(solar["annual"]), [0] * len(solar["cumulative"])

        savings_annual = [ref - so for ref, so in zip(ref_annual, solar["annual"])]
        npv = -upfront + calculate_npv(savings_annual)
        payback = calculate_payback_period(upfront, savings_annual)
        break_even = calculate_break_even_year(
            {"cumulative": ref_cum}, solar, diesel_projection=None
        )
        per_scenario.append(
            {
                "scenario": s.label,
                "grid_cumulative_10y": grid["cumulative"][-1],
                "diesel_cumulative_10y": diesel["cumulative"][-1],
                "solar_cumulative_10y": solar["cumulative"][-1],
                "solar_upfront": upfront,
                "break_even_year": break_even,
                "npv_inr": round(npv, 2),
                "payback_years": payback,
            }
        )

    expected = next((p for p in per_scenario if p["scenario"] == "expected"), per_scenario[0])
    return {
        "upfront_cost_inr": round(upfront, 2),
        "break_even_year": expected["break_even_year"],
        "payback_years": expected["payback_years"],
        "npv_inr": expected["npv_inr"],
        "scenarios": per_scenario,
        "estimate_type": "range",
        "confidence": "medium",
        "assumptions": [
            "Diesel replacement assumes equivalent irrigation energy output.",
            "Subsidy is a preliminary input and must be officially verified.",
            "Electricity and diesel prices escalate at assumed rates.",
        ],
        "limitations": [
            "Actual pump efficiency, water table depth and tariff slabs change results.",
            "Solar system output degrades over time and varies with weather.",
            "Grid subsidy schemes (e.g. PM-KUSUM) vary by state and year.",
        ],
        "requires_farmer_confirmation": True,
        "requires_official_verification": True,
    }


def generate_solar_recommendation(comparison: dict, inputs: dict):
    """Rule-based recommendation from the comparison result."""
    break_even = comparison.get("break_even_year")
    upfront = comparison.get("upfront_cost_inr", 0)
    annual_kwh = float(inputs.get("annual_kwh", 0))
    litres = float(inputs.get("litres_per_year", 0))

    if annual_kwh <= 0 and litres <= 0:
        return {
            "recommendation": "gather_more_information",
            "reason": "No meaningful irrigation energy consumption entered.",
            "solar_recommended": False,
        }
    if break_even is None:
        return {
            "recommendation": "not_recommended_yet",
            "reason": "Solar cumulative cost exceeds grid/diesel within the 10-year horizon.",
            "solar_recommended": False,
            "break_even_year": None,
        }
    if break_even <= 6:
        solar_recommended = True
        strength = "high"
    elif break_even <= 9:
        solar_recommended = True
        strength = "medium"
    else:
        solar_recommended = break_even is not None
        strength = "low"

    return {
        "recommendation": "adopt_solar" if solar_recommended else "compare_carefully",
        "recommendation_strength": strength,
        "solar_recommended": solar_recommended,
        "reason": (
            f"Under the expected scenario the system breaks even in year {break_even} "
            f"with an upfront cost of Rs {upfront:,.0f}."
        ),
        "break_even_year": break_even,
        "next_steps": [
            "Verify current subsidy availability with the state renewable energy department.",
            "Confirm pump replacement cost with 2-3 local vendors.",
            "Keep the battery/backup needs explicit before finalizing system capacity.",
        ],
        "confidence": "medium",
        "requires_official_verification": True,
    }


class EnergyAnalysisService:
    """Build an energy comparison from stored farm data (pump + solar config)."""

    def __init__(self, farm):
        self.farm = farm

    def resolve_inputs(self):
        pump = self.farm.pump_profiles.order_by("-created_at").first()
        config = self.farm.solar_configurations.order_by("-created_at").first()
        inputs = {
            "annual_kwh": 0.0,
            "litres_per_year": 0.0,
            "system_cost_inr": 0.0,
            "subsidy_inr": 0.0,
            "upfront_install_inr": 0.0,
            "annual_maintenance_inr": 5000.0,
            "tariff_kwh": 8.5,
            "diesel_price": 92.0,
        }
        if pump:
            kw = float(pump.power_kw) if pump.power_kw else (float(pump.horsepower or 0) * 0.746)
            hours_day = float(pump.operating_hours_per_day or 6)
            days = int(pump.irrigation_days_per_year or 120)
            inputs["annual_kwh"] = round(kw * hours_day * days, 2)
            # Diesel pump alternative: ~1 L/hr per 10 HP effective load
            if pump.pump_type == "diesel":
                inputs["litres_per_year"] = round((float(pump.horsepower or 10) * 0.9) * hours_day * days * 0.1, 2)
        if config:
            inputs["system_cost_inr"] = float(config.system_kw) * 75000 if config.pump_cost_inr is None else float(config.pump_cost_inr)
            inputs["subsidy_inr"] = float(config.estimated_subsidy_inr or 0)
            inputs["upfront_install_inr"] = float(config.installation_cost_inr or 0)
            if config.annual_maintenance_inr:
                inputs["annual_maintenance_inr"] = float(config.annual_maintenance_inr)
        else:
            inputs["system_cost_inr"] = 50000  # conservative default kW pricing placeholder
        return inputs

    def run_analysis(self, persist=True):
        inputs = self.resolve_inputs()
        comparison = compare_energy_options(inputs)
        recommendation = generate_solar_recommendation(comparison, inputs)
        result = {"input_summary": inputs, "comparison": comparison, "recommendation": recommendation}
        if persist:
            config = self.farm.solar_configurations.order_by("-created_at").first()
            from apps.energy.models import SolarAnalysis, SolarProjectionYear

            analysis = SolarAnalysis.objects.create(
                farm=self.farm,
                configuration=config,
                scenario="expected",
                break_even_year=comparison.get("break_even_year"),
                payback_years=comparison.get("payback_years"),
                npv_inr=comparison.get("npv_inr"),
                calculations_json=comparison,
                confidence="medium",
                needs_confirmation=True,
                assumptions_json=comparison["assumptions"],
                limitations_json=comparison["limitations"],
            )
            result["analysis_id"] = str(analysis.id)
            best = next((p for p in comparison["scenarios"] if p["scenario"] == "expected"), comparison["scenarios"][0])
            for years_data in _build_projection_rows(inputs, comparison):
                SolarProjectionYear.objects.create(analysis=analysis, **years_data)
        return result


def _build_projection_rows(inputs, comparison):
    annual_kwh = float(inputs.get("annual_kwh", 0))
    litres = float(inputs.get("litres_per_year", 0))
    grid = calculate_grid_cost_projection(annual_kwh, float(inputs.get("tariff_kwh", 8.5)))
    diesel = calculate_diesel_cost_projection(litres, float(inputs.get("diesel_price", 92)))
    upfront = comparison.get("upfront_cost_inr", 0)
    solar = calculate_solar_cost_projection(upfront, float(inputs.get("annual_maintenance_inr", 5000)))
    rows = []
    break_even = comparison.get("break_even_year")
    for i, year in enumerate(grid["years"]):
        grid_cost = grid["annual"][i]
        diesel_cost = diesel["annual"][i]
        solar_cum = solar["cumulative"][i]
        ref_cum = min(grid["cumulative"][i], diesel["cumulative"][i])
        rows.append(
            {
                "year_index": year,
                "year_label": f"Y{year}",
                "grid_cost": round(grid_cost, 2),
                "diesel_cost": round(diesel_cost, 2),
                "solar_cumulative": round(solar_cum, 2),
                "solar_maintenance": round(solar["annual"][i], 2),
                "cumulative_savings": round(ref_cum - solar_cum, 2),
                "is_break_even": break_even is not None and year >= break_even,
            }
        )
    return rows