# Final report — First real CNN training run (equipment classifier)

Date: 2026-09-25. Artifacts in `data/models/equipment_classifier/`
(`equipment_classifier_mobilenetv3_top6_v1.*`). Accompanying metrics are in
`_metrics.json`, `_classification_report.json`, `_confusion_matrix*.csv`,
`_training_history.csv`, `_metadata.json`, `_checksum.txt`, `_eval_report.json`.

## 1. Exact command used

```
python scripts/train_equipment_classifier.py \
  --dataset-dir "D:\S-H\open-tractor\open-tractor\data\tractor_brand_dataset" \
  --output-dir "D:\S-H\open-tractor\khetsathi_ai\data\models\equipment_classifier" \
  --architecture mobilenet_v3_large --version v1 \
  --epochs 25 --batch-size 16 --learning-rate 0.0003 --weight-decay 1e-4 \
  --patience 5 --seed 42
```

(4 dir-arg form was used on the command line; equivalent.) Run on `cuda`
(NVIDIA GeForce RTX 4050 Laptop GPU), torch 2.11.0+cu128, torchvision 0.26.0+cu128,
Python 3.13.0.

Independent re-evaluation:

```
python scripts/evaluate_equipment_classifier.py \
  --model-dir "data\models\equipment_classifier" \
  --stem "equipment_classifier_mobilenetv3_top6_v1" \
  --test-dir "D:\S-H\open-tractor\open-tractor\data\tractor_brand_dataset\test"
```

## 2. Training completed successfully?

**Yes.** 19 epochs ran (config max 25), early stopping triggered at epoch 19
because validation macro-F1 had not improved for 5 epochs (patience 5). Best
epoch: **14**. The saved checkpoint is the epoch-14 best (val macro-F1 0.7458).

## 3. Validation and held-out test macro-F1

| Split | macro-F1 | top-1 acc | notes |
| --- | --- | --- | --- |
| Validation (best) | **0.7458** | 0.8111 | early-stopped on this |
| **Test (held-out)** | **0.7316** | 0.8101 | 179 images, never used for early stop |

Test also: balanced accuracy 0.6935, weighted-F1 0.8002, top-3 accuracy
0.9832. These test numbers are honest — computed once from the saved epoch-14
checkpoint on the held-out split; val/train numbers were never relabeled as
test metrics.

## 4. Per-class test metrics

| Class | precision | recall | F1 | support |
| --- | --- | --- | --- | --- |
| Farmtrac | 1.000 | 0.750 | 0.857 | 8 |
| John Deere | 1.000 | 0.857 | 0.923 | 7 |
| Mahindra | 0.500 | 0.667 | 0.571 | 15 |
| New Holland | 1.000 | 0.571 | 0.727 | 7 |
| Powertrac | 0.714 | 0.833 | 0.769 | 6 |
| Sonalika | 0.800 | 0.267 | 0.400 | 15 |
| other | 0.840 | 0.909 | 0.873 | 121 |

## 5. Most-confused pairs (test set, rows=true / cols=pred)

1. **Sonalika → other:** 10 of 15 true Sonalika images predicted `other` —
   dominant driver of the 0.40 Sonalika recall.
2. **Mahindra → other:** 10 of 15 true Mahindra images predicted `other`
   (Mahindra also received 10 false-positive `other`→Mahindra, hence 0.50
   precision).
3. New Holland → other (3/7), Powertrac → other (1/6), Farmtrac → other (1/8)
   keep `other` central: 110/121 `other` correct.

Interpretation: `other` (1,208 images, a long-tail of diverse brands) absorbs
confusable silhouettes; named-brand test supports are tiny (6–15 images).

## 6. Activation gate

**Passed.** Gate requires: artifact present + sha256 checksum valid + labels &
metadata parse & agree + metadata `test_macro_f1 ≥ 0.70` (config default) +
inference smoke test uses the model. Recorded:

