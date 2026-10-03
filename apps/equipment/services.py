"""Equipment operating-cost estimation service.

Benchmark and rule-first approach; ML adjustments (if any) are applied within
controlled bounds and recorded separately.
"""
from apps.core.estimates import EstimateRange
from apps.equipment.models import EquipmentCategory, FarmerEquipment

# Conservative per-kW fuel consumption benchmarks (L/hr per 1 HP) by class.
FUEL_PER_HP = {
    "tractor": 0.055,
    "power_tiller": 0.080,
    "water_pump": 0.130,
    "diesel_pump": 0.130,
    "solar_pump": 0.0,
    "rotavator": 0.0,  # implement-driven, no separate engine
    "cultivator": 0.0,
    "plough": 0.0,
    "seed_drill": 0.0,
    "sprayer": 0.090,
    "thresher": 0.070,
    "harvester": 0.060,
    "combine_harvester": 0.070,
    "trailer": 0.0,
}
# If category fuel consumption not available fall back to tractor-like estimate.
DEFAULT_FUEL_PER_HP = 0.055

# Annual maintenance as a fraction of purchase price, by age band.
MAINTENANCE_PCT_BY_AGE = {
    (0, 3): (0.02, 0.05),
    (3, 7): (0.03, 0.07),
    (7, 12): (0.05, 0.10),
    (12, None): (0.06, 0.12),
}

DIESEL_PRICE_RANGE = (88.0, 96.0)

DEPRECIATION_RATE = {"min": 7.0, "max": 12.0}  # straight-line % per year
INSURANCE_PCT = (1.5, 2.5)
INTEREST_RATE_PCT = (10.0, 14.0)

STANDARD_ANNUAL_HOURS = (600, 1000)


