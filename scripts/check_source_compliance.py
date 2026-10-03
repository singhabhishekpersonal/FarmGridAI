#!/usr/bin/env python3
"""Check one (or all) data sources' compliance state.

Offline by default: with networking disabled every automated check is recorded
as ``manual_review`` with an explicit reason, so a human must still decide.
Run with the ``DATA_INGESTION_NETWORK_ALLOWED=true`` env var to actually fetch
robots.txt / terms from approved-or-pending sources.
"""
import argparse
from pathlib import Path

from data_ingestion_cli import bootstrap, print_report, resolve_source

bootstrap()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", nargs="?", help="source slug/id/name (default: all sources)")
    parser.add_argument("--run-id", default="", help="logical run id for audit grouping")
    args = parser.parse_args()

    from apps.data_ingestion.models import DataSource
    from apps.data_ingestion.services.compliance import run_compliance_check

    if args.source:
        sources = [resolve_source(args.source)]
    else:
        sources = list(DataSource.objects.order_by("name"))

    for source in sources:
        check = run_compliance_check(source, run_id=args.run_id)
        print(f"\nsource: {source.name} [{source.approval_status}]")
        print(f"  decision: {check.decision}")
        print(f"  robots retrieved: {check.robots_retrieved} | terms manual-review: {check.terms_manual_review_required}")
        if check.notes:
            print(f"  notes: {check.notes}")
        if check.evidence_path:
            print(f"  evidence: {Path(check.evidence_path).as_posix()}")


if __name__ == "__main__":
    main()