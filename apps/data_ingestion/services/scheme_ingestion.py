"""Government subsidy scheme ingestion.

Applies the subsidy data-safety rules: every scheme payload must carry
``status=preliminary`` (or explicitly labeled), ``needs_official_verification``
and an official ``source_url``. Records always enter the review queue as
HIGH risk — publication is never automatic.
"""
from apps.data_ingestion.models import ExtractedRecord
from apps.data_ingestion.services.record_factory import create_validated_record


def ingest_scheme_payload(payload, *, source, ingestion_run=None, collected_artifact=None, source_url="", confidence="low"):
    """Validate + enqueue a single subsidy scheme record."""
    payload = dict(payload or {})
    payload.setdefault("status", payload.get("status") or "preliminary")
    payload.setdefault("needs_official_verification", True)
    if "scheme_version" not in payload:
        payload["scheme_version"] = "1.0"
    if "last_verified_at" not in payload:
        payload["last_verified_at"] = ""
    if source_url:
        payload.setdefault("official_url", source_url)
    return create_validated_record(
        record_type=ExtractedRecord.RecordType.SCHEME,
        payload=payload,
        source=source,
        ingestion_run=ingestion_run,
        collected_artifact=collected_artifact,
        source_url=source_url or payload.get("source_url", ""),
        confidence=confidence,
        target_model="SubsidyScheme",
    )


def ingest_scheme_export(rows, *, source, ingestion_run=None, collected_artifact=None, confidence="low"):
    """Ingest many scheme rows (from a JSON/CSV/published export)."""
    records = []
    for item in rows:
        if not isinstance(item, dict):
            continue
        records.append(
            ingest_scheme_payload(
                item,
                source=source,
                ingestion_run=ingestion_run,
                collected_artifact=collected_artifact,
                source_url=item.get("source_url", ""),
                confidence=confidence,
            )
        )
    return records