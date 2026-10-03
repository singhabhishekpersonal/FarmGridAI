import pytest

from apps.farms.models import FarmService
from apps.recommendations.models import RecommendationRun
from apps.recommendations.services import RecommendationEngine


@pytest.fixture
def user(db):
    from django.contrib.auth import get_user_model

    return get_user_model().objects.create_user(username="anna", password="Str0ng!", phone="9876522222")


@pytest.fixture
def farm(user, db):
    return FarmService.create_farm(user, "Anna Farm", area=8, unit="acre", state="Uttar Pradesh")


def test_recommendation_engine_runs_and_persists(farm, user):
    result = RecommendationEngine(farm).run(persist=True, user=user)
    run = RecommendationRun.objects.filter(farm=farm).order_by("-created_at").first()
    assert run is not None
    assert run.status == "completed"
    assert result["run_id"] == str(run.pk)
    assert result["recommendations_count"] == len(result["recommendations"])


def test_recommendation_has_honest_guards(farm, user):
    result = RecommendationEngine(farm).run(persist=True, user=user)
    # A fresh farm always produces the collect_more_data guidance.
    assert result["recommendations_count"] >= 1
    for rec in result["recommendations"]:
        assert rec["confidence"]
        assert "estimate" in rec["disclaimer"].lower() or rec["expected_benefit_range_inr"] is not None
        assert rec["financial_risk_level"]


def test_explanation_builder(farm, user):
    from apps.recommendations.services import ExplainabilityGenerator

    result = RecommendationEngine(farm).run(persist=True, user=user)
    rec = RecommendationRun.objects.get(pk=result["run_id"]).recommendations.first()
    explanation = ExplainabilityGenerator().explain(rec)
    assert explanation["what_was_recommended"]
    assert explanation["uncertainty"]["confidence"] in ("high", "medium", "low")
    assert explanation["official_verification_required"]
    assert explanation["disclaimer"]