"""Human-review workflow and guarded publication to live domain models.

This is the **only** code path that may copy extracted/validated records into
live tables (``SubsidyScheme``, ``EquipmentCatalog``). It enforces:

* nothing is published without an explicit human approval recorded in
  :class:`DataReviewQueue`;
* subsidy schemes are always published ``is_illustrative=True`` with
  ``needs_official_verification=True`` and never overwrite verified/active
  values;
* every decision is written to the audit log.
"""
import logging
from datetime import date

from django.utils import timezone

from apps.data_ingestion.models import DataReviewQueue, ExtractedRecord
from apps.data_ingestion.services.validation import validate_extracted_record_payload

logger = logging.getLogger("khetsathi.audit")


class ReviewWorkflowError(Exception):
    pass


def _strict_bool(value, default=False):
    """Parse a boolean without treating the string 'false' as True."""
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def enqueue_record(
    extracted_record,
    *,
    proposed_target_model="",
    proposed_action=DataReviewQueue.ProposedAction.CREATE,
    risk_level=DataReviewQueue.RiskLevel.MEDIUM,
    validation_result=None,
    requires_human_review=True,
    source_freshness_status="unverified",
    justification="",
):
    validation_result = validation_result or {}
    if justification and not validation_result.get("ok"):
        validation_result.setdefault("warnings", []).append(justification)
    return DataReviewQueue.objects.create(
        extracted_record=extracted_record,
        proposed_target_model=proposed_target_model,
        proposed_action=proposed_action,
        risk_level=risk_level,
        validation_result=validation_result,
        requires_human_review=requires_human_review,
        source_freshness_status=source_freshness_status,
    )


def resolve(queue_item, user, decision=DataReviewQueue.Decision.APPROVED, notes=""):
    """Record a human decision on a queue item (no publication)."""
    if decision not in {DataReviewQueue.Decision.APPROVED, DataReviewQueue.Decision.REJECTED, DataReviewQueue.Decision.NEEDS_CHANGES}:
        raise ReviewWorkflowError(f"invalid decision {decision}")
    queue_item.decision = decision
    queue_item.decided_by = user
    queue_item.decided_at = timezone.now()
    queue_item.decision_notes = notes
    queue_item.save(update_fields=["decision", "decided_by", "decided_at", "decision_notes", "updated_at"])
    if decision == DataReviewQueue.Decision.REJECTED:
        record = queue_item.extracted_record
        record.verification_status = ExtractedRecord.VerificationStatus.REJECTED
        record.reviewer = user
        record.reviewed_at = timezone.now()
        record.review_notes = notes
        record.save(update_fields=["verification_status", "reviewer", "reviewed_at", "review_notes", "updated_at"])
    logger.info("review decision id=%s decision=%s by=%s notes=%r", queue_item.pk, decision, user, notes[:200])
    return queue_item


def publish(queue_item, user, notes=""):
    """Copy validated data into the target live model after an explicit approval.

    Publishing is the *second* half of a two-step human gate: the queue item
    must already carry an APPROVED decision recorded by a logged-in human via
    :func:`resolve`. This service never self-approves.
    """
    if queue_item.decision != DataReviewQueue.Decision.APPROVED:
        raise ReviewWorkflowError("queue item must be resolved as APPROVED by a human before publishing")
    if user is None or not queue_item.decided_by or not queue_item.decided_at:
        raise ReviewWorkflowError("a logged-in human decision is required before publishing")

    validation_result = queue_item.validation_result or {}
    if validation_result.get("ok") is False:
        raise ReviewWorkflowError("cannot publish: record failed validation")

    if queue_item.requires_human_review and user is None:
        raise ReviewWorkflowError("requires_human_review item must be published by a logged-in user")

    record = queue_item.extracted_record
    target = queue_item.proposed_target_model or ""

    published_note = _publish_to_target(record, queue_item.proposed_action, payload=record.normalized_data_json, target=target)

    queue_item.proposed_action = queue_item.proposed_action
    queue_item.decision = DataReviewQueue.Decision.APPROVED
    queue_item.decision_notes = (notes or "") + (" " + published_note if published_note else "")
    queue_item.decided_by = user
    queue_item.decided_at = timezone.now()
    queue_item.save(update_fields=["decision", "decision_notes", "decided_by", "decided_at", "updated_at"])

    record.verification_status = ExtractedRecord.VerificationStatus.PUBLISHED
    record.reviewer = user
    record.reviewed_at = timezone.now()
    record.review_notes = (record.review_notes or "") + (" " + published_note if published_note else "")
    record.save(update_fields=["verification_status", "reviewer", "reviewed_at", "review_notes", "updated_at"])

    logger.info("published queue id=%s target=%s action=%s by=%s", queue_item.pk, target, queue_item.proposed_action, user)
    return queue_item


