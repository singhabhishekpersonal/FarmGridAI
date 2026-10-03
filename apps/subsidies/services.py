"""Subsidy eligibility rule engine.

Rules are declarative records on ``SubsidyEligibilityRule`` and are evaluated
by a safe interpreter (no ``eval``). Output includes the exact triggered rules
for explainability, plus explicit "needs official verification" flags.
"""
from datetime import date

from apps.subsidies.models import (
    FarmerSchemeMatch,
    SchemeApplicationChecklist,
    SubsidyEligibilityRule,
    SubsidyScheme,
)


class ProfileContext:
    """Normalized farmer/farm attributes for rule evaluation."""

    def __init__(self, farm):
        self.farm = farm
        user = farm.user
        profile = getattr(user, "farmer_profile", None)
        self.state = (profile.state if profile and profile.state else (farm.location.state if farm.location else "")) or ""
        self.district = (profile.district if profile and profile.district else (farm.location.district if farm.location else "")) or ""
        self.land_hectares = profile.area_in_hectares if profile else farm.total_hectares
        self.land_unit = profile.land_unit if profile else "acre"
        self.irrigated = profile.irrigated if profile else "rainfed"
        self.irrigation_source = profile.irrigation_source if profile else "other"
        self.yearly_farm_income_min = profile.yearly_farm_income_min if profile else None
        self.gender = profile.gender if profile else "undisclosed"

    def get(self, field):
        if field == "state":
            return self.state or ""
        if field == "district":
            return self.district or ""
        if field == "land_hectares":
            return float(self.land_hectares or 0)
        if field == "land_unit":
            return self.land_unit
        if field == "irrigated":
            return self.irrigated
        if field == "irrigation_source":
            return self.irrigation_source
        if field == "yearly_farm_income_min":
            return float(self.yearly_farm_income_min or 0)
        if field == "income_farm":
            return float(self.yearly_farm_income_min or 0)
        if field == "gender":
            return self.gender
        return None


def _compare(operator, actual, expected):
    if operator == "always":
        return True
    if actual is None:
        return False
    try:
        if operator == "eq":
            return str(actual).strip().lower() == str(expected).strip().lower()
        if operator == "neq":
            return str(actual).strip().lower() != str(expected).strip().lower()
        if operator == "in":
            return str(actual).strip().lower() in [str(v).strip().lower() for v in expected]
        if operator == "contains":
            return str(expected).strip().lower() in str(actual).strip().lower()
        a = float(actual)
        e = float(expected)
        if operator == "gt":
            return a > e
        if operator == "gte":
            return a >= e
        if operator == "lt":
            return a < e
        if operator == "lte":
            return a <= e
    except (ValueError, TypeError):
        return False
    return False


class RuleEvaluator:
    """Evaluate all rules for a scheme against a farm context."""

    def evaluate_scheme(self, scheme, context):
        rules = scheme.rules.all()
        reasons = []
        matched = True
        if not rules:
            matched = False
            reasons.append({"matched": False, "reason": "Scheme has no eligibility rules defined yet.", "rule": None})
        for rule in rules:
            actual = context.get(rule.field)
            outcome = _compare(rule.operator, actual, rule.value)
            if not outcome:
                matched = False
            reasons.append(
                {
                    "matched": outcome,
                    "reason": rule.reason or f"{rule.get_field_display()} {rule.get_operator_display()} {rule.value}",
                    "rule": {
                        "field": rule.field,
                        "operator": rule.operator,
                        "value": rule.value,
                        "actual": actual,
                    },
                }
            )
        return matched, reasons


class SchemeEligibilityEngine:
    """Match all applicable schemes to a farm."""

    def __init__(self, farm):
        self.farm = farm
        self.context = ProfileContext(farm)

    def _candidate_schemes(self):
        return SubsidyScheme.objects.filter(is_active=True)

    def run_match(self, interest_category=None, persist=True):
        schemes = self._candidate_schemes()
        results = []
        for scheme in schemes:
            if scheme.state and self.context.state and scheme.state.lower() != self.context.state.lower():
                continue
            if interest_category and scheme.category != interest_category:
                continue
            if scheme.effective_to and scheme.effective_to < date.today():
                continue
            matched, reasons = RuleEvaluator().evaluate_scheme(scheme, self.context)
            match = self._persist(scheme, matched, reasons, persist)
            results.append(self._serialize(scheme, matched, reasons))
        matched_count = sum(1 for r in results if r["matched"])
        return {
            "farm_id": str(self.farm.id),
            "checked_schemes": len(results),
            "matched_schemes": matched_count,
            "results": results,
            "needs_official_verification": True,
            "message": "Preliminary matching only - official verification required for every scheme.",
        }

    def _persist(self, scheme, matched, reasons, persist):
        if not persist:
            return None
        match, _ = FarmerSchemeMatch.objects.update_or_create(
            farm=self.farm,
            scheme=scheme,
            defaults={
                "matched": matched,
                "reasons_json": reasons,
                "confidence": "medium" if self.context.state else "low",
                "needs_official_verification": True,
            },
        )
        if matched and not match.checklists.exists():
            items = [
                {"document": r.document_name, "required": r.required, "gathered": False}
                for r in scheme.documents.all()
            ]
            SchemeApplicationChecklist.objects.create(match=match, items_json=items)
        return match

    def _serialize(self, scheme, matched, reasons):
        return {
            "scheme_id": str(scheme.pk),
            "name": scheme.name,
            "category": scheme.category,
            "administrative_level": scheme.administrative_level,
            "state": scheme.state,
            "benefit_type": scheme.benefit_type,
            "benefit_range_inr": [scheme.benefit_min_inr, scheme.benefit_max_inr],
            "official_url": scheme.official_url,
            "last_verified_at": scheme.last_verified_at.isoformat() if scheme.last_verified_at else None,
            "is_illustrative": scheme.is_illustrative,
            "matched": matched,
            "reasons": reasons,
            "needs_official_verification": True,
            "documents": [
                {"document_name": d.document_name, "required": d.required, "notes": d.notes}
                for d in scheme.documents.all()
            ],
        }