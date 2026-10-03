"""Contract tests for the public API surface.

Locks in the audit results:
1. Every named route still reverses and resolves back to itself.
2. No two URL patterns share the same path with different views (the
   subsidy/recommendation collision that shadowed RecommendationsListView).
3. Every ModelSerializer only exposes fields that exist on its model.
4. Farm-scoped endpoints return 404 for other farmers' farms.
"""
import importlib
import uuid

import pytest
from django.urls import URLPattern, URLResolver, get_resolver, resolve, reverse
from rest_framework.serializers import ModelSerializer, SerializerMethodField
from rest_framework.test import APIClient

from apps.farms.models import FarmService

SERIALIZER_MODULES = [
    "apps.accounts.serializers",
    "apps.farms.serializers",
    "apps.crops.serializers",
    "apps.equipment.serializers",
    "apps.expenses.serializers",
    "apps.energy.serializers",
    "apps.finance.serializers",
    "apps.subsidies.serializers",
    "apps.recommendations.serializers",
    "apps.chatbot.serializers",
]

U = str(uuid.uuid4())

ROUTE_KWARGS = {
    "farm-detail": {"farm_id": U},
    "farm-land-parcels": {"farm_id": U},
    "farm-summary": {"farm_id": U},
    "farm-crop-list": {"farm_id": U},
    "farm-crop-estimates": {"farm_id": U},
    "farm-crop-estimate-detail": {"farm_id": U, "crop_id": U},
    "farmer-equipment-list": {"farm_id": U},
    "farmer-equipment-detail": {"farm_id": U, "equipment_id": U},
    "equipment-image-upload": {"farm_id": U, "equipment_id": U},
    "equipment-image-analyze": {"farm_id": U, "equipment_id": U, "image_id": U},
    "equipment-operating-cost": {"farm_id": U, "equipment_id": U},
    "expense-list": {"farm_id": U},
    "electricity-bill": {"farm_id": U},
    "fuel-expense": {"farm_id": U},
    "input-expense": {"farm_id": U},
    "labour-expense": {"farm_id": U},
    "transport-expense": {"farm_id": U},
    "rental-expense": {"farm_id": U},
    "expense-analysis": {"farm_id": U},
    "expense-summary": {"farm_id": U},
    "expense-document": {"farm_id": U},
    "pump-profile": {"farm_id": U},
    "solar-configuration": {"farm_id": U},
    "energy-analyze": {"farm_id": U},
    "solar-comparison": {"farm_id": U},
    "energy-projection": {"farm_id": U},
    "income-profile": {"farm_id": U},
    "buy-vs-rent": {"farm_id": U},
    "repair-vs-replace": {"farm_id": U},
    "affordability": {"farm_id": U},
    "machinery-decision": {"farm_id": U},
    "finance-scenarios": {"farm_id": U},
    "subsidy-scheme-detail": {"scheme_id": U},
    "subsidy-match": {"farm_id": U},
    "subsidy-recommendations": {"farm_id": U},
    "subsidy-checklists": {"farm_id": U},
    "recommendation-list": {"farm_id": U},
    "recommendation-run": {"farm_id": U},
    "recommendation-explain": {"farm_id": U, "recommendation_id": U},
    "recommendation-feedback": {"farm_id": U, "recommendation_id": U},
    "cost-saving-opportunities": {"farm_id": U},
    "recommendation-runs": {"farm_id": U},
    "chat-ask": {"session_id": U},
    "chat-history": {"session_id": U},
}

NO_ARG_ROUTES = [
    "auth-register", "auth-login", "auth-logout", "profile", "consents", "language",
    "farm-list", "land-unit-convert", "bigha-rules", "crop-catalog",
    "equipment-categories", "equipment-catalog", "tariff-benchmarks",
    "diesel-price-benchmarks", "subsidy-scheme-list", "chat-session-create",
    "health", "readiness", "system-capabilities", "system-model-status",
    "system-data-source-status",
]


def _children_of(patterns, prefix=""):
    for p in patterns:
        if isinstance(p, URLPattern):
            yield p, prefix
        elif isinstance(p, URLResolver):
            yield from _children_of(p.url_patterns, prefix + str(p.pattern))


def test_all_named_routes_reverse_and_resolve_back():
    for name in ROUTE_KWARGS:
        url = reverse(name, kwargs=ROUTE_KWARGS[name])
        assert resolve(url).url_name == name
    for name in NO_ARG_ROUTES:
        url = reverse(name)
        assert resolve(url).url_name == name


def test_no_url_path_maps_to_two_different_views():
    resolver = get_resolver()
    seen = {}
    for p, prefix in _children_of(resolver.url_patterns):
        key = (prefix, str(p.pattern))
        all_prefix, all_route = key
        if not all_route or all_route.startswith("^"):
            continue
        view_id = repr(p.callback)
        if key in seen and seen[key] != view_id:
            raise AssertionError(f"collision on path {key}: {seen[key]} vs {view_id}")
        seen[key] = view_id


def test_serializer_fields_all_exist_on_models():
    mismatches = []
    for module_name in SERIALIZER_MODULES:
        mod = importlib.import_module(module_name)
        for value in vars(mod).values():
            if not (isinstance(value, type) and issubclass(value, ModelSerializer) and value is not ModelSerializer):
                continue
            if not hasattr(value.Meta, "model"):
                continue
            fields = getattr(value.Meta, "fields", None)
            if not fields or fields == "__all__":
                continue
            if not isinstance(fields, (list, tuple)):
                continue
            model = value.Meta.model
            for field in fields:
                if field in value._declared_fields:
                    if isinstance(value._declared_fields[field], (SerializerMethodField,)):
                        continue
                    continue
                try:
                    model._meta.get_field(field)
                except Exception:
                    if not hasattr(model, field):
                        mismatches.append((module_name, value.__name__, field))
    assert not mismatches, mismatches


def _client_for(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


@pytest.fixture
def user(db):
    from django.contrib.auth import get_user_model

    return get_user_model().objects.create_user(username="ram_lal", password="Str0ng!", phone="9876500003")


@pytest.fixture
def other_user(db):
    from django.contrib.auth import get_user_model

    return get_user_model().objects.create_user(username="sam_singh", password="Str0ng!", phone="9876500004")


def test_foreign_farm_scope_is_404(user, other_user):
    farm = FarmService.create_farm(user, "My Farm", area=1, unit="acre", state="Uttar Pradesh", district="Lucknow")
    client = _client_for(other_user)
    resp = client.get(f"/api/v1/farms/{farm.id}/summary")
    assert resp.status_code == 404


def test_system_endpoints_return_safe_envelope(user):
    client = _client_for(user)
    for path in (
        "/api/v1/system/capabilities",
        "/api/v1/system/model-status",
        "/api/v1/system/data-source-status",
    ):
        resp = client.get(path)
        assert resp.status_code == 200, (path, resp.content)
        assert resp.json()["success"] is True


def test_model_status_hides_artifact_paths(user):
    client = _client_for(user)
    body = client.get("/api/v1/system/model-status").json()
    for model in body["data"]["models"]:
        assert "artifact_path" not in model
        assert "path" not in str(model)


def test_readiness_redacts_database_details():
    resp = APIClient().get("/api/v1/readiness")
    assert resp.status_code in (200, 503)
    payload = resp.json()
    assert "error" in payload
    assert "password" not in payload["error"].lower()
    assert "host" not in payload["error"].lower()