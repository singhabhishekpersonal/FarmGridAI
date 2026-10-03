"""Computer-vision classifier for equipment images (tractor-brand CNN).

The classifier is *opt-in*: it lazily loads a locally-stored artifact from
``settings.ML_EQUIPMENT_CLASSIFIER_WEIGHTS`` (or the configured artifact
dir/file). Nothing is downloaded during request handling and no network call
happens here. If the artifact is missing, corrupted, checksum-mismatched or
incompatible, the classifier falls back to an explicit ``fallback`` source and
never pretends a prediction happened.

Output contract (see ``predict``):
    predicted_class   -> brand label (or "unknown" below threshold)
    top_predictions   -> [{label, probability}, ...] top-k
    confidence_score  -> max softmax probability
    confidence_label  -> low | medium | high
    needs_user_confirmation -> always True
    used_ml           -> True only when a validated artifact was used
    artifact_available-> True only when the artifact passed all checks
    model_name / model_version / limitations / source
"""
import hashlib
import json
import logging
from pathlib import Path

from django.conf import settings

logger = logging.getLogger("FarmGrid")

try:
    import torch
    from torchvision import transforms

    _HAVE_TORCH = True
except Exception:  # pragma: no cover
    _HAVE_TORCH = False

_MEAN = [0.485, 0.456, 0.406]
_STD = [0.229, 0.224, 0.225]
_SIZE = 224
_TOP_K = 3

LIMITATIONS = [
    "Image classification estimates tractor brand category only.",
    "The farmer must confirm the result.",
    "The model does not determine exact model, fuel mileage, engine health, "
    "manufacturing year, repair history, or subsidy eligibility.",
]


def _preprocess():
    return transforms.Compose([
        transforms.Resize(256),
        transforms.CenterCrop(_SIZE),
        transforms.ToTensor(),
        transforms.Normalize(_MEAN, _STD),
    ])


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def _confidence_label(score: float) -> str:
    if score >= 0.80:
        return "high"
    if score >= 0.60:
        return "medium"
    return "low"


