"""Machinery finance calculators: EMI, ownership cost, buy vs rent,
repair vs replace, affordability and the decision engine.

Every decision returns options, reasons, key calculations, risk level and
explicit assumptions/warnings. Numbers are estimates, not guarantees.
"""
from math import pow


def calculate_loan_emi(principal, annual_interest_rate_pct, tenure_months):
    """Standard EMI formula. Returns emi, total interest, total payable."""
    principal = float(principal)
    r = float(annual_interest_rate_pct) / 100 / 12
    n = int(tenure_months)
    if n <= 0 or principal <= 0:
        return None
    if r == 0:
        emi = principal / n
    else:
        emi = principal * r * pow(1 + r, n) / (pow(1 + r, n) - 1)
    total_payable = emi * n
    return {
        "emi_inr": round(emi, 2),
        "interest_total_inr": round(total_payable - principal, 2),
        "total_payable_inr": round(total_payable, 2),
        "principal_inr": round(principal, 2),
        "annual_interest_rate_pct": float(annual_interest_rate_pct),
        "tenure_months": n,
    }


def calculate_annual_ownership_cost(
    purchase_price,
    annual_hours=700,
    interest_rate_pct=12.0,
    depreciation_pct=10.0,
    maintenance_pct=5.0,
    insurance_pct=2.0,
    fuel_cost_per_hour=150.0,
):
    """5-year and 10-year ownership cost with annual breakdown."""
    price = float(purchase_price)
    annual_interest = price * interest_rate_pct / 100
    annual_depreciation = price * depreciation_pct / 100
    annual_maintenance = price * maintenance_pct / 100
    annual_insurance = price * insurance_pct / 100
    annual_fuel = annual_hours * fuel_cost_per_hour
    annual_total = annual_interest + annual_depreciation + annual_maintenance + annual_insurance + annual_fuel
    return {
        "annual_total": round(annual_total, 2),
        "cost_per_hour": round(annual_total / max(1, annual_hours), 2),
        "five_year_total": round(annual_total * 5, 2),
        "ten_year_total": round(annual_total * 10, 2),
        "breakdown": {
            "interest": round(annual_interest, 2),
            "depreciation": round(annual_depreciation, 2),
            "maintenance": round(annual_maintenance, 2),
            "insurance": round(annual_insurance, 2),
            "fuel": round(annual_fuel, 2),
        },
    }


def calculate_rental_cost(annual_hours, rental_rate_per_hour):
    return round(annual_hours * rental_rate_per_hour, 2)


def calculate_equipment_utilization_score(annual_hours):
    """0..100 utilization score vs a 1500-hour 'high use' reference."""
    return round(min(100, annual_hours / 15), 1)


def calculate_buy_vs_rent(purchase_price, annual_hours, rental_rate_per_hour, subsidy=0, loan_years=5, interest_rate_pct=12.0, maintenance_pct=5.0, depreciation_pct=10.0, insurance_pct=2.0, fuel_cost_per_hour=150.0):
    """Returns buy vs rent decision with calculated comparison."""
    net_price = purchase_price - subsidy
    ownership = calculate_annual_ownership_cost(
        net_price, annual_hours, interest_rate_pct=interest_rate_pct,
        depreciation_pct=depreciation_pct, maintenance_pct=maintenance_pct,
        insurance_pct=insurance_pct, fuel_cost_per_hour=fuel_cost_per_hour,
    )
    rental = calculate_rental_cost(annual_hours, rental_rate_per_hour)
    utilization = calculate_equipment_utilization_score(annual_hours)

    loan = calculate_loan_emi(net_price, interest_rate_pct, loan_years * 12)

    buy_cheaper = ownership["annual_total"] <= rental
    reasons = []
    if buy_cheaper:
        reasons.append(f"Annual ownership (Rs {ownership['annual_total']:,.0f}) is at or below annual rental cost (Rs {rental:,.0f}).")
    else:
        reasons.append(f"Annual rental (Rs {rental:,.0f}) is lower than annual ownership (Rs {ownership['annual_total']:,.0f}).")
    if utilization >= 50:
        reasons.append(f"Utilization is relatively high ({utilization}/100), favoring ownership.")
    else:
        reasons.append(f"Utilization is low ({utilization}/100); renting when needed may save capital.")
    if subsidy > 0:
        reasons.append(f"Subsidy of Rs {subsidy:,.0f} reduces net purchase price.")

    suggestion = "buy" if buy_cheaper else "rent_when_needed"
    loan_annual = loan["emi_inr"] * 12 if loan else 0
    risk = "medium" if (buy_cheaper and loan_annual and loan_annual / max(1, net_price) > 0.25) else "low"
    return {
        "suggested_option": suggestion,
        "buy": ownership,
        "rent_annual": rental,
        "utilization_score": utilization,
        "loan": loan,
        "subsidy": subsidy,
        "net_purchase_price": round(net_price, 2),
        "reasons": reasons,
        "financial_risk_level": "low" if not buy_cheaper else "medium",
        "data_confidence": "medium",
        "assumptions": [
            f"Loan at {interest_rate_pct}% over {loan_years} years" if loan else "No loan assumed",
            f"Maintenance {maintenance_pct}%, depreciation {depreciation_pct}%, insurance {insurance_pct}% of price",
            f"Fuel cost Rs {fuel_cost_per_hour}/hr",
        ],
        "warnings": ["Purchase locks capital; rental may be cheaper for occasional use.", "Rates and availability of rentals vary locally."],
        "limitations": [
            "Depreciation, maintenance and fuel costs are flat national-estimate curves, not machine-specific values.",
            "Rental rates and subsidy approval vary by state, scheme and season; verify locally.",
        ],
        "requires_farmer_confirmation": True,
        "requires_official_verification": bool(subsidy > 0),
    }


