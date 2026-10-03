# Model Card — Equipment Classifier (tractor brand, vision)

## 1. Summary
- **Model name:** `equipment_classifier`
- **Registry key:** `equipment_classifier`
- **Version:** `v1`
- **Status / activation:** `active` in `MLModelRegistry` (activation gate passed),
  one active `MLModelVersion v1` (`is_active=True`)
- **Model type:** vision (fine-tuned CNN)
- **Architecture:** `mobilenet_v3_large` (MobileNetV3-Large), fine-tuned
  classifier head with `num_classes=7`
- **Framework:** PyTorch 2.11.0+cu128 / torchvision 0.26.0+cu128 (per the
  training run record). Inference does not require a GPU and performs **no
  network access** during request handling.
- **Artifact (verified):**
  `data/models/equipment_classifier/equipment_classifier_mobilenetv3_top6_v1.pt`
  (17,067,779 bytes), sha256 `741b94b839a6c11b07be9300a48d4ae975edb234b9fbee3c8b3f0887933d79d3`.
  Recorded checksum `_checksum.txt` recomputed and **matches** the on-disk file
  (independently re-verified during this review).
- **Sidecar files (must travel with the artifact):** `_labels.json`,
  `_metadata.json`, `_checksum.txt`, `_metrics.json`, `_classification_report.json`,
  `_confusion_matrix*.csv`, `_training_history.csv`, `_eval_report.json`.

## 2. Intended use
- Given a photo of a tractor, estimate the **brand category** among
  {Farmtrac, John Deere, Mahindra, New Holland, Powertrac, Sonalika, other}.
- Output is an **estimate only**: the model never determines exact model,
  fuel mileage, engine health, manufacturing year, repair history, or
  subsidy/financial eligibility.
- **Every prediction requires farmer/user confirmation** (`needs_user_confirmation=true`
  always) and rides on the shared estimate contract (assumptions, limitations,
  flags, confidence).

## 3. Training data and splits
Dataset: `tractor_brand_dataset` (source `D:\S-H\open-tractor\open-tractor\data\tractor_brand_dataset`),
verified present with train/val/test directories and per-class counts:

| Class | train | val | test |
| --- | --- | --- | --- |
| Farmtrac | 66 | 8 | 8 |
| John Deere | 59 | 7 | 7 |
| Mahindra | 124 | 15 | 15 |
| New Holland | 57 | 7 | 7 |
| Powertrac | 54 | 7 | 6 |
| Sonalika | 118 | 15 | 15 |
| other | 966 | 121 | 121 |
| **Total images** | **1,444** | **180** | **179** |

- Imbalance: `other` (broad visual bucket) is substantially larger than any
  named brand; per-brand test supports are tiny (6–15 images). Class imbalance
  handled by weighted CrossEntropyLoss (inverse-frequency weights) only.
- Test split is a true held-out set and was used exactly once for the reported
  test metrics.

## 4. Training configuration
- Epochs: config max 25; **early stop at epoch 19** (patience 5); best saved
  checkpoint at **epoch 14**.
- Batch size 16, learning rate 0.0003, weight decay 1e-4, seed 42, GPU cuda.
- Training history (`_training_history.csv`) shows best validation at epoch 14:
  `val_macro_f1=0.74584`, `val_top1=0.81111`; train loss 0.08208.

## 5. Performance (independent held-out evaluation)
From `_eval_report.json` (regenerated never, but recomputed checksum and loaded
artifact during this review); `test_samples=179`:

| Metric | Value |
| --- | --- |
| test accuracy (top-1) | **0.81006** |
| test balanced accuracy | **0.69348** |
| test macro-F1 | **0.7316** |
| test weighted F1 | **0.80017** |
| test macro precision | 0.83628 |
| test macro recall | 0.69348 |
| test top-3 accuracy | **0.98324** |
| validation macro-F1 (best, epoch 14) | 0.74584 |

Per-class (test) — same values as `_eval_report.json`:

