#!/usr/bin/env python3
"""Emit a provenance/history report for a source, artifact or record.

Read-only. Traces every compliance check, ingestion run, artifact, extracted
record and review decision, and writes a JSON + Markdown report under
``DATA_INGESTION_REPORTS_DIR``.
"""
import argparse
import json
from pathlib import Path

from data_ingestion_cli import bootstrap, resolve_source

bootstrap()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", help="source slug/id/name to trace")
    parser.add_argument("--artifact", help="artifact UUID (raw) to trace")
    parser.add_argument("--record", help="record UUID (raw) to trace")
    parser.add_argument("--out", type=Path, default=None, help="output base path (default: data/ingested/reports/provenance_<key>.[json|md])")
    args = parser.parse_args()

    if not any((args.source, args.artifact, args.record)):
        parser.error("provide one of --source, --artifact, --record")

    from django.conf import settings

    from apps.data_ingestion.models import CollectedArtifact, ExtractedRecord
    from apps.data_ingestion.services.provenance import artifact_provenance, record_provenance, source_history

    if args.source:
        source = resolve_source(args.source)
        data = source_history(source)
        key = str(source.pk)
    elif args.artifact:
        artifact = CollectedArtifact.objects.get(pk=args.artifact)
        data = artifact_provenance(artifact)
        key = args.artifact
    else:
        record = ExtractedRecord.objects.get(pk=args.record)
        data = record_provenance(record)
        key = args.record

    base = args.out or Path(getattr(settings, "DATA_INGESTION_REPORTS_DIR", "data/ingested/reports")) / f"provenance_{key}"
    base.parent.mkdir(parents=True, exist_ok=True)
    base.with_suffix(".json").write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(data, indent=2, ensure_ascii=False))
    print(f"\nwritten: {base.with_suffix('.json')}")


if __name__ == "__main__":
    main()