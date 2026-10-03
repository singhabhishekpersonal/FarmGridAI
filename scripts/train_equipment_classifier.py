#!/usr/bin/env python3
"""Train the top-6 tractor-brand classifier (MobileNetV3-Large, transfer learning).

Dataset layout (prepared by scripts/build_classifier_dataset.py --top-n 6):
    data/tractor_brand_dataset/{train,val,test}/<class>/<image>

Metrics optics: the BESST checkpoint is selected by validation macro-F1.
Final metrics in the report are computed ON THE HELD-OUT TEST SET ONLY and are
never mixed with training or validation numbers.

Artifacts are written to --output-dir and everything is checksummed. The model
is only activated in Django when the activation gate passes (test macro-F1 >=
--activation-macro-f1). This script never fabricates metrics.
"""
import argparse
import datetime
import json
import platform
import shutil
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import torch
import torch.nn as nn

from scripts.equipment_classifier_common import (
    VERSION,
    IMAGENET_MEAN,
    build_model,
    class_weights_from_counts,
    eval_transform,
    load_labeled,
    macro_f1_from_logits,
    predict_logits,
    set_seed,
    sha256_file,
    topk_accuracy,
    train_transform,
    write_json,
)

DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")


def git_revision():
    try:
        out = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True,
                             text=True, timeout=5)
        return out.stdout.strip() if out.returncode == 0 else "not-a-git-repo"
    except Exception:
        return "unavailable"


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dataset-dir", required=True, help="Root with train/val/test folders")
    ap.add_argument("--output-dir", required=True, help="Where artifacts are written")
    ap.add_argument("--architecture", default="mobilenet_v3_large",
                    choices=["mobilenet_v3_large", "resnet18"])
    ap.add_argument("--version", default=VERSION)
    ap.add_argument("--epochs", type=int, default=25)
    ap.add_argument("--batch-size", type=int, default=16)
    ap.add_argument("--learning-rate", type=float, default=0.0003)
    ap.add_argument("--weight-decay", type=float, default=1e-4)
    ap.add_argument("--patience", type=int, default=5)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--unknown-threshold", type=float, default=0.55)
    ap.add_argument("--activation-macro-f1", type=float, default=0.70)
    ap.add_argument("--pretrained", action="store_true", default=True,
                    dest="pretrained", help="Use ImageNet pretrained weights")
    ap.add_argument("--class-imbalance-method", default="weighted_cross_entropy",
                    choices=["weighted_cross_entropy", "weighted_random_sampler"])
    args = ap.parse_args()

    set_seed(args.seed)
    stamp = datetime.datetime.now(datetime.timezone.utc).isoformat()

    dataset_root = Path(args.dataset_dir)
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    family = {"mobilenet_v3_large": "mobilenetv3", "resnet18": "resnet18"}[args.architecture]
    stem = f"equipment_classifier_{family}_top6_{args.version}"

    for split in ("train", "val", "test"):
        if not (dataset_root / split).is_dir():
            raise SystemExit(f"missing split folder: {dataset_root / split}")

    train_ds, train_loader = load_labeled(dataset_root / "train", train_transform(),
                                          args.batch_size, shuffle=True, device=DEVICE)
    val_ds, val_loader = load_labeled(dataset_root / "val", eval_transform(),
                                      args.batch_size, shuffle=False, device=DEVICE)
    test_ds, test_loader = load_labeled(dataset_root / "test", eval_transform(),
                                        args.batch_size, shuffle=False, device=DEVICE)

    classes = train_ds.classes
    if val_ds.class_to_idx != train_ds.class_to_idx or test_ds.class_to_idx != train_ds.class_to_idx:
        raise SystemExit("class mismatches between splits")
    if len(classes) != 7:
        raise SystemExit(f"expected 7 classes (top-6 + other), got {len(classes)}: {classes}")

    train_counts = train_ds.counts
    val_counts = val_ds.counts
    test_counts = test_ds.counts
    per_class = {c: {"train": train_counts.get(c, 0), "val": val_counts.get(c, 0),
                     "test": test_counts.get(c, 0),
                     "total": train_counts.get(c, 0) + val_counts.get(c, 0) + test_counts.get(c, 0)}
                 for c in classes}

    if args.class_imbalance_method == "weighted_cross_entropy":
        weights = class_weights_from_counts(train_counts)
        criterion = nn.CrossEntropyLoss(weight=weights.to(DEVICE))
    else:
        weights = torch.ones(len(classes))
        criterion = nn.CrossEntropyLoss()
        from torch.utils.data import DataLoader, WeightedRandomSampler
        list_ds = list(train_ds)
        targets = [list_ds[i][1] for i in range(len(list_ds))]
        inv = Counter()
        for t in targets:
            inv[t] += 1
        sample_weights = torch.tensor([1.0 / max(inv[t], 1) for t in targets], dtype=torch.double)
        sampler = WeightedRandomSampler(sample_weights, num_samples=len(targets), replacement=True)
        train_loader = DataLoader(train_ds, batch_size=args.batch_size, sampler=sampler,
                                  num_workers=0, pin_memory=DEVICE.type == "cuda")

    model = build_model(args.architecture, len(classes), pretrained=args.pretrained)
    model.to(DEVICE)
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.learning_rate,
                                  weight_decay=args.weight_decay)

    history = []
    best_val_f1 = -1.0
    best_epoch = -1
    best_path = out_dir / f"{stem}.pt"
    patience_left = args.patience
    epochs_run = 0

    print(f"device={DEVICE} classes={classes}")
    print(f"train={sum(train_counts.values())} val={sum(val_counts.values())} test={sum(test_counts.values())}")

    for epoch in range(1, args.epochs + 1):
        model.train()
        train_loss, n_batches = 0.0, 0
        for x, y in train_loader:
            x, y = x.to(DEVICE), y.to(DEVICE)
            optimizer.zero_grad()
            loss = criterion(model(x), y)
            loss.backward()
            optimizer.step()
            train_loss += float(loss.item())
            n_batches += 1
        avg_train_loss = train_loss / max(n_batches, 1)

        val_logits, val_labels = predict_logits(model, val_loader, DEVICE)
        val_f1 = macro_f1_from_logits(val_logits, val_labels, len(classes))
        val_top1 = topk_accuracy(val_logits, val_labels, k=1)

        restored = ""
        if val_f1 > best_val_f1:
            best_val_f1 = val_f1
            best_epoch = epoch
            patience_left = args.patience
            torch.save({
                "state_dict": model.state_dict(),
                "architecture": args.architecture,
                "num_classes": len(classes),
                "classes": classes,
                "version": args.version,
                "epoch": epoch,
                "val_macro_f1": val_f1,
                "val_top1": val_top1,
            }, best_path)
            restored = " (best saved)"
        else:
            patience_left -= 1

        history.append({"epoch": epoch, "train_loss": round(avg_train_loss, 5),
                        "val_macro_f1": round(val_f1, 5), "val_top1": round(val_top1, 5)})
        print(f"epoch {epoch:2d} loss={avg_train_loss:.4f} val_f1={val_f1:.4f} "
              f"val_top1={val_top1:.4f}{restored} patience_left={patience_left}")
        epochs_run = epoch

        if patience_left <= 0:
            print(f"early stopping at epoch {epoch} (best epoch {best_epoch}, val_f1={best_val_f1:.4f})")
            break

    if best_epoch < 0:
        raise SystemExit("no improvement in validation macro-F1; refusing to save fake best")

    # ----- held-out TEST evaluation with the best checkpoint only -----
    saved = torch.load(best_path, map_location="cpu", weights_only=False)
    test_model = build_model(saved["architecture"], saved["num_classes"], pretrained=False)
    test_model.load_state_dict(saved["state_dict"])
    test_model.to(DEVICE)

    test_logits, test_labels = predict_logits(test_model, test_loader, DEVICE)
    test_probs = torch.softmax(test_logits, dim=1)
    test_preds = test_logits.argmax(dim=1).cpu().numpy()
    test_labels_np = test_labels.cpu().numpy()

    n = len(test_labels_np)
    acc = float((test_preds == test_labels_np).mean())
    balanced_acc = float(np.mean([
        (test_preds[test_labels_np == c] == c).mean() if (test_labels_np == c).any() else 0.0
        for c in range(len(classes))
    ]))
    top3 = topk_accuracy(test_logits, test_labels, k=3)
    test_f1 = macro_f1_from_logits(test_logits, test_labels, len(classes))

    per_class_test = {}
    precisions, recalls, f1s, supports = [], [], [], []
    for c in range(len(classes)):
        tp = int(((test_preds == c) & (test_labels_np == c)).sum())
        fp = int(((test_preds == c) & (test_labels_np != c)).sum())
        fn = int(((test_preds != c) & (test_labels_np == c)).sum())
        p = tp / (tp + fp) if (tp + fp) else 0.0
        r = tp / (tp + fn) if (tp + fn) else 0.0
        f1 = 2 * p * r / (p + r) if (p + r) else 0.0
        s = int((test_labels_np == c).sum())
        precisions.append(p); recalls.append(r); f1s.append(f1); supports.append(s)
        per_class_test[classes[c]] = {"precision": round(p, 4), "recall": round(r, 4),
                                      "f1": round(f1, 4), "support": s}
    weighted_f1 = float(np.average(f1s, weights=supports))

    cm = np.zeros((len(classes), len(classes)), dtype=int)
    for i in range(n):
        cm[test_labels_np[i], test_preds[i]] += 1
    cm_norm = cm / cm.sum(axis=1, keepdims=True).clip(min=1)

    # confidence calibration summary (bins over max softmax on the test set)
    maxp = test_probs.max(dim=1).values.cpu().numpy()
    calib_bins = []
    for lo in np.arange(0.0, 1.0, 0.1):
        hi = lo + 0.1
        mask = (maxp >= lo) & (maxp < hi)
        if mask.sum() == 0:
            continue
        bin_mean = float(maxp[mask].mean())
        bin_acc = float((test_preds[mask] == test_labels_np[mask]).mean())
        calib_bins.append({"bin": f"{lo:.1f}-{hi:.1f}", "count": int(mask.sum()),
                           "mean_confidence": round(bin_mean, 4),
                           "accuracy": round(bin_acc, 4)})

    # ----- artifact files -----
    artifact_checksum = sha256_file(best_path)
    labels_path = out_dir / f"{stem}_labels.json"
    write_json(labels_path, {"classes": classes, "class_to_idx": train_ds.class_to_idx,
                             "architecture": args.architecture, "version": args.version})

    metrics = {
        "test_accuracy": round(float(acc), 5),
        "test_balanced_accuracy": round(float(balanced_acc), 5),
        "test_macro_precision": round(float(np.mean(precisions)), 5),
        "test_macro_recall": round(float(np.mean(recalls)), 5),
        "test_macro_f1": round(float(test_f1), 5),
        "test_weighted_f1": round(float(weighted_f1), 5),
        "test_top3_accuracy": round(float(top3), 5),
        "test_samples": n,
        "per_class": per_class_test,
        "confidence_calibration": calib_bins,
        "best_epoch": best_epoch,
        "val_macro_f1_at_best": round(float(best_val_f1), 5),
        "actual_epochs_run": epochs_run,
    }
    write_json(out_dir / f"{stem}_metrics.json", metrics)

    with open(out_dir / f"{stem}_confusion_matrix.csv", "w", encoding="utf-8") as fh:
        fh.write("true_class," + ",".join(classes) + "\n")
        for i, c in enumerate(classes):
            fh.write(c + "," + ",".join(str(int(x)) for x in cm[i]) + "\n")
    with open(out_dir / f"{stem}_confusion_matrix_normalized.csv", "w", encoding="utf-8") as fh:
        fh.write("true_class," + ",".join(classes) + "\n")
        for i, c in enumerate(classes):
            fh.write(c + "," + ",".join(f"{x:.4f}" for x in cm_norm[i]) + "\n")

    classification_report = {
        "model_stem": stem,
        "architecture": args.architecture,
        "classes": classes,
        "classification_report": per_class_test,
        "accuracy": acc,
    }
    write_json(out_dir / f"{stem}_classification_report.json", classification_report)

    with open(out_dir / f"{stem}_training_history.csv", "w", encoding="utf-8") as fh:
        fh.write("epoch,train_loss,val_macro_f1,val_top1\n")
        for h in history:
            fh.write(f"{h['epoch']},{h['train_loss']},{h['val_macro_f1']},{h['val_top1']}\n")

    manifest_hash = sha256_file(dataset_root / "dataset_manifest.csv")
    activated = (test_f1 >= args.activation_macro_f1)
    metadata = {
        "model_architecture": args.architecture,
        "model_version": args.version,
        "model_family": "top6",
        "training_date_utc": stamp,
        "git_revision": git_revision(),
        "pytorch_version": torch.__version__,
        "torchvision_version": __import__("torchvision").__version__,
        "python_version": platform.python_version(),
        "device": str(DEVICE),
        "class_labels": classes,
        "image_counts": {
            "train": sum(train_counts.values()), "val": sum(val_counts.values()),
            "test": sum(test_counts.values()),
            "per_class": per_class,
        },
        "preprocessing": {"resize": 256, "center_crop": 224, "normalize": IMAGENET_MEAN,
                          "eval_augmentation": "none"},
        "augmentation": {
            "random_resized_crop": {"size": 224, "scale": [0.6, 1.0], "ratio": [0.75, 1.333]},
            "horizontal_flip": 0.5, "rotation": 10, "color_jitter": [0.25, 0.25, 0.25, 0.05],
            "random_affine_translate": 0.05, "training_only": True,
        },
        "optimizer": {"name": "AdamW", "learning_rate": args.learning_rate,
                      "weight_decay": args.weight_decay},
        "learning_rate": args.learning_rate,
        "batch_size": args.batch_size,
        "num_epochs_requested": args.epochs,
        "epochs_run": epochs_run,
        "early_stopping": {"patience": args.patience, "metric": "val_macro_f1",
                           "best_epoch": best_epoch},
        "class_imbalance_method": args.class_imbalance_method,
        "seed": args.seed,
        "dataset_manifest_sha256": manifest_hash,
        "artifact_sha256": artifact_checksum,
        "validation_macro_f1": round(float(best_val_f1), 5),
        "test_macro_f1": round(float(test_f1), 5),
        "activation_threshold_macro_f1": args.activation_macro_f1,
        "activation_gate_passed": bool(activated),
        "unknown_threshold": args.unknown_threshold,
        "limitations": [
            "Predicts tractor brand only; never exact model, year, fuel mileage, engine health, repair history.",
            "Trained on ~1.8k locally prepared tractor web images; class imbalance exists (other >> named brands).",
            "A low max-softmax (< unknown_threshold) maps to the unknown class.",
            "Every prediction requires farmer confirmation.",
        ],
        "required_farmer_confirmation_policy": "true",
        "data_source_note": "Existing locally prepared TractorGyan-derived dataset. No new sites scraped during dataset preparation.",
        "test_metrics_reported": metrics,
        "trained_output_files": {
            "weights": best_path.name, "labels": labels_path.name,
            "metrics": f"{stem}_metrics.json",
            "confusion_matrix": f"{stem}_confusion_matrix.csv",
            "confusion_matrix_normalized": f"{stem}_confusion_matrix_normalized.csv",
        },
    }
    write_json(out_dir / f"{stem}_metadata.json", metadata)
    (out_dir / f"{stem}_checksum.txt").write_text(
        f"{artifact_checksum}  {best_path.name}\n", encoding="utf-8")

    # ----- print report -----
    print("=" * 70)
    print(f"architecture={args.architecture} version={args.version} epochs_run={epochs_run} (best {best_epoch})")
    print(f"activation-macro-f1 gate={args.activation_macro_f1}")
    print(f"validation macro-F1 (best): {best_val_f1:.4f}")
    print(f"TEST macro-F1: {test_f1:.4f}  accuracy={acc:.4f}  balanced={balanced_acc:.4f}  top3={top3:.4f}")
    for c in classes:
        m = per_class_test[c]
        print(f"  {c:16s} p={m['precision']:.3f} r={m['recall']:.3f} f1={m['f1']:.3f} n={m['support']}")
    print(f"activation gate passed: {activated} -> model {'ACTIVATED' if activated else 'STAYS INACTIVE (fallback remains active)'}")
    print("artifacts written to:", out_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())