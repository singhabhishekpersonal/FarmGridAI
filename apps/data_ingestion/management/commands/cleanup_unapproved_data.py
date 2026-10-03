"""Clean up / quarantine data originating from unapproved sources.

This command never hard-deletes anything. It marks CollectedArtifacts of
non-approved sources with ``retention_status='quarantined'`` and flags their
ExtractedRecords for manual review. Admin API + admin actions can reverse it.
"""
from django.core.management.base import BaseCommand, CommandError

from apps.data_ingestion.models import CollectedArtifact, DataSource, ExtractedRecord


class Command(BaseCommand):
    help = "Quarantine data ingested from non-approved sources (no hard deletes)."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="Apply the quarantine; default lists what would change.")

    def handle(self, *args, **options):
        approved_source_ids = list(
            DataSource.objects.filter(
                approval_status=DataSource.ApprovalStatus.APPROVED, collection_enabled=True
            ).values_list("id", flat=True)
        )
        artifacts = CollectedArtifact.objects.exclude(source_id__in=approved_source_ids)
        records = ExtractedRecord.objects.filter(
            collected_artifact__isnull=False
        ).exclude(source_id__in=approved_source_ids)
        self.stdout.write(f"sources active: {len(approved_source_ids)}")
        self.stdout.write(f"artifacts from non-active sources: {artifacts.count()}")
        self.stdout.write(f"records from non-active sources   : {records.count()}")

        if not options["apply"]:
            self.stdout.write("dry run - rerun with --apply to quarantine")
            return

        for artifact in artifacts:
            artifact.retention_status = "quarantined"
            artifact.is_approved = False
            artifact.save(update_fields=["retention_status", "is_approved", "updated_at"])
        for record in records:
            record.verification_status = ExtractedRecord.VerificationStatus.REJECTED
            record.review_notes = (record.review_notes or "") + "; quarantined (source not approved)"
            record.save(update_fields=["verification_status", "review_notes", "updated_at"])
        self.stdout.write(self.style.SUCCESS(f"quarantined {artifacts.count()} artifacts, {records.count()} records"))