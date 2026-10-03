"""Factory helpers: validated ExtractedRecord + review-queue entries."""
import logging

from apps.data_ingestion.models import DataReviewQueue, ExtractedRecord
from apps.data_ingestion.services.hashing import short_hash
from apps.data_ingestion.services.review_workflow import enqueue_record
from apps.data_ingestion.services.validation import validate_extracted_record_payload

logger = logging.getLogger("khetsathi.audit")

_RISK_BY_TYPE = {
    ExtractedRecord.RecordType.SCHEME: DataReviewQueue.RiskLevel.HIGH,
    ExtractedRecord.RecordType.CROP_BENCHMARK: DataReviewQueue.RiskLevel.MEDIUM,
    ExtractedRecord.RecordType.ENERGY_BENCHMARK: DataReviewQueue.RiskLevel.MEDIUM,
    ExtractedRecord.RecordType.DIESEL_BENCHMARK: DataReviewQueue.RiskLevel.MEDIUM,
    ExtractedRecord.RecordType.MACHINERY_BENCHMARK: DataReviewQueue.RiskLevel.MEDIUM,
    ExtractedRecord.RecordType.EQUIPMENT_SPEC: DataReviewQueue.RiskLevel.MEDIUM,
    ExtractedRecord.RecordType.EQUIPMENT_IMAGE: DataReviewQueue.RiskLevel.LOW,
    ExtractedRecord.RecordType.CATALOG_ITEM: DataReviewQueue.RiskLevel.MEDIUM,
    ExtractedRecord.RecordType.OTHER: DataReviewQueue.RiskLevel.MEDIUM,
}

_TARGET_BY_TYPE = {
    ExtractedRecord.RecordType.SCHEME: "SubsidyScheme",
    ExtractedRecord.RecordType.CATALOG_ITEM: "EquipmentCatalog",
    ExtractedRecord.RecordType.EQUIPMENT_SPEC: "EquipmentCatalog",
}


def create_validated_record(
    *,
    record_type,
    payload,
    source,
    ingestion_run=None,
    collected_artifact=None,
    source_url="",
    confidence="low",
    target_model=None,
    queue=True,
):
    """Validate ``payload``, create an :class:`ExtractedRecord`, and enqueue.

    Returns ``(record, validation_passed:bool, errors:list)``. Records are
    created regardless of validation outcome so nothing is silently dropped,
    but only passing records reach the review queue.
    """
    result = validate_extracted_record_payload(record_type, payload or {})
    content_hash = short_hash((source.base_url + source_url + str(payload)).encode("utf-8"), 32)

    record = ExtractedRecord.objects.create(
        source=source,
        ingestion_run=ingestion_run,
        collected_artifact=collected_artifact,
        record_type=record_type,
        normalized_data_json=payload or {},
        raw_data_json=payload.get("_raw", {}) if isinstance(payload, dict) else {},
        source_url=source_url or "",
        source_locator=payload.get("locator", "") if isinstance(payload, dict) else "",
        content_hash=content_hash,
        confidence=confidence,
        verification_status=(
            ExtractedRecord.VerificationStatus.VALIDATED if result["ok"] else ExtractedRecord.VerificationStatus.RAW
        ),
    )
    if result["ok"] and queue:
        target_model = target_model or _TARGET_BY_TYPE.get(record_type, "")
        risk = _RISK_BY_TYPE.get(record_type, DataReviewQueue.RiskLevel.MEDIUM)
        enqueue_record(
            record,
            proposed_target_model=target_model,
            proposed_action=DataReviewQueue.ProposedAction.CREATE,
            risk_level=risk,
            validation_result={"ok": True, "errors": [], "warnings": result["warnings"]},
        )
        logger.info("record created+queued type=%s hash=%s ok=%s", record_type, content_hash[:10], result["ok"])
    return record, result["ok"], result["errors"]