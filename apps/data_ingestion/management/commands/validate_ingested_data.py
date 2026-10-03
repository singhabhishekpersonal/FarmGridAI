"""Validate ingested records and forward valid ones to the review queue.

Records in ``raw``/``parsed`` status are re-validated; records that pass move
to ``validated`` and get a pending ``DataReviewQueue`` entry. Invalid records
stay in the queue-free raw state with reasons reported.
"""
from django.core.management.base import BaseCommand, CommandError

from apps.data_ingestion.models import DataSource, ExtractedRecord
from apps.data_ingestion.services.review_workflow import enqueue_record
from apps.data_ingestion.services.validation import validate_extracted_record_payload


class Command(BaseCommand):
    help = "Validate unvalidated ingested records and enqueue passing ones for human review."

    def add_arguments(self, parser):
        parser.add_argument("--source-id", default="", help="Restrict to one source (optional).")
        parser.add_argument("--record-type", default="", help="Restrict to one record type (optional).")

    def handle(self, *args, **options):
        records = ExtractedRecord.objects.filter(
            verification_status__in=[ExtractedRecord.VerificationStatus.RAW, ExtractedRecord.VerificationStatus.PARSED]
        )
        if options["source_id"]:
            try:
                source = DataSource.objects.get(pk=options["source_id"])
            except (DataSource.DoesNotExist, ValueError) as exc:
                raise CommandError(f"unknown source {options['source_id']}") from exc
            records = records.filter(source=source)
        if options["record_type"]:
            if options["record_type"] not in ExtractedRecord.RecordType.values:
                raise CommandError(f"unknown record type {options['record_type']!r}")
            records = records.filter(record_type=options["record_type"])

        total = records.count()
        passed = failed = queued = 0
        for record in records:
            result = validate_extracted_record_payload(record.record_type, record.normalized_data_json)
            if not result["ok"]:
                record.verification_status = ExtractedRecord.VerificationStatus.RAW
                record.review_notes = "; ".join(result["errors"])
                record.save(update_fields=["verification_status", "review_notes", "updated_at"])
                failed += 1
                continue
            record.verification_status = ExtractedRecord.VerificationStatus.VALIDATED
            record.review_notes = "; ".join(result["warnings"]) if result["warnings"] else ""
            record.save(update_fields=["verification_status", "review_notes", "updated_at"])
            passed += 1
            if not record.review_queue_entries.exists():
                enqueue_record(
                    record,
                    proposed_target_model=record.normalized_data_json.get("_target") or "",
                    validation_result={"ok": True, "errors": [], "warnings": result["warnings"]},
                )
            queued += 1

        self.stdout.write(f"total={total} passed={passed} failed={failed} already_queued={queued}")
        if failed:
            self.stdout.write(self.style.WARNING(f"{failed} record(s) failed validation and remain in review-free raw state"))