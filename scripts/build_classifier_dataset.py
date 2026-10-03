#!/usr/bin/env python3
"""Build a top-N tractor-brand classifier dataset from the existing local data.

Sources (local only):
- data/tractor_dataset.json (labelled records with brand/model/img_url)
- tractor_images/ (already-downloaded images referred to by local_image_path).
  Records that point to a missing file are excluded and reported.

Nothing is downloaded. No new sites are contacted.

Pipeline:
1. Join tractor_images <- tractor_dataset.json via local_image_path basename.
2. Exclude: empty local path, missing file, UI assets (topbrand/menu/finance/
   icon/logo/darkwith/banner/whatsapp signatures), corrupt images (PIL decode
   failure), images below --min-size px.
3. Deduplicate by SHA-256 (first occurrence wins; later ones go to
   duplicates_removed.csv).
4. Normalize brand strings (John->John Deere, New->New Holland,
   Massey->Massey Ferguson, Vst->VST).
5. Top-N brands become classes; every other labelled record becomes "other";
   empty brand becomes "unknown".
6. Near-duplicate grouping: perceptual dHash (hamming <= --hash-dist) is
   computed per (class, model) bucket; connected components become atomic
   groups so the same tractor/model photo cannot leak across splits.
7. Grouped stratified split: atomic groups are assigned greedily per class to
   reach train/val/test fractions while keeping whole groups in one split.
8. Writes train/val/test folders + CSV/JSON report files. Split leakage is
   re-verified after assignment (exits 1 if any group spans >1 split).
"""
import argparse
import csv
import hashlib
import json
import shutil
import sys
from collections import Counter, defaultdict
from pathlib import Path, PurePath
from urllib.parse import urlparse

import numpy as np
from PIL import Image

BRAND_ALIASES = {
    "John": "John Deere",
    "New": "New Holland",
    "Massey": "Massey Ferguson",
    "Vst": "VST",
}
UI_SIGNATURE = ("topbrand", "menu", "finance", "icon", "logo", "darkwith", "banner", "whatsapp")
UNMAPPED = "unmapped"
UNKNOWN = "unknown"
OTHER = "other"


def dhash(img, hash_size=8):
    gray = img.convert("L").resize((hash_size + 1, hash_size), Image.LANCZOS)
    arr = np.asarray(gray, dtype=np.uint8)
    diff = arr[:, :-1] > arr[:, 1:]
    out = 0
    for b in diff.flatten():
        out = (out << 1) | int(b)
    return out


def hamming(a, b):
    return (a ^ b).bit_count()


