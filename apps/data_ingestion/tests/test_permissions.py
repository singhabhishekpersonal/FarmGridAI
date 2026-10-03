"""Permission tests for the data-ingestion API surface."""
import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient


@pytest.fixture
def plain_user(db):
    return get_user_model().objects.create_user(username="farmer", password="Str0ng!", phone="9876500009")


@pytest.fixture
def staff(db):
    return get_user_model().objects.create_user(username="ops", password="Str0ng!", phone="9876500010", is_staff=True)


class TestSourceListReadableByAuthenticated:
    def test_unauthenticated_denied(self):
        resp = APIClient().get("/api/v1/data-ingestion/sources")
        assert resp.status_code in (401, 403)

    def test_authenticated_user_can_list(self, plain_user):
        client = APIClient()
        client.force_authenticate(user=plain_user)
        resp = client.get("/api/v1/data-ingestion/sources")
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_any_authenticated_user_can_read_reports(self, plain_user):
        client = APIClient()
        client.force_authenticate(user=plain_user)
        resp = client.get("/api/v1/data-ingestion/dataset-report")
        assert resp.status_code == 200
        body = resp.json()
        assert "expanded_plan" in body["data"]


class TestStaffOnlyWrites:
    def test_non_staff_cannot_register_source(self, plain_user):
        client = APIClient()
        client.force_authenticate(user=plain_user)
        resp = client.post(
            "/api/v1/data-ingestion/sources",
            {"name": "X", "base_url": "https://x.example", "source_type": "public_dataset", "category": "subsidy"},
            format="json",
        )
        assert resp.status_code == 403

    def test_staff_can_register_source(self, staff):
        client = APIClient()
        client.force_authenticate(user=staff)
        resp = client.post(
            "/api/v1/data-ingestion/sources",
            {"name": "Approved API", "base_url": "https://api.secure.example.in", "source_type": "government_api", "category": "subsidy"},
            format="json",
        )
        assert resp.status_code == 201
        assert resp.json()["data"]["approval_status"] == "pending"

    def test_non_staff_cannot_run_compliance(self, plain_user, staff, db):
        from apps.data_ingestion.services.source_registry import register_source

        source = register_source(name="S", base_url="https://s.example", source_type="government", category="subsidy")
        client = APIClient()
        client.force_authenticate(user=plain_user)
        resp = client.post(f"/api/v1/data-ingestion/sources/{source.pk}/compliance-check", {}, format="json")
        assert resp.status_code == 403

    def test_non_staff_cannot_collect(self, plain_user, staff, db):
        from apps.data_ingestion.services.source_registry import register_source

        source = register_source(name="S", base_url="https://s.example", source_type="government", category="subsidy")
        client = APIClient()
        client.force_authenticate(user=plain_user)
        resp = client.post(
            f"/api/v1/data-ingestion/sources/{source.pk}/collect",
            {"image_urls": ["https://s.example/a.jpg"]},
            format="json",
        )
        assert resp.status_code == 403

    def test_non_staff_cannot_approve_queue_item(self, plain_user, staff, db):
        from apps.data_ingestion.models import DataReviewQueue, DataSource, ExtractedRecord

        source = DataSource.objects.create(
            name="T", base_url="https://t.example", source_type="government", category="subsidy",
            approval_status=DataSource.ApprovalStatus.APPROVED,
        )
        record = ExtractedRecord.objects.create(source=source, record_type="scheme", normalized_data_json={}, content_hash="x" * 32)
        item = DataReviewQueue.objects.create(extracted_record=record)
        client = APIClient()
        client.force_authenticate(user=plain_user)
        resp = client.post(f"/api/v1/data-ingestion/review-queue/{item.pk}/approve", {"notes": "nope"}, format="json")
        assert resp.status_code == 403


class TestStaffReviewActions:
    def test_staff_approves_queue_item(self, staff, db):
        from apps.data_ingestion.models import DataReviewQueue, DataSource, ExtractedRecord

        source = DataSource.objects.create(
            name="T", base_url="https://t.example", source_type="government", category="subsidy",
            approval_status=DataSource.ApprovalStatus.APPROVED,
        )
        record = ExtractedRecord.objects.create(source=source, record_type="scheme", normalized_data_json={}, content_hash="y" * 32)
        item = DataReviewQueue.objects.create(extracted_record=record)
        client = APIClient()
        client.force_authenticate(user=staff)
        resp = client.post(f"/api/v1/data-ingestion/review-queue/{item.pk}/approve", {"notes": "verified"}, format="json")
        assert resp.status_code == 200
        item.refresh_from_db()
        assert item.decision == DataReviewQueue.Decision.APPROVED
        assert item.decided_by == staff