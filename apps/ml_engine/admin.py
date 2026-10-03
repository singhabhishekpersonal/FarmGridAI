"""Admin configuration for the ML engine app."""
from django.contrib import admin

from apps.ml_engine.models import (
    DataQualityReport,
    FeatureSnapshot,
    MLModelRegistry,
    MLModelVersion,
    ModelEvaluationMetric,
    PredictionAuditLog,
    TrainingRun,
)


class MLModelVersionInline(admin.TabularInline):
    model = MLModelVersion
    extra = 0


@admin.register(MLModelRegistry)
class MLModelRegistryAdmin(admin.ModelAdmin):
    list_display = ["key", "name", "model_type", "status", "requires_dependency", "fallback_strategy"]
    list_filter = ["model_type", "status"]
    search_fields = ["key", "name"]
    inlines = [MLModelVersionInline]


@admin.register(PredictionAuditLog)
class PredictionAuditLogAdmin(admin.ModelAdmin):
    list_display = ["model_name", "model_version", "status", "confidence", "user", "farm", "created_at"]
    list_filter = ["status", "confidence", "model_name"]
    search_fields = ["model_name", "registry_key", "input_hash"]
    readonly_fields = ["input_snapshot", "output_snapshot", "input_hash", "latency_ms", "created_at"]


class ModelEvaluationMetricInline(admin.TabularInline):
    model = ModelEvaluationMetric
    extra = 0


@admin.register(TrainingRun)
class TrainingRunAdmin(admin.ModelAdmin):
    list_display = ["run_label", "registry", "status", "dataset_version", "created_at"]
    list_filter = ["status"]
    inlines = [ModelEvaluationMetricInline]


@admin.register(FeatureSnapshot)
class FeatureSnapshotAdmin(admin.ModelAdmin):
    list_display = ["name", "schema_version", "created_at"]
    search_fields = ["name", "values_hash"]


@admin.register(DataQualityReport)
class DataQualityReportAdmin(admin.ModelAdmin):
    list_display = ["dataset_name", "quality_score", "row_count", "created_at"]