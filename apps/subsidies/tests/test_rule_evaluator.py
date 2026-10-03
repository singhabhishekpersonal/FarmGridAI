import pytest

from apps.farms.models import FarmService
from apps.subsidies.models import SubsidyEligibilityRule, SubsidyScheme
from apps.subsidies.services import ProfileContext, RuleEvaluator, SchemeEligibilityEngine


@pytest.fixture
def user(db):
    from django.contrib.auth import get_user_model

    return get_user_model().objects.create_user(username="sita", password="Str0ng!", phone="9876500000")


@pytest.fixture
def farm(user, db):
    return FarmService.create_farm(user, "Test Farm", area=3, unit="acre", state="Uttar Pradesh", district="Lucknow")


def _rule(scheme, field, operator, value, sequence=10, reason="test rule"):
    return SubsidyEligibilityRule.objects.create(scheme=scheme, field=field, operator=operator, value=value, sequence=sequence, reason=reason)


def _compare(operator, actual, value):
    from apps.subsidies.services import _compare

    return _compare(operator, actual, value)


def test_compare_operators():
    assert _compare("gte", 3.0, 2) is True
    assert _compare("gt", 3.0, 3) is False
    assert _compare("in", "borewell", ["well", "borewell"]) is True
    assert _compare("eq", "Uttar Pradesh", "uttar pradesh") is True
    assert _compare("contains", "Lucknow District", "lucknow") is True
    assert _compare("always", None, {}) is True


def test_context_reads_profile_before_farm(user, farm):
    context = ProfileContext(farm)
    assert context.state == "Uttar Pradesh"
    assert context.land_hectares > 0


def test_rule_evaluator_requires_all_rules_true(farm):
    scheme = SubsidyScheme.objects.create(name="Demo Scheme", slug="demo-scheme", is_active=True)
    _rule(scheme, "land_hectares", "gte", 1.0)
    _rule(scheme, "irrigation_source", "in", ["well", "borewell"])
    context = ProfileContext(farm)
    matched, reasons = RuleEvaluator().evaluate_scheme(scheme, context)
    assert matched is False
    assert len(reasons) == 2
    assert any(r["matched"] is False for r in reasons)


def test_engine_matches_and_persists_checklist(user, farm):
    scheme = SubsidyScheme.objects.create(name="UP Solar", slug="up-solar", category="solar_pump", state="Uttar Pradesh", is_active=True)
    _rule(scheme, "land_hectares", "gte", 1.0)
    from apps.subsidies.models import SchemeDocumentRequirement

    SchemeDocumentRequirement.objects.create(scheme=scheme, document_name="Aadhaar card", required=True)

    result = SchemeEligibilityEngine(farm).run_match()
    assert result["matched_schemes"] == 1
    assert result["results"][0]["matched"] is True
    persisted = scheme.farmer_matches.first()
    assert persisted.matched is True
    assert persisted.checklists.exists()
    assert persisted.checklists.first().items_json[0]["document"] == "Aadhaar card"


def test_engine_skips_other_state_scheme(user, farm):
    bihar_scheme = SubsidyScheme.objects.create(name="Bihar Solar", slug="bihar-solar", category="solar_pump", state="Bihar", is_active=True)
    _rule(bihar_scheme, "land_hectares", "gte", 1.0)
    result = SchemeEligibilityEngine(farm).run_match()
    assert result["checked_schemes"] == 0