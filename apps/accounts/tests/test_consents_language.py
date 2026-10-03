"""Regression tests for accounts consent/language fixes.

- ``granted="false"`` (a JSON string) was previously truthy, granting consent
  the farmer explicitly refused. The view now parses booleans strictly with
  ``_strict_bool``.
- Language preference save now uses ``update_fields=["preferred_language"]``
  (before, the implicit full save was fine but inconsistent).
"""

import pytest
from rest_framework.test import APIClient

from apps.accounts.models import ConsentRecord


@pytest.fixture
def user(db):
    from django.contrib.auth import get_user_model

    return get_user_model().objects.create_user(username="consentor", password="Str0ng!", phone="9876500301")


def test_granted_false_string_revokes_not_grants(user):
    client = APIClient()
    client.force_authenticate(user=user)
    client.post("/api/v1/auth/consents/", {"purpose": "expenses", "granted": True}, format="json")

    resp = client.post("/api/v1/auth/consents/", {"purpose": "expenses", "granted": "false"}, format="json")
    assert resp.status_code == 200, resp.content
    body = resp.json()
    assert body["success"] is True
    consent = ConsentRecord.objects.get(user=user, purpose=ConsentRecord.PURPOSE_EXPENSES)
    assert consent.granted is False
    assert consent.revoked_at is not None
    # A granted record must not have been re-created by the truthy string bug.
    assert ConsentRecord.objects.filter(user=user, purpose=ConsentRecord.PURPOSE_EXPENSES, granted=True).count() == 0


def test_unset_granted_defaults_to_grant(user):
    client = APIClient()
    client.force_authenticate(user=user)
    resp = client.post("/api/v1/auth/consents/", {"purpose": "profile"}, format="json")
    assert resp.status_code == 200, resp.content
    consent = ConsentRecord.objects.get(user=user, purpose=ConsentRecord.PURPOSE_PROFILE)
    assert consent.granted is True


def test_granted_true_string_grants(user):
    client = APIClient()
    client.force_authenticate(user=user)
    resp = client.post("/api/v1/auth/consents/", {"purpose": "location", "granted": "true"}, format="json")
    assert resp.status_code == 200, resp.content
    consent = ConsentRecord.objects.get(user=user, purpose=ConsentRecord.PURPOSE_LOCATION)
    assert consent.granted is True


def test_unknown_purpose_is_rejected(user):
    client = APIClient()
    client.force_authenticate(user=user)
    resp = client.post("/api/v1/auth/consents/", {"purpose": "data_selling", "granted": True}, format="json")
    assert resp.status_code == 400


def test_language_preference_accepts_hindi(user):
    client = APIClient()
    client.force_authenticate(user=user)
    resp = client.post("/api/v1/auth/language/", {"language_code": "hi"}, format="json")
    assert resp.status_code == 200, resp.content
    user.refresh_from_db()
    assert user.preferred_language == "hi"


def test_language_preference_rejects_unknown_codes(user):
    client = APIClient()
    client.force_authenticate(user=user)
    resp = client.post("/api/v1/auth/language/", {"language_code": "fr"}, format="json")
    assert resp.status_code == 400