class EquipmentOperatingCostEstimator:
    """Produce explainable cost ranges for owning/running a farmer equipment."""

    def __init__(self, diesel_price_range=DIESEL_PRICE_RANGE):
        self.diesel_min, self.diesel_max = diesel_price_range

    # ------------------------------------------------------------------
    def _age_band(self, equipment):
        age = equipment.age_years
        if age is None:
            return (0, None)
        for lo, hi in [(0, 3), (3, 7), (7, 12), (12, None)]:
            if hi is None or age <= hi:
                return (lo, hi)
        return (12, None)

    def effective_hp(self, equipment):
        if equipment.horsepower:
            return float(equipment.horsepower)
        catalog = equipment.catalog
        if catalog and catalog.hp:
            return float(catalog.hp) * 0.9  # catalog HP includes a small constant
        category = equipment.category
        if category.typical_hp_min and category.typical_hp_max:
            return (float(category.typical_hp_min) + float(category.typical_hp_max)) / 2
        return 35.0

    def fuel_cost(self, equipment, hours=None):
        if equipment.fuel_type in ("electric", "solar"):
            return EstimateRange(
                minimum=0,
                maximum=0,
                expected=0,
                confidence="high",
                assumptions=[f"{equipment.fuel_type.title()} equipment has no direct fuel cost."],
                limitations=["Indirect electricity charges are captured separately."],
            )
        hp = self.effective_hp(equipment)
        hours = hours or equipment.usage_hours_per_year
        if not hours:
            hours = sum(STANDARD_ANNUAL_HOURS) / 2
        per_hp = FUEL_PER_HP.get(equipment.category.code, DEFAULT_FUEL_PER_HP)
        low_l = hp * per_hp * hours * 0.8
        high_l = hp * per_hp * hours * 1.2
        return EstimateRange(
            minimum=round(low_l * self.diesel_min),
            maximum=round(high_l * self.diesel_max),
            expected=round(((low_l + high_l) / 2) * ((self.diesel_min + self.diesel_max) / 2)),
            confidence="medium",
            assumptions=[f"Fuel benchmark {per_hp:.3f} L/hr per HP for {equipment.category.code}", f"Diesel price assumed Rs {self.diesel_min}-{self.diesel_max}/L"],
            limitations=["Actual mileage varies with load, age and field conditions; estimate only."],
        )

    def maintenance_and_repair(self, equipment, purchase_price=None):
        price = purchase_price or equipment.purchase_price
        if not price:
            # Fall back to category price midpoint
            cat = equipment.category
            if cat.price_range_min and cat.price_range_max:
                price = (cat.price_range_min + cat.price_range_max) // 2
            else:
                price = 500000
        lo, hi = None, None
        for band, (p_lo, p_hi) in MAINTENANCE_PCT_BY_AGE.items():
            age_lo, age_hi = band
            age = equipment.age_years
            if age_hi is None or (age is not None and age_lo <= age <= age_hi) or (age is None and age_lo == 0):
                lo, hi = p_lo, p_hi
                break
        if lo is None:
            lo, hi = 0.05, 0.10
        return EstimateRange(
            minimum=round(price * lo),
            maximum=round(price * hi),
            expected=round(price * (lo + hi) / 2),
            confidence="medium",
            assumptions=[f"Maintenance {lo*100:.0f}-{hi*100:.0f}% of purchase price per year", f"Reference price Rs {price}"],
            limitations=["Repair history, if provided, overrides this benchmark estimate."],
        )

    def annual_depreciation(self, purchase_price=None):
        price = purchase_price or 0
        return EstimateRange(
            minimum=round(price * DEPRECIATION_RATE["min"] / 100),
            maximum=round(price * DEPRECIATION_RATE["max"] / 100),
            expected=round(price * (DEPRECIATION_RATE["min"] + DEPRECIATION_RATE["max"]) / 200),
            confidence="medium",
            assumptions=[f"Straight-line depreciation {DEPRECIATION_RATE['min']}-{DEPRECIATION_RATE['max']}% per year"],
            limitations=["Depreciation varies by brand, market and maintenance."],
        )

    def annual_insurance(self, purchase_price=None):
        price = purchase_price or 0
        return EstimateRange(
            minimum=round(price * INSURANCE_PCT[0] / 100),
            maximum=round(price * INSURANCE_PCT[1] / 100),
            expected=round(price * (INSURANCE_PCT[0] + INSURANCE_PCT[1]) / 200),
            assumptions=["Insurance 1.5%-2.5% of purchase price per year"],
            limitations=["Insurance may be optional; varies by provider."],
        )

    def unit_costs(self, equipment, annual_cost: EstimateRange, hours=None):
        """Cost per hour and per acre."""
        hours = hours or equipment.usage_hours_per_year or 700
        acre_capacity = equipment.area_served_acres
        cost_per_hour = EstimateRange(
            minimum=annual_cost.minimum / hours if hours else 0,
            maximum=annual_cost.maximum / hours if hours else 0,
            expected=annual_cost.expected / hours if hours else 0,
            confidence="medium",
            assumptions=[f"Assumed {hours} hours annual use"],
            limitations=["Unit cost is very sensitive to actual hours used."],
        )
        if acre_capacity:
            cost_per_acre = EstimateRange(
                minimum=annual_cost.minimum / float(acre_capacity),
                maximum=annual_cost.maximum / float(acre_capacity),
                expected=annual_cost.expected / float(acre_capacity),
                confidence="medium",
                assumptions=[f"Assumed {acre_capacity} acres served annually"],
                limitations=[],
            )
        else:
            cost_per_acre = None
        return {"per_hour": cost_per_hour.to_dict(), "per_acre": cost_per_acre and cost_per_acre.to_dict()}

    def annual_ownership_cost(self, equipment, purchase_price=None):
        """Fuel + maintenance + depreciation + insurance (annual operating ranges)."""
        fuel = self.fuel_cost(equipment)
        maint = self.maintenance_and_repair(equipment, purchase_price)
        dep = self.annual_depreciation(purchase_price)
        ins = self.annual_insurance(purchase_price)
        annual = EstimateRange(
            minimum=fuel.minimum + maint.minimum + dep.minimum + ins.minimum,
            maximum=fuel.maximum + maint.maximum + dep.maximum + ins.maximum,
            expected=fuel.expected + maint.expected + dep.expected + ins.expected,
            confidence="medium",
            assumptions=[*fuel.assumptions, *maint.assumptions, *dep.assumptions, *ins.assumptions],
            limitations=["All figures are estimates; actual costs vary."],
        )
        return {
            "fuel": fuel.to_dict(),
            "maintenance": maint.to_dict(),
            "depreciation": dep.to_dict(),
            "insurance": ins.to_dict(),
            "annual_total": annual.to_dict(),
            "cost_breakdown": {
                "fuel_pct": round(fuel.expected / max(1, annual.expected) * 100),
                "maintenance_pct": round(maint.expected / max(1, annual.expected) * 100),
                "depreciation_pct": round(dep.expected / max(1, annual.expected) * 100),
                "insurance_pct": round(ins.expected / max(1, annual.expected) * 100),
            },
        }

    def condition_assessment_from_inputs(self, equipment):
        """Rule-based condition estimate from declared inputs (not from photos)."""
        score = None
        band = equipment.condition
        tags = []
        age = equipment.age_years
        if age is not None:
            if age <= 5:
                score = 85
            elif age <= 12:
                score = 65
            else:
                score = 40
        repair_count = equipment.maintenance_records.filter(kind__in=["repair", "emergency"]).count()
        if repair_count >= 3:
            tags.append("frequent_repairs")
            score = max(20, (score or 70) - 20)
        if score is not None:
            if score >= 75:
                band = "good"
            elif score >= 50:
                band = "moderate"
            else:
                band = "poor"
        return {
            "visible_condition_score": score,
            "condition_band": band,
            "issue_tags": tags,
            "method": "farmer-declared rule-based",
            "confidence": "medium" if (age is not None or repair_count) else "low",
            "needs_user_confirmation": True,
            "wording": f"Based on age and repair history, condition is estimated as {band}. This is not a mechanical inspection."
            if score is not None
            else "Not enough information to estimate condition.",
        }

    def operating_cost_estimate(self, equipment):
        """Full operating-cost pack for one equipment item (endpoint contract)."""
        annual = self.annual_ownership_cost(equipment, purchase_price=equipment.purchase_price)
        total = annual["annual_total"]
        annual_range = EstimateRange(
            minimum=total["minimum"],
            maximum=total["maximum"],
            expected=total["expected"],
            confidence=total["confidence"],
            assumptions=total["assumptions"],
            limitations=total["limitations"],
            data_completeness=total.get("data_completeness", 0.0),
            requires_farmer_confirmation=total.get("requires_farmer_confirmation", True),
            requires_official_verification=total.get("requires_official_verification", False),
        )
        units = self.unit_costs(equipment, annual_range)
        condition = self.condition_assessment_from_inputs(equipment)
        return {
            "equipment_id": str(equipment.id),
            "annual_ownership_cost": annual["annual_total"],
            "breakdown": {k: annual[k] for k in ("fuel", "maintenance", "depreciation", "insurance")},
            "cost_per_hour": units["per_hour"],
            "cost_per_acre": units["per_acre"],
            "condition_assessment": condition,
            "estimate_type": "range",
            "confidence": annual["annual_total"]["confidence"],
            "assumptions": annual["annual_total"]["assumptions"],
            "limitations": annual["annual_total"]["limitations"],
            "warnings": ["Operating-cost figures are benchmark estimates only; actual costs vary by load, age and local prices."],
            "requires_farmer_confirmation": True,
            "requires_official_verification": False,
        }