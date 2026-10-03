"""Recommendation engine: combines data sources into explainable recommendations.

Pipeline:
1.  Collect evidence across profile, expenses, crops, equipment, energy, finance,
    subsidies, anomaly detection, and forecasting.
2.  Apply deterministic policy rules to create candidate recommendations.
3.  Optionally rank candidates with a classical ML ranker (fallback to a
    deterministic priority score when unavailable).
4.  Persist recommendations with evidence + assumptions and return them.

Final decisions always come from deterministic policy and affordability
constraints - never from a black-box model alone.
"""
import logging

from apps.recommendations.models import (
    CostSavingOpportunity,
    Recommendation,
    RecommendationAssumption,
    RecommendationEvidence,
    RecommendationRun,
)

logger = logging.getLogger("FarmGrid")

# Ranking order used by the deterministic policy.
PRIORITY_ORDER = {
    "critical": 0,
    "high": 1,
    "medium": 2,
    "low": 3,
}

CATEGORY_TO_PRIORITY = {
    "review_unusual_expense": "high",
    "review_high_energy_cost": "high",
    "solar_feasibility": "medium",
    "apply_for_subsidy": "high",
    "machine_buy_or_rent": "medium",
    "repair_or_replace": "medium",
    "use_custom_hiring_center": "medium",
    "consider_shared_ownership": "low",
    "reduce_fertilizer_cost": "medium",
    "optimize_crop_cost_plan": "medium",
    "preventive_maintenance": "low",
    "collect_more_data": "low",
    "general_financial_health": "medium",
}


