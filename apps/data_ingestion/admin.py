"""Admin for the data-ingestion module.

Every mutation exposed here funnels through the same services used by the API
and management commands, and writes to the ``khetsathi.audit`` log.
"""
import json
import logging

from django.contrib import admin
from django.utils import timezone

from apps.data_ingestion.models import (
    CollectedArtifact,
    DataReviewQueue,
    DataSource,
    ExtractedRecord,
    IngestionRun,
    SourceComplianceCheck,
)
from apps.data_ingestion.services.compliance import run_compliance_check
from apps.data_ingestion.services.provenance import source_history, write_provenance_report
from apps.data_ingestion.services.review_workflow import publish, resolve
from apps.data_ingestion.services.source_registry import approve_source, block_source, reject_source
from apps.data_ingestion.services.validation import validate_extracted_record_payload

logger = logging.getLogger("khetsathi.audit")


class IsDataSourceAdmin(admin.ModelAdmin):
    list_display = ["name", "organization", "source_type", "category", "approval_status", "collection_enabled", "robots_status", "terms_status"]
    list_filter = ["source_type", "category", "approval_status", "robots_status", "terms_status", "collection_enabled"]
    search_fields = ["name", "organization", "base_url"]
    readonly_fields = ["approved_by", "last_compliance_check_at", "last_successful_collection_at", "created_at", "updated_at"]
    actions = ["approve_selected", "reject_selected", "block_selected", "deactivate_selected", "run_compliance_selected", "export_history"]

    @admin.action(description="Approve selected sources (records logged-in user as approver)")
    def approve_selected(self, request, queryset):
        for source in queryset:
            approve_source(source, request.user, reason="approved via admin action")
        self.message_user(request, f"approved {queryset.count()} source(s); compliance evidence still applies per source.")

    @admin.action(description="Reject selected sources")
    def reject_selected(self, request, queryset):
        for source in queryset:
            reject_source(source, request.user, reason="rejected via admin action")
        self.message_user(request, f"rejected {queryset.count()} source(s)")

    @admin.action(description="Block selected sources")
    def block_selected(self, request, queryset):
        for source in queryset:
            block_source(source, "blocked via admin action")
        self.message_user(request, f"blocked {queryset.count()} source(s)")

    @admin.action(description="Deactivate collection for selected sources")
    def deactivate_selected(self, request, queryset):
        updated = queryset.update(collection_enabled=False, updated_at=timezone.now())
        self.message_user(request, f"deactivated collection for {updated} source(s)")

    @admin.action(description="Run compliance check for selected sources (offline-safe)")
    def run_compliance_selected(self, request, queryset):
        count = 0
        for source in queryset:
            run_compliance_check(source)
            count += 1
        self.message_user(request, f"ran compliance check for {count} source(s)")

    @admin.action(description="Export provenance history (Markdown) for selected sources")
    def export_history(self, request, queryset):
        import tempfile

        buffer = []
        for source in queryset:
            buffer.append(source_history(source))
        path = tempfile.mktemp(suffix=".json")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(buffer, handle, indent=2)
        self.message_user(request, f"exported {queryset.count()} source history to {path}")
        return path


class SourceComplianceCheckAdmin(admin.ModelAdmin):
    list_display = ["source", "checked_at", "decision", "robots_retrieved", "robots_allows_target_paths", "terms_manual_review_required"]
    list_filter = ["decision", "robots_retrieved", "terms_manual_review_required", "login_required_detected", "captcha_detected", "paywall_detected"]
    search_fields = ["source__name", "blocked_reason"]
    readonly_fields = [f.name for f in SourceComplianceCheck._meta.fields]


class IngestionRunAdmin(admin.ModelAdmin):
    list_display = ["run_id", "source", "status", "is_dry_run", "started_at", "pages_collected", "records_extracted"]
    list_filter = ["status", "is_dry_run", "source"]
    readonly_fields = [f.name for f in IngestionRun._meta.fields]
    actions = ["export_run_json"]

    @admin.action(description="Export selected runs as JSON to server temp file")
    def export_run_json(self, request, queryset):
        import tempfile

        rows = [{"run_id": r.run_id, "status": r.status, "config": r.configuration_snapshot, "warnings": r.warnings} for r in queryset]
        path = tempfile.mktemp(suffix=".json")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(rows, handle, indent=2)
        self.message_user(request, f"exported {len(rows)} run(s) to {path}")


class CollectedArtifactAdmin(admin.ModelAdmin):
    list_display = ["sha256", "source", "artifact_type", "validation_status", "is_approved", "is_duplicate", "retrieved_at"]
    list_filter = ["artifact_type", "validation_status", "is_approved", "is_duplicate", "retention_status"]
    search_fields = ["sha256", "original_url"]
    readonly_fields = [f.name for f in CollectedArtifact._meta.fields]
    actions = ["approve_selected", "export_provenance"]

    @admin.action(description="Approve selected artifacts -> keep")
    def approve_selected(self, request, queryset):
        updated = queryset.update(is_approved=True, retention_status="kept", updated_at=timezone.now())
        self.message_user(request, f"approved {updated} artifact(s)")

    @admin.action(description="Export provenance for selected artifacts")
    def export_provenance(self, request, queryset):
        import tempfile

        rows = [write_provenance_report(a) for a in queryset]
        path = tempfile.mktemp(suffix=".md")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("\n\n".join(rows if isinstance(rows, str) else [str(r) for r in rows]))
        self.message_user(request, f"provenance exported to {path}")


