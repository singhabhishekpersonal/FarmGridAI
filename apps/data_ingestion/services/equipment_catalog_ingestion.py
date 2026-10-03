"""Equipment catalogue / specification ingestion.

Structured catalogue items (from approved sources or manual imports) are
validated and enqueued before they may land in ``EquipmentCatalog``.
"""
from apps.data_ingestion.models import ExtractedRecord
from apps.data_ingestion.services.record_factory import create_validated_record


def ingest_catalog_item(payload, *, source, ingestion_run=None, collected_artifact=None, source_url="", confidence="low"):
    """Validate + enqueue a single catalogue item."""
    payload = dict(payload or {})
    if "source_url" not in payload and source_url:
        payload["source_url"] = source_url
    return create_validated_record(
        record_type=ExtractedRecord.RecordType.CATALOG_ITEM,
        payload=payload,
        source=source,
        ingestion_run=ingestion_run,
        collected_artifact=collected_artifact,
        source_url=source_url or payload.get("source_url", ""),
        confidence=confidence,
        target_model="EquipmentCatalog",
    )


def ingest_catalogue(categories, brand, *, base_source, ingestion_run=None, collected_artifact=None, confidence="low"):
    """Ingest a catalogue object keyed by category (baseline for import commands)."""
    records = []
    for category, items in (categories or {}).items():
        for item in items or []:
            payload = {"category": category, "brand": brand}
            payload.update(item or {})
            records.append(
                ingest_catalog_item(
                    payload,
                    source=base_source,
                    ingestion_run=ingestion_run,
                    collected_artifact=collected_artifact,
                    source_url=item.get("source_url", "") if isinstance(item, dict) else "",
                    confidence=confidence,
                )
            )
    return records