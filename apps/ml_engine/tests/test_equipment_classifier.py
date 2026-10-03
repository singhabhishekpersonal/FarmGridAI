"""Tests for the equipment image classifier pipeline and its Django integration.

Each test builds its own tiny isolated "artifact" (tmp_path) so the suite never
depends on the real trained model OR the network. Fallback behaviour is
exercised by pointing the classifier at missing/corrupt/incompatible paths.

The tiny artifacts are REAL torchvision MobileNetV3-Large models with the final
linear layer force-set so logits are deterministic:
  * dominant_class: bias +5 for that class, -5 for others, weights 0
  * dominant_class None: all biases 0 -> uniform softmax (low confidence)
"""
import hashlib
import io
import json

import pytest

from apps.ml_engine.vision.classifier import EquipmentClassifier, LIMITATIONS


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def _build_model(num_classes, dominant_class=None):
    import torch
    from torchvision.models import mobilenet_v3_large

    model = mobilenet_v3_large(weights=None)
    in_features = model.classifier[-1].in_features
    model.classifier[-1] = torch.nn.Linear(in_features, num_classes)
    with torch.no_grad():
        model.classifier[-1].weight.zero_()
        bias = model.classifier[-1].bias
        bias.zero_()
        if dominant_class is not None:
            bias[dominant_class] = 5.0
            for i in range(num_classes):
                if i != dominant_class:
                    bias[i] = -5.0
    return model


def make_tiny_artifact(tmp_path, num_classes=3, classes=None, dominant_class=None,
                       corrupt_checksum=False, unsupported_arch=False):
    """Create a minimal but valid classifier artifact for injection tests."""
    import torch

    classes = classes or [f"C{i}" for i in range(num_classes)]
    assert len(classes) == num_classes
    model = _build_model(num_classes, dominant_class=dominant_class)

    weights = tmp_path / "toy_model.pt"
    torch.save({
        "state_dict": model.state_dict(),
        "architecture": "mobilenet_v3_large" if not unsupported_arch else "something_else",
        "num_classes": num_classes,
        "classes": classes,
        "version": "test",
        "epoch": 0,
        "val_macro_f1": 0.0,
        "val_top1": 0.0,
    }, weights)

    stem = weights.stem
    (tmp_path / f"{stem}_labels.json").write_text(
        json.dumps({"classes": classes,
                     "class_to_idx": {c: i for i, c in enumerate(classes)},
                     "architecture": "mobilenet_v3_large",
                     "version": "test"}),
        encoding="utf-8",
    )
    (tmp_path / f"{stem}_metadata.json").write_text(
        json.dumps({
            "model_architecture": "mobilenet_v3_large",
            "model_family": "top6",
            "model_version": "test",
            "class_labels": classes,
            "unknown_threshold": 0.55,
            "test_macro_f1": 0.8,
            "validation_macro_f1": 0.8,
            "test_metrics_reported": {"test_accuracy": 0.9, "test_balanced_accuracy": 0.8,
                                       "test_weighted_f1": 0.85, "test_top3_accuracy": 0.95,
                                       "test_samples": 10},
        }),
        encoding="utf-8",
    )
    checksum = sha256_file(weights)
    if corrupt_checksum:
        checksum = "0" * 64
    (tmp_path / f"{stem}_checksum.txt").write_text(f"{checksum}  {weights.name}\n", encoding="utf-8")
    return weights


def make_image_bytes():
    from PIL import Image
    img = Image.new("RGB", (300, 200), color=(128, 128, 128))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf


# ---------------------------------------------------------------------------
# classifier behaviour
# ---------------------------------------------------------------------------
def test_has_limitation_text():
    assert any("brand" in l for l in LIMITATIONS)
    assert any("farmer must confirm" in l.lower() for l in LIMITATIONS)


def test_lazy_load_no_such_file():
    classifier = EquipmentClassifier(artifact_path="D:/definitely/missing/model.pt")
    assert classifier.available is False
    assert classifier.artifact_available is False
    out = classifier.predict(None)
    assert out["used_ml"] is False
    assert out["source"] == "fallback"
    assert out["model_version"] == "fallback"
    assert out["needs_user_confirmation"] is True