def normalize(label):
    parts = [p.strip() for p in str(label or "").split("/") if p.strip()]
    if not parts:
        return ""
    return BRAND_ALIASES.get(parts[0], parts[0])


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def connected_components(members, hashes, hash_dist):
    """Return list of index lists (atomic groups) via union-find on dHash hamming."""
    n = len(members)
    parent = list(range(n))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    if n > 1:
        arr = np.array(hashes, dtype=np.uint64)
        xor = np.bitwise_xor(arr[:, None], arr[None, :])
        dist = np.bitwise_count(xor)
        for i in range(n):
            for j in range(i + 1, n):
                if int(dist[i, j]) <= hash_dist:
                    ri, rj = find(i), find(j)
                    if ri != rj:
                        parent[ri] = rj
    comp = defaultdict(list)
    for i in range(n):
        comp[find(i)].append(i)
    return list(comp.values())


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dataset-json", required=True)
    ap.add_argument("--image-root", required=True)
    ap.add_argument("--output-dir", required=True)
    ap.add_argument("--top-n", type=int, default=10)
    ap.add_argument("--min-size", type=int, default=200)
    ap.add_argument("--val-frac", type=float, default=0.10)
    ap.add_argument("--test-frac", type=float, default=0.10)
    ap.add_argument("--hash-dist", type=int, default=6)
    ap.add_argument("--model-group", action="store_true",
                    help="Cluster near-dups within the same (class, model) bucket only")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    dataset_path = Path(args.dataset_json)
    image_root = Path(args.image_root)
    out_root = Path(args.output_dir)
    records = json.loads(dataset_path.read_text(encoding="utf-8"))

    avail = {p.name for p in image_root.iterdir() if p.is_file()}
    referenced = {PurePath(r.get("local_image_path") or "").name for r in records}
    referenced.discard("")

    kept = []
    excluded = []
    seen_sha = {}

    for rec_idx, rec in enumerate(records):
        name = PurePath(rec.get("local_image_path") or "").name
        base = {
            "record_index": rec_idx,
            "brand": str(rec.get("brand") or "").strip(),
            "model": str(rec.get("model") or "").strip(),
            "filename": name,
            "img_url": str(rec.get("img_url") or "").strip(),
        }
        if not name:
            excluded.append({**base, "reason": "empty_local_path"})
            continue
        if name not in avail:
            excluded.append({**base, "reason": "missing_image"})
            continue
        lowered = name.lower()
        if any(sig in lowered for sig in UI_SIGNATURE):
            excluded.append({**base, "reason": "ui_asset"})
            continue
        try:
            with Image.open(image_root / name) as im:
                im.load()
                w, h = im.size
        except Exception as exc:
            excluded.append({**base, "reason": f"corrupt:{type(exc).__name__}"})
            continue
        if w < args.min_size or h < args.min_size:
            excluded.append({**base, "reason": "below_min_size"})
            continue
        digest = sha256_file(image_root / name)
        if digest in seen_sha:
            excluded.append({**base, "sha256": digest, "reason": "duplicate",
                             "kept_as": seen_sha[digest]})
            continue
        seen_sha[digest] = name
        kept.append({**base, "width": w, "height": h, "sha256": digest})

    for name in sorted(avail - referenced):
        excluded.append({"record_index": None, "brand": "", "model": "", "filename": name,
                         "img_url": "", "reason": UNMAPPED})

    for r in kept:
        r["normalized_brand"] = normalize(r["brand"])

    brand_counts = Counter(r["normalized_brand"] for r in kept if r["normalized_brand"])
    top_brands = [b for b, _ in brand_counts.most_common(args.top_n)]
    top_set = set(top_brands)
    for r in kept:
        nb = r["normalized_brand"]
        if not nb:
            r["class"] = UNKNOWN
        elif nb in top_set:
            r["class"] = nb
        else:
            r["class"] = OTHER
        r["label"] = r["class"]

    buckets = defaultdict(list)
    for r in kept:
        key = (r["class"], r["model"]) if (args.model_group and r["model"]) else (r["class"],)
        buckets[key].append(r)

    groups = []
    for _, members in buckets.items():
        hashes = [dhash(Image.open(image_root / m["filename"])) for m in members]
        for idxs in connected_components(members, hashes, args.hash_dist):
            group = [members[i] for i in idxs]
            gid = len(groups)
            for m in group:
                m["group_id"] = gid
            groups.append(group)

    split_order = {"train": 0, "val": 1, "test": 2}
    per_class_total = Counter(m["class"] for g in groups for m in g)
    alloc = defaultdict(lambda: defaultdict(list))

    ordering = sorted(groups, key=lambda g: (-len(g), g[0]["group_id"]))
    totals = defaultdict(lambda: Counter())
    remaining = {}
    for cls, tgt in per_class_total.items():
        remaining[cls] = {
            "train": int(round(tgt * (1.0 - args.val_frac - args.test_frac))),
            "val": int(round(tgt * args.val_frac)),
            "test": int(round(tgt * args.test_frac)),
        }
    for group in ordering:
        cls = group[0]["class"]
        rem = remaining[cls]
        best = max(("train", "val", "test"),
                   key=lambda s: (rem[s], -split_order[s]))
        alloc[cls][best].append(group)
        totals[cls][best] += len(group)
        rem[best] -= len(group)

    final_rows = []
    for cls, split_map in alloc.items():
        for split, groups_here in split_map.items():
            for g in groups_here:
                for m in g:
                    final_rows.append({
                        "split": split, "class": m["class"], "label": m["label"],
                        "record_index": m["record_index"], "brand": m["brand"],
                        "model": m["model"], "normalized_brand": m["normalized_brand"],
                        "filename": m["filename"], "width": m["width"], "height": m["height"],
                        "sha256": m["sha256"], "img_url": m["img_url"],
                        "group_id": m["group_id"], "source_path": str(image_root / m["filename"]),
                    })

    group_splits = defaultdict(set)
    for row in final_rows:
        group_splits[row["group_id"]].add(row["split"])
    leak_bad = sum(1 for ss in group_splits.values() if len(ss) > 1)

    out_root.mkdir(parents=True, exist_ok=True)
    manifest_cols = ["split", "class", "label", "record_index", "brand", "model",
                     "normalized_brand", "filename", "width", "height", "sha256",
                     "img_url", "group_id", "source_path"]
    with open(out_root / "dataset_manifest.csv", "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=manifest_cols, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(final_rows)

    total_kept = len(final_rows)
    all_classes = [*top_brands, OTHER, UNKNOWN]
    dist_rows = []
    for cls in all_classes:
        rows = [r for r in final_rows if r["class"] == cls]
        c = Counter(r["split"] for r in rows)
        dist_rows.append({"class": cls, "count_train": c["train"], "count_val": c["val"],
                          "count_test": c["test"], "total": len(rows),
                          "pct_of_dataset": round(100.0 * len(rows) / total_kept, 2) if total_kept else 0.0})
    with open(out_root / "class_distribution.csv", "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=["class", "count_train", "count_val", "count_test", "total", "pct_of_dataset"])
        writer.writeheader()
        writer.writerows(dist_rows)

    dup_cols = ["record_index", "brand", "filename", "sha256", "kept_as"]
    dup_rows = [{k: e.get(k) for k in dup_cols} for e in excluded if e["reason"] == "duplicate"]
    with open(out_root / "duplicates_removed.csv", "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=dup_cols)
        writer.writeheader()
        writer.writerows(dup_rows)

    ex_cols = ["record_index", "filename", "brand", "reason", "kept_as", "model", "img_url"]
    with open(out_root / "excluded_images.csv", "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=ex_cols, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(excluded)

    (out_root / "labels.json").write_text(json.dumps({
        "classes": all_classes,
        "top_n": args.top_n,
        "top_brands": top_brands,
        "other_label": OTHER,
        "unknown_label": UNKNOWN,
        "brand_aliases": BRAND_ALIASES,
        "source": "local dataset only; existing listed image URLs",
    }, indent=2, ensure_ascii=False), encoding="utf-8")

    ex_reasons = Counter(e["reason"] for e in excluded)
    imbalance = {}
    if total_kept:
        nonempty = [r for r in dist_rows if r["total"] > 0]
        if nonempty:
            mx = max(nonempty, key=lambda r: r["total"])
            mn = min(nonempty, key=lambda r: r["total"])
            imbalance = {"largest_class": mx["class"], "largest_count": mx["total"],
                         "smallest_nonempty_class": mn["class"], "smallest_count": mn["total"],
                         "max_to_min_ratio": round(mx["total"] / mn["total"], 2)}

    domains = sorted({urlparse(r["img_url"]).netloc or "(empty)" for r in final_rows})
    split_totals = Counter(r["split"] for r in final_rows)
    metadata = {
        "dataset_type": f"top-{args.top_n} tractor brand classifier",
        "source": {
            "dataset_json": str(dataset_path),
            "image_root": str(image_root),
            "provenance": "sourced exclusively from the existing local dataset "
                          "(data/tractor_dataset.json) and the existing local "
                          "tractor_images folder; existing listed image URLs only; "
                          "no new sites were scraped or accessed.",
        },
        "counts": {
            "records_in_dataset": len(records),
            "retained_images": total_kept,
            "excluded_images": len(excluded),
            "excluded_by_reason": dict(ex_reasons),
            "duplicates_removed": ex_reasons.get("duplicate", 0),
            "unmapped_folder_files": ex_reasons.get(UNMAPPED, 0),
        },
        "quality_checks": {
            "minimum_dimension_px": args.min_size,
            "corrupt_images": ex_reasons.get("corrupt", 0),
            "below_min_size": ex_reasons.get("below_min_size", 0),
            "duplicate_sha256": ex_reasons.get("duplicate", 0),
            "split_leakage_groups": leak_bad,
            "near_dup_hash_dist": args.hash_dist,
            "model_grouping": bool(args.model_group),
            "class_imbalance": imbalance,
            "source_url_domains": domains,
            "split_distribution": dict(split_totals),
            "split_fractions": ({k: round(v / total_kept, 4) for k, v in split_totals.items()}
                                if total_kept else {}),
        },
    }
    (out_root / "dataset_metadata.json").write_text(json.dumps(metadata, indent=2,
                                                               ensure_ascii=False),
                                                    encoding="utf-8")

    for row in final_rows:
        dst_dir = out_root / row["split"] / row["class"]
        dst_dir.mkdir(parents=True, exist_ok=True)
        dst = dst_dir / row["filename"]
        if not dst.exists():
            shutil.copy2(Path(row["source_path"]), dst)

    print("=" * 70)
    print("top-%d brands:" % args.top_n, top_brands)
    print("retained:", total_kept, " excluded:", len(excluded))
    print("excluded by reason:", dict(ex_reasons))
    print("split totals:", dict(split_totals))
    leak_report = "OK (0 groups span >1 split)" if leak_bad == 0 else "FAILED %d groups" % leak_bad
    print("split leakage check:", leak_report)
    print(f"{'class':16s} {'train':>5s} {'val':>4s} {'test':>4s} {'total':>5s} {'%':>6s}")
    for d in dist_rows:
        print(f"{d['class']:16s} {d['count_train']:5d} {d['count_val']:4d} "
              f"{d['count_test']:4d} {d['total']:5d} {d['pct_of_dataset']:5.1f}%")
    if imbalance:
        print("class imbalance:", imbalance)
    print("output dir:", out_root)
    return 0 if leak_bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main())