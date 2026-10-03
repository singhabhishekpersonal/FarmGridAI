#!/usr/bin/env python3
"""Build a versioned staging dataset (proposal) from reviewed records.

Leakage-safe grouped partitions + a manifest of sha256 and provenance chains.
This never retrains/overwrites any model artifact — it only writes a proposal
under ``DATA_INGESTION_DATA_DIR/datasets/<catalog>/``.
"""
import argparse

from data_ingestion_cli import bootstrap, print_report

bootstrap()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("name", help="dataset name (e.g. 'equipment_images_top6_v2')")
    parser.add_argument("--output-dir", default="", help="where to write the staging dataset (default: data/ingested/datasets)")
    parser.add_argument("--train", type=float, default=0.8)
    parser.add_argument("--val", type=float, default=0.1)
    parser.add_argument("--test", type=float, default=0.1)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    split = (args.train, args.val, args.test)
    if abs(sum(split) - 1.0) > 1e-6:
        raise SystemExit("train+val+test must sum to 1.0")

    from apps.data_ingestion.services.dataset_enrichment import build_staging_dataset

    report = build_staging_dataset(
        args.name,
        output_dir=args.output_dir or None,
        split=split,
        seed=args.seed,
    )
    print_report(report)
    print("\nThis is a PROPOSAL. A human must review the manifest before any training use.")


if __name__ == "__main__":
    main()