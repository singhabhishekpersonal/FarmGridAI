"""Data-ingestion domain models.

These models underpin a **compliant, conservative, reproducible, auditable**
web-data collection + dataset-enrichment system.

Core guarantees enforced by this module's services (not by the models alone):

* a source may only be *collected from* once it is explicitly ``approved`` in
  :class:`DataSource` (approval is a human action — never automated);
* robots.txt / Terms constraints are checked and persisted per-source
  (:class:`SourceComplianceCheck`);
* every collected artifact carries provenance + a content hash
  (:class:`CollectedArtifact`);
* extracted records enter :class:`DataReviewQueue` before they may ever be
  copied into live domain models (``SubsidyScheme``, benchmarks, catalogues);
* publication actions are logged to the audit trail.
"""
import uuid

from django.conf import settings
from django.db import models

from apps.core.models import BaseModel


class DataSource(BaseModel):
    """A source of data that this platform may (or may not) collect from.

    Nothing may be collected from a source until a human has set
    ``approval_status=approved`` AND ``collection_enabled=True``.
    ``approved_by`` must be recorded for every approved source.
    """

    class SourceType(models.TextChoices):
        GOVERNMENT = "government", "Government portal"
        GOVERNMENT_API = "government_api", "Government API"
        OFFICIAL_MANUFACTURER = "official_manufacturer", "Official manufacturer"
        PUBLIC_DATASET = "public_dataset", "Public dataset"
        APPROVED_THIRD_PARTY = "approved_third_party", "Approved third party"
        MANUAL_IMPORT = "manual_import", "Manual import"

    class Category(models.TextChoices):
        SUBSIDY = "subsidy", "Subsidy"
        CROP_BENCHMARK = "crop_benchmark", "Crop benchmark"
        MACHINERY_BENCHMARK = "machinery_benchmark", "Machinery benchmark"
        SOLAR_BENCHMARK = "solar_benchmark", "Solar benchmark"
        ELECTRICITY_BENCHMARK = "electricity_benchmark", "Electricity benchmark"
        DIESEL_BENCHMARK = "diesel_benchmark", "Diesel benchmark"
        EQUIPMENT_CATALOG = "equipment_catalog", "Equipment catalog"
        EQUIPMENT_IMAGES = "equipment_images", "Equipment images"
        WEATHER = "weather", "Weather"
        MARKET_PRICE = "market_price", "Market price"
        FAQ = "faq", "FAQ"

    class AllowedMethod(models.TextChoices):
        API = "api", "API"
        RSS = "rss", "RSS"
        DOWNLOADABLE_FILE = "downloadable_file", "Downloadable file"
        PUBLIC_HTML = "public_html", "Public HTML"
        MANUAL_IMPORT_ONLY = "manual_import_only", "Manual import only"

    class ApprovalStatus(models.TextChoices):
        PENDING = "pending", "Pending"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"
        BLOCKED = "blocked", "Blocked"
        MANUAL_REVIEW = "manual_review", "Manual review"

    class RobotsStatus(models.TextChoices):
        UNKNOWN = "unknown", "Unknown"
        RETRIEVED = "retrieved", "Robots retrieved"
        UNAVAILABLE = "unavailable", "Robots unavailable"
        PARTIAL = "partial", "Partially retrieved"
        NOT_APPLICABLE = "not_applicable", "Not applicable"

    class TermsStatus(models.TextChoices):
        UNKNOWN = "unknown", "Unknown"
        RETRIEVED = "retrieved", "Terms retrieved"
        UNAVAILABLE = "unavailable", "Terms unavailable"
        MANUAL_REVIEW = "manual_review", "Manual review required"

    name = models.CharField(max_length=150)
    organization = models.CharField(max_length=150, blank=True)
    base_url = models.URLField()
    source_type = models.CharField(max_length=24, choices=SourceType.choices, default=SourceType.PUBLIC_DATASET)
    category = models.CharField(max_length=28, choices=Category.choices, default=Category.EQUIPMENT_IMAGES)
    geographic_scope = models.CharField(max_length=120, blank=True)
    country = models.CharField(max_length=60, default="IN")
    state = models.CharField(max_length=60, blank=True)
    district = models.CharField(max_length=60, blank=True)
    allowed_collection_methods = models.JSONField(
        default=list,
        help_text="List of AllowedMethod values, e.g. ['api', 'downloadable_file'].",
    )
    robots_url = models.URLField(blank=True)
    terms_url = models.URLField(blank=True)
    license_url = models.URLField(blank=True)
    attribution_text = models.TextField(blank=True)

    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="approved_sources",
    )
    approval_status = models.CharField(max_length=16, choices=ApprovalStatus.choices, default=ApprovalStatus.PENDING)
    approval_reason = models.TextField(blank=True)

    robots_status = models.CharField(max_length=16, choices=RobotsStatus.choices, default=RobotsStatus.UNKNOWN)
    terms_status = models.CharField(max_length=16, choices=TermsStatus.choices, default=TermsStatus.UNKNOWN)

    rate_limit_per_minute = models.PositiveIntegerField(default=10)
    request_delay_seconds = models.FloatField(default=1.0)
    max_pages_per_run = models.PositiveIntegerField(default=20)

    allows_images = models.BooleanField(default=False)
    allows_documents = models.BooleanField(default=False)
    allows_structured_data = models.BooleanField(default=False)

    collection_enabled = models.BooleanField(default=False)
    last_compliance_check_at = models.DateTimeField(null=True, blank=True)
    last_successful_collection_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=["base_url"], name="uniq_data_source_base_url"),
            models.UniqueConstraint(fields=["name", "organization"], name="uniq_data_source_name_org"),
        ]

    def __str__(self):
        return f"{self.name} [{self.approval_status}]"


