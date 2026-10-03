"""Data-source registry operations.

Approval decisions are **explicitly human actions**: ``approve_source`` always
records ``approved_by`` + an off-by-default ``collection_enabled`` flag. No
automated pipeline may approve a source.
"""
import logging

from django.utils import timezone

from apps.data_ingestion.models import DataSource

logger = logging.getLogger("khetsathi.audit")


class SourceRegistryError(Exception):
    pass


def register_source(
    *,
    name,
    base_url,
    source_type,
    category,
    organization="",
    geographic_scope="",
    country="IN",
    state="",
    district="",
    allowed_collection_methods=None,
    robots_url="",
    terms_url="",
    license_url="",
    attribution_text="",
    rate_limit_per_minute=None,
    request_delay_seconds=None,
    max_pages_per_run=None,
    allows_images=False,
    allows_documents=False,
    allows_structured_data=False,
    notes="",
    created_by=None,
):
    """Create a :class:`DataSource` in the ``pending`` state."""
    if not name.strip():
        raise SourceRegistryError("name is required")
    if not base_url.strip():
        raise SourceRegistryError("base_url is required")
    if rate_limit_per_minute is None:
        rate_limit_per_minute = 10
    if rate_limit_per_minute < 1:
        raise SourceRegistryError("rate_limit_per_minute must be >= 1")
    request_delay_seconds = request_delay_seconds if request_delay_seconds is not None else 1.0
    max_pages_per_run = max_pages_per_run or 20

    source = DataSource.objects.create(
        name=name.strip(),
        organization=organization.strip(),
        base_url=base_url.strip(),
        source_type=source_type,
        category=category,
        geographic_scope=geographic_scope,
        country=country,
        state=state,
        district=district,
        allowed_collection_methods=allowed_collection_methods or [],
        robots_url=robots_url.strip(),
        terms_url=terms_url.strip(),
        license_url=license_url.strip(),
        attribution_text=attribution_text,
        rate_limit_per_minute=rate_limit_per_minute,
        request_delay_seconds=request_delay_seconds,
        max_pages_per_run=max_pages_per_run,
        allows_images=allows_images,
        allows_documents=allows_documents,
        allows_structured_data=allows_structured_data,
        notes=notes,
        created_by=created_by,
    )
    logger.info("data source registered name=%s url=%s type=%s", source.name, source.base_url, source.source_type)
    return source


def approve_source(source, user, reason="", enable_collection=True):
    """Human approval of a source. Records the approver and audit event."""
    source.approval_status = DataSource.ApprovalStatus.APPROVED
    source.approved_by = user
    source.approval_reason = reason
    source.collection_enabled = bool(enable_collection)
    source.save(update_fields=["approval_status", "approved_by", "approval_reason", "collection_enabled", "updated_at"])
    logger.info("data source APPROVED id=%s by=%s reason=%r", source.pk, user, reason[:200])
    return source


def reject_source(source, user, reason):
    source.approval_status = DataSource.ApprovalStatus.REJECTED
    source.approval_reason = reason
    source.collection_enabled = False
    source.save(update_fields=["approval_status", "approval_reason", "collection_enabled", "updated_at"])
    logger.info("data source REJECTED id=%s by=%s reason=%r", source.pk, user, reason[:200])
    return source


def block_source(source, reason):
    source.approval_status = DataSource.ApprovalStatus.BLOCKED
    source.approval_reason = reason
    source.collection_enabled = False
    source.save(update_fields=["approval_status", "approval_reason", "collection_enabled", "updated_at"])
    logger.info("data source BLOCKED id=%s reason=%r", source.pk, reason[:200])
    return source


def mark_manual_review(source, note=""):
    source.approval_status = DataSource.ApprovalStatus.MANUAL_REVIEW
    source.approval_reason = note
    source.collection_enabled = False
    source.save(update_fields=["approval_status", "approval_reason", "collection_enabled", "updated_at"])
    return source


def is_collectable(source):
    """True only for explicitly approved, collection-enabled, non-manual sources."""
    return (
        source.approval_status == DataSource.ApprovalStatus.APPROVED
        and source.collection_enabled
        and source.source_type != DataSource.SourceType.MANUAL_IMPORT
    )