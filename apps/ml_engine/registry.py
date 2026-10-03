"""Registry + audit helpers for the ML engine.

Every prediction goes through :func:`log_prediction` so we keep a complete,
queryable audit trail and know exactly which model (or fallback) produced it.
"""
import hashlib
import json
import time
import uuid

from apps.ml_engine.models import MLModelRegistry, MLModelVersion, PredictionAuditLog


def registry_record(key):
    """Return the active model registry row, or None (means 'rule fallback')."""
    return MLModelRegistry.objects.filter(key=key, status="active").first()


def resolve_version(registry):
    if registry is None:
        return ""
    version = MLModelVersion.objects.filter(registry=registry, is_active=True).order_by("-created_at").first()
    return version.version if version else ""


def _hash(obj) -> str:
    try:
        return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode("utf-8")).hexdigest()
    except (TypeError, ValueError):
        return ""


def log_prediction(
    *,
    user=None,
    farm=None,
    model_name="rules",
    model_version="",
    registry_key="",
    input_type="",
    input_snapshot=None,
    output_snapshot=None,
    confidence="low",
    status="success",
):
    """Create a PredictionAuditLog row with a stable input hash."""
    started = time.monotonic()
    audit = PredictionAuditLog.objects.create(
        user=user,
        farm=farm,
        model_name=model_name,
        model_version=model_version or "N/A",
        registry_key=registry_key or ("rules:" + model_name),
        input_type=input_type or "generic",
        input_snapshot=input_snapshot or {},
        input_hash=_hash(input_snapshot) or uuid.uuid4().hex,
        output_snapshot=output_snapshot or {},
        confidence=confidence or "low",
        latency_ms=int((time.monotonic() - started) * 1000),
        status=status,
    )
    return audit


def snapshot_ml_usage(keys) -> list:
    """Return a list of {key, version} for the models actually used."""
    rows = []
    for key in keys:
        registry = MLModelRegistry.objects.filter(key=key).first()
        rows.append(
            {
                "key": key,
                "version": resolve_version(registry) if registry else "fallback",
                "used_ml": bool(registry) and registry.status == "active",
            }
        )
    return rows


def touch_registry(key, name, model_type, description="", fallback_strategy="deterministic rules fallback") -> MLModelRegistry:
    """Ensure a registry row exists (used at startup / seed time)."""
    registry, _ = MLModelRegistry.objects.get_or_create(
        key=key,
        defaults={
            "name": name,
            "model_type": model_type,
            "status": "active",
            "description": description,
            "fallback_strategy": fallback_strategy,
        },
    )
    return registry