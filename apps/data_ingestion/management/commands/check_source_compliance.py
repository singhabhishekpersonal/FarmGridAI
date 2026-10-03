"""Run a compliance check for a data source (offline-safe).

By default the check runs with the network disabled and records a
``manual_review`` decision — safe for tests and dry runs. Collection only
becomes permissible after a human approves the source with an ``allowed``
compliance decision on record.
"""
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from apps.data_ingestion.models import DataSource, SourceComplianceCheck
from apps.data_ingestion.services.compliance import run_compliance_check
from apps.data_ingestion.services.source_registry import approve_source


class Command(BaseCommand):
    help = "Run one compliance check against a DataSource and persist the evidence."

    def add_arguments(self, parser):
        parser.add_argument("--source-id", required=True, help="DataSource primary key (uuid).")
        parser.add_argument("--run-id", default="", help="Optional run id.")
        parser.add_argument("--approve", action="store_true", help="Approve the source if the check allows (records supplied --user).")
        parser.add_argument("--user", default="", help="Username recorded as the approver when --approve is used.")

    def handle(self, *args, **options):
        try:
            source = DataSource.objects.get(pk=options["source_id"])
        except (DataSource.DoesNotExist, ValueError) as exc:
            raise CommandError(f"unknown source: {options['source_id']}") from exc

        check = run_compliance_check(source, run_id=options["run_id"])
        self.stdout.write(f"decision       : {check.decision}")
        self.stdout.write(f"robots_retrieved={check.robots_retrieved} allows={check.robots_allows_target_paths}")
        self.stdout.write(f"terms_retrieved={check.terms_retrieved} manual_review={check.terms_manual_review_required}")
        self.stdout.write(f"blocked_reason : {check.blocked_reason or '-'}")
        self.stdout.write(f"evidence       : {check.evidence_path or '-'}")

        if options["approve"]:
            if check.decision != SourceComplianceCheck.Decision.ALLOWED:
                raise CommandError("cannot approve: latest compliance decision is not ALLOWED")
            user_model = get_user_model()
            user = None
            if options["user"]:
                try:
                    user = user_model.objects.get(username=options["user"])
                except user_model.DoesNotExist as exc:
                    raise CommandError(f"unknown user {options['user']!r}") from exc
            if user is None:
                raise CommandError("--approve requires --user (human approver)")
            approve_source(source, user, reason="approval granted via check_source_compliance --approve")
            self.stdout.write(self.style.SUCCESS("source approved + collection_enabled=True"))