"""Serializers for the data-ingestion API."""
from rest_framework import serializers

from apps.data_ingestion.models import (
    CollectedArtifact,
    DataReviewQueue,
    DataSource,
    ExtractedRecord,
    IngestionRun,
    SourceComplianceCheck,
)


class DataSourceSerializer(serializers.ModelSerializer):
    class Meta:
        model = DataSource
        fields = [
            "pk", "name", "organization", "base_url", "source_type", "category",
            "geographic_scope", "country", "state", "district",
            "allowed_collection_methods", "robots_url", "terms_url", "license_url",
            "attribution_text", "approval_status", "approval_reason",
            "robots_status", "terms_status", "rate_limit_per_minute",
            "request_delay_seconds", "max_pages_per_run", "allows_images",
            "allows_documents", "allows_structured_data", "collection_enabled",
            "last_compliance_check_at", "last_successful_collection_at", "notes",
            "created_at",
        ]
        read_only_fields = [
            "pk", "approval_status", "collection_enabled", "robots_status",
            "terms_status", "last_compliance_check_at", "last_successful_collection_at",
            "created_at",
        ]


class SourceComplianceCheckSerializer(serializers.ModelSerializer):
    class Meta:
        model = SourceComplianceCheck
        fields = [
            "pk", "source", "run_id", "checked_at", "robots_url",
            "robots_retrieved", "robots_allows_target_paths", "terms_url",
            "terms_retrieved", "terms_manual_review_required",
            "login_required_detected", "captcha_detected", "paywall_detected",
            "blocked_reason", "decision", "evidence_path", "evidence_hash", "notes",
        ]
        read_only_fields = fields


class IngestionRunSerializer(serializers.ModelSerializer):
    class Meta:
        model = IngestionRun
        fields = [
            "pk", "source", "run_id", "started_at", "completed_at", "status",
            "collector_version", "configuration_snapshot", "pages_attempted",
            "pages_collected", "records_extracted", "documents_downloaded",
            "images_downloaded", "duplicates_skipped", "validation_failures",
            "blocked_items", "warnings", "report_path", "is_dry_run",
        ]
        read_only_fields = fields


class CollectedArtifactSerializer(serializers.ModelSerializer):
    class Meta:
        model = CollectedArtifact
        fields = [
            "pk", "source", "ingestion_run", "artifact_type", "original_url",
            "final_url", "local_path", "sha256", "content_type", "file_size",
            "retrieved_at", "http_status", "license_note", "attribution",
            "is_approved", "is_duplicate", "validation_status", "retention_status",
        ]
        read_only_fields = fields


class ExtractedRecordSerializer(serializers.ModelSerializer):
    class Meta:
        model = ExtractedRecord
        fields = [
            "pk", "source", "ingestion_run", "collected_artifact", "record_type",
            "normalized_data_json", "source_url", "source_locator",
            "source_published_date", "retrieved_at", "content_hash", "confidence",
            "verification_status", "review_notes", "reviewed_at",
        ]
        read_only_fields = fields


class DataReviewQueueSerializer(serializers.ModelSerializer):
    class Meta:
        model = DataReviewQueue
        fields = [
            "pk", "extracted_record", "proposed_target_model", "proposed_action",
            "risk_level", "validation_result", "source_freshness_status",
            "requires_human_review", "decision", "decision_notes", "decided_at",
            "created_at",
        ]
        read_only_fields = fields