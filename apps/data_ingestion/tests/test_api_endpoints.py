"""End-to-end API behavior tests for the data-ingestion endpoints.

Verifies the register -> approve -> dry-run collect -> dataset-report flow and
the review publish round-trip through the HTTP surface.
"""
import io

import pytest
from PIL import Image
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.data_ingestion.models import CollectedArtifact, DataSource, ExtractedRecord
from apps.data_ingestion.services.source_registry import approve_source, register_source


@pytest.fixture
def staff(db):
    return get_user_model().objects.create_user(username="ops2", password="Str0ng!", is_staff=True)


@pytest.fixture
def client(staff):
    client = APIClient()
    client.force_authenticate(user=staff)
    return client


def _png():
    """Deterministic high-contrast textured PNG that clears blur/brightness gates."""
    import numpy as np

    height, width = (420, 500)
    rng = np.random.default_rng(11)
    block = 8
    blocks = rng.integers(-120, 121, size=(height // block + 1, width // block + 1, 3))
    arr = np.zeros((height, width, 3), dtype=np.int16)
    for channel in range(3):
        tile = np.repeat(np.repeat(blocks[:, :, channel], block, 0), block, 1)[:height, :width]
        arr[:, :, channel] = 140 + tile
    arr = np.clip(arr, 0, 255).astype(np.uint8)
    buf = io.BytesIO()
    Image.fromarray(arr).save(buf, format="PNG")
    return buf.getvalue()


class TestRegisterAndApprovalFlow:
    def test_register_then_approve_via_admin_service(self, client, staff):
        resp = client.post(
            "/api/v1/data-ingestion/sources",
            {
                "name": "Manual corpus B",
                "base_url": "manual://corpus-b",
                "source_type": "manual_import",
                "category": "equipment_images",
                "allowed_collection_methods": ["manual_import_only"],
            },
            format="json",
        )
        assert resp.status_code == 201
        source = DataSource.objects.get(pk=resp.json()["data"]["pk"])
        assert source.approval_status == DataSource.ApprovalStatus.PENDING
        approve_source(source, staff)
        assert source.collection_enabled is True


class TestDryRunCollect:
    def test_dry_run_collect_never_persists(self, client, staff, db):
        source = register_source(
            name="Approved imgs",
            base_url="https://img.example.in",
            source_type="official_manufacturer",
            category="equipment_images",
        )
        approve_source(source, staff)
        resp = client.post(
            f"/api/v1/data-ingestion/sources/{source.pk}/collect",
            {"image_urls": ["https://img.example.in/1.jpg"], "execute": False},
            format="json",
        )
        assert resp.status_code == 200
        assert resp.json()["data"]["dry_run"] is True
        assert CollectedArtifact.objects.filter(source=source).count() == 0


class TestDatasetReport:
    def test_dataset_report_returns_plan(self, client, db):
        resp = client.get("/api/v1/data-ingestion/dataset-report")
        assert resp.status_code == 200
        data = resp.json()["data"]
        rows = {row["label"]: row for row in data["expanded_plan"]["rows"]}
        assert "Mahindra" in rows
        assert rows["Mahindra"]["target"] == 150
        assert data["expanded_plan"]["auto_actions_taken"] == []


class TestReviewPublishFlow:
    def test_publish_subsidy_through_api_creates_illustrative_scheme(self, client, staff, db):
        from apps.data_ingestion.services.scheme_ingestion import ingest_scheme_payload

        source = DataSource.objects.create(
            name="Gov pump API",
            base_url="https://pump.gov.example.in",
            source_type="government_api",
            category="subsidy",
            approval_status=DataSource.ApprovalStatus.APPROVED,
        )
        record, ok, _ = ingest_scheme_payload(
            {"name": "Well Pump Aid", "status": "preliminary", "source_url": "https://pump.gov.example.in/aid"},
            source=source,
        )
        assert ok is True
        item = record.review_queue_entries.get()
        resp = client.post(f"/api/v1/data-ingestion/review-queue/{item.pk}/approve", {"notes": "reviewed live"}, format="json")
        assert resp.status_code == 200
        resp = client.post(f"/api/v1/data-ingestion/review-queue/{item.pk}/publish", {"notes": "verified live"}, format="json")
        assert resp.status_code == 200
        from apps.subsidies.models import SubsidyScheme

        scheme = SubsidyScheme.objects.get(slug="well-pump-aid")
        assert scheme.is_illustrative is True


class TestManualImportAPI:
    def test_manual_import_from_server_folder(self, client, staff, tmp_path, db):
        source = register_source(
            name="Local api corpus",
            base_url="manual://local-api-corpus",
            source_type="manual_import",
            category="equipment_images",
            allowed_collection_methods=["manual_import_only"],
        )
        approve_source(source, staff)
        folder = tmp_path / "Mahindra"
        folder.mkdir()
        (folder / "a.png").write_bytes(_png())
        resp = client.post(
            "/api/v1/data-ingestion/manual-import",
            {"source_id": str(source.pk), "path": str(folder), "label_hint": "Mahindra"},
            format="json",
        )
        assert resp.status_code == 200
        assert resp.json()["data"]["imported"] == 1
        record = ExtractedRecord.objects.get(source=source, record_type="equipment_image")
        assert record.normalized_data_json["label_hint"] == "Mahindra"
        assert record.verification_status == ExtractedRecord.VerificationStatus.RAW