def calculate_repair_vs_replace(repair_cost, replacement_price, residual_value, annual_usage_hours, repair_frequency_per_year=1.0, interest_rate_pct=12.0):
    """Repair vs replacement decision."""
    remaining_life_years = max(1, annual_usage_hours / max(1, repair_frequency_per_year * 200))
    expected_annual_repair = repair_cost * repair_frequency_per_year
    replacement_annual_cost_equivalent = (replacement_price - residual_value) / max(1, remaining_life_years) * (1 + interest_rate_pct / 100)
    repair_cheaper = expected_annual_repair < replacement_annual_cost_equivalent

    reasons = []
    if repair_cheaper:
        reasons.append(f"Expected annual repair (Rs {expected_annual_repair:,.0f}) is below the replacement cost equivalent (Rs {replacement_annual_cost_equivalent:,.0f}).")
    else:
        reasons.append(f"Replacement cost equivalent (Rs {replacement_annual_cost_equivalent:,.0f}) is below expected annual repair (Rs {expected_annual_repair:,.0f}).")
    if repair_frequency_per_year >= 3:
        reasons.append("Frequent repairs suggest reliability risk; consider replacement or professional inspection.")

    return {
        "suggested_option": "repair_existing" if repair_cheaper else "replace",
        "expected_annual_repair": round(expected_annual_repair, 2),
        "replacement_annual_cost_equivalent": round(replacement_annual_cost_equivalent, 2),
        "remaining_life_years_estimate": round(remaining_life_years, 1),
        "reasons": reasons,
        "financial_risk_level": "medium",
        "data_confidence": "medium",
        "assumptions": [
            f"Repair cost Rs {repair_cost:,.0f} repeated {repair_frequency_per_year:.1f}x/year",
            "Remaining life estimated from usage intensity; requires farmer confirmation.",
        ],
        "warnings": ["A mechanical inspection is required before a final replacement decision.", "Residual value estimate is approximate."],
        "limitations": [
            "Repair cost and residual value are farmer estimates or indicative quotes, not guaranteed prices.",
            "Repeat-failure patterns and hidden damage cannot be judged from numbers alone.",
        ],
        "requires_farmer_confirmation": True,
        "requires_official_verification": True,
    }