def test_corrupt_checksum_falls_back(tmp_path):
    weights = make_tiny_artifact(tmp_path, corrupt_checksum=True)
    classifier = EquipmentClassifier(artifact_path=str(weights))
    assert classifier.available is False
    assert classifier.artifact_error and "checksum mismatch" in classifier.artifact_error
    out = classifier.predict(None)
    assert out["source"] == "fallback"
    assert out["used_ml"] is False


def test_unsupported_architecture_falls_back(tmp_path):
    weights = make_tiny_artifact(tmp_path, unsupported_arch=True)
    classifier = EquipmentClassifier(artifact_path=str(weights))
    assert classifier.available is False
    out = classifier.predict(None)
    assert out["source"] == "fallback"


def test_valid_artifact_loads_and_infers(tmp_path):
    weights = make_tiny_artifact(tmp_path, num_classes=3, dominant_class=0)
    classifier = EquipmentClassifier(artifact_path=str(weights))
    assert classifier.available is True
    assert classifier.artifact_available is True
    assert classifier.classes == ["C0", "C1", "C2"]
    assert classifier.artifact_error is None

    out = classifier.ready_predict(make_image_bytes())
    assert out["used_ml"] is True
    assert out["artifact_available"] is True
    assert out["predicted_class"] == "C0"
    assert out["predicted_brand"] == "C0"
    assert out["confidence_score"] > 0.8
    assert out["model_version"] == "test"
    assert out["source"] == "ml_model"
    assert out["needs_user_confirmation"] is True
    assert out["limitations"] == LIMITATIONS
    assert len(out["top_predictions"]) == 3


def test_flat_unknown_model_returns_unknown(tmp_path):
    """Uniform logits (dominant_class=None) fall below the threshold -> unknown."""
    weights = make_tiny_artifact(
        tmp_path,
        num_classes=7,
        classes=["Mahindra", "Sonalika", "Farmtrac", "John Deere", "New Holland", "Powertrac", "other"],
        dominant_class=None,
    )
    classifier = EquipmentClassifier(artifact_path=str(weights), unknown_threshold=0.55)
    assert classifier.available is True
    out = classifier.ready_predict(make_image_bytes())
    assert out["predicted_class"] == "unknown"
    assert out["confidence_score"] < classifier.unknown_threshold
    assert out["confidence_label"] == "low"
    assert out["source"] == "ml_model_low_confidence"
    assert out["needs_user_confirmation"] is True


def test_confidence_label_mapping():
    from apps.ml_engine.vision.classifier import _confidence_label
    assert _confidence_label(0.9) == "high"
    assert _confidence_label(0.7) == "medium"
    assert _confidence_label(0.4) == "low"


def test_kind_for_brand_mapping():
    from apps.ml_engine.services.equipment_analysis import EquipmentAnalysisService
    assert EquipmentAnalysisService._kind_for_brand("Mahindra") == "tractor"
    assert EquipmentAnalysisService._kind_for_brand("John Deere") == "tractor"
    assert EquipmentAnalysisService._kind_for_brand("Sonalika") == "tractor"
    assert EquipmentAnalysisService._kind_for_brand("other") == "unknown"
    assert EquipmentAnalysisService._kind_for_brand("") == "unknown"


def test_import_classify_image_present():
    from apps.ml_engine.vision.classifier import classify_image
    assert callable(classify_image)


# ---------------------------------------------------------------------------
# service-level integration: brand -> kind mapping + audit
# ---------------------------------------------------------------------------
@pytest.fixture
def user(db):
    from django.contrib.auth import get_user_model
    return get_user_model().objects.create_user(username="green", password="Str0ng!", phone="9876511111")


