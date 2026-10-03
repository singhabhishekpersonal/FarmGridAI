"""Benchmark ingestion for crops / machinery / solar / electricity / diesel.

Benchmark records are informational; they never drive arithmetic on their own.
Every numeric benchmark requires ``source_url`` + an explicit ``is_estimate``
flag and enters the review queue before anything may reference it.
"""
from apps.data_ingestion.models import ExtractedRecord
from apps.data_ingestion.services.record_factory import create_validated_record

_BENCHMARK_RECORD_TYPE = {
    "crop_benchmark": ExtractedRecord.RecordType.CROP_BENCHMARK,
    "machinery_benchmark": ExtractedRecord.RecordType.MACHINERY_BENCHMARK,
    "solar_benchmark": ExtractedRecord.RecordType.ENERGY_BENCHMARK,
    "electricity_benchmark": ExtractedRecord.RecordType.ENERGY_BENCHMARK,
    "diesel_benchmark": ExtractedRecord.RecordType.DIESEL_BENCHMARK,
}


def ingest_benchmark_payload(kind, payload, *, source, ingestion_run=None, collected_artifact=None, source_url="", confidence="low"):
    """Validate + enqueue a single benchmark record for ``kind``."""
    if kind not in _BENCHMARK_RECORD_TYPE:
        raise ValueError(f"unknown benchmark kind {kind!r}")
    record_type = _BENCHMARK_RECORD_TYPE[kind]
    payload = dict(payload or {})
    if payload.get("is_estimate") is not True:
        payload["is_estimate"] = True
    payload.setdefault("indicator", kind)
    if "source_url" not in payload and source_url:
        payload["source_url"] = source_url
    return create_validated_record(
        record_type=record_type,
        payload=payload,
        source=source,
        ingestion_run=ingestion_run,
        collected_artifact=collected_artifact,
        source_url=source_url or payload.get("source_url", ""),
        confidence=confidence,
    )


def ingest_benchmark_rows(kind, rows, *, source, ingestion_run=None, collected_artifact=None, confidence="low"):
    """Ingest many benchmark rows of one kind."""
    records = []
    for item in rows:
        if not isinstance(item, dict):
            continue
        records.append(
            ingest_benchmark_payload(
                kind,
                item,
                source=source,
                ingestion_run=ingestion_run,
                collected_artifact=collected_artifact,
                source_url=item.get("source_url", ""),
                confidence=confidence,
            )
        )
    return records