class SourceComplianceCheck(BaseModel):
    """Persisted evidence of a compliance check against a source."""

    class Decision(models.TextChoices):
        ALLOWED = "allowed", "Allowed"
        DENIED = "denied", "Denied"
        MANUAL_REVIEW = "manual_review", "Manual review"

    source = models.ForeignKey(DataSource, on_delete=models.CASCADE, related_name="compliance_checks")
    run_id = models.CharField(max_length=40, blank=True)
    checked_at = models.DateTimeField(auto_now_add=True)

    robots_url = models.URLField(blank=True)
    robots_retrieved = models.BooleanField(default=False)
    robots_allows_target_paths = models.BooleanField(default=False)

    terms_url = models.URLField(blank=True)
    terms_retrieved = models.BooleanField(default=False)
    terms_manual_review_required = models.BooleanField(default=True)

    login_required_detected = models.BooleanField(default=False)
    captcha_detected = models.BooleanField(default=False)
    paywall_detected = models.BooleanField(default=False)

    blocked_reason = models.TextField(blank=True)
    decision = models.CharField(max_length=16, choices=Decision.choices, default=Decision.MANUAL_REVIEW)

    evidence_path = models.CharField(max_length=500, blank=True)
    evidence_hash = models.CharField(max_length=64, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-checked_at"]

    def __str__(self):
        return f"{self.source.name} -> {self.decision} @ {self.checked_at:%Y-%m-%d %H:%M}"


class IngestionRun(BaseModel):
    """A single collection/import run against one source."""

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        RUNNING = "running", "Running"
        COMPLETED = "completed", "Completed"
        PARTIAL = "partial", "Partial"
        FAILED = "failed", "Failed"
        DRY_RUN = "dry_run", "Dry run"

    source = models.ForeignKey(DataSource, on_delete=models.CASCADE, related_name="runs", null=True, blank=True)
    run_id = models.CharField(max_length=40, unique=True)
    started_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING)
    collector_version = models.CharField(max_length=40, blank=True)
    configuration_snapshot = models.JSONField(default=dict)
    pages_attempted = models.PositiveIntegerField(default=0)
    pages_collected = models.PositiveIntegerField(default=0)
    records_extracted = models.PositiveIntegerField(default=0)
    documents_downloaded = models.PositiveIntegerField(default=0)
    images_downloaded = models.PositiveIntegerField(default=0)
    duplicates_skipped = models.PositiveIntegerField(default=0)
    validation_failures = models.PositiveIntegerField(default=0)
    blocked_items = models.PositiveIntegerField(default=0)
    warnings = models.JSONField(default=list)
    report_path = models.CharField(max_length=500, blank=True)
    is_dry_run = models.BooleanField(default=False)

    class Meta:
        ordering = ["-started_at"]

    def __str__(self):
        return f"{self.run_id} ({self.status})"


class CollectedArtifact(BaseModel):
    """A raw file (html/json/csv/pdf/image/...) preserved verbatim."""

    class ArtifactType(models.TextChoices):
        HTML = "html", "HTML"
        JSON = "json", "JSON"
        CSV = "csv", "CSV"
        PDF = "pdf", "PDF"
        IMAGE = "image", "Image"
        XLSX = "xlsx", "XLSX"
        TEXT = "text", "Text"

    class ValidationStatus(models.TextChoices):
        PENDING = "pending", "Pending"
        VALID = "valid", "Valid"
        INVALID = "invalid", "Invalid"
        REVIEW = "review", "Needs review"

    source = models.ForeignKey(DataSource, on_delete=models.CASCADE, related_name="artifacts")
    ingestion_run = models.ForeignKey(IngestionRun, on_delete=models.SET_NULL, null=True, blank=True, related_name="artifacts")
    artifact_type = models.CharField(max_length=8, choices=ArtifactType.choices)
    original_url = models.URLField()
    final_url = models.URLField(blank=True)
    local_path = models.CharField(max_length=500)
    sha256 = models.CharField(max_length=64, db_index=True)
    content_type = models.CharField(max_length=120, blank=True)
    file_size = models.PositiveIntegerField(default=0)
    retrieved_at = models.DateTimeField(auto_now_add=True)
    http_status = models.PositiveIntegerField(default=0)
    license_note = models.TextField(blank=True)
    attribution = models.TextField(blank=True)
    is_approved = models.BooleanField(default=False)
    is_duplicate = models.BooleanField(default=False)
    validation_status = models.CharField(max_length=10, choices=ValidationStatus.choices, default=ValidationStatus.PENDING)
    retention_status = models.CharField(max_length=20, default="kept")

    class Meta:
        ordering = ["-retrieved_at"]
        indexes = [models.Index(fields=["sha256"]), models.Index(fields=["source", "-retrieved_at"])]

    def __str__(self):
        return f"{self.artifact_type} {self.sha256[:8]} ({self.source.name})"