@pytest.fixture
def equipment_image(user, db):
    from apps.core.constants import EQUIPMENT_CLASS_CHOICES
    from apps.equipment.models import EquipmentCategory, EquipmentImage, FarmerEquipment
    from apps.equipment.models import CONDITION_BANDS
    from apps.farms.models import FarmService

    farm = FarmService.create_farm(user, "Green Farm", area=5, unit="acre", state="Uttar Pradesh")
    category, _ = EquipmentCategory.objects.get_or_create(code="tractor", defaults={"name": "Tractor"})
    equipment = FarmerEquipment.objects.create(farm=farm, category=category, is_owned=True, created_by=user)
    img = EquipmentImage.objects.create(
        equipment=equipment,
        content_hash="a" * 64,
        file_size=100,
        mime_type="image/png",
        status="processed",
        created_by=user,
    )
    return img


def test_service_maps_high_confidence_brand_to_tractor(monkeypatch, db, equipment_image):
    from apps.ml_engine.services import equipment_analysis as svc

    fake_result = {
        "predicted_class": "Mahindra",
        "predicted_brand": "Mahindra",
        "top_predictions": [{"label": "Mahindra", "probability": 0.95}],
        "confidence_score": 0.95,
        "confidence_label": "high",
        "used_ml": True,
        "artifact_available": True,
        "unknown_threshold": 0.55,
        "model_name": "mobilenet_v3_large",
        "model_version": "test",
        "source": "ml_model",
        "limitations": LIMITATIONS,
    }
    monkeypatch.setattr(svc, "classify_image", lambda image_file: fake_result)

    service = svc.EquipmentAnalysisService(equipment_image, user=equipment_image.created_by)
    pred = service.classify(persist=True)

    assert pred["predicted_class"] == "tractor"
    assert pred["predicted_brand"] == "Mahindra"
    assert pred["confidence_label"] == "high"
    assert pred["used_ml"] is True
    assert pred["artifact_available"] is True
    assert pred["needs_user_confirmation"] is True

    stored = equipment_image.predictions.first()
    assert stored.predicted_class == "tractor"
    assert stored.predicted_brand == "Mahindra"
    assert stored.used_ml is True
    assert stored.confidence_label == "high"
    assert stored.top_predictions == [{"label": "Mahindra", "probability": 0.95}]

    from apps.ml_engine.models import PredictionAuditLog
    assert PredictionAuditLog.objects.filter(registry_key="equipment_classifier").exists()


def test_service_unknown_brand_maps_to_unknown(monkeypatch, db, equipment_image):
    from apps.ml_engine.services import equipment_analysis as svc

    fake_result = {
        "predicted_class": "other",
        "predicted_brand": "other",
        "top_predictions": [{"label": "other", "probability": 0.6}],
        "confidence_score": 0.6,
        "confidence_label": "medium",
        "used_ml": True,
        "artifact_available": True,
        "unknown_threshold": 0.55,
        "model_name": "mobilenet_v3_large",
        "model_version": "test",
        "source": "ml_model",
        "limitations": LIMITATIONS,
    }
    monkeypatch.setattr(svc, "classify_image", lambda image_file: fake_result)

    service = svc.EquipmentAnalysisService(equipment_image, user=equipment_image.created_by)
    pred = service.classify(persist=True)
    assert pred["predicted_class"] == "unknown"
    assert pred["predicted_brand"] == "other"


def test_service_keeps_fallback_source_on_missing_artifact(db, equipment_image):
    from apps.ml_engine import registry
    from apps.ml_engine.services import equipment_analysis as svc

    fallback = {
        "predicted_class": "unknown",
        "predicted_brand": "",
        "top_predictions": [{"label": "unknown", "probability": 1.0}],
        "confidence_score": 1.0,
        "confidence_label": "low",
        "used_ml": False,
        "artifact_available": False,
        "unknown_threshold": 0.55,
        "model_name": "equipment_classifier",
        "model_version": "fallback",
        "source": "fallback",
        "limitations": LIMITATIONS,
    }
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(svc, "classify_image", lambda image_file: fallback)

    service = svc.EquipmentAnalysisService(equipment_image, user=equipment_image.created_by)
    pred = service.classify(persist=True)
    assert pred["source"] == "fallback"
    assert pred["used_ml"] is False
    assert pred["predicted_class"] == "unknown"
    assert pred["needs_user_confirmation"] is True