- test macro-F1 0.7316 ≥ 0.70 ✓
- artifact sha256 verified (`741b94b8…`, matches `_checksum.txt`) ✓
- 7 classes in labels/metadata ✓
- smoke inference on a real Mahindra test image → `Mahindra`, confidence 0.997 ✓

`python manage.py register_equipment_model --smoke-image <real image> --activate`
therefore marked `MLModelRegistry(key=equipment_classifier)` **active** and
`MLModelVersion v1` active with honest metrics
(`test_macro_f1=0.7316`, `test_accuracy=0.81006`, `test_samples=179`).

## 7. Not-activated concerns — none

The gate passed, so the model **is** active. It remains a **small-data demo**:
per-brand test supports of ≤15 images mean the 0.73 macro-F1 has wide
uncertainty. This is disclosed in metadata `limitations`, and every prediction
still sets `needs_user_confirmation=true`; the brand result is never presented
as exact model/year/mileage/health/repair/subsidy facts.

## 8. Runtime-consistency evidence

- Django `EquipmentClassifier` lazy-loads the artifact, recomputes the sha256
  from `_checksum.txt`, requires `_labels.json` + `_metadata.json`, rebuilds the
  same MobileNetV3-Large head, uses identical eval preprocessing
  (Resize 256 → CenterCrop 224 → ImageNet normalize), and only then serves
  predictions — in-process smoke test confirmed `used_ml=True`.
- Missing/corrupt/checksum-mismatched/unsupported-state artifacts all fall back
  to `source="fallback"`, `used_ml=false`, `model_version="fallback"` without
  raising and without any network access.
- End-to-end DB test: a real Mahindra image through the analyze pipeline
  persisted `predicted_class=tractor`, `predicted_brand=Mahindra`,
  `used_ml=True`, `artifact_available=True`, `confidence_label=high`,
  `confidence=0.997`.
- Registry: `MLModelRegistry.active`, `MLModelVersion v1.is_active=True`,
  metrics in `metrics_json`; every call is audited via `log_prediction()`.
- Test coverage added and passing (70 total): fallback paths, checksum, unknown
  threshold, kind/brand mapping, service persistence, audit rows, activation
  gate pass/reject, dataset sanity (no empty class folder, no split leakage,
  no `unknown` images).

## 9. Honest limitations

- **Tiny per-brand test sets (6–15 images)** — macro-F1 0.73 reported with huge
  uncertainty; this is a feasibility demo, not a production model.
- **Imbalance:** `other` has 18× Powertrac's images; weighted CE only partially
  compensates (Sonalika + Mahindra confusion dominated by `other`).
- Brand-only output: the model never estimates exact model, manufacturing year,
  fuel mileage, engine health, repair history, or financial/subsidy advice.
- **Unknown handling:** softmax is usually well-calibrated on the 6 trained
  brands, but `other` is a broad visual bucket; a true out-of-domain image may
  hit ≥0.55 on a named brand merely because it resembles one (only max-score
  thresholding is used, no OOD detector).
- Licensing of source images is unverified — redistribution/disclosure remains
  an open issue (dataset prep policy unchanged).
- Model asset must travel with its sidecar files + checksum; losing them forces
  the safe fallback path (by design).

## 10. No HTML/CSS/JS content added

Confirmed. All 22 files under `templates/` and `static/` remain **0 bytes**
(empty placeholders). No `.html`, `.css`, `.js`, or component code was created
or modified in this work. All changes were Python (scripts, Django models/
services/views/commands/tests/settings), JSON/CSV/MD artifacts and SQLite
migrations.

## Next collection targets (to raise macro-F1)

1. Add ≥50 labeled images per named brand (esp. Sonalika, Mahindra, New
   Holland) from compliant sources; keep per-split stratified grouping.
2. Consider a dedicated `unknown`/`other` validation set with out-of-domain
   tractors (well-lit, dealer/gallery shots) to tune the unknown threshold.
3. Re-train at higher epochs/patience or newer arch (e.g. `efficientnet_v2_s`)
   after data grows; re-evaluate with the same held-out script before any
   re-activation.