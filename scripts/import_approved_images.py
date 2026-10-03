#!/usr/bin/env python3
"""Offline manual import: copy local image files into the review pipeline.

Never touches the network. Requires an approved ``manual_import`` source; the
files are validated, deduplicated by SHA-256, stored under the ingestion data
dir and enqueued as RAW records for human review before any dataset use.
"""
import argparse
from pathlib import Path

from data_ingestion_cli import (
    bootstrap,
    add_dry_run_flag,
    is_execute,
    print_report,
    resolve_source,
)

bootstrap()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", help="slug/id/name of an APPROVED manual_import source")
    parser.add_argument("--dir", type=Path, help="folder to import (imports all image files inside)")
    parser.add_argument("--files", nargs="+", type=Path, help="explicit file list instead of --dir")
    parser.add_argument("--label", default="", help="label hint applied to every image")
    parser.add_argument("--license", default="", help="license note for the imported artifacts")
    parser.add_argument("--attribution", default="", help="attribution text")
    add_dry_run_flag(parser, default=True)
    args = parser.parse_args()

    if not args.dir and not args.files:
        parser.error("provide either --dir or --files")

    extensions = {".jpg", ".jpeg", ".png", ".webp"}
    if args.files:
        files = args.files
    else:
        files = [p for p in sorted(args.dir.rglob("*")) if p.is_file() and p.suffix.lower() in extensions]

    if not files:
        raise SystemExit("no matching image files found")

    from apps.data_ingestion.services.downloader import make_ingestion_run
    from apps.data_ingestion.services.image_collector import import_manual_images

    source = resolve_source(args.source)
    if source.source_type != "manual_import":
        raise SystemExit(f"source {source.name!r} is not a manual_import source")

    run = make_ingestion_run(source, dry_run=not is_execute(args))
    try:
        report = import_manual_images(
            source,
            run,
            [str(p) for p in files],
            label_hint=args.label,
            attribution=args.attribution,
            license_note=args.license,
        )
    except RuntimeError as exc:
        raise SystemExit(str(exc)) from exc
    print(f"\nrun: {run.run_id} (dry_run={run.is_dry_run})")
    print_report(report)
    print("\nIMPORTANT: imported images are RAW; they require human review before dataset use.")


if __name__ == "__main__":
    main()