class RecommendationEngine:
    """Produce recommendations for a farm."""

    def __init__(self, farm, use_ml_ranker=True):
        self.farm = farm
        self.use_ml_ranker = use_ml_ranker
        self.models_used = []

    # ------------------------------------------------------------------
    # Evidence gathering (each returns None on missing data, never raises)
    # ------------------------------------------------------------------
    def _expense_snapshot(self):
        try:
            from apps.expenses.services import ExpenseAggregationService

            return ExpenseAggregationService(self.farm.id).summarize()
        except Exception as exc:  # pragma: no cover - defensive
            logger.info("expense snapshot skipped: %s", exc)
            return None

    def _anomaly_snapshot(self):
        try:
            from apps.ml_engine.services.expense_analysis import ExpenseAnalysisService

            return ExpenseAnalysisService(self.farm).run_analysis()
        except Exception as exc:  # pragma: no cover - defensive
            logger.info("anomaly analysis skipped: %s", exc)
            return None

    def _energy_snapshot(self):
        try:
            from apps.energy.services import EnergyAnalysisService

            return EnergyAnalysisService(self.farm).run_analysis(persist=False)
        except Exception as exc:  # pragma: no cover - defensive
            logger.info("energy analysis skipped: %s", exc)
            return None

    def _crop_snapshot(self):
        try:
            from apps.crops.services import estimate_farm_crops

            return estimate_farm_crops(self.farm.id)
        except Exception as exc:  # pragma: no cover - defensive
            logger.info("crop estimate skipped: %s", exc)
            return None

    def _subsidy_snapshot(self):
        try:
            from apps.subsidies.services import SchemeEligibilityEngine

            return SchemeEligibilityEngine(self.farm).run_match(persist=False)
        except Exception as exc:  # pragma: no cover - defensive
            logger.info("subsidy match skipped: %s", exc)
            return None

    def _profile_completeness(self):
        try:
            from apps.accounts.services import ProfileCompleteness

            profile = getattr(self.farm.user, "farmer_profile", None)
            if not profile:
                return {"score": 0.0, "missing_fields": ["farmer_profile"]}
            return ProfileCompleteness.score(profile)
        except Exception as exc:  # pragma: no cover - defensive
            logger.info("profile completeness skipped: %s", exc)
            return {"score": 0.0, "missing_fields": []}

    def _forecast_snapshot(self):
        try:
            from apps.ml_engine.services.expense_analysis import ExpenseAnalysisService

            return ExpenseAnalysisService(self.farm).forecast()
        except Exception as exc:  # pragma: no cover - defensive
            logger.info("forecast skipped: %s", exc)
            return None

    # ------------------------------------------------------------------
    # Candidate policies
    # ------------------------------------------------------------------
    def _candidates(self, snapshot):
        candidates = []

        expense = snapshot["expense"]
        if expense and expense.get("total", 0) > 0:
            top = expense.get("most_expensive")
            candidates.append(
                {
                    "category": "optimize_crop_cost_plan" if top in ("fertilizer", "seed", "pesticide") else "general_financial_health",
                    "title": f"Your largest cost is {top or 'unspecified'} (Rs {expense['total']:,.0f})",
                    "text": "Review the largest cost category for savings opportunities while maintaining productivity.",
                    "benefit_min": max(0, int(expense["total"] * 0.03)),
                    "benefit_max": int(expense["total"] * 0.10),
                    "confidence": "medium",
                    "evidence": [("expense_summary", "Total annual expense Rs %s" % expense["total"], {"total": expense["total"]})],
                }
            )

        anomalies = snapshot["anomaly"]
        for anomaly in (anomalies or {}).get("anomalies", []) or []:
            if anomaly.get("severity") in ("high", "medium"):
                candidates.append(
                    {
                        "category": "review_unusual_expense",
                        "title": f"Unusual expense: {anomaly.get('label', 'expense')}",
                        "text": anomaly.get("explanation", "This expense looks high against benchmark ranges and requires review."),
                        "benefit_min": 0,
                        "benefit_max": int(anomaly.get("excess_amount", 0)),
                        "confidence": anomaly.get("confidence", "low"),
                        "evidence": [("anomaly_detection", anomaly.get("explanation", ""), anomaly)],
                    }
                )

        energy = snapshot["energy"]
        if energy and energy.get("recommendation", {}).get("solar_recommended"):
            rec = energy["recommendation"]
            candidates.append(
                {
                    "category": "solar_feasibility",
                    "title": "Solar irrigation may reduce long-term energy cost",
                    "text": rec.get("reason", "Solar adoption could pay back within the horizon; verify subsidy."),
                    "benefit_min": int(energy["comparison"]["upfront_cost_inr"]),
                    "benefit_max": int(energy["comparison"]["scenarios"][1]["grid_cumulative_10y"]) if len(energy["comparison"]["scenarios"]) > 1 else 0,
                    "confidence": energy["comparison"]["confidence"],
                    "evidence": [("energy_comparison", "Break-even year %s" % rec.get("break_even_year"), rec)],
                }
            )

        subsidy = snapshot["subsidy"]
        if subsidy and subsidy.get("matched_schemes", 0) > 0:
            matched = [r for r in subsidy.get("results", []) if r.get("matched")][:5]
            candidates.append(
                {
                    "category": "apply_for_subsidy",
                    "title": f"{len(matched)} subsidy scheme(s) may apply to you",
                    "text": "Schemes matched preliminarily. Verify eligibility officially before applying.",
                    "benefit_min": min((r["benefit_range_inr"][0] or 0 for r in matched), default=0),
                    "benefit_max": max((r["benefit_range_inr"][1] or 0 for r in matched), default=0),
                    "confidence": "medium",
                    "evidence": [("subsidy_match", "Matched: " + ", ".join(r["name"] for r in matched), {"matched": matched})],
                }
            )

        profile = snapshot["profile"]
        if profile and profile.get("score", 1) < 0.5:
            candidates.append(
                {
                    "category": "collect_more_data",
                    "title": "Add more farm data to improve recommendations",
                    "text": "Missing fields: " + (", ".join(profile["missing_fields"]) or "none"),
                    "benefit_min": 0,
                    "benefit_max": 0,
                    "confidence": "high",
                    "evidence": [("profile_completeness", "Completeness %s" % profile["score"], profile)],
                }
            )

        crop = snapshot["crop"]
        if crop and crop.get("totals", {}).get("expected", 0) > 0 and crop.get("crop_estimates"):
            candidates.append(
                {
                    "category": "optimize_crop_cost_plan",
                    "title": "Crop-wise cost planning available",
                    "text": "Review and benchmark your crop input spend against verified crop cost benchmarks.",
                    "benefit_min": max(0, int(crop["totals"]["expected"] * 0.05)),
                    "benefit_max": max(0, int(crop["totals"]["expected"] * 0.15)),
                    "confidence": "medium",
                    "evidence": [("crop_cost", "Estimated crop costs Rs %s" % crop["totals"]["expected"], crop["totals"])],
                }
            )

        for equipment in self.farm.equipment.all():
            if equipment.usage_hours_per_year and equipment.usage_hours_per_year < 200 and equipment.is_owned:
                candidates.append(
                    {
                        "category": "machine_buy_or_rent",
                        "title": f"{equipment.display_name} is lightly used - consider renting",
                        "text": "Low annual usage may make renting or hiring more economical than owning.",
                        "benefit_min": 0,
                        "benefit_max": int((equipment.purchase_price or 300000) * 0.3),
                        "confidence": "low",
                        "evidence": [("equipment_usage", f"{equipment.usage_hours_per_year} hours/yr", {"hours": equipment.usage_hours_per_year})],
                    }
                )
            if equipment.condition == "poor":
                candidates.append(
                    {
                        "category": "repair_or_replace",
                        "title": f"{equipment.display_name} condition flagged as poor",
                        "text": "Get a professional inspection before deciding between repair and replacement.",
                        "benefit_min": 0,
                        "benefit_max": 0,
                        "confidence": "low",
                        "evidence": [("equipment_condition", "Condition 'poor'", {"condition": equipment.condition})],
                    }
                )

        forecast = snapshot["forecast"]
        if forecast and forecast.get("increasing_trend") is True:
            candidates.append(
                {
                    "category": "review_high_energy_cost",
                    "title": "Energy/expense trend is increasing",
                    "text": forecast.get("message", "The forecast shows an increasing expenditure trend; review usage."),
                    "benefit_min": 0,
                    "benefit_max": 0,
                    "confidence": "low",
                    "evidence": [("forecast", forecast.get("message", ""), forecast)],
                }
            )

        return candidates

    # ------------------------------------------------------------------
    def _rank(self, candidates):
        """Deterministic ranking; optionally refined by the ML ranker."""
        try:
            if self.use_ml_ranker:
                from apps.ml_engine.classical import recommendation_ranker as ranker

                score_row = ranker.score_candidates(candidates)
                self.models_used.append("recommendation_ranker")
                for i, idx in enumerate(sorted(range(len(candidates)), key=lambda k: score_row[k] if k < len(score_row) else 0, reverse=True)):
                    candidates[idx]["rank"] = i
                return
        except Exception as exc:  # pragma: no cover
            logger.info("ML ranker unavailable, deterministic ranking used: %s", exc)
        candidates.sort(
            key=lambda c: (
                PRIORITY_ORDER.get(CATEGORY_TO_PRIORITY.get(c["category"], "low"), 4),
                -(c.get("benefit_max") or 0),
            )
        )
        for idx, candidate in enumerate(candidates):
            candidate["rank"] = idx

    # ------------------------------------------------------------------
    def run(self, persist=True, user=None):
        snapshot = {
            "expense": self._expense_snapshot(),
            "anomaly": self._anomaly_snapshot(),
            "energy": self._energy_snapshot(),
            "crop": self._crop_snapshot(),
            "subsidy": self._subsidy_snapshot(),
            "profile": self._profile_completeness(),
            "forecast": self._forecast_snapshot(),
        }
        candidates = self._candidates(snapshot)
        self._rank(candidates)

        run = None
        if persist:
            run = RecommendationRun.objects.create(
                farm=self.farm,
                status="completed",
                summary_json={"candidates": len(candidates)},
                models_used_json=self.models_used,
                score=min(1.0, len(candidates) / 10),
                created_by=user,
            )

        results = []
        for candidate in candidates:
            if persist:
                rec = Recommendation.objects.create(
                    farm=self.farm,
                    run=run,
                    category=candidate["category"],
                    priority=CATEGORY_TO_PRIORITY.get(candidate["category"], "medium"),
                    title=candidate["title"],
                    text=candidate["text"],
                    expected_benefit_min=candidate.get("benefit_min"),
                    expected_benefit_max=candidate.get("benefit_max"),
                    financial_risk_level="medium",
                    confidence=candidate.get("confidence", "low"),
                    model_versions_json=self.models_used,
                    disclaimer="These are preliminary estimates for planning. Actual costs vary; verify important claims locally.",
                    next_steps=["Confirm data accuracy in your profile.", "Discuss with a local extension officer or credible vendor."],
                    created_by=user,
                )
                for evidence_type, description, data_ref in candidate.get("evidence", []):
                    RecommendationEvidence.objects.create(recommendation=rec, evidence_type=evidence_type, description=description, data_reference=data_ref, created_by=user)
                RecommendationAssumption.objects.create(
                    recommendation=rec,
                    assumption="All outputs are estimates using benchmark data; farmer confirmation and official verification are required.",
                    created_by=user,
                )
                results.append(_serialize(rec))
            else:
                results.append(candidate)
        return {
            "run_id": str(run.pk) if run else None,
            "recommendations_count": len(results),
            "recommendations": results,
            "models_used": self.models_used,
            "note": "Recommendations are estimates; official verification required before acting.",
        }


