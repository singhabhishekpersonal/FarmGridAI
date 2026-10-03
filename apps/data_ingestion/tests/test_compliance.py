"""Compliance-check behavior tests (offline by default)."""
import pytest
from django.contrib.auth import get_user_model

from apps.data_ingestion.models import DataSource, SourceComplianceCheck
from apps.data_ingestion.services.compliance import run_compliance_check
from apps.data_ingestion.services.source_registry import (
    approve_source,
    register_source,
)


@pytest.fixture
def staff(db):
    return get_user_model().objects.create_user(username="auditor", password="Str0ng!", is_staff=True)


@pytest.fixture
def source(db):
    return register_source(
        name="Test Gov Portal",
        base_url="https://gov.example.in",
        source_type="government",
        category="subsidy",
        allowed_collection_methods=["api"],
    )


class TestComplianceOffline:
    def test_network_disabled_yields_manual_review(self, source):
        check = run_compliance_check(source)
        assert check is not None
        assert check.decision == SourceComplianceCheck.Decision.MANUAL_REVIEW
        assert "Network disabled" in check.notes
        assert check.robots_retrieved is False
        assert source.robots_status == DataSource.RobotsStatus.UNAVAILABLE
        assert source.last_compliance_check_at is not None

    def test_manual_import_source_no_automated_fetching(self, db):
        source = register_source(
            name="Manual corpus",
            base_url="manual://corpus",
            source_type="manual_import",
            category="equipment_images",
            allowed_collection_methods=["manual_import_only"],
        )
        check = run_compliance_check(source)
        assert check.decision == SourceComplianceCheck.Decision.MANUAL_REVIEW
        assert source.robots_status == DataSource.RobotsStatus.NOT_APPLICABLE
        assert source.terms_status == DataSource.TermsStatus.MANUAL_REVIEW

    def test_requires_human_approval_for_collection(self, source, staff):
        assert DataSource.objects.get(pk=source.pk).collection_enabled is False
        approve_source(source, staff, reason="reviewed manually")
        refreshed = DataSource.objects.get(pk=source.pk)
        assert refreshed.approval_status == DataSource.ApprovalStatus.APPROVED
        assert refreshed.approved_by == staff
        assert refreshed.collection_enabled is True

    def test_previous_check_counts(self, source):
        run_compliance_check(source)
        run_compliance_check(source)
        assert source.compliance_checks.count() == 2