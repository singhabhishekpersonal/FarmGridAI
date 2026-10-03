#!/usr/bin/env python3
"""Collect image URLs from an approved + collection-enabled source.

Dry-run by default (``./collect_approved_source.py GOV-API --urls ...`` plans
the run without touching the network or persisting anything). Use ``--execute``
AND ``DATA_INGESTION_NETWORK_ALLOWED=true`` to actually download; images land
in the staging area as RAW records awaiting human review.
"""
import argparse

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
    parser.add_argument("source", help="source slug/id/name (must be approved + collection-enabled)")
    parser.add_argument("--urls", nargs="+", required=True, help="image URLs to fetch")
    parser.add_argument("--label", default="", help="label hint applied to every image (kept as-is)")
    parser.add_argument("--license", default="", help="license note attached to the artifacts")
    parser.add_argument("--attribution", default="", help="attribution text")
    parser.add_argument("--max", type=int, default=0, help="cap on number of images to collect")
    add_dry_run_flag(parser, default=True)
    args = parser.parse_args()

    from apps.data_ingestion.services.downloader import make_ingestion_run
    from apps.data_ingestion.services.image_collector import collect_images
    from apps.data_ingestion.services.source_registry import is_collectable

    source = resolve_source(args.source)
    if not is_collectable(source):
        raise SystemExit(f"source {source.name!r} is not approved & collection-enabled")

    run = make_ingestion_run(source, dry_run=not is_execute(args))

    def progress(done, total, url):
        print(f"  [{done}/{total}] {url}")

    report = collect_images(
        source,
        run,
        args.urls,
        attribution=args.attribution,
        license_note=args.license,
        label_hint=args.label,
        max_images=args.max or None,
        on_progress=progress,
    )
    print(f"\nrun: {run.run_id} (dry_run={run.is_dry_run})")
    print_report(report)
    print("\nIMPORTANT: collected images are awaiting human review; nothing is published automatically.")


if __name__ == "__main__":
    main()