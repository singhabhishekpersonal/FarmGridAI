"""ML engine domain models: registry, versions, audits, training runs."""
import uuid

from django.conf import settings
from django.db import models

from apps.core.constants import ConfidenceLevel, DataSource
from apps.core.models import AuditModel, BaseModel, TimeStampedModel


class MLModelRegistry(BaseModel):
    """Registered model metadata. Models can be active, inactive, or archived.

    ``key`` is a stable machine identifier (e.g. ``equipment_classifier``).
    """

    KEY_CHOICES = [
        ("equipment_classifier", "Equipment classifier (vision)"),
        ("condition_assessor", "Condition risk assessor (vision/rules)"),
        ("expense_estimator", "Expense range estimator (classical)"),
        ("operating_cost_estimator", "Equipment operating cost estimator (classical)"),
        ("recommendation_ranker", "Recommendation ranker (classical)"),
        ("anomaly_detector", "Anomaly detector (isolation forest)"),
        ("forecast_baseline", "Time-series baseline forecaster"),
        ("forecast_lstm", "Time-series LSTM forecaster"),
        ("rag_chatbot_orchestrator", "RAG chatbot orchestrator (LLM)"),
    ]

    MODEL_TYPE_CHOICES = [("vision", "Vision"), ("classical", "Classical ML"), ("forecast", "Forecasting"), ("llm", "LLM/RAG"), ("rules", "Rules only")]

    STATUS_CHOICES = [("active", "Active"), ("inactive", "Inactive"), ("archived", "Archived"), ("training", "Training")]

    key = models.CharField(max_length=60, choices=KEY_CHOICES, unique=True)
    name = models.CharField(max_length=120)
    model_type = models.CharField(max_length=15, choices=MODEL_TYPE_CHOICES)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default="inactive")
    description = models.TextField(blank=True)
    artifact_path = models.CharField(max_length=255, blank=True)
    input_schema_version = models.CharField(max_length=20, default="1.0")
    requires_dependency = models.CharField(max_length=120, blank=True)
    fallback_strategy = models.CharField(max_length=200, default="deterministic rules fallback")

    class Meta:
        ordering = ["key"]

    def __str__(self):
        return f"{self.key} ({self.status})"


class MLModelVersion(TimeStampedModel):
    """An immutable version of a registered model."""

    registry = models.ForeignKey(MLModelRegistry, on_delete=models.CASCADE, related_name="versions")
    version = models.CharField(max_length=40)
    artifact_path = models.CharField(max_length=255, blank=True)
    metrics_json = models.JSONField(default=dict)
    dataset_version = models.CharField(max_length=40, blank=True)
    is_active = models.BooleanField(default=True)
    is_fallback = models.BooleanField(default=False)
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
        editable=False,
    )

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["registry", "version"], name="uniq_model_registry_version")
        ]

    def __str__(self):
        return f"{self.registry.key} @ {self.version}"


class FeatureSnapshot(models.Model):
    """Hashed snapshot of the raw feature vector used for a prediction."""

    name = models.CharField(max_length=80)
    values_json = models.JSONField(default=dict)
    values_hash = models.CharField(max_length=64, db_index=True)
    schema_version = models.CharField(max_length=20, default="1.0")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.name} {self.values_hash[:8]}"


class PredictionAuditLog(BaseModel):
    """Complete audit trail for every prediction made on the platform."""

    STATUS_CHOICES = [("success", "Success"), ("fallback", "Fallback"), ("failed", "Failed")]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="prediction_audits")
    farm = models.ForeignKey("farms.Farm", on_delete=models.SET_NULL, null=True, blank=True, related_name="prediction_audits")
    model_name = models.CharField(max_length=120)
    model_version = models.CharField(max_length=40, blank=True)
    registry_key = models.CharField(max_length=60, blank=True)
    input_type = models.CharField(max_length=30)
    input_snapshot = models.JSONField(default=dict)
    input_hash = models.CharField(max_length=64, blank=True)
    output_snapshot = models.JSONField(default=dict)
    confidence = models.CharField(max_length=10, choices=ConfidenceLevel.choices, default=ConfidenceLevel.LOW)
    latency_ms = models.PositiveIntegerField(null=True, blank=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default="success")

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["registry_key", "-created_at"])]

    def __str__(self):
        return f"{self.model_name} v{self.model_version} {self.status}"


class TrainingRun(BaseModel):
    """A training job execution with its configuration and outcome."""

    STATUS_CHOICES = [("pending", "Pending"), ("running", "Running"), ("completed", "Completed"), ("failed", "Failed"), ("cancelled", "Cancelled")]

    registry = models.ForeignKey(MLModelRegistry, on_delete=models.CASCADE, related_name="training_runs")
    run_label = models.CharField(max_length=120)
    dataset_version = models.CharField(max_length=60, blank=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default="pending")
    params_json = models.JSONField(default=dict)
    metrics_json = models.JSONField(default=dict)
    artifact_path = models.CharField(max_length=255, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.run_label} ({self.status})"


class ModelEvaluationMetric(TimeStampedModel):
    """A single scalar metric from an evaluation / training run."""

    training_run = models.ForeignKey(TrainingRun, on_delete=models.CASCADE, related_name="metrics")
    metric_name = models.CharField(max_length=60)
    value = models.FloatField()
    split = models.CharField(max_length=20, default="test")

    class Meta:
        ordering = ["metric_name"]

    def __str__(self):
        return f"{self.metric_name}={self.value:.4f} ({self.split})"


class DataQualityReport(BaseModel):
    """Report on dataset quality with a summary score and issue list."""

    dataset_name = models.CharField(max_length=120)
    quality_score = models.FloatField(default=0.0)
    issues_json = models.JSONField(default=list)  # list of {severity, message}
    row_count = models.PositiveIntegerField(default=0)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.dataset_name}: {self.quality_score:.2f}"