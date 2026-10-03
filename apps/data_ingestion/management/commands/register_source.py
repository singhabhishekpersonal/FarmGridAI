"""Register a data source (pending approval by default).

The command mirrors the register-equipment-model convention: it never
approves or enables collection on its own.
"""
from django.core.management.base import BaseCommand, CommandError

from apps.data_ingestion.models import DataSource
from apps.data_ingestion.services.source_registry import SourceRegistryError, register_source


class Command(BaseCommand):
    help = "Register a DataSource in the pending state (collection disabled)."

    def add_arguments(self, parser):
        parser.add_argument("--name", required=True, help="Source display name.")
        parser.add_argument("--base-url", required=True, help="Base URL (scheme://host).")
        parser.add_argument(
            "--source-type",
            default="public_dataset",
            choices=DataSource.SourceType.values,
        )
        parser.add_argument("--category", default="equipment_images", choices=DataSource.Category.values)
        parser.add_argument("--organization", default="")
        parser.add_argument("--state", default="")
        parser.add_argument("--country", default="IN")
        parser.add_argument("--robots-url", default="")
        parser.add_argument("--terms-url", default="")
        parser.add_argument("--license-url", default="")
        parser.add_argument("--attribution", default="")
        parser.add_argument(
            "--methods",
            default="api,downloadable_file",
            help="Comma-separated AllowedMethod values.",
        )
        parser.add_argument("--rate-limit", type=int, default=10)
        parser.add_argument("--delay", type=float, default=1.0)
        parser.add_argument("--max-pages", type=int, default=20)
        parser.add_argument("--allows-images", action="store_true")
        parser.add_argument("--allows-documents", action="store_true")
        parser.add_argument("--allows-structured-data", action="store_true")
        parser.add_argument("--notes", default="")

    def handle(self, *args, **options):
        for flag in ("--source-type", "--category"):
            value = options.get(flag.lstrip("-"))
            if value not in (DataSource.SourceType.values if "type" in flag else DataSource.Category.values):
                raise CommandError(f"{flag} must be one of ...")

        methods = [m.strip() for m in options["methods"].split(",") if m.strip()]
        for method in methods:
            if method not in DataSource.AllowedMethod.values:
                raise CommandError(f"unknown collection method {method!r}")
        try:
            source = register_source(
                name=options["name"],
                base_url=options["base_url"],
                source_type=options["source_type"],
                category=options["category"],
                organization=options["organization"],
                state=options["state"],
                country=options["country"],
                robots_url=options["robots_url"],
                terms_url=options["terms_url"],
                license_url=options["license_url"],
                attribution_text=options["attribution"],
                allowed_collection_methods=methods,
                rate_limit_per_minute=options["rate_limit"],
                request_delay_seconds=options["delay"],
                max_pages_per_run=options["max_pages"],
                allows_images=options["allows_images"],
                allows_documents=options["allows_documents"],
                allows_structured_data=options["allows_structured_data"],
                notes=options["notes"],
            )
        except SourceRegistryError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(self.style.SUCCESS(f"source registered id={source.pk} name={source.name}"))
        self.stdout.write("status: pending (approve via admin, API, or check_source_compliance + human approval)")