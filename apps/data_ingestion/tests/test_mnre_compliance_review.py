"""Offline guard tests for the MNRE compliance-only review command (no network)."""
import pytest
from django.core.management import CommandError, call_command

from apps.data_ingestion.management.commands import mnre_compliance_review
from apps.data_ingestion.services.source_registry import register_source


def test_host_lock_refuses_non_mnre_source(db):
    other = register_source(
        name="Other",
        base_url="https://example.gov.in/",
        source_type="government",
        category="subsidy",
    )
    with pytest.raises(CommandError, match="refusing"):
        call_command("mnre_compliance_review", "--source-id", str(other.pk), "--operator-user", "x")


def test_refuses_when_network_disabled(db):
    mnre = register_source(
        name="MNRE",
        base_url=mnre_compliance_review.MNRE_BASE,
        source_type="government",
        category="solar_benchmark",
    )
    with pytest.raises(CommandError, match="NETWORK_ALLOWED"):
        call_command("mnre_compliance_review", "--source-id", str(mnre.pk), "--operator-user", "x")


def test_approved_host_constant_is_https_mnre():
    assert mnre_compliance_review.MNRE_BASE == "https://mnre.gov.in/"
    assert mnre_compliance_review.ALLOWED_HOST == "mnre.gov.in"
    assert mnre_compliance_review.MAX_REQUESTS == 5