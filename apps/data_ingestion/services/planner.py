"""Dataset expansion planner.

Produces a **recommendation only** — it never activates models, changes
labels, or downloads anything. It computes per-class current counts, targets,
shortfalls, and counts of approved-source candidates currently in review.
"""
from apps.data_ingestion.models import DataSource, ExtractedRecord
from apps.data_ingestion.services.dataset_enrichment import label_of

# Per the project brief: build balanced coverage for the 6 trained classes,
# with a second tier supporting rows and a hard cap for the rest.
DEFAULT_TARGETS = {
    "Mahindra": 150,
    "Sonalika": 150,
    "Farmtrac": 150,
    "John Deere": 150,
    "New Holland": 150,
    "Powertrac": 150,
    "Massey Ferguson": 120,
    "Eicher": 120,
    "Swaraj": 120,
    "Shaktiman": 120,
}
DEFAULT_OTHER_CAP = 50


def current_counts(known_counts=None):
    """Current per-class counts.

    ``known_counts`` overrides/enriches the DB-derived staging counts with the
    verified figures from the existing Gyan-derived dataset (passed by the
    command/CLI so it is not hard-coded here).
    """
    counts = {}
    records = ExtractedRecord.objects.filter(record_type=ExtractedRecord.RecordType.EQUIPMENT_IMAGE)
    for record in records:
        label = label_of(record)
        counts[label] = counts.get(label, 0) + 1
    for label, value in (known_counts or {}).items():
        counts[label] = max(counts.get(label, 0), int(value))
    return counts


def approved_candidates():
    """Counts of equipment-image records from approved sources, by label.

    (Approved + collection-enabled sources, whether from downloads or manual
    imports; each record must still pass human review to be usable.)
    """
    candidates = {}
    qs = ExtractedRecord.objects.filter(
        record_type=ExtractedRecord.RecordType.EQUIPMENT_IMAGE,
        source__approval_status=DataSource.ApprovalStatus.APPROVED,
    )
    for record in qs:
        label = label_of(record)
        candidates[label] = candidates.get(label, 0) + 1
    return candidates


def expansion_plan(*, targets=None, other_cap=DEFAULT_OTHER_CAP, known_counts=None):
    """Compute the expansion plan. Returns the plan dict (never mutates DB)."""
    targets = {**DEFAULT_TARGETS, **(targets or {})}
    current = current_counts(known_counts=known_counts)
    candidates = approved_candidates()

    classes = sorted(set(list(targets) + list(current) + list(candidates)))
    rows = []
    for label in classes:
        target = targets.get(label, other_cap)
        have = current.get(label, 0)
        cand = candidates.get(label, 0)
        shortfall = max(0, target - have - cand)
        rows.append(
            {
                "label": label,
                "target": target,
                "current": have,
                "approved_source_candidates_in_review": cand,
                "shortfall_after_candidates": shortfall,
            }
        )

    totals = {
        "current_total": sum(current.values()),
        "candidate_total": sum(candidates.values()),
        "rows": rows,
    }
    totals["recommendation"] = (
        "No automatic download/retrain/activation performed. "
        "Only collect from individually approved DataSources after a published "
        "compliance check; send every image through review before staging."
    )
    totals["auto_actions_taken"] = []
    return totals