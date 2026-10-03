#!/usr/bin/env python3
"""Export the review queue so a human can triage pending items offline.

Read-only. Writes every PENDING DataReviewQueue entry (with record/artifact
provenance) to a JSON file; an "already reviewed" section shows the last
resolved rows for context. This script never applies a decision — triage must
happen in the admin/API under a human actor.
"""
import argparse
import json
from datetime import datetime
from pathlib import Path

from data_ingestion_cli import bootstrap

bootstrap()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=None, help="output JSON path (default: data/ingested/reports/review_queue_<date>.json)")
    parser.add_argument("--limit", type=int, default=500, help="max pending rows to export")
    args = parser.parse_args()

    from django.conf import settings

    from apps.data_ingestion.models import DataReviewQueue
    from apps.data_ingestion.services.provenance import record_provenance

    pending = DataReviewQueue.objects.filter(decision=DataReviewQueue.Decision.PENDING).order_by("-created_at")[: args.limit]
    reviewed = DataReviewQueue.objects.exclude(decision=DataReviewQueue.Decision.PENDING).order_by("-decided_at")[:200]

    def row(item, detailed):
        base = {
            "id": str(item.pk),
            "record_id": str(item.extracted_record_id),
            "proposed_target_model": item.proposed_target_model,
            "proposed_action": item.proposed_action,
            "risk_level": item.risk_level,
            "source": item.extracted_record.source.name,
            "record_type": str(item.extracted_record.record_type),
            "source_freshness_status": item.source_freshness_status,
        }
        if detailed:
            base["normalized_data"] = item.extracted_record.normalized_data_json
            base["provenance"] = record_provenance(item.extracted_record)
            base["enqueued_at"] = item.created_at.isoformat()
        else:
            base["decision"] = item.decision
            base["resolved_by"] = str(item.decided_by)
            base["decided_at"] = item.decided_at.isoformat() if item.decided_at else ""
            base["decision_notes"] = item.decision_notes
        return base

    payload = {
        "exported_at": datetime.now().isoformat(),
        "pending_count": len(pending),
        "already_reviewed_count": len(reviewed),
        "note": "This script never applies a decision; triage must happen in the admin/API under a human actor.",
        "pending": [row(item, True) for item in pending],
        "already_reviewed": [row(item, False) for item in reviewed],
    }
    out = args.out or Path(getattr(settings, "DATA_INGESTION_REPORTS_DIR", "data/ingested/reports")) / f"review_queue_{datetime.now():%Y%m%d}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"pending review items: {len(pending)}")
    print(f"written: {out}")


if __name__ == "__main__":
    main()