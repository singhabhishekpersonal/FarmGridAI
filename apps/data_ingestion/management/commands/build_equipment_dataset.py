"""Build a staged, leakage-safe, versioned equipment dataset from reviewed records.

Never retrains or touches trained artifacts. Produces a manifest + provenance
report and (optionally) writes the expansion plan to disk for human review.
"""
import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.data_ingestion.services.dataset_enrichment import build_staging_dataset, eligible_records
from apps.data_ingestion.services.planner import expansion_plan
from apps.data_ingestion.services.provenance import record_provenance


class Command(BaseCommand):
    help = "Build (or report on) a staging equipment dataset from reviewed ingested records."

    def add_arguments(self, parser):
        parser.add_argument("--name", default="equipment_staging", help="Dataset catalog name.")
        parser.add_argument("--report-only", action="store_true", help="Only print the expansion plan, write nothing.")
        parser.add_argument("--known-counts", default="", help='JSON map of class->current count, e.g. {"Mahindra": 154}.')
        parser.add_argument("--out", default="", help="Output directory for the staging dataset (default: settings path).")
        parser.add_argument("--split", default="0.8,0.1,0.1", help="Comma-separated train/val/test split.")

    def handle(self, *args, **options):
        known_counts = {}
        if options["known_counts"]:
            try:
                known_counts = json.loads(options["known_counts"])
            except json.JSONDecodeError as exc:
                raise CommandError(f"--known-counts must be valid JSON: {exc}") from exc

        split_parts = [float(p) for p in options["split"].split(",")]
        if len(split_parts) != 3 or abs(sum(split_parts) - 1.0) > 1e-6:
            raise CommandError("--split must be three fractions summing to 1.0")

        plan = expansion_plan(known_counts=known_counts)
        self.stdout.write("expanded expansion plan:")
        for row in plan["rows"]:
            self.stdout.write(
                f"  {row['label']:16} target={row['target']:4} current={row['current']:4} "
                f"candidates={row['approved_source_candidates_in_review']:4} shortfall={row['shortfall_after_candidates']:4}"
            )
        self.stdout.write("  " + plan["recommendation"])

        if options["report_only"]:
            return

        records = eligible_records()
        if not records.exists():
            raise CommandError("no eligible (reviewed/published, approved-source) equipment-image records to build from")
        report = build_staging_dataset(options["name"], list(records), output_dir=options["out"] or None, split=tuple(split_parts))
        self.stdout.write(self.style.SUCCESS(f"staging dataset built: {json.dumps(report['counts'], indent=2)}"))
        self.stdout.write(f"manifest: {report['manifest_path']}")

        provenance_dir = Path(settings.DATA_INGESTION_DATA_DIR) / "reports"
        provenance_dir.mkdir(parents=True, exist_ok=True)
        for record in records:
            Path(provenance_dir, f"provenance_record_{str(record.pk)[:12]}.json").write_text(
                json.dumps(record_provenance(record), indent=2), encoding="utf-8"
            )
        self.stdout.write(f"provenance records written to {provenance_dir}")