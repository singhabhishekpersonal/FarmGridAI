"""API views for the data-ingestion module.

Mounted at ``/api/v1/data-ingestion/`` (see ``urls.py``). Every mutating
action requires a staff/admin user so a named human is always in the audit
trail. Collection endpoints default to dry-run unless ``execute=true``.
"""
import json
import logging
from pathlib import Path

from rest_framework import status
from rest_framework.exceptions import NotFound, PermissionDenied

from apps.data_ingestion.models import (
    CollectedArtifact,
    DataReviewQueue,
    DataSource,
    ExtractedRecord,
    IngestionRun,
)
from apps.data_ingestion.permissions import IsStaffOrAdmin, StaffOrReadOnly
from apps.data_ingestion.serializers import (
    CollectedArtifactSerializer,
    DataReviewQueueSerializer,
    DataSourceSerializer,
    ExtractedRecordSerializer,
    IngestionRunSerializer,
    SourceComplianceCheckSerializer,
)
from apps.data_ingestion.services.compliance import run_compliance_check
from apps.data_ingestion.services.dataset_enrichment import eligible_records
from apps.data_ingestion.services.downloader import make_ingestion_run
from apps.data_ingestion.services.image_collector import collect_images, import_manual_images
from apps.data_ingestion.services.planner import expansion_plan
from apps.data_ingestion.services.provenance import artifact_provenance, record_provenance, source_history
from apps.data_ingestion.services.review_workflow import publish, resolve
from apps.data_ingestion.services.source_registry import SourceRegistryError, is_collectable, register_source
from apps.api.mixins import ApiResponseMixin
from drf_spectacular.utils import extend_schema

logger = logging.getLogger("khetsathi.audit")


def _staff_pass_or_403(view):
    user = view.request.user
    if not (user and (user.is_staff or user.is_superuser)):
        raise PermissionDenied("staff/admin privileges required")


def _strict_bool(value, default=False):
    """Parse a boolean sent as bool/number/string without treating 'false' as True."""
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


class SourceListCreateView(ApiResponseMixin):
    """List registered data sources, or register a new one.

    GET filters by name/category/approval_status and is open to any
    authenticated user. POST is staff/admin only and always creates the source in
    the pending state, so collection stays disabled until it is approved.
    """
    permission_classes = [StaffOrReadOnly]

    @extend_schema(operation_id="v1_data_ingestion_sources_list")
    def get(self, request):
        qs = DataSource.objects.all()
        name = request.query_params.get("name")
        category = request.query_params.get("category")
        approval = request.query_params.get("approval_status")
        if name:
            qs = qs.filter(name__icontains=name)
        if category:
            qs = qs.filter(category=category)
        if approval:
            qs = qs.filter(approval_status=approval)
        data = DataSourceSerializer(qs, many=True).data
        return self.respond(data=data, meta={"count": qs.count()})

    def post(self, request):
        _staff_pass_or_403(self)
        payload = request.data
        try:
            source = register_source(
                name=payload.get("name", ""),
                base_url=payload.get("base_url", ""),
                source_type=payload.get("source_type", DataSource.SourceType.PUBLIC_DATASET),
                category=payload.get("category", DataSource.Category.EQUIPMENT_IMAGES),
                organization=payload.get("organization", ""),
                state=payload.get("state", ""),
                country=payload.get("country", "IN"),
                robots_url=payload.get("robots_url", ""),
                terms_url=payload.get("terms_url", ""),
                license_url=payload.get("license_url", ""),
                attribution_text=payload.get("attribution_text", ""),
                allowed_collection_methods=payload.get("allowed_collection_methods", []),
                rate_limit_per_minute=payload.get("rate_limit_per_minute", 10),
                request_delay_seconds=payload.get("request_delay_seconds", 1.0),
                allows_images=_strict_bool(payload.get("allows_images")),
                allows_documents=_strict_bool(payload.get("allows_documents")),
                allows_structured_data=_strict_bool(payload.get("allows_structured_data")),
                notes=payload.get("notes", ""),
                created_by=request.user,
            )
        except SourceRegistryError as exc:
            return self.respond_error([str(exc)], "Source registration failed.")
        return self.respond(DataSourceSerializer(source).data, "Source registered (pending approval).", status_code=status.HTTP_201_CREATED)


