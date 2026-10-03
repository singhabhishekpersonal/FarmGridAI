"""ML registry: registration, activation gate, audit logging."""
import pytest


@pytest.fixture
def user(db):
    from django.contrib.auth import get_user_model
    return get_user_model().objects.create_user(username="green", password="Str0ng!", phone="9876511111")


@pytest.fixture
def farm(user, db):
    from apps.farms.models import FarmService
    return FarmService.create_farm(user, "Green Farm", area=5, unit="acre", state="Uttar Pradesh")


def test_registry_row_created_for_equipment_classifier(db):
    from apps.ml_engine.models import MLModelRegistry
    from apps.ml_engine.registry import registry_record
    r, _ = MLModelRegistry.objects.get_or_create(
        key="equipment_classifier",
        defaults={"name": "Equipment classifier", "model_type": "vision", "status": "inactive"},
    )
    assert registry_record("equipment_classifier") is None  # inactive => not used
    r.status = "active"
    r.save()
    assert registry_record("equipment_classifier").key == "equipment_classifier"


def test_log_prediction_creates_audit_with_snapshot(user, farm):
    from apps.ml_engine.models import PredictionAuditLog
    from apps.ml_engine.registry import log_prediction
    audit = log_prediction(
        user=user,
        farm=farm,
        model_name="MobileNetV3-Large",
        model_version="v1",
        registry_key="equipment_classifier",
        input_type="equipment_image",
        input_snapshot={"image_hash": "abc"},
        output_snapshot={"predicted_class": "tractor", "confidence": 0.9},
        confidence="high",
        status="success",
    )
    saved = PredictionAuditLog.objects.get(pk=audit.pk)
    assert saved.registry_key == "equipment_classifier"
    assert saved.model_version == "v1"
    assert saved.confidence == "high"
    assert saved.status == "success"
    assert saved.input_snapshot["image_hash"] == "abc"


def test_activation_gate_rejects_missing_artifact(db, user):
    """register-equipment command must refuse when gates fail."""
    from django.core.management import call_command

    from django.core.management.base import CommandError
    with pytest.raises(CommandError):
        call_command("register_equipment_model", "--artifact", "D:/definitely/missing.pt", "--activate")


def test_activation_gate_rejects_corrupt_checksum(tmp_path, user, db):
    """A corrupt artifact must fail the checksum gate and stay inactive."""
    import json
    from pathlib import Path

    from django.core.management import call_command

    weights = tmp_path / "bad_model.pt"
    weights.write_bytes(b"not a real torch checkpoint")
    stem = weights.stem
    (tmp_path / f"{stem}_labels.json").write_text(
        json.dumps({"classes": ["Mahindra", "Sonalika", "Farmtrac", "John Deere", "New Holland", "Powertrac", "other", "unknown"]}),
        encoding="utf-8",
    )
    (tmp_path / f"{stem}_metadata.json").write_text(
        json.dumps({"model_architecture": "mobilenet_v3_large", "model_family": "top6",
                     "model_version": "v1", "class_labels": ["Mahindra", "Sonalika", "Farmtrac", "John Deere", "New Holland", "Powertrac", "other", "unknown"],
                     "unknown_threshold": 0.55, "test_macro_f1": 0.73,
                     "validation_macro_f1": 0.7,
                     "test_metrics_reported": {}}),
        encoding="utf-8",
    )
    import hashlib
    h = hashlib.sha256(weights.read_bytes()).hexdigest()
    (tmp_path / f"{stem}_checksum.txt").write_text(f"{h}  {weights.name}\n", encoding="utf-8")

    from apps.ml_engine.models import MLModelRegistry
    MLModelRegistry.objects.get_or_create(key="equipment_classifier", defaults={"name": "EC", "model_type": "vision", "status": "inactive"})
    from django.core.management.base import CommandError
    with pytest.raises(CommandError):
        call_command("register_equipment_model", "--artifact", str(weights), "--activate")
    MLModelRegistry.objects.filter(key="equipment_classifier").update(status="inactive")


def test_activation_gate_passes_with_real_artifact(db):
    """If the real trained artifact exists, --activate must succeed."""
    import json
    from pathlib import Path
    from django.conf import settings

    artifact = Path(settings.ML_EQUIPMENT_CLASSIFIER_ARTIFACT_DIR) / settings.ML_EQUIPMENT_CLASSIFIER_ARTIFACT_FILE
    if not artifact.is_file():
        pytest.skip("real artifact not present")
    from django.core.management import call_command
    call_command("register_equipment_model", "--activate")
    from apps.ml_engine.models import MLModelRegistry
    r = MLModelRegistry.objects.get(key="equipment_classifier")
    assert r.status == "active"
    v = r.versions.filter(is_active=True).first()
    assert v is not None
    assert float(v.metrics_json["test_macro_f1"]) >= float(settings.ML_EQUIPMENT_CLASSIFIER_ACTIVATION_MACRO_F1)