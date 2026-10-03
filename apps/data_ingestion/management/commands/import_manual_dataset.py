"""Import a manual dataset folder (offline) into the ingestion pipeline.

Creates (or reuses) a ``manual_import`` DataSource, then validates, dedups and
registers each image as an ``equipment_image`` record in the review queue.

Two layouts:
* ``--subdir-labels`` (or ``--label-map``): each subfolder is a label;
* single flat folder: use ``--label-hint LABEL`` for one class.
"""
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.data_ingestion.models import DataSource
from apps.data_ingestion.services.downloader import make_ingestion_run
from apps.data_ingestion.services.image_collector import import_manual_images
from apps.data_ingestion.services.source_registry import approve_source, register_source


class Command(BaseCommand):
    help = "Import local image files into the ingestion pipeline (offline, review-first)."

    def add_arguments(self, parser):
        parser.add_argument("--folder", required=True, help="Folder with images.")
        parser.add_argument("--source-name", default="Manual import", help="DataSource name (created if missing).")
        parser.add_argument("--label-map", default="", help="Comma-separated subfolder=label pairs, e.g. 'Mahindra=Mahindra'.")
        parser.add_argument("--label-hint", default="", help="Single label-hint for a flat-folder import.")
        parser.add_argument("--subdir-labels", action="store_true", help="Treat immediate subdirectories as labels.")
        parser.add_argument("--approve", action="store_true", help="Approve the manual-import source (records --user).")
        parser.add_argument("--user", default="", help="Approver username (required with --approve).")

    def handle(self, *args, **options):
        folder = Path(options["folder"])
        if not folder.is_dir():
            raise CommandError(f"folder not found: {folder}")

        source = DataSource.objects.filter(
            source_type=DataSource.SourceType.MANUAL_IMPORT, name=options["source_name"]
        ).first()
        if source is None:
            source = register_source(
                name=options["source_name"],
                base_url=f"manual://{options['source_name']}".replace(" ", "-"),
                source_type=DataSource.SourceType.MANUAL_IMPORT,
                category=DataSource.Category.EQUIPMENT_IMAGES,
                allowed_collection_methods=[DataSource.AllowedMethod.MANUAL_IMPORT_ONLY],
                allows_images=True,
            )
            self.stdout.write(f"created manual_import source id={source.pk}")

        if options["approve"]:
            user = get_user_model().objects.filter(username=options["user"]).first() if options["user"] else None
            if user is None:
                raise CommandError("--approve requires --user (human approver)")
            approve_source(source, user, reason="manual import approval via import_manual_dataset")
        if not (source.approval_status == DataSource.ApprovalStatus.APPROVED and source.collection_enabled):
            raise CommandError("manual-import source not approved; re-run with --approve --user <staff>")

        use_subdirs = options["subdir_labels"] or bool(options["label_map"])
        if not use_subdirs and not options["label_hint"]:
            raise CommandError("specify --subdir-labels, --label-map, or --label-hint for a flat import")

        label_map = {}
        if options["label_map"]:
            for pair in options["label_map"].split(","):
                if "=" not in pair:
                    raise CommandError(f"label-map entries must be subfolder=label, got {pair!r}")
                sub, label = pair.split("=", 1)
                label_map[sub.strip()] = label.strip()

        files_by_label = {}
        if use_subdirs:
            for child in sorted(folder.iterdir()):
                if child.is_dir():
                    label = label_map.get(child.name, child.name)
                    files_by_label[label] = sorted(p for p in child.rglob("*") if p.is_file())
        else:
            files_by_label[options["label_hint"]] = sorted(p for p in folder.rglob("*") if p.is_file())

        if not any(files_by_label.values()):
            raise CommandError("no image files found in folder")

        run = make_ingestion_run(
            source,
            dry_run=False,
            config={"command": "import_manual_dataset", "folder": str(folder)},
            collector_version="import_manual_dataset.1",
        )
        total = {"requested": 0, "imported": 0, "invalid": 0, "duplicates": 0, "by_label": {}}
        for label, files in sorted(files_by_label.items()):
            report = import_manual_images(source, run, files, label_hint=label)
            for key in ("requested", "imported", "invalid", "duplicates"):
                total[key] += report[key]
            total["by_label"][label] = {k: report[k] for k in ("requested", "imported", "invalid", "duplicates")}
            self.stdout.write(
                f"label {label:24} imported={report['imported']} invalid={report['invalid']} dup={report['duplicates']}"
            )

        run.status = "completed"
        run.completed_at = timezone.now()
        run.save(update_fields=["status", "completed_at"])
        self.stdout.write(self.style.SUCCESS(f"import completed: {total}"))
        self.stdout.write(f"next: run `validate_ingested_data --source-id {source.pk}` to forward records to the review queue.")