class SourceDetailView(ApiResponseMixin):
    """Retrieve or partially update a single registered source.

    Reads are open to any authenticated user; PATCH is staff/admin only and
    silently ignores fields outside a fixed editable set. An unknown id returns
    404 rather than raising.
    """
    permission_classes = [StaffOrReadOnly]

    def get(self, request, source_id):
        try:
            source = DataSource.objects.get(pk=source_id)
        except (DataSource.DoesNotExist, ValueError):
            return self.respond_error(["source not found"], status_code=status.HTTP_404_NOT_FOUND)
        return self.respond(DataSourceSerializer(source).data)

    def patch(self, request, source_id):
        _staff_pass_or_403(self)
        try:
            source = DataSource.objects.get(pk=source_id)
        except (DataSource.DoesNotExist, ValueError):
            return self.respond_error(["source not found"], status_code=status.HTTP_404_NOT_FOUND)
        editable = {
            "name", "organization", "category", "geographic_scope", "state", "district",
            "allowed_collection_methods", "robots_url", "terms_url", "license_url",
            "attribution_text", "rate_limit_per_minute", "request_delay_seconds",
            "max_pages_per_run", "allows_images", "allows_documents",
            "allows_structured_data", "notes",
        }
        for field, value in request.data.items():
            if field in editable:
                if field in {"allows_images", "allows_documents", "allows_structured_data"}:
                    value = _strict_bool(value)
                setattr(source, field, value)
        source.save(update_fields=list(set(editable) & set(request.data)) + ["updated_at"])
        return self.respond(DataSourceSerializer(source).data, "Source updated.")


class SourceComplianceView(ApiResponseMixin):
    """Run a robots/terms compliance decision against a source.

    Staff/admin only. Recomputed on every call and not persisted as a decision
    state on the source; an optional run_id links the check to an ingestion run.
    """
    permission_classes = [IsStaffOrAdmin]

    def post(self, request, source_id):
        try:
            source = DataSource.objects.get(pk=source_id)
        except (DataSource.DoesNotExist, ValueError):
            return self.respond_error(["source not found"], status_code=status.HTTP_404_NOT_FOUND)
        check = run_compliance_check(source, run_id=request.data.get("run_id", ""))
        return self.respond(SourceComplianceCheckSerializer(check).data, f"Compliance decision: {check.decision}.")


class SourceCollectView(ApiResponseMixin):
    """Collect images for a source from an explicit list of URLs.

    Staff/admin only. Defaults to a dry run; execute=true is required for real
    collection and is rejected unless the source is approved and collection
    enabled. Creates an IngestionRun and returns the collector report.
    """
    permission_classes = [IsStaffOrAdmin]

    def post(self, request, source_id):
        try:
            source = DataSource.objects.get(pk=source_id)
        except (DataSource.DoesNotExist, ValueError):
            return self.respond_error(["source not found"], status_code=status.HTTP_404_NOT_FOUND)
        dry_run = not _strict_bool(request.data.get("execute"))
        urls = [u.strip() for u in request.data.get("image_urls", []) if isinstance(u, str) and u.strip()]
        if not urls:
            return self.respond_error(["image_urls required (list of URLs)"])
        if not dry_run and not is_collectable(source):
            return self.respond_error(["source is not approved & collection-enabled; collection requires execute=true and an approved source"])

        run = make_ingestion_run(
            source,
            dry_run=dry_run,
            config={"via": "api", "dry_run": dry_run, "urls": len(urls)},
            collector_version="api.collect_source.1",
        )
        report = collect_images(
            source,
            run,
            urls,
            attribution=request.data.get("attribution", ""),
            label_hint=request.data.get("label_hint", ""),
            max_images=request.data.get("max_images") or None,
        )
        if run.is_dry_run:
            run.status = IngestionRun.Status.DRY_RUN
            run.save(update_fields=["status"])
        return self.respond(report, "dry run completed; rerun with execute=true once the source is approved." if dry_run else "collection completed.")


class SourceRunsView(ApiResponseMixin):
    """List the most recent ingestion runs for one source, newest first.

    Capped at 50 rows and read-only for any authenticated user.
    """
    permission_classes = [StaffOrReadOnly]

    def get(self, request, source_id):
        try:
            source = DataSource.objects.get(pk=source_id)
        except (DataSource.DoesNotExist, ValueError):
            return self.respond_error(["source not found"], status_code=status.HTTP_404_NOT_FOUND)
        runs = source.runs.order_by("-started_at")[:50]
        return self.respond(IngestionRunSerializer(runs, many=True).data, meta={"count": runs.count()})


class RunListView(ApiResponseMixin):
    """List recent ingestion runs across all sources, newest first.

    Read-only, capped at 100 rows.
    """
    permission_classes = [StaffOrReadOnly]

    @extend_schema(operation_id="v1_data_ingestion_runs_list")
    def get(self, request):
        qs = IngestionRun.objects.all().order_by("-started_at")[:100]
        return self.respond(IngestionRunSerializer(qs, many=True).data, meta={"count": qs.count()})


class RunDetailView(ApiResponseMixin):
    """Retrieve a single ingestion run by id.

    Read-only; an unknown id returns 404 rather than raising.
    """
    permission_classes = [StaffOrReadOnly]

    def get(self, request, run_id):
        try:
            run = IngestionRun.objects.get(pk=run_id)
        except (IngestionRun.DoesNotExist, ValueError):
            return self.respond_error(["run not found"], status_code=status.HTTP_404_NOT_FOUND)
        return self.respond(IngestionRunSerializer(run).data)


