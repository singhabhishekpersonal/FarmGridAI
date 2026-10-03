"""Regression tests for the equipment image upload endpoint.

Covers the audit fix: the endpoint previously passed an ``UploadedFile``
object into ``reencode_image()`` (which expects bytes) and unpacked its
single ``bytes`` return as a ``(bytes, mime)`` tuple, so any real upload
crashed with a 500. It now validates size, extension and MIME before
re-encoding, and returns 400 for every invalid upload.
"""
import io

import pytest
from PIL import Image
from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from apps.equipment.models import EquipmentCategory, FarmerEquipment
from apps.farms.models import FarmService


@pytest.fixture
def user(db):
    from django.contrib.auth import get_user_model

    return get_user_model().objects.create_user(username="ramu", password="Str0ng!", phone="9876500001")


@pytest.fixture
def user_b(db):
    from django.contrib.auth import get_user_model

    return get_user_model().objects.create_user(username="shamu", password="Str0ng!", phone="9876500002")


@pytest.fixture
def farm(user, db):
    return FarmService.create_farm(user, "Photo Farm", area=2, unit="acre", state="Uttar Pradesh", district="Lucknow")


@pytest.fixture
def farm_b(user_b, db):
    return FarmService.create_farm(user_b, "Other Farm", area=2, unit="acre", state="Uttar Pradesh", district="Kanpur")


@pytest.fixture
def equipment(farm, db):
    category = EquipmentCategory.objects.create(code="tractor", name="Tractor")
    return FarmerEquipment.objects.create(farm=farm, category=category, is_owned=True)


def _png_bytes():
    buf = io.BytesIO()
    Image.new("RGB", (64, 48), "red").save(buf, format="PNG")
    return buf.getvalue()


def _upload(farm, equipment, payload_name, data, content_type):
    client = APIClient()
    client.force_authenticate(user=farm.user)
    return client.post(
        f"/api/v1/farms/{farm.id}/equipment/{equipment.id}/images",
        {payload_name: SimpleUploadedFile(name=data["name"], content=data.get("content", b""), content_type=content_type)},
        format="multipart",
    )


def test_valid_png_upload_returns_201(user, farm, equipment):
    resp = _upload(farm, equipment, "image", {"name": "photo.png", "content": _png_bytes(), "content_type": "image/png"}, "multipart/form-data")
    assert resp.status_code == 201, resp.content
    body = resp.json()
    assert body["success"] is True
    obj = FarmerEquipment.objects.get(id=equipment.id).images.get()
    assert obj.mime_type == "image/jpeg"
    assert obj.width == 64 and obj.height == 48
    assert obj.file_size > 0
    assert len(obj.content_hash) == 64


def test_unsupported_extension_rejected(user, farm, equipment):
    resp = _upload(farm, equipment, "image", {"name": "photo.txt", "content": _png_bytes()}, "multipart/form-data")
    assert resp.status_code == 400
    assert resp.json()["success"] is False


def test_corrupt_image_rejected(user, farm, equipment):
    resp = _upload(farm, equipment, "image", {"name": "photo.jpg", "content": b"not an image at all"}, "multipart/form-data")
    assert resp.status_code == 400
    assert resp.json()["success"] is False


def test_unsafe_mime_rejected(user, farm, equipment):
    gif = b"GIF89a" + b"\x00" * 32
    resp = _upload(farm, equipment, "image", {"name": "photo.gif", "content": gif, "content_type": "image/gif"}, "multipart/form-data")
    assert resp.status_code == 400
    assert resp.json()["success"] is False


def test_oversize_upload_rejected(user, farm, equipment):
    big = b"\x00" * (settings.MAX_UPLOAD_FILE_SIZE_MB * 1024 * 1024 + 1)
    resp = _upload(farm, equipment, "image", {"name": "photo.png", "content": big}, "multipart/form-data")
    assert resp.status_code == 400
    assert resp.json()["success"] is False


def test_foreign_farm_upload_is_404(user_b, farm, farm_b, equipment):
    client = APIClient()
    client.force_authenticate(user=user_b)
    resp = client.post(
        f"/api/v1/farms/{farm.id}/equipment/{equipment.id}/images",
        {"image": SimpleUploadedFile("photo.png", _png_bytes())},
        format="multipart",
    )
    assert resp.status_code == 404


def test_missing_file_is_400(user, farm, equipment):
    client = APIClient()
    client.force_authenticate(user=user)
    resp = client.post(
        f"/api/v1/farms/{farm.id}/equipment/{equipment.id}/images", {}, format="multipart"
    )
    assert resp.status_code == 400
    assert resp.json()["success"] is False