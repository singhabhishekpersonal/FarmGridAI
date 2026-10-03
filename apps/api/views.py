"""Health, readiness and operational status endpoints.

Public endpoints here only ever reveal safe, stable aggregates: they never
expose database internals, secrets, filesystem paths or hostnames. DB errors
are redacted to a generic message so operators cannot leak connection details
through the readiness probe.
"""
from django.conf import settings
from django.db import connection
from django.http import JsonResponse
from rest_framework import status
from rest_framework.views import APIView

from apps.api.mixins import ApiResponseMixin


def health_check(request):
    """Liveness: the process is up."""
    return JsonResponse({"status": "ok", "service": "FarmGrid AI"})


def readiness_check(request):
    """Readiness: DB connectivity check (error details redacted)."""
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        ready = True
        error = ""
    except Exception:  # pragma: no cover
        ready = False
        error = "database unavailable"
    return JsonResponse({"ready": ready, "error": error}, status=200 if ready else 503)


class CapabilitiesView(ApiResponseMixin):
    """Stable, public descriptor of what the platform can do.

    Contains no secrets, paths, hostnames or per-farmer data. Reported model
    information is derived from settings defaults (the classifier only runs
    when an artifact is present) and is deliberately conservative.
    """

    def get(self, request):
        capabilities = {
            "offline_capable": True,
            "analytics_types": [
                "expense", "machinery_finance", "solar_energy", "crop_cost",
                "subsidies", "recommendations",
            ],
            "estimate_contract": {
                "always_uses_ranges": True,
                "confidence_levels": ["low", "medium", "high"],
                "requires_farmer_confirmation": True,
                "requires_official_verification": True,
            },
            "models": {
                "equipment_classifier": {
                    "architecture": getattr(settings, "ML_EQUIPMENT_CLASSIFIER_ARCH", "mobilenet_v3_large"),
                    "artifact_required": True,
                    "offline_inference": True,
                    "fallback_available": True,
                    "requires_farmer_confirmation": True,
                }
            },
            "chatbot": {
                "llm_optional": True,
                "offline_fallback": True,
                "sources_only_web": True,
                "preliminary_warnings": True,
            },
            "data_ingestion": {
                "network_default_off": True,
                "collection_disabled_by_default": True,
                "manual_review_required": True,
                "never_auto_publishes": True,
            },
        }
        return self.respond(data={"capabilities": capabilities}, message="Platform capabilities.")


class ModelStatusView(ApiResponseMixin):
    """Safe aggregate over the ML model registry (no artifact paths/weights)."""

    def get(self, request):
        from apps.ml_engine.models import MLModelRegistry

        models = []
        for reg in MLModelRegistry.objects.all().order_by("key"):
            active = reg.versions.filter(is_active=True).first()
            models.append(
                {
                    "key": reg.key,
                    "model_type": reg.model_type,
                    "status": reg.status,
                    "version": active.version if active else "",
                    "has_metrics_recorded": bool(active and active.metrics_json),
                    "auto_retrain": False,
                }
            )
        return self.respond(data={"models": models, "count": len(models)}, message="ML registry status.")


class DataSourceStatusView(ApiResponseMixin):
    """Safe aggregate of ingestion-source approval state (no URLs or notes)."""

    def get(self, request):
        from apps.data_ingestion.models import DataSource

        statuses = DataSource.ApprovalStatus.values
        counts = {}
        for value in statuses:
            counts[value] = DataSource.objects.filter(approval_status=value).count()
        return self.respond(
            data={
                "sources_total": sum(counts.values()),
                "by_approval_status": counts,
            },
            message="Data-source approval status.",
        )