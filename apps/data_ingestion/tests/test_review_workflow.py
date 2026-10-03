"""Review-workflow tests: the human gate between extracted data and live tables."""
import pytest
from django.contrib.auth import get_user_model

from apps.data_ingestion.models import DataReviewQueue, DataSource, ExtractedRecord
from apps.data_ingestion.services.review_workflow import (
    ReviewWorkflowError,
    enqueue_record,
    publish,
    resolve,
)
from apps.data_ingestion.services.scheme_ingestion import ingest_scheme_payload
from apps.subsidies.models import SubsidyScheme


@pytest.fixture
def staff(db):
    return get_user_model().objects.create_user(username="reviewer", password="Str0ng!", is_staff=True)


@pytest.fixture
def source(db):
    return DataSource.objects.create(
        name="Gov API",
        base_url="https://api.gov.example.in",
        source_type="government_api",
        category="subsidy",
        approval_status=DataSource.ApprovalStatus.APPROVED,
    )


class TestEnqueue:
    def test_enqueue_creates_pending_item(self, source):
        record = ExtractedRecord.objects.create(
            source=source,
            record_type=ExtractedRecord.RecordType.SCHEME,
            normalized_data_json={},
            verification_status=ExtractedRecord.VerificationStatus.VALIDATED,
        )
        item = enqueue_record(
            record,
            proposed_target_model="SubsidyScheme",
            risk_level=DataReviewQueue.RiskLevel.HIGH,
            validation_result={"ok": True, "errors": [], "warnings": []},
        )
        assert item.decision == DataReviewQueue.Decision.PENDING
        assert item.requires_human_review is True


class TestResolve:
    def test_approve_records_decision(self, staff, source):
        record = ExtractedRecord.objects.create(source=source, record_type=ExtractedRecord.RecordType.SCHEME, normalized_data_json={})
        item = enqueue_record(record, validation_result={"ok": True})
        resolve(item, staff, decision=DataReviewQueue.Decision.APPROVED, notes="ok")
        item.refresh_from_db()
        assert item.decided_by == staff
        assert item.decision == DataReviewQueue.Decision.APPROVED

    def test_reject_marks_record_rejected(self, staff, source):
        record = ExtractedRecord.objects.create(source=source, record_type=ExtractedRecord.RecordType.SCHEME, normalized_data_json={})
        item = enqueue_record(record, validation_result={"ok": True})
        resolve(item, staff, decision=DataReviewQueue.Decision.REJECTED, notes="no")
        record.refresh_from_db()
        assert record.verification_status == ExtractedRecord.VerificationStatus.REJECTED


class TestPublishSubsidy:
    def test_publish_creates_illustrative_scheme(self, staff, source):
        record, ok, errors = ingest_scheme_payload(
            {
                "name": "Solar Pump Support Scheme",
                "status": "preliminary",
                "source_url": "https://api.gov.example.in/pump",
                "official_url": "https://api.gov.example.in/pump",
                "needs_official_verification": True,
            },
            source=source,
        )
        assert ok is True, errors
        item = record.review_queue_entries.get()
        resolve(item, staff, decision=DataReviewQueue.Decision.APPROVED, notes="verified by reviewer")
        publish(item, staff, notes="verified by reviewer")
        scheme = SubsidyScheme.objects.get(slug="solar-pump-support-scheme")
        assert scheme.is_illustrative is True
        assert "needs_official_verification" in scheme.notes

    def test_publish_requires_prior_human_approval(self, staff, source):
        record, ok, errors = ingest_scheme_payload(
            {
                "name": "Pending Scheme",
                "status": "preliminary",
                "source_url": "https://api.gov.example.in/pending",
                "needs_official_verification": True,
            },
            source=source,
        )
        assert ok is True, errors
        item = record.review_queue_entries.get()
        assert item.decision == DataReviewQueue.Decision.PENDING
        with pytest.raises(ReviewWorkflowError):
            publish(item, staff)
        assert not SubsidyScheme.objects.filter(slug="pending-scheme").exists()

    def test_publish_rejects_non_approved_decision(self, staff, source):
        record, ok, _ = ingest_scheme_payload(
            {"name": "Rejected Scheme", "status": "preliminary", "source_url": "https://api.gov.example.in/rejected"},
            source=source,
        )
        item = record.review_queue_entries.get()
        resolve(item, staff, decision=DataReviewQueue.Decision.REJECTED, notes="no")
        with pytest.raises(ReviewWorkflowError):
            publish(item, staff)

    def test_never_overwrite_existing_verified_scheme(self, staff, source):
        SubsidyScheme.objects.create(
            name="Verified Pump",
            slug="verified-pump",
            is_illustrative=False,
            is_active=True,
        )
        record, ok, _ = ingest_scheme_payload(
            {"name": "Verified Pump", "status": "preliminary", "source_url": "https://api.gov.example.in/pump"},
            source=source,
        )
        item = record.review_queue_entries.get()
        resolve(item, staff, decision=DataReviewQueue.Decision.APPROVED, notes="approved for update")
        note = None
        original = SubsidyScheme.objects.get(slug="verified-pump")
        publish(item, staff, notes="attempted update")
        same = SubsidyScheme.objects.get(slug="verified-pump")
        assert same.is_illustrative is False
        assert same.notes == original.notes

    def test_invalid_payload_cannot_publish(self, staff, source):
        record, ok, _ = ingest_scheme_payload(
            {"status": "preliminary"},  # no name -> validation failure
            source=source,
        )
        assert ok is False
        item = enqueue_record(record, validation_result={"ok": False, "errors": ["missing"]})
        with pytest.raises(ReviewWorkflowError):
            publish(item, staff)


class TestPublishCatalog:
    def test_publish_catalog_creates_item(self, staff, db):
        source = DataSource.objects.create(
            name="Mfr",
            base_url="https://mfr.example",
            source_type="official_manufacturer",
            category="equipment_catalog",
            approval_status=DataSource.ApprovalStatus.APPROVED,
        )
        from apps.data_ingestion.services.equipment_catalog_ingestion import ingest_catalog_item

        record, ok, _ = ingest_catalog_item(
            {"brand": "Make", "model": "M100", "hp": "42.0", "source_url": "https://mfr.example/m100"},
            source=source,
        )
        assert ok is True
        item = record.review_queue_entries.get()
        resolve(item, staff, decision=DataReviewQueue.Decision.APPROVED, notes="reviewed")
        publish(item, staff, notes="reviewed")
        from apps.equipment.models import EquipmentCatalog

        catalog = EquipmentCatalog.objects.get(brand="Make", model="M100")
        assert catalog.is_verified is False
        assert catalog.hp == 42.0