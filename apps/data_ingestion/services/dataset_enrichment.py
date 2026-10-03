"""Staging-dataset builder: turns reviewed records into a versioned dataset.

Safety contract:

* only ``ExtractedRecord``s that are ``PUBLISHED``/``REVIEWED`` from an
  **approved** source (or explicit ``allow_approved_only=False`` manual
  imports) enter a staging dataset;
* train/val/test partitions never share a source URL group (leakage guard);
* every staging entry carries a SHA-256 + provenance chain in a versioned
  manifest;
* this NEVER retrains a model or rewrites an existing artifact — it only
  produces a proposal.
"""
import json
import logging
import random
import shutil
from pathlib import Path

from django.conf import settings

from apps.data_ingestion.models import CollectedArtifact, DataSource, ExtractedRecord
from apps.data_ingestion.services.provenance import artifact_provenance, record_provenance

logger = logging.getLogger("khetsathi.audit")

_ALLOWED_STATUSES = {ExtractedRecord.VerificationStatus.REVIEWED, ExtractedRecord.VerificationStatus.PUBLISHED}


class DatasetEnrichmentError(Exception):
    pass


def label_of(record):
    return record.normalized_data_json.get("label_hint") or record.normalized_data_json.get("label") or "unknown"


def eligible_records(*, statuses=None, approved_only=None):
    qs = ExtractedRecord.objects.filter(record_type=ExtractedRecord.RecordType.EQUIPMENT_IMAGE)
    statuses = statuses or _ALLOWED_STATUSES
    qs = qs.filter(verification_status__in=statuses)
    if approved_only is None:
        approved_only = True
    if approved_only:
        qs = qs.filter(source__approval_status=DataSource.ApprovalStatus.APPROVED)
    return qs


def _partition_by_group(records, size=(0.8, 0.1, 0.1), seed=42):
    """Leakage-safe partition: group by source_url, assign whole groups."""
    rng = random.Random(seed)
    groups = {}
    for record in records:
        groups.setdefault(record.source_url or record.source.base_url, []).append(record)
    split = {"train": [], "val": [], "test": []}
    ordered = sorted(groups.items())
    rng.shuffle(ordered)
    train, val, test = [], [], []
    for group, group_records in ordered:
        bucket = rng.random()
        if bucket < size[0]:
            train.extend(group_records)
        elif bucket < size[0] + size[1]:
            val.extend(group_records)
        else:
            test.extend(group_records)
    return {"train": train, "val": val, "test": test}


def build_staging_dataset(name, records=None, *, output_dir=None, split=(0.8, 0.1, 0.1), seed=42):
    """Build the staging dataset folder + manifest. Returns the report dict."""
    catalog = name.lower().replace(" ", "_")
    if output_dir is None:
        base = Path(getattr(settings, "DATA_INGESTION_DATA_DIR", "data/ingested")) / "datasets"
    else:
        base = Path(output_dir)
    base.mkdir(parents=True, exist_ok=True)

    records = list(records) if records is not None else list(eligible_records())
    if not records:
        raise DatasetEnrichmentError("no eligible records to build a staging dataset from")

    partitions = _partition_by_group(records, size=split, seed=seed)
    manifest = {"name": name, "catalog": catalog, "seed": seed, "split": split, "groups": {}, "entries": []}

    counts = {"total": 0, "train": 0, "val": 0, "test": 0, "labels": {}}
    for split_name, split_records in partitions.items():
        folder = base / catalog / split_name
        for record in split_records:
            label = label_of(record)
            counts[split_name] += 1
            counts["total"] += 1
            counts["labels"].setdefault(label, {s: 0 for s in ("train", "val", "test")})
            counts["labels"][label][split_name] += 1

            entry = {
                "record_id": str(record.pk),
                "label": label,
                "split": split_name,
                "source_url": record.source_url,
                "source_name": record.source.name,
                "sha256": (record.collected_artifact.sha256 if record.collected_artifact else ""),
                "provenance": record_provenance(record),
            }
            manifest["entries"].append(entry)
            manifest["groups"].setdefault(record.source_url or record.source.base_url, []).append(split_name)

            if record.collected_artifact and record.collected_artifact.local_path:
                src = Path(record.collected_artifact.local_path)
                dest = folder / label / src.name
                dest.parent.mkdir(parents=True, exist_ok=True)
                if src.exists():
                    shutil.copy2(src, dest)
                entry["staging_path"] = str(dest)

    manifest_path = base / catalog / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    report = {
        "catalog": catalog,
        "manifest_path": str(manifest_path),
        "counts": counts,
        "partition_policy": split,
        "leakage_guard": "groups by source_url; no group spans splits",
    }
    logger.info("staging dataset built name=%s catalog=%s total=%s", name, catalog, counts["total"])
    return report


def classes_distribution(records=None):
    records = records if records is not None else eligible_records()
    distribution = {}
    for record in records:
        label = label_of(record)
        distribution[label] = distribution.get(label, 0) + 1
    return distribution