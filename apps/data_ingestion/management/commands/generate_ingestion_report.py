"""Generate a full ingestion status report (JSON + Markdown) for the audit trail."""
import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from apps.data_ingestion.models import (
    CollectedArtifact,
    DataReviewQueue,
    DataSource,
    ExtractedRecord,
    IngestionRun,
    SourceComplianceCheck,
)
from apps.data_ingestion.services.provenance import source_history


class Command(BaseCommand):
    help = "Generate a consolidated ingestion status report and write it to disk."

    def add_arguments(self, parser):
        parser.add_argument("--out", default="", help="Output directory (default: DATA_INGESTION_DATA_DIR/reports).")

    def handle(self, *args, **options):
        report = {
            "sources_total": DataSource.objects.count(),
            "sources_by_status": _counts(DataSource, "approval_status"),
            "sources_by_category": _counts(DataSource, "category"),
            "compliance_checks_total": SourceComplianceCheck.objects.count(),
            "runs_total": IngestionRun.objects.count(),
            "runs_by_status": _counts(IngestionRun, "status"),
            "artifacts_total": CollectedArtifact.objects.count(),
            "artifacts_by_type": _counts(CollectedArtifact, "artifact_type"),
            "artifacts_invalid": CollectedArtifact.objects.filter(validation_status="invalid").count(),
            "artifacts_duplicates": CollectedArtifact.objects.filter(is_duplicate=True).count(),
            "records_total": ExtractedRecord.objects.count(),
            "records_by_type": _counts(ExtractedRecord, "record_type"),
            "records_by_status": _counts(ExtractedRecord, "verification_status"),
            "review_queue_pending": DataReviewQueue.objects.filter(decision="pending").count(),
            "review_queue_approved": DataReviewQueue.objects.filter(decision="approved").count(),
            "review_queue_rejected": DataReviewQueue.objects.filter(decision="rejected").count(),
            "sources": [source_history(s) for s in DataSource.objects.all()],
        }

        out_dir = Path(options["out"] or Path(getattr(settings, "DATA_INGESTION_DATA_DIR", "data/ingested")) / "reports")
        out_dir.mkdir(parents=True, exist_ok=True)
        json_path = out_dir / "ingestion_status_report.json"
        json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        md_path = out_dir / "ingestion_status_report.md"
        md_path.write_text(_to_markdown(report), encoding="utf-8")
        self.stdout.write(f"report written: {json_path}")
        self.stdout.write(f"markdown     : {md_path}")
        self.stdout.write(json.dumps({k: v for k, v in report.items() if not isinstance(v, list)}, indent=2))


def _counts(model, field):
    values = {}
    for row in model.objects.values(field):
        key = row[field] or "unknown"
        values[key] = values.get(key, 0) + 1
    return values


def _to_markdown(report):
    lines = ["# Ingestion status report", ""]
    scalar = {k: v for k, v in report.items() if not isinstance(v, (dict, list))}
    for key, value in sorted(scalar.items()):
        lines.append(f"- **{key}**: {value}")
    for section in ("sources_by_status", "sources_by_category", "artifacts_by_type", "records_by_type", "records_by_status"):
        lines.append("")
        lines.append(f"### {section}")
        lines.extend(f"- {k}: {v}" for k, v in sorted(report.get(section, {}).items()))
    return "\n".join(lines)