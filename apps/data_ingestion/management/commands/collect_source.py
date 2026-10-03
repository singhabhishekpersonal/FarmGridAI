"""Collect data from an approved source.

Defaults to a dry run so nothing is downloaded or recorded accidentally. Use
``--dry-run=no`` only after the source is approved and its compliance check is
``allowed`` on record. Image URLs come from ``--image-urls`` (comma separated)
or ``--image-list-file`` (one per line).
"""
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.data_ingestion.models import DataSource
from apps.data_ingestion.services.downloader import make_ingestion_run
from apps.data_ingestion.services.http_client import SafeHTTPClient
from apps.data_ingestion.services.image_collector import collect_images
from apps.data_ingestion.services.source_registry import is_collectable


class Command(BaseCommand):
    help = "Collect equipment images from an approved source (dry-run by default)."

    def add_arguments(self, parser):
        parser.add_argument("--source-id", required=True)
        parser.add_argument("--image-urls", default="", help="Comma-separated image URLs.")
        parser.add_argument("--image-list-file", default="", help="File with one image URL per line.")
        parser.add_argument("--dry-run", default="yes", choices=["yes", "no"])
        parser.add_argument("--max-images", type=int, default=0, help="0 = unlimited.")
        parser.add_argument("--label-hint", default="", help="Optional label hint (goes to review, not trusted).")
        parser.add_argument("--attribution", default="")

    def handle(self, *args, **options):
        try:
            source = DataSource.objects.get(pk=options["source_id"])
        except (DataSource.DoesNotExist, ValueError) as exc:
            raise CommandError(f"unknown source {options['source_id']}") from exc

        urls = [u.strip() for u in (options["image_urls"] or "").split(",") if u.strip()]
        if options["image_list_file"]:
            path = Path(options["image_list_file"])
            if not path.is_file():
                raise CommandError(f"image list file not found: {path}")
            urls += [line.strip() for line in path.read_text().splitlines() if line.strip()]

        urls = list(dict.fromkeys(urls))
        if not urls:
            raise CommandError("no image URLs provided")

        dry_run = options["dry_run"] == "yes"
        if not dry_run and not is_collectable(source):
            raise CommandError("cannot execute: source is not approved & collection-enabled")

        run = make_ingestion_run(
            source,
            dry_run=dry_run,
            config={"command": "collect_source", "dry_run": dry_run, "urls": len(urls)},
            collector_version="collect_source.1",
        )

        client = SafeHTTPClient(
            timeout=15,
            max_bytes=15 * 1024 * 1024,
        )
        report = collect_images(
            source,
            run,
            urls,
            client=client,
            attribution=options["attribution"],
            label_hint=options["label_hint"],
            max_images=options["max_images"] or None,
        )
        for key, value in report.items():
            self.stdout.write(f"{key:12}: {value}")

        run.status = "dry_run" if run.is_dry_run else "completed"
        run.completed_at = timezone.now()
        if run.is_dry_run:
            self.stdout.write(self.style.WARNING("dry run completed - no artifacts/records persisted"))
            run.status = "dry_run"
        else:
            self.stdout.write(self.style.SUCCESS(f"collection completed run_id={run.run_id}"))
        run.save(update_fields=["status", "completed_at"])