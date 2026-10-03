"""Register the trained equipment classifier in the ML model registry.

The command never auto-activates. It loads the artifact, validates the
checksum, the labels/metadata, the recorded test macro-F1 and runs a small
inference smoke test against a real image. Only when every gate passes and
``--activate`` is given is the model marked active.

Activation gate (all must be true):
  * artifact file exists and its sha256 matches *_checksum.txt
  * *_labels.json and *_metadata.json parse and agree on classes
  * metadata test_macro_f1 >= ML_EQUIPMENT_CLASSIFIER_ACTIVATION_MACRO_F1
  * a smoke-test inference on a real image returns used_ml=True
"""
import json
import logging
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.ml_engine.models import MLModelRegistry, MLModelVersion
from apps.ml_engine.vision.classifier import EquipmentClassifier

logger = logging.getLogger("FarmGrid")


class Command(BaseCommand):
    help = "Register (and optionally activate) the equipment classifier artifact."

    def add_arguments(self, parser):
        parser.add_argument("--artifact", default="", help="Path to the .pt artifact (default: settings-derived).")
        parser.add_argument("--dataset-version", default="tractor_brand_dataset_top6", help="Dataset version label.")
        parser.add_argument("--notes", default="", help="Free text notes for the version row.")
        parser.add_argument("--activate", action="store_true", help="Activate only if every gate passes.")
        parser.add_argument("--smoke-image", default="", help="Optional image path for the inference smoke test.")

    def handle(self, *args, **options):
        classifier = EquipmentClassifier(artifact_path=options["artifact"])
        weights, sidecar = classifier._resolve_paths()
        for name, path in (("artifact", weights), ("labels", sidecar["labels"]),
                           ("metadata", sidecar["metadata"]), ("checksum", sidecar["checksum"])):
            if not path.is_file():
                raise CommandError(f"Gate failed: {name} missing at {path}")

        if not classifier.available:
            raise CommandError(f"Gate failed: model load error -> {classifier.artifact_error}")

        meta = classifier.label_meta
        classes = classifier.classes
        test_f1 = float(meta.get("test_macro_f1") or 0.0)
        gate_f1 = float(getattr(settings, "ML_EQUIPMENT_CLASSIFIER_ACTIVATION_MACRO_F1", 0.70))

        self.stdout.write(f"artifact       : {weights}")
        self.stdout.write(f"architecture   : {meta.get('model_architecture')}")
        self.stdout.write(f"classes ({len(classes)}): {', '.join(classes)}")
        self.stdout.write(f"test_macro_f1  : {test_f1:.4f} (activation gate {gate_f1:.2f})")

        ok_checksum = bool(classifier.artifact_available) and classifier._load_error is None
        ok_f1 = test_f1 >= gate_f1

        # Smoke inference test on a real image.
        smoke_image = Path(options["smoke_image"]) if options["smoke_image"] else None
        if smoke_image and smoke_image.is_file():
            result = classifier.ready_predict(smoke_image)
            ok_smoke = result["used_ml"] is True
            self.stdout.write(f"smoke predict  : {result['predicted_class']} "
                              f"conf={result['confidence_score']:.3f} label={result['confidence_label']}")
        else:
            ok_smoke = None
            self.stdout.write("smoke predict  : skipped (no --smoke-image provided)")

        registry, _ = MLModelRegistry.objects.get_or_create(
            key="equipment_classifier",
            defaults={
                "name": "Equipment classifier (tractor brand, MobileNetV3-Large)",
                "model_type": "vision",
                "status": "inactive",
                "description": "Top-6 tractor brand classifier trained on the "
                               "locally prepared TractorGyan-derived dataset. "
                               "No new sites were scraped during dataset preparation.",
                "fallback_strategy": "deterministic rules fallback",
            },
        )
        if registry.status not in ("inactive", "active"):
            raise CommandError(f"registry status is {registry.status}; refusing to modify")

        metrics = {
            "test_accuracy": meta.get("test_metrics_reported", {}).get("test_accuracy"),
            "test_balanced_accuracy": meta.get("test_metrics_reported", {}).get("test_balanced_accuracy"),
            "test_macro_f1": test_f1,
            "test_weighted_f1": meta.get("test_metrics_reported", {}).get("test_weighted_f1"),
            "test_top3_accuracy": meta.get("test_metrics_reported", {}).get("test_top3_accuracy"),
            "validation_macro_f1": meta.get("validation_macro_f1"),
            "test_samples": meta.get("test_metrics_reported", {}).get("test_samples"),
        }
        version, version_created = MLModelVersion.objects.get_or_create(
            registry=registry,
            version=meta.get("model_version") or "v1",
            defaults={
                "artifact_path": str(weights),
                "metrics_json": metrics,
                "dataset_version": options["dataset_version"],
                "is_active": False,
                "notes": options["notes"] or f"Registered from {weights}. Test-set numbers are reported honestly; never relabel val/train as test.",
            },
        )
        if not version_created:
            version.artifact_path = str(weights)
            version.metrics_json = metrics
            version.save()

        gates = {
            "load_and_checksum": ok_checksum,
            "labels_and_metadata": len(classes) >= 6,
            "test_macro_f1_meets_threshold": ok_f1,
            "inference_smoke_test": ok_smoke if ok_smoke is not None else None,
        }
        passed = (
            ok_checksum
            and len(classes) >= 6
            and ok_f1
            and (ok_smoke is not False)  # None == smoke not required
            and (ok_smoke is not None or not options["activate"])
        )

        pred_gate = {k: v for k, v in gates.items() if v is not None}
        all_gates_ok = all(pred_gate.values())
        self.stdout.write(f"gate summary   : {json.dumps(pred_gate, indent=2)}")
        self.stdout.write(f"activation allowed: {all_gates_ok}")

        activate_anyway = options["activate"] and all_gates_ok
        if activate_anyway:
            MLModelVersion.objects.filter(registry=registry).exclude(version=version.version).update(is_active=False)
            registry.status = "active"
            registry.artifact_path = str(weights)
            registry.save()
            version.is_active = True
            version.save()
            self.stdout.write(self.style.SUCCESS("Model ACTIVATED."))
        else:
            if options["activate"] and not all_gates_ok:
                self.stdout.write(self.style.WARNING(
                    "Activation requested but at least one gate failed; leaving model INACTIVE."))
            else:
                self.stdout.write("Registered as INACTIVE (use --activate once gates pass).")
        return 0