class ExplainabilityGenerator:
    """Build the standardized explanation object for a recommendation."""

    def explain(self, recommendation: Recommendation) -> dict:
        evidence = [
            {"type": e.evidence_type, "description": e.description, "data": e.data_reference} for e in recommendation.evidence.all()
        ]
        assumptions = [a.assumption for a in recommendation.assumptions.all()]
        return {
            "what_was_recommended": f"{recommendation.title} ({recommendation.get_category_display()})",
            "why": recommendation.text,
            "farmer_data_used": [e["data"] for e in evidence],
            "assumptions": assumptions,
            "key_numbers": {
                "expected_benefit_min_inr": recommendation.expected_benefit_min,
                "expected_benefit_max_inr": recommendation.expected_benefit_max,
                "expected_cost_inr": recommendation.expected_cost,
            },
            "uncertainty": {
                "confidence": recommendation.confidence,
                "financial_risk_level": recommendation.financial_risk_level,
            },
            "what_can_improve_accuracy": [
                "Verify farm income and expense details.",
                "Confirm equipment usage hours and condition.",
                "Complete missing profile fields.",
            ],
            "official_verification_required": [
                "Scheme availability, amounts and documents must be verified with official sources.",
                "Prices and rates change; verify locally before major spending.",
            ],
            "disclaimer": recommendation.disclaimer or "Estimated range values, not guarantees.",
        }


def _serialize(rec: Recommendation):
    return {
        "recommendation_id": str(rec.pk),
        "category": rec.category,
        "priority": rec.priority,
        "title": rec.title,
        "text": rec.text,
        "expected_benefit_range_inr": {"minimum": rec.expected_benefit_min, "maximum": rec.expected_benefit_max},
        "expected_cost_inr": rec.expected_cost,
        "financial_risk_level": rec.financial_risk_level,
        "confidence": rec.confidence,
        "model_versions": rec.model_versions_json,
        "disclaimer": rec.disclaimer,
        "next_steps": rec.next_steps,
        "created_at": rec.created_at.isoformat(),
    }