class ExtractedRecord(BaseModel):
    """A normalized record extracted from a collected artifact."""

    class RecordType(models.TextChoices):
        SCHEME = "scheme", "Government scheme"
        CROP_BENCHMARK = "crop_benchmark", "Crop cost benchmark"
        ENERGY_BENCHMARK = "energy_benchmark", "Energy/tariff benchmark"
        DIESEL_BENCHMARK = "diesel_benchmark", "Diesel price benchmark"
        MACHINERY_BENCHMARK = "machinery_benchmark", "Machinery benchmark"
        EQUIPMENT_SPEC = "equipment_spec", "Equipment specification"
        EQUIPMENT_IMAGE = "equipment_image", "Equipment image"
        CATALOG_ITEM = "catalog_item", "Catalogue item"
        OTHER = "other", "Other"

    class VerificationStatus(models.TextChoices):
        RAW = "raw", "Raw"
        PARSED = "parsed", "Parsed"
        VALIDATED = "validated", "Validated"
        REVIEWED = "reviewed", "Reviewed"
        PUBLISHED = "published", "Published"
        REJECTED = "rejected", "Rejected"

    source = models.ForeignKey(DataSource, on_delete=models.CASCADE, related_name="records")
    ingestion_run = models.ForeignKey(IngestionRun, on_delete=models.SET_NULL, null=True, blank=True, related_name="records")
    collected_artifact = models.ForeignKey(CollectedArtifact, on_delete=models.SET_NULL, null=True, blank=True, related_name="records")
    record_type = models.CharField(max_length=20, choices=RecordType.choices)
    normalized_data_json = models.JSONField(default=dict)
    raw_data_json = models.JSONField(default=dict)
    source_url = models.URLField(blank=True)
    source_locator = models.CharField(max_length=500, blank=True)
    source_published_date = models.DateField(null=True, blank=True)
    retrieved_at = models.DateTimeField(auto_now_add=True)
    content_hash = models.CharField(max_length=64, db_index=True, blank=True)
    confidence = models.CharField(max_length=10, default="low")
    verification_status = models.CharField(max_length=12, choices=VerificationStatus.choices, default=VerificationStatus.RAW)
    review_notes = models.TextField(blank=True)
    reviewer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="reviewed_ingested_records",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-retrieved_at"]
        indexes = [models.Index(fields=["content_hash"]), models.Index(fields=["record_type"])]

    def __str__(self):
        return f"{self.record_type} {self.content_hash[:8]}"


class DataReviewQueue(BaseModel):
    """Gate between extracted data and live domain models.

    Nothing reaches ``SubsidyScheme`` / benchmark / catalogue tables unless a
    human reviews the corresponding queue row here.
    """

    class RiskLevel(models.TextChoices):
        LOW = "low", "Low"
        MEDIUM = "medium", "Medium"
        HIGH = "high", "High"

    class ProposedAction(models.TextChoices):
        CREATE = "create", "Create"
        UPDATE = "update", "Update"
        IGNORE = "ignore", "Ignore"

    class Decision(models.TextChoices):
        PENDING = "pending", "Pending"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"
        NEEDS_CHANGES = "needs_changes", "Needs changes"

    extracted_record = models.ForeignKey(ExtractedRecord, on_delete=models.CASCADE, related_name="review_queue_entries")
    proposed_target_model = models.CharField(max_length=60, blank=True)
    proposed_action = models.CharField(max_length=10, choices=ProposedAction.choices, default=ProposedAction.CREATE)
    risk_level = models.CharField(max_length=8, choices=RiskLevel.choices, default=RiskLevel.MEDIUM)
    validation_result = models.JSONField(default=dict)
    source_freshness_status = models.CharField(max_length=30, default="unverified")
    requires_human_review = models.BooleanField(default=True)
    decision = models.CharField(max_length=14, choices=Decision.choices, default=Decision.PENDING)
    decision_notes = models.TextField(blank=True)
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="data_ingestion_decisions",
    )
    decided_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.extracted_record_id} -> {self.proposed_target_model} ({self.decision})"