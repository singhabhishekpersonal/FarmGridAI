"""Regression tests for the farm soft-delete fix.

The audit found ``FarmDetailView.delete`` called
``self.get_object().delete(updated_by=request.user)`` where ``Farm.delete``
(soft delete) does not accept an ``updated_by`` kwarg -> TypeError/500 on
every farm deletion. The fix soft-deletes through ``farm.delete()`` and then
stamps ``updated_by`` via ``Farm.all_objects``.
"""

import pytest
from rest_framework.test import APIClient

from apps.farms.models import Farm, FarmService


@pytest.fixture
def user(db):
    from django.contrib.auth import get_user_model

    return get_user_model().objects.create_user(username="deler", password="Str0ng!", phone="9876500201")


def test_farm_delete_soft_deletes_and_stamps_updated_by(user):
    farm = FarmService.create_farm(user, "Doomed Farm", area=2, unit="acre", state="Uttar Pradesh")
    client = APIClient()
    client.force_authenticate(user=user)

    resp = client.delete(f"/api/v1/farms/{farm.id}")
    assert resp.status_code == 200, resp.content

    # Default manager hides the deleted farm; all_objects keeps the row.
    assert Farm.objects.filter(pk=farm.id).exists() is False
    deleted = Farm.all_objects.get(pk=farm.id)
    assert deleted.deleted_at is not None
    assert deleted.is_active is False
    assert deleted.updated_by == user


def test_farm_delete_then_detail_is_404(user):
    farm = FarmService.create_farm(user, "Gone Farm", area=1, unit="acre", state="Uttar Pradesh")
    client = APIClient()
    client.force_authenticate(user=user)
    client.delete(f"/api/v1/farms/{farm.id}")
    resp = client.get(f"/api/v1/farms/{farm.id}")
    assert resp.status_code == 404


def test_foreign_farm_delete_is_404(user):
    from django.contrib.auth import get_user_model

    other = get_user_model().objects.create_user(username="notmine", password="Str0ng!", phone="9876500202")
    farm = FarmService.create_farm(user, "Mine Farm", area=1, unit="acre", state="Uttar Pradesh")
    client = APIClient()
    client.force_authenticate(user=other)
    resp = client.delete(f"/api/v1/farms/{farm.id}")
    assert resp.status_code == 404
    assert Farm.all_objects.get(pk=farm.id).deleted_at is None