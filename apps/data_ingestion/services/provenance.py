"""Provenance reporting: source -> run -> artifact -> record -> review.

The provenance report is the single source of truth for "where did this data
come from and what decisions were made about it". It is generated from
database records only (no file reads), so it is fully offline/testable.
"""
from pathlib import Path

from django.utils import timezone

from apps.data_ingestion.models import CollectedArtifact, DataReviewQueue, DataSource, ExtractedRecord, IngestionRun, SourceComplianceCheck


def _iso(when):
    return when.isoformat() if when else None


def _source_block(source):
    return {
        "id": str(source.pk),
        "name": source.name,
        "organization": source.organization,
        "base_url": source.base_url,
        "source_type": source.source_type,
        "category": source.category,
        "approval_status": source.approval_status,
        "approval_reason": source.approval_reason,
        "approved_by": getattr(source.approved_by, "username", ""),
        "approved_at": _iso(source.updated_at),
        "robots_status": source.robots_status,
        "terms_status": source.terms_status,
        "collection_enabled": source.collection_enabled,
        "license_url": source.license_url,
        "attribution_text": source.attribution_text,
    }


def artifact_provenance(artifact: CollectedArtifact):
    run = artifact.ingestion_run
    source = artifact.source
    record_count = artifact.records.count()
    return {
        "artifact": {
            "id": str(artifact.pk),
            "type": artifact.artifact_type,
            "sha256": artifact.sha256,
            "original_url": artifact.original_url,
            "final_url": artifact.final_url,
            "local_path": artifact.local_path,
            "retrieved_at": _iso(artifact.retrieved_at),
            "file_size": artifact.file_size,
            "is_approved": artifact.is_approved,
            "is_duplicate": artifact.is_duplicate,
            "validation_status": artifact.validation_status,
            "http_status": artifact.http_status,
            "records_extracted": record_count,
        },
        "source": _source_block(source),
        "run": {
            "run_id": run.run_id if run else "",
            "status": run.status if run else "",
            "started_at": _iso(run.started_at) if run else None,
            "collector_version": run.collector_version if run else "",
        },
    }


def record_provenance(record: ExtractedRecord, include_queue=True):
    queue = None
    if include_queue:
        queue = record.review_queue_entries.order_by("-created_at").first()
    return {
        "record": {
            "id": str(record.pk),
            "record_type": record.record_type,
            "content_hash": record.content_hash,
            "status": record.verification_status,
            "confidence": record.confidence,
            "source_url": record.source_url,
            "retrieved_at": _iso(record.retrieved_at),
            "reviewed_at": _iso(record.reviewed_at),
            "reviewer": getattr(record.reviewer, "username", ""),
        },
        "artifact": {
            "id": str(record.collected_artifact.pk) if record.collected_artifact else "",
            "sha256": record.collected_artifact.sha256 if record.collected_artifact else "",
            "url": record.collected_artifact.original_url if record.collected_artifact else "",
        },
        "source": _source_block(record.source),
        "run": {
            "run_id": record.ingestion_run.run_id if record.ingestion_run else "",
            "status": record.ingestion_run.status if record.ingestion_run else "",
        },
        "review_queue": _queue_block(queue) if queue else None,
    }


def source_history(source: DataSource):
    checks = [
        {
            "run_id": c.run_id,
            "checked_at": _iso(c.checked_at),
            "decision": c.decision,
            "robots_retrieved": c.robots_retrieved,
            "robots_allows": c.robots_allows_target_paths,
            "terms_manual_review": c.terms_manual_review_required,
            "blocked_reason": c.blocked_reason,
            "evidence_path": c.evidence_path,
            "evidence_hash": c.evidence_hash,
        }
        for c in source.compliance_checks.order_by("checked_at")
    ]
    runs = [
        {
            "run_id": r.run_id,
            "status": r.status,
            "started_at": _iso(r.started_at),
            "pages": r.pages_collected,
            "records": r.records_extracted,
            "duplicates": r.duplicates_skipped,
        }
        for r in source.runs.order_by("started_at")
    ]
    return {"source": _source_block(source), "compliance_checks": checks, "runs": runs}


def _queue_block(queue: DataReviewQueue):
    return {
        "id": str(queue.pk),
        "proposed_target_model": queue.proposed_target_model,
        "proposed_action": queue.proposed_action,
        "risk_level": queue.risk_level,
        "decision": queue.decision,
        "decided_by": getattr(queue.decided_by, "username", ""),
        "decided_at": _iso(queue.decided_at),
        "notes": queue.decision_notes,
    }


def write_provenance_report(model, report_dir=None):
    """Write a human-readable (Markdown) provenance report to disk."""
    if isinstance(model, CollectedArtifact):
        data = artifact_provenance(model)
        title = f"Artifact {model.sha256[:16]}"
    elif isinstance(model, ExtractedRecord):
        data = record_provenance(model)
        title = f"Record {str(model.pk)[:8]}"
    elif isinstance(model, DataSource):
        data = source_history(model)
        title = f"Source {model.name}"
    elif isinstance(model, IngestionRun):
        data = {
            "run": {
                "run_id": model.run_id,
                "status": model.status,
                "started_at": _iso(model.started_at),
                "completed_at": _iso(model.completed_at),
                "collector_version": model.collector_version,
            },
            "source": _source_block(model.source) if model.source else {},
            "pages_attempted": model.pages_attempted,
            "pages_collected": model.pages_collected,
            "records_extracted": model.records_extracted,
            "duplicates_skipped": model.duplicates_skipped,
            "warnings": model.warnings,
        }
        title = f"Run {model.run_id}"
    else:
        raise ValueError(f"unsupported model type {type(model).__name__}")

    lines = [f"# Provenance: {title}", "", f"Generated: {timezone.now().isoformat()}", ""]
    lines.extend(_markdown_lines(data))
    text = "\n".join(lines)

    if report_dir:
        base = Path(report_dir)
        base.mkdir(parents=True, exist_ok=True)
        name = f"provenance_{str(model.pk)[:12]}.md"
        (base / name).write_text(text, encoding="utf-8")
        return str(base / name)
    return text


def _markdown_lines(data, indent=0):
    lines = []
    prefix = "  " * indent
    for key, value in data.items():
        if isinstance(value, dict):
            lines.append(f"{prefix}- **{key}**")
            lines.extend(_markdown_lines(value, indent + 1))
        elif isinstance(value, list):
            lines.append(f"{prefix}- **{key}**")
            for item in value:
                if isinstance(item, dict):
                    lines.extend(_markdown_lines(item, indent + 1))
                else:
                    lines.append(f"{prefix}  - {item}")
        else:
            lines.append(f"{prefix}- **{key}**: {value}")
    return lines