| Class | precision | recall | F1 | support |
| --- | --- | --- | --- | --- |
| Farmtrac | 1.000 | 0.750 | 0.857 | 8 |
| John Deere | 1.000 | 0.857 | 0.923 | 7 |
| Mahindra | 0.500 | 0.667 | 0.571 | 15 |
| New Holland | 1.000 | 0.571 | 0.727 | 7 |
| Powertrac | 0.714 | 0.833 | 0.769 | 6 |
| Sonalika | 0.800 | 0.267 | 0.400 | 15 |
| other | 0.840 | 0.909 | 0.873 | 121 |

Most-confused pairs (rows=true, cols=pred): Sonalika → other (10/15), Mahindra
→ other (10/15), New Holland → other (3/7).

### Confidence calibration (test)
| bin | count | mean confidence | accuracy |
| --- | --- | --- | --- |
| 0.4–0.5 | 1 | 0.4446 | 0.000 |
| 0.5–0.6 | 6 | 0.5547 | 0.333 |
| 0.6–0.7 | 5 | 0.6266 | 0.400 |
| 0.7–0.8 | 14 | 0.7547 | 0.571 |
| 0.8–0.9 | 16 | 0.8711 | 0.813 |
| 0.9–1.0 | 132 | 0.9861 | 0.871 |

At the configured unknown threshold (0.55), low-confidence images return
`predicted_class=unknown` / `source="ml_model_low_confidence"`.

## 6. Activation gate (performed, passed)
Gate checks: artifact present + sha256 checksum valid + labels/metadata parse
and agree + metadata `test_macro_f1 >= 0.70` (0.7316 ✓) + in-process inference
smoke test (Mahindra test image → `Mahindra`, conf 0.997). Registration run via
`python manage.py register_equipment_model --smoke-image <real image> --activate`.

## 7. Runtime wrapper guarantees
`apps/ml_engine/vision/classifier.py`:
- Lazy-checksum-load (recomputes sha256 each load) → no load on missing/corrupt/
  mismatched/unreadable artifact; explicit `fallback` source; `used_ml=false`.
- Rebuilds the same MobileNetV3-Large head from the artifact's own
  architecture/num_classes; identical eval preprocessing (Resize 256 →
  CenterCrop 224 → ImageNet normalize).
- Never raises; `predict()` always returns the documented dict.
- Unknown threshold configurable via `ML_EQUIPMENT_CLASSIFIER_UNKNOWN_THRESHOLD`
  (default 0.55 in `FarmGridAI/settings/base.py:292`).
- Every call audited via `log_prediction()`.

## 8. Limitations / risks
- **Tiny per-brand test sets (6–15 images)** → macro-F1 0.73 has wide
  uncertainty; this is a small-data feasibility demo, **not** a production model.
- Strong class imbalance (`other` 18× Powertrac); only weighted CE compensation.
- Brand-only output — no model/year/mileage/engine/health/repair/subsidy facts.
- Unknown-handling is max-score thresholding only; **no OOD detector** — a true
  out-of-domain image can still exceed 0.55 on a named brand it merely
  resembles.
- Source-image licensing unverified; redistribution/disclosure remains open.
- Artifact must travel with sidecars + checksum (loss forces safe fallback).

## 9. Governance
- Registry `MLModelRegistry(key=equipment_classifier)` is `active`;
  `MLModelVersion v1` `metrics_json` matches `_eval_report.json` exactly.
- No auto-retrain and no auto-activation: activation is gated, manual and
  evidence-backed (see section 6). No `TrainingRun` rows exist.
- `ModelStatusView` (API) exposes registry/version stats and **never** exposes
  artifact paths.

## 10. Provenance of this card
- Artifact presence: verified (17,067,779 bytes).
- Checksum: independently recomputed → `741b94b8…` matches `_checksum.txt`.
- Classifier load smoke test: `available=True`, `artifact_available=True`,
  `model_version=v1`, 7 classes, no load error.
- Dataset: verified present (1,444 / 180 / 179).
- Metrics table above is copied verbatim from `_eval_report.json` and matches
  the registry `metrics_json`.