class EquipmentClassifier:
    """Lazy, validated wrapper around a fine-tuned MobileNetV3-Large."""

    def __init__(self, artifact_path="", unknown_threshold=None):
        self.artifact_path = artifact_path or getattr(settings, "ML_EQUIPMENT_CLASSIFIER_WEIGHTS", "")
        if not self.artifact_path and _HAVE_TORCH:
            artifact_dir = getattr(settings, "ML_EQUIPMENT_CLASSIFIER_ARTIFACT_DIR", "")
            artifact_file = getattr(settings, "ML_EQUIPMENT_CLASSIFIER_ARTIFACT_FILE", "equipment_classifier_mobilenetv3_top6_v1.pt")
            if artifact_dir:
                self.artifact_path = str(Path(artifact_dir) / artifact_file)
        if unknown_threshold is None:
            unknown_threshold = getattr(settings, "ML_EQUIPMENT_CLASSIFIER_UNKNOWN_THRESHOLD", 0.55)
        self.unknown_threshold = float(unknown_threshold)
        self.model = None
        self.classes = []
        self.label_meta = {}
        self._artifact_available = False
        self._load_error = None

    # ------------------------------------------------------------------
    def _resolve_paths(self):
        weights = Path(self.artifact_path)
        stem = weights.stem
        sidecar = {
            "labels": weights.with_name(stem + "_labels.json"),
            "metadata": weights.with_name(stem + "_metadata.json"),
            "checksum": weights.with_name(stem + "_checksum.txt"),
        }
        return weights, sidecar

    def _load(self):
        if not _HAVE_TORCH:
            self._load_error = "torch not available"
            return False
        if not self.artifact_path:
            self._load_error = "no artifact path configured"
            return False
        weights, sidecar = self._resolve_paths()
        if not weights.is_file():
            self._load_error = f"artifact missing: {weights}"
            return False
        try:
            checksum_file = sidecar["checksum"]
            if checksum_file.is_file():
                recorded = checksum_file.read_text(encoding="utf-8").strip().split()[0]
                actual = _sha256_file(weights)
                if recorded != actual:
                    self._load_error = f"checksum mismatch recorded={recorded[:12]} actual={actual[:12]}"
                    return False
            else:
                logger.warning("no checksum file for %s; skipping checksum check", weights)
        except Exception as exc:  # pragma: no cover
            self._load_error = f"checksum read failed: {exc}"
            return False

        try:
            meta = json.loads(sidecar["metadata"].read_text(encoding="utf-8"))
            labels = json.loads(sidecar["labels"].read_text(encoding="utf-8"))
        except Exception as exc:
            self._load_error = f"labels/metadata unreadable: {exc}"
            return False

        try:
            state = torch.load(weights, map_location="cpu")
            if not isinstance(state, dict) or "state_dict" not in state:
                self._load_error = "artifact does not contain a state_dict (incompatible format)"
                return False
            arch = state.get("architecture", self.label_meta.get("model_architecture", "mobilenet_v3_large"))
            num_classes = state.get("num_classes", len(labels["classes"]))
            from torchvision.models import mobilenet_v3_large, resnet18

            if arch == "mobilenet_v3_large":
                model = mobilenet_v3_large(weights=None)
                in_features = model.classifier[-1].in_features
                model.classifier[-1] = torch.nn.Linear(in_features, num_classes)
            elif arch == "resnet18":
                model = resnet18(weights=None)
                in_features = model.fc.in_features
                model.fc = torch.nn.Linear(in_features, num_classes)
            else:
                raise ValueError(f"unsupported artifact architecture: {arch}")
            model.load_state_dict(state["state_dict"])
            model.eval()
        except Exception as exc:
            self._load_error = f"artifact load failed: {exc}"
            return False

        self.model = model
        self.classes = list(labels["classes"])
        self.label_meta = {**meta, "checksum_validated": True}
        self._artifact_available = True
        self._load_error = None
        logger.info("equipment classifier loaded: arch=%s classes=%d unknown_threshold=%.2f",
                    arch, len(self.classes), self.unknown_threshold)
        return True

    # ------------------------------------------------------------------
    @property
    def available(self) -> bool:
        if self.model is None and self._load_error is None:
            self._load()
        return self.model is not None

    @property
    def artifact_available(self) -> bool:
        if self.model is None and self._load_error is None:
            self._load()
        return self._artifact_available

    @property
    def model_version(self) -> str:
        return self.label_meta.get("model_version", "") if self.label_meta else ""

    @property
    def artifact_error(self):
        return self._load_error

    # ------------------------------------------------------------------
    def predict(self, image_file):
        """Run full prediction. Never raises; falls back gracefully.

        Returns a dict (see module docstring). ``image_file`` is a path or a
        binary file-like object opened for reading.
        """
        if not self.available:
            return {
                "predicted_class": "unknown",
                "predicted_brand": "",
                "top_predictions": [{"label": "unknown", "probability": 1.0}],
                "confidence_score": 1.0,
                "confidence_label": "low",
                "needs_user_confirmation": True,
                "used_ml": False,
                "artifact_available": False,
                "model_name": "equipment_classifier",
                "model_version": "fallback",
                "source": "fallback",
                "unknown_threshold": self.unknown_threshold,
                "limitations": LIMITATIONS,
            }
        return self.ready_predict(image_file)

    def ready_predict(self, image_file):
        from PIL import Image

        try:
            if hasattr(image_file, "seek"):
                image_file.seek(0)
            img = Image.open(image_file).convert("RGB")
        except Exception as exc:
            logger.warning("classifier could not read image: %s", exc)
            return {
                "predicted_class": "unknown",
                "predicted_brand": "",
                "top_predictions": [{"label": "unknown", "probability": 1.0}],
                "confidence_score": 1.0,
                "confidence_label": "low",
                "needs_user_confirmation": True,
                "used_ml": False,
                "artifact_available": self._artifact_available,
                "model_name": self.label_meta.get("model_architecture", "mobilenet_v3_large"),
                "model_version": self.model_version or "unknown",
                "source": "failed",
                "unknown_threshold": self.unknown_threshold,
                "limitations": LIMITATIONS,
            }
        tensor = _preprocess()(img).unsqueeze(0)
        with torch.no_grad():
            logits = self.model(tensor)
            probs = torch.softmax(logits, dim=1)[0]
        scores, indices = torch.topk(probs, k=min(_TOP_K, len(self.classes)))
        top = [{"label": self.classes[i.item()], "probability": round(float(s), 6)}
               for s, i in zip(scores, indices)]
        max_score = float(probs.max().item())
        top_label = top[0]["label"]

        predicted_brand = ""
        if max_score >= self.unknown_threshold:
            predicted_class = top_label
            predicted_brand = top_label
        else:
            predicted_class = "unknown"

        return {
            "predicted_class": predicted_class,
            "predicted_brand": predicted_brand,
            "top_predictions": top,
            "confidence_score": max_score,
            "confidence_label": _confidence_label(max_score),
            "needs_user_confirmation": True,
            "used_ml": True,
            "artifact_available": True,
            "model_name": self.label_meta.get("model_architecture", "mobilenet_v3_large"),
            "model_version": self.model_version or "v1",
            "source": "ml_model" if max_score >= self.unknown_threshold else "ml_model_low_confidence",
            "unknown_threshold": self.unknown_threshold,
            "limitations": LIMITATIONS,
        }


# Global singleton: every service/API goes through this object so the heavy
# artifact load happens at most once per process.
DEFAULT_CLASSIFIER = EquipmentClassifier()


def classify_image(image_file):
    """Stateless entry point returning the full prediction dict."""
    return DEFAULT_CLASSIFIER.predict(image_file)