class ExtractedRecordAdmin(admin.ModelAdmin):
    list_display = ["record_type", "source", "verification_status", "confidence", "retrieved_at", "reviewed_at"]
    list_filter = ["record_type", "verification_status", "confidence", "source"]
    search_fields = ["content_hash", "source_url", "source__name"]
    readonly_fields = ["content_hash", "retrieved_at", "reviewer", "reviewed_at"]
    actions = ["validate_selected"]

    @admin.action(description="(Re)validate selected records")
    def validate_selected(self, request, queryset):
        passed = failed = 0
        for record in queryset:
            result = validate_extracted_record_payload(record.record_type, record.normalized_data_json)
            if result["ok"]:
                record.verification_status = ExtractedRecord.VerificationStatus.VALIDATED
                passed += 1
            else:
                record.verification_status = ExtractedRecord.VerificationStatus.RAW
                record.review_notes = "; ".join(result["errors"])
                failed += 1
            record.save()
        self.message_user(request, f"validated: passed={passed} failed={failed}")


class DataReviewQueueAdmin(admin.ModelAdmin):
    list_display = ["extracted_record", "proposed_target_model", "proposed_action", "risk_level", "decision", "decided_by", "decided_at"]
    list_filter = ["proposed_target_model", "proposed_action", "risk_level", "decision", "requires_human_review"]
    search_fields = ["extracted_record__content_hash", "decision_notes"]
    readonly_fields = ["extracted_record", "created_at", "decided_at"]
    actions = [
        "approve_selected",
        "reject_selected",
        "publish_selected",
        "mark_stale",
        "rollback_published",
    ]

    @admin.action(description="Approve selected queue items (decision only)")
    def approve_selected(self, request, queryset):
        for item in queryset:
            resolve(item, request.user, decision=DataReviewQueue.Decision.APPROVED, notes="approved via admin action")
        self.message_user(request, f"approved {queryset.count()} queue item(s)")

    @admin.action(description="Reject selected queue items")
    def reject_selected(self, request, queryset):
        for item in queryset:
            resolve(item, request.user, decision=DataReviewQueue.Decision.REJECTED, notes="rejected via admin action")
        self.message_user(request, f"rejected {queryset.count()} queue item(s)")

    @admin.action(description="Publish selected queue items (approved + written to live model)")
    def publish_selected(self, request, queryset):
        ok = failed = 0
        for item in queryset:
            try:
                publish(item, request.user, notes="published via admin action")
                ok += 1
            except Exception as exc:  # noqa: BLE001
                failed += 1
                logger.warning("publish failed queue=%s: %s", item.pk, exc)
        self.message_user(request, f"published {ok}, failed {failed}")

    @admin.action(description="Mark selected items stale (forces re-review)")
    def mark_stale(self, request, queryset):
        for item in queryset:
            item.source_freshness_status = "stale"
            item.requires_human_review = True
            if item.decision == DataReviewQueue.Decision.APPROVED:
                item.decision = DataReviewQueue.Decision.PENDING
            item.save()
        self.message_user(request, f"marked {queryset.count()} item(s) stale")

    @admin.action(description="Roll back published items (soft-deactivate illustrative scheme, reject record)")
    def rollback_published(self, request, queryset):
        from apps.subsidies.models import SubsidyScheme

        rolled = 0
        for item in queryset:
            if item.decision != DataReviewQueue.Decision.APPROVED:
                continue
            scheme = None
            if item.proposed_target_model == "SubsidyScheme":
                slug = _slug(item.extracted_record.normalized_data_json.get("name", ""))
                scheme = SubsidyScheme.objects.filter(slug=slug, is_illustrative=True).first()
                if scheme:
                    scheme.is_active = False
                    scheme.save(update_fields=["is_active", "updated_at"])
            reject_source_like = resolve(
                item,
                request.user,
                decision=DataReviewQueue.Decision.REJECTED,
                notes=f"rolled back via admin action; scheme additionally deactivated={bool(scheme)}",
            )
            rollback_record = item.extracted_record
            rollback_record.verification_status = ExtractedRecord.VerificationStatus.REJECTED
            rollback_record.review_notes = (rollback_record.review_notes or "") + "; rolled back"
            rollback_record.save(update_fields=["verification_status", "review_notes", "updated_at"])
            logger.info("rollback queue=%s scheme_deactivated=%s", item.pk, bool(scheme))
            rolled += 1
        self.message_user(request, f"rolled back {rolled} item(s); subsides deactivated when illustrative")


def _slug(value):
    import re

    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")[:160]


admin.site.register(DataSource, IsDataSourceAdmin)
admin.site.register(SourceComplianceCheck, SourceComplianceCheckAdmin)
admin.site.register(IngestionRun, IngestionRunAdmin)
admin.site.register(CollectedArtifact, CollectedArtifactAdmin)
admin.site.register(ExtractedRecord, ExtractedRecordAdmin)
admin.site.register(DataReviewQueue, DataReviewQueueAdmin)