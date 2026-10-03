#!/usr/bin/env python3
"""Quality-check a staging dataset folder without any network access.

Re-runs the same image-validation gates (MIME, decode, min dimension, blur,
dark/bright, UI-icon/text-heavy) over every image in a built staging split and
emits a per-label JSON report under ``DATA_INGESTION_REPORTS_DIR``.
"""
import argparse
import json
from pathlib import Path

from data_ingestion_cli import bootstrap

bootstrap()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset_dir", type=Path, help="folder containing train/val/test subfolders")
    parser.add_argument("--out", type=Path, default=None, help="report path (default: data/ingested/reports/dataset_quality_<dataset>.json)")
    args = parser.parse_args()

    from django.conf import settings

    from apps.data_ingestion.services.image_validation import validate_image

    extensions = {".jpg", ".jpeg", ".png", ".webp"}
    images = [p for p in args.dataset_dir.rglob("*") if p.is_file() and p.suffix.lower() in extensions]
    if not images:
        raise SystemExit(f"no image files under {args.dataset_dir}")

    problems, summary = [], {"total": len(images), "ok": 0, "flagged": 0, "labels": {}}
    for path in images:
        label = path.parent.name
        summary["labels"].setdefault(label, {"total": 0, "flagged": 0})
        summary["labels"][label]["total"] += 1
        result = validate_image(path.read_bytes(), filename=path.name)
        if result["status"] != "valid":
            summary["flagged"] += 1
            summary["labels"][label]["flagged"] += 1
            problems.append({"path": str(path), "label": label, "status": str(result["status"]), "errors": result["errors"]})
        else:
            summary["ok"] += 1

    out = (args.out or Path(getattr(settings, "DATA_INGESTION_REPORTS_DIR", "data/ingested/reports")) / f"dataset_quality_{args.dataset_dir.name}.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"summary": summary, "problems": problems}, indent=2), encoding="utf-8")

    print(f"checked {summary['total']} images; ok={summary['ok']} flagged={summary['flagged']}")
    print(f"report: {out}")
    if problems:
        for p in problems[:20]:
            print(f"  FLAG {p['path']}: {p['errors']}")


if __name__ == "__main__":
    main()