def _publish_to_target(record, action, payload, target):
    if target == "SubsidyScheme":
        return _publish_subsidy(record, payload)
    if target == "EquipmentCatalog":
        return _publish_catalog(record, payload)
    return "published as validated record (no live domain table for '%s')" % target


def _publish_subsidy(record, payload):
    from apps.subsidies.models import SubsidyScheme

    validation = validate_extracted_record_payload("scheme", payload)
    if not validation["ok"]:
        raise ReviewWorkflowError("subsidy payload failed validation: %s" % validation["errors"])

    slug = _slugify(payload.get("name") or "")
    if not slug:
        raise ReviewWorkflowError("subsidy payload is missing a name")

    existing = SubsidyScheme.objects.filter(slug=slug).first()
    if existing and not existing.is_illustrative:
        # Never overwrite a verified/active scheme. Keep ours queued as a note.
        return "EXISTING VERIFIED SCHEME left untouched (slug=%s); collected value deferred" % slug

    defaults = {
        "name": payload.get("name") or "",
        "category": payload.get("category") or "farm_mechanization",
        "administrative_level": payload.get("administrative_level") or "central",
        "state": payload.get("state") or "",
        "official_url": payload.get("official_url") or payload.get("source_url") or "",
        "is_active": _strict_bool(payload.get("is_active", True)),
        "notes": record.review_notes or "",
        "is_illustrative": True,
        "scheme_version": payload.get("scheme_version") or "1.0",
    }
    for field in ("benefit_min_inr", "benefit_max_inr"):
        if field in payload:
            defaults[field] = payload[field]
    if payload.get("effective_from"):
        defaults["effective_from"] = payload["effective_from"]
    if payload.get("effective_to"):
        defaults["effective_to"] = payload["effective_to"]
    defaults["notes"] = (
        f"verification_status=preliminary; needs_official_verification; "
        f"source={payload.get('source_url', '')}"
    )

    if existing:
        for key, value in defaults.items():
            if not getattr(existing, key):
                setattr(existing, key, value)
        existing.save()
        return "updated illustrative scheme (slug=%s, is_illustrative kept True)" % slug

    SubsidyScheme.objects.create(slug=slug, **defaults)
    return "created illustrative scheme (slug=%s)" % slug


def _publish_catalog(record, payload):
    from apps.equipment.models import EquipmentCatalog

    brand = (payload.get("brand") or "").strip()
    model = (payload.get("model") or "").strip()
    if not brand or not model:
        raise ReviewWorkflowError("catalog payload requires brand + model")

    category = _catalog_category(record.source.category)
    existing = EquipmentCatalog.objects.filter(brand=brand, model=model).first()
    if existing:
        return "EXISTING catalog item (brand=%s model=%s) left untouched" % (brand, model)

    EquipmentCatalog.objects.create(
        category=category,
        brand=brand[:80],
        model=model[:120],
        hp=payload.get("hp"),
        price_min=payload.get("price_min"),
        price_max=payload.get("price_max"),
        price_expected=payload.get("price_expected"),
        fuel_type=payload.get("fuel_type") or "",
        drive_type=payload.get("drive_type") or "",
        image_url=payload.get("image_url") or "",
        source_url=payload.get("source_url") or record.source.base_url,
        source=_catalog_source(record.source),
        is_verified=False,
        is_synthetic_benchmark=False,
    )
    return "created catalog item (brand=%s model=%s)" % (brand, model)


def _catalog_source(source):
    from apps.core.constants import DataSource

    if source.source_type in {
        "government",
        "government_api",
        "official_manufacturer",
    }:
        return DataSource.OFFICIAL
    return DataSource.BENCHMARK


def _catalog_category(source_category):
    from apps.equipment.models import EquipmentCategory

    code = "tractor"
    mapping = {
        "equipment_catalog": code,
        "equipment_images": code,
        "machinery_benchmark": code,
        "subsidy": "implement",
    }
    code = mapping.get(source_category, code)
    category = EquipmentCategory.objects.filter(code=code).first()
    if category is None:
        category, _ = EquipmentCategory.objects.get_or_create(
            code=code, defaults={"name": code.replace("_", " ").title(), "is_synthetic_benchmark": True}
        )
    return category


def _slugify(value):
    import re

    value = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return value[:160]