def calculate_machine_affordability(annual_income, proposed_emi, existing_emi_total=0, safe_burden_pct=25.0):
    """EMI burden as % of farm income; flag if unaffordable."""
    proposed_emi = proposed_emi or 0
    if annual_income is None or annual_income <= 0:
        return {
            "income_burden_pct": None,
            "safe_burden_pct": safe_burden_pct,
            "affordable": False,
            "financial_risk_level": "high",
            "reasons": ["No annual income entered; affordability cannot be assessed."],
            "assumptions": [f"Existing EMI Rs {existing_emi_total:,.0f}/month"],
            "warnings": ["Enter a verified annual farm income to assess affordability.", "This is an estimate, not loan approval."],
            "limitations": [
                "Income is self-reported; actual repayment capacity depends on verified cash flow and lender rules.",
            ],
            "data_confidence": "low",
            "requires_farmer_confirmation": True,
            "requires_official_verification": True,
        }
    burden = (proposed_emi + existing_emi_total) * 12 / max(1, annual_income) * 100
    affordable = burden <= safe_burden_pct + 10
    return {
        "income_burden_pct": round(burden, 2),
        "safe_burden_pct": safe_burden_pct,
        "affordable": affordable,
        "financial_risk_level": "high" if burden > safe_burden_pct + 15 else ("medium" if burden > safe_burden_pct else "low"),
        "reasons": [
            f"EMI burden is {burden:.1f}% of annual income.",
            f"Recommended safe burden is {safe_burden_pct}% (plus 10% tolerance).",
            "Existing EMIs are added before this decision.",
        ],
        "assumptions": [f"Annual income Rs {annual_income:,.0f}", f"Existing EMI Rs {existing_emi_total:,.0f}/month"],
        "warnings": ["Income volatility and other repayments affect real affordability.", "This is an estimate, not loan approval."],
        "limitations": [
            "Income is self-reported; actual repayment capacity depends on verified cash flow and lender rules.",
        ],
        "data_confidence": "medium",
        "requires_farmer_confirmation": True,
        "requires_official_verification": True,
    }


def generate_machinery_recommendation(usage_hours, rental_available, annual_repair_spend, residual_value, purchase_price, annual_income, emi, existing_emi=0, subsidy=0):
    """Rule-first decision engine combining the sub-calculations."""
    if usage_hours is None or purchase_price is None:
        return {
            "suggested_option": "gather_more_information",
            "reasons": ["Insufficient usage or price data entered."],
            "data_confidence": "low",
            "assumptions": [],
            "warnings": ["A confident machinery decision requires usage hours and a purchase price quote."],
            "limitations": ["No usage or price data provided; this recommendation should not be treated as a decision."],
            "requires_farmer_confirmation": True,
            "requires_official_verification": True,
        }

    utilization = calculate_equipment_utilization_score(usage_hours)

    affordability = calculate_machine_affordability(annual_income, emi or 0, existing_emi)
    affinity_check = affordability["financial_risk_level"] != "high" or annual_income <= 0

    if utilization < 30 and rental_available:
        suggestion = "rent_when_needed"
        reasons = [f"Low utilization ({utilization}/100) with rental availability favors renting."]
    elif annual_repair_spend > 0.35 * max(residual_value, 1) and utilization >= 50:
        suggestion = "replace"
        reasons = [f"Annual repair spend (Rs {annual_repair_spend:,.0f}) exceeds 35% of residual value (Rs {residual_value:,.0f}) with high usage."]
    elif subsidy > 0.2 * purchase_price and utilization >= 40:
        suggestion = "buy"
        reasons = [f"Subsidy (Rs {subsidy:,.0f}) materially reduces net price; utilization is moderate to high."]
    elif not affinity_check:
        suggestion = "repair_existing"
        reasons = ["New EMI would strain farm income; repair the existing machine and reduce cost."]
    else:
        suggestion = "gather_more_information"
        reasons = ["More data (exact usage, rental market, repair history) is needed for a confident decision."]

    if affordability["income_burden_pct"] > affordability["safe_burden_pct"] + 15:
        risk = "high"
    elif affordability["income_burden_pct"] > affordability["safe_burden_pct"]:
        risk = "medium"
    else:
        risk = "low"

    return {
        "suggested_option": suggestion,
        "utilization_score": utilization,
        "financial_risk_level": risk,
        "income_burden_percentage": affordability["income_burden_pct"],
        "affordability": affordability,
        "reasons": reasons,
        "alternatives": ["buy_new", "buy_used", "rent_when_needed", "shared_ownership", "custom_hiring_center", "repair_existing"],
        "key_calculations": {
            "utilization_score": utilization,
            "income_burden_pct": affordability["income_burden_pct"],
            "repair_to_residual_ratio": round(annual_repair_spend / max(1, residual_value), 3),
        },
        "data_confidence": "medium",
        "assumptions": ["Usage, income and rental availability are farmer-provided estimates."],
        "warnings": ["Final decisions need local price verification and ideally a mechanical inspection."],
        "limitations": [
            "Rental availability, dealer quotes and subsidy scheme rules must be confirmed locally.",
            "Depreciation and repair references are generic national estimates, not machine-specific data.",
        ],
        "requires_farmer_confirmation": True,
        "requires_official_verification": bool(subsidy > 0),
    }