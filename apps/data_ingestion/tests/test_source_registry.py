"""Data-source registry tests: registration + human-only approval."""
import pytest
from django.contrib.auth import get_user_model

from apps.data_ingestion.models import DataSource
from apps.data_ingestion.services.source_registry import (
    SourceRegistryError,
    approve_source,
    block_source,
    is_collectable,
    register_source,
    reject_source,
)


@pytest.fixture
def staff(db):
    return get_user_model().objects.create_user(username="admin1", password="Str0ng!", is_staff=True)


class TestRegisterSource:
    def test_registers_pending_source(self, db):
        source = register_source(
            name="Aggri Portal",
            base_url="https://agri.example.in",
            source_type="government",
            category="machinery_benchmark",
        )
        assert source.approval_status == DataSource.ApprovalStatus.PENDING
        assert source.collection_enabled is False
        assert source.rate_limit_per_minute >= 1

    def test_missing_name_rejected(self, db):
        with pytest.raises(SourceRegistryError):
            register_source(name="   ", base_url="https://x.example", source_type="government", category="subsidy")

    def test_zero_rate_limit_rejected(self, db):
        with pytest.raises(SourceRegistryError):
            register_source(
                name="S", base_url="https://x.example", source_type="government",
                category="subsidy", rate_limit_per_minute=0,
            )


class TestApprovalLifecycle:
    def test_approval_records_human_and_enables_collection(self, staff):
        source = register_source(name="D", base_url="https://d.example", source_type="public_dataset", category="equipment_images")
        assert not is_collectable(source)
        approve_source(source, staff, reason="explicit approval for testing")
        assert is_collectable(source)
        assert DataSource.objects.get(pk=source.pk).approved_by == staff

    def test_manual_import_is_not_automatically_collectable(self, staff):
        source = register_source(
            name="Corpus", base_url="manual://corpus", source_type="manual_import",
            category="equipment_images", allowed_collection_methods=["manual_import_only"],
        )
        approve_source(source, staff)
        assert is_collectable(source) is False  # manual imports never auto-collect

    def test_reject_revokes_collection(self, staff):
        source = register_source(name="R", base_url="https://r.example", source_type="public_dataset", category="subsidy")
        approve_source(source, staff)
        reject_source(source, staff, reason="terms forbade it")
        refreshed = DataSource.objects.get(pk=source.pk)
        assert refreshed.approval_status == DataSource.ApprovalStatus.REJECTED
        assert refreshed.collection_enabled is False
        assert is_collectable(refreshed) is False

    def test_block_quarantines_source(self, staff):
        source = register_source(name="B", base_url="https://b.example", source_type="public_dataset", category="subsidy")
        approve_source(source, staff)
        block_source(source, "captcha wall detected")
        assert DataSource.objects.get(pk=source.pk).approval_status == DataSource.ApprovalStatus.BLOCKED