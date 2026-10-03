#!/usr/bin/env python3
"""Evaluate the saved top-6 tractor-brand classifier on the HELD-OUT TEST SET.

Refuses to run when the artifact is missing or the checksum does not match.
Reports on test data only; training/validation numbers are never relabeled as
test metrics. Writes an evaluation summary JSON alongside the metrics file.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import torch

from scripts.equipment_classifier_common import (
    eval_transform,
    load_labeled,
    macro_f1_from_logits,
    predict_logits,
    sha256_file,
    topk_accuracy,
    write_json,
)

DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--model-dir", required=True, help="Artifact directory")
    ap.add_argument("--stem", required=True, help="Artifact stem, e.g. equipment_classifier_mobilenetv3_top6_v1")
    ap.add_argument("--test-dir", required=True, help="Held-out test folder")
    args = ap.parse_args()

    out_dir = Path(args.model_dir)
    stem = args.stem
    weights_path = out_dir / f"{stem}.pt"
    metadata_path = out_dir / f"{stem}_metadata.json"
    metrics_path = out_dir / f"{stem}_metrics.json"
    checksum_path = out_dir / f"{stem}_checksum.txt"

    if not weights_path.exists():
        raise SystemExit(f"artifact missing: {weights_path}")
    if not metadata_path.exists():
        raise SystemExit(f"metadata missing: {metadata_path}")
    if not checksum_path.exists():
        raise SystemExit(f"checksum missing: {checksum_path}")

    recorded = checksum_path.read_text(encoding="utf-8").strip().split()[0]
    actual = sha256_file(weights_path)
    if recorded != actual:
        raise SystemExit(f"checksum mismatch: recorded={recorded} actual={actual}")

    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    classes = metadata["class_labels"]
    saved = torch.load(weights_path, map_location="cpu", weights_only=False)

    from scripts.equipment_classifier_common import build_model
    model = build_model(saved["architecture"], saved["num_classes"], pretrained=False)
    model.load_state_dict(saved["state_dict"])
    model.to(DEVICE)

    test_ds, test_loader = load_labeled(Path(args.test_dir), eval_transform(),
                                        16, shuffle=False, device=DEVICE)
    if test_ds.classes != classes:
        raise SystemExit(f"test classes {test_ds.classes} != metadata classes {classes}")

    logits, labels = predict_logits(model, test_loader, DEVICE)
    probs = torch.softmax(logits, dim=1)
    preds = logits.argmax(dim=1).cpu().numpy()
    labels_np = labels.cpu().numpy()
    n = len(labels_np)

    acc = float((preds == labels_np).mean())
    balanced = float(np.mean([
        (preds[labels_np == c] == c).mean() if (labels_np == c).any() else 0.0
        for c in range(len(classes))
    ]))
    top3 = topk_accuracy(logits, labels, k=3)
    macro_f1 = macro_f1_from_logits(logits, labels, len(classes))

    per_class = {}
    ps, rs, fs, supports = [], [], [], []
    for c in range(len(classes)):
        tp = int(((preds == c) & (labels_np == c)).sum())
        fp = int(((preds == c) & (labels_np != c)).sum())
        fn = int(((preds != c) & (labels_np == c)).sum())
        p = tp / (tp + fp) if (tp + fp) else 0.0
        r = tp / (tp + fn) if (tp + fn) else 0.0
        f1 = 2 * p * r / (p + r) if (p + r) else 0.0
        s = int((labels_np == c).sum())
        ps.append(p); rs.append(r); fs.append(f1); supports.append(s)
        per_class[classes[c]] = {"precision": round(p, 4), "recall": round(r, 4),
                                 "f1": round(f1, 4), "support": s}
    weighted_f1 = float(np.average(fs, weights=supports))

    cm = np.zeros((len(classes), len(classes)), dtype=int)
    for i in range(n):
        cm[labels_np[i], preds[i]] += 1

    maxp = probs.max(dim=1).values.cpu().numpy()
    calib = []
    for lo in np.arange(0.0, 1.0, 0.1):
        hi = lo + 0.1
        mask = (maxp >= lo) & (maxp < hi)
        if mask.sum() == 0:
            continue
        calib.append({"bin": f"{lo:.1f}-{hi:.1f}", "count": int(mask.sum()),
                      "mean_confidence": round(float(maxp[mask].mean()), 4),
                      "accuracy": round(float((preds[mask] == labels_np[mask]).mean()), 4)})

    evals = {
        "stem": stem,
        "architecture": metadata["model_architecture"],
        "validation_macro_f1": metadata.get("validation_macro_f1"),
        "test_accuracy": round(acc, 5),
        "test_balanced_accuracy": round(balanced, 5),
        "test_macro_precision": round(float(np.mean(ps)), 5),
        "test_macro_recall": round(float(np.mean(rs)), 5),
        "test_macro_f1": round(macro_f1, 5),
        "test_weighted_f1": round(weighted_f1, 5),
        "test_top3_accuracy": round(top3, 5),
        "test_samples": n,
        "per_class": per_class,
        "confidence_calibration": calib,
        "checksum_verified": True,
        "note": "Evaluation on the held-out TEST split only.",
    }
    write_json(out_dir / f"{stem}_eval_report.json", evals)

    print("=" * 70)
    print(f"CHECKSUM: verified ({actual[:16]}...)")
    print(f"test accuracy={acc:.4f} balanced={balanced:.4f} top3={top3:.4f}")
    print(f"test macro-F1={macro_f1:.4f} weighted-F1={weighted_f1:.4f} samples={n}")
    for c in classes:
        m = per_class[c]
        print(f"  {c:16s} p={m['precision']:.3f} r={m['recall']:.3f} f1={m['f1']:.3f} n={m['support']}")
    print("confusion matrix (rows=true, cols=pred):")
    header = "           " + "".join(f"{c[:8]:>9}" for c in classes)
    print(header)
    for i, c in enumerate(classes):
        print(f"{c[:10]:>10} " + "".join(f"{int(x):9d}" for x in cm[i]))
    print("wrote:", out_dir / f"{stem}_eval_report.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())