class ArtifactListView(ApiResponseMixin):
    """List recently collected artifacts across all sources, newest first.

    Read-only, capped at 100 rows.
    """
    permission_classes = [StaffOrReadOnly]

    @extend_schema(operation_id="v1_data_ingestion_artifacts_list")
    def get(self, request):
        qs = CollectedArtifact.objects.all().order_by("-retrieved_at")[:100]
        return self.respond(CollectedArtifactSerializer(qs, many=True).data, meta={"count": qs.count()})


class ArtifactDetailView(ApiResponseMixin):
    """Retrieve one collected artifact together with its provenance chain.

    Provenance is computed per request, not cached on the row.
    """
    permission_classes = [StaffOrReadOnly]

    def get(self, request, artifact_id):
        try:
            artifact = CollectedArtifact.objects.get(pk=artifact_id)
        except (CollectedArtifact.DoesNotExist, ValueError):
            return self.respond_error(["artifact not found"], status_code=status.HTTP_404_NOT_FOUND)
        return self.respond({**CollectedArtifactSerializer(artifact).data, "provenance": artifact_provenance(artifact)})


class RecordListView(ApiResponseMixin):
    """List extracted records, optionally filtered by record_type and status.

    Read-only, capped at 100 rows.
    """
    permission_classes = [StaffOrReadOnly]

    @extend_schema(operation_id="v1_data_ingestion_records_list")
    def get(self, request):
        qs = ExtractedRecord.objects.all().order_by("-retrieved_at")
        record_type = request.query_params.get("record_type")
        status_filter = request.query_params.get("status")
        if record_type:
            qs = qs.filter(record_type=record_type)
        if status_filter:
            qs = qs.filter(verification_status=status_filter)
        qs = qs[:100]
        return self.respond(ExtractedRecordSerializer(qs, many=True).data, meta={"count": qs.count()})


class RecordDetailView(ApiResponseMixin):
    """Retrieve one extracted record together with its provenance chain.

    Provenance is recomputed on every request, not cached.
    """
    permission_classes = [StaffOrReadOnly]

    def get(self, request, record_id):
        try:
            record = ExtractedRecord.objects.get(pk=record_id)
        except (ExtractedRecord.DoesNotExist, ValueError):
            return self.respond_error(["record not found"], status_code=status.HTTP_404_NOT_FOUND)
        return self.respond({**ExtractedRecordSerializer(record).data, "provenance": record_provenance(record)})


class ReviewQueueListView(ApiResponseMixin):
    """List human-review queue items, optionally filtered by decision and risk.

    Read-only, capped at 100 rows.
    """
    permission_classes = [StaffOrReadOnly]

    def get(self, request):
        qs = DataReviewQueue.objects.all()
        decision = request.query_params.get("decision")
        risk = request.query_params.get("risk_level")
        if decision:
            qs = qs.filter(decision=decision)
        if risk:
            qs = qs.filter(risk_level=risk)
        qs = qs.order_by("-created_at")[:100]
        return self.respond(DataReviewQueueSerializer(qs, many=True).data, meta={"count": qs.count()})


class ReviewQueueDecisionView(ApiResponseMixin):
    """Apply a review decision to a queue item; the subclass sets the action.

    Dispatching on self.action covers approve/reject/publish, so every subclass
    shares this handler. Notes are stored on the queue item and publish failures
    are surfaced as a response error rather than a 500.
    """
    permission_classes = [IsStaffOrAdmin]
    action = "approve"

    def post(self, request, queue_id):
        try:
            queue_item = DataReviewQueue.objects.get(pk=queue_id)
        except (DataReviewQueue.DoesNotExist, ValueError):
            return self.respond_error(["queue item not found"], status_code=status.HTTP_404_NOT_FOUND)
        notes = request.data.get("notes", "")

        from apps.data_ingestion.models import DataReviewQueue as Q

        if self.action == "approve":
            resolve(queue_item, request.user, decision=Q.Decision.APPROVED, notes=notes)
            message = "approved"
        elif self.action == "reject":
            resolve(queue_item, request.user, decision=Q.Decision.REJECTED, notes=notes)
            message = "rejected"
        elif self.action == "publish":
            try:
                publish(queue_item, request.user, notes=notes)
            except Exception as exc:  # noqa: BLE001 - surfaced to the caller
                return self.respond_error([str(exc)], "Publication failed.")
            message = "published"
        else:
            return self.respond_error(["unsupported action"])
        queue_item.refresh_from_db()
        return self.respond(DataReviewQueueSerializer(queue_item).data, message=f"Queue item {message}.")


class ReviewQueueApproveView(ReviewQueueDecisionView):
    """Record an APPROVED decision on a queue item.

    Overwrites any earlier decision; the linked record's status is left alone
    since only REJECTED propagates to it.
    """
    action = "approve"


class ReviewQueueRejectView(ReviewQueueDecisionView):
    """Record a REJECTED decision on a queue item.

    Unlike approval, this also flips the linked extracted record to REJECTED
    and stamps the reviewing user, notes and timestamp on it.
    """
    action = "reject"


class ReviewQueuePublishView(ReviewQueueDecisionView):
    """Publish an already-approved queue item into its target live model.

    Second half of the two-step human gate: it never self-approves, so an item
    without a human APPROVED decision, or one that failed validation, is
    rejected with a response error instead of a 500.
    """
    action = "publish"


class ManualImportView(ApiResponseMixin):
    """Ingest image files from a server-side folder for a manual_import source.

    Staff/admin only. Refuses non-manual_import or unapproved sources, rejects
    paths that are missing/empty or hold more than 5000 files, and always runs
    for real (no dry-run option). Results land in the review queue.
    """
    permission_classes = [IsStaffOrAdmin]

    def post(self, request):
        source_id = request.data.get("source_id", "")
        try:
            source = DataSource.objects.get(pk=source_id)
        except (DataSource.DoesNotExist, ValueError):
            return self.respond_error(["source not found"], status_code=status.HTTP_404_NOT_FOUND)
        if source.source_type != DataSource.SourceType.MANUAL_IMPORT:
            return self.respond_error(["manual import requires a manual_import source"])
        if not (source.approval_status == DataSource.ApprovalStatus.APPROVED and source.collection_enabled):
            return self.respond_error(["source not approved for import; approve the source first."])

        base_path = request.data.get("path", "")
        label_hint = request.data.get("label_hint", "")
        if not base_path:
            return self.respond_error(["path required (server-side folder with image files)"])
        folder = Path(base_path)
        if not folder.is_dir():
            return self.respond_error(["path does not exist or is not a directory"])

        files = sorted(p for p in folder.rglob("*") if p.is_file())
        if not files:
            return self.respond_error(["no files found in path"])
        if len(files) > 5000:
            return self.respond_error(["too many files for a single request (>5000)"])

        run = make_ingestion_run(source, dry_run=False, config={"via": "api", "operation": "manual_import"}, collector_version="api.manual_import.1")
        report = import_manual_images(source, run, files, label_hint=label_hint)
        run.status = IngestionRun.Status.COMPLETED
        run.save(update_fields=["status"])
        return self.respond(report, "Manual import completed (review queue next).")


class DatasetReportView(ApiResponseMixin):
    """Report the dataset expansion plan alongside the eligible-record count.

    Read-only and recomputed per request. The optional known_counts query param
    is a JSON object of existing class counts; malformed JSON returns an error.
    """
    permission_classes = [StaffOrReadOnly]

    def get(self, request):
        known = {}
        if request.query_params.get("known_counts"):
            try:
                known = json.loads(request.query_params["known_counts"])
            except json.JSONDecodeError as exc:
                return self.respond_error([f"known_counts must be JSON: {exc}"])
        plan = expansion_plan(known_counts=known)
        eligible = eligible_records().count()
        return self.respond({"expanded_plan": plan, "eligible_reviewed_records": eligible})


class ProvenanceReportView(ApiResponseMixin):
    """Report the provenance chain for a source, extracted record or artifact.

    Read-only. Exactly one of source_id, record_id or artifact_id selects the
    subject, checked in that order; supplying none returns an error.
    """
    permission_classes = [StaffOrReadOnly]

    def get(self, request):
        source_id = request.query_params.get("source_id", "")
        if source_id:
            try:
                source = DataSource.objects.get(pk=source_id)
            except (DataSource.DoesNotExist, ValueError):
                return self.respond_error(["source not found"], status_code=status.HTTP_404_NOT_FOUND)
            return self.respond(source_history(source))
        record_id = request.query_params.get("record_id", "")
        if record_id:
            try:
                record = ExtractedRecord.objects.get(pk=record_id)
            except (ExtractedRecord.DoesNotExist, ValueError):
                return self.respond_error(["record not found"], status_code=status.HTTP_404_NOT_FOUND)
            return self.respond(record_provenance(record))
        artifact_id = request.query_params.get("artifact_id", "")
        if artifact_id:
            try:
                artifact = CollectedArtifact.objects.get(pk=artifact_id)
            except (CollectedArtifact.DoesNotExist, ValueError):
                return self.respond_error(["artifact not found"], status_code=status.HTTP_404_NOT_FOUND)
            return self.respond(artifact_provenance(artifact))
        return self.respond_error(["provide source_id, record_id, or artifact_id"])
