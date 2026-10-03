"""Equipment-image collection for an approved source.

Downloads image URLs (from an approved equipment_images source), validates
each image, deduplicates by SHA-256, saves the raw bytes to disk, and records
both a :class:`CollectedArtifact` and (optionally) an :class:`ExtractedRecord`
in ``raw`` status — which must still pass review before it may be used to
build a dataset.
"""
import logging

from pathlib import Path

from django.conf import settings

from apps.data_ingestion.models import CollectedArtifact, DataSource, ExtractedRecord, IngestionRun
from apps.data_ingestion.services.downloader import _run_folder, download_url
from apps.data_ingestion.services.hashing import short_hash
from apps.data_ingestion.services.image_validation import validate_image
from apps.data_ingestion.services.source_registry import is_collectable

logger = logging.getLogger("khetsathi.audit")


def collect_images(
    source,
    run,
    image_urls,
    *,
    client=None,
    min_dimension=None,
    max_bytes=None,
    allowed_extensions=None,
    attribution="",
    license_note="",
    label_hint="",
    create_records=True,
    max_images=None,
    on_progress=None,
):
    """Download + validate + dedup ``image_urls`` for an approved source.

    Returns a report dict with counters and per-URL outcomes.
    """
    if not is_collectable(source):
        if run.is_dry_run:
            return _empty_report({"dry_run": True})
        raise RuntimeError(f"source {source.name!r} is not approved & collection-enabled")

    min_dimension = min_dimension if min_dimension is not None else getattr(settings, "DATA_INGESTION_MIN_IMAGE_DIMENSION", 320)
    max_bytes = max_bytes if max_bytes is not None else getattr(settings, "DATA_INGESTION_MAX_IMAGE_SIZE_MB", 15) * 1024 * 1024
    allowed_extensions = set(
        allowed_extensions or getattr(settings, "DATA_INGESTION_ALLOWED_IMAGE_EXTENSIONS", [".jpg", ".jpeg", ".png", ".webp"])
    )

    report = {
        "dry_run": run.is_dry_run,
        "requested": len(image_urls),
        "downloaded": 0,
        "valid": 0,
        "invalid": 0,
        "duplicates": 0,
        "blocked": 0,
        "failures": [],
        "artifacts": [],
    }

    limit = max_images or len(image_urls)
    for idx, url in enumerate(image_urls[:limit]):
        if on_progress:
            on_progress(idx + 1, len(image_urls[:limit]), url)
        artifact, reason = download_url(
            source,
            run,
            url,
            CollectedArtifact.ArtifactType.IMAGE,
            client=client,
            allowed_extensions=allowed_extensions,
            max_bytes=max_bytes,
            license_note=license_note,
            attribution=attribution,
        )
        if artifact is None:
            if "duplicate" in (reason or ""):
                report["duplicates"] += 1
            else:
                report["blocked"] += 1
                report["failures"].append(reason)
            continue
        report["downloaded"] += 1
        run.images_downloaded += 1

        raw = _load_raw(artifact)
        if raw is None:
            artifact.validation_status = CollectedArtifact.ValidationStatus.INVALID
            artifact.is_approved = False
            artifact.save(update_fields=["validation_status", "is_approved"])
            report["invalid"] += 1
            continue

        check = validate_image(
            raw,
            filename=artifact.original_url,
            max_bytes=max_bytes,
            min_dimension=min_dimension,
            allowed_extensions=allowed_extensions,
            allowed_mimes=getattr(settings, "DATA_INGESTION_ALLOWED_IMAGE_MIME_TYPES", None),
        )
        check["local_path"] = artifact.local_path
        check["source_url"] = artifact.original_url
        check["label_hint"] = label_hint

        if check["status"] != CollectedArtifact.ValidationStatus.VALID:
            artifact.validation_status = check["status"]
            artifact.is_approved = False
            artifact.save(update_fields=["validation_status", "is_approved"])
            report["invalid"] += 1
            report["failures"].append(f"{url}: {check['errors']}")
            continue

        artifact.validation_status = CollectedArtifact.ValidationStatus.VALID
        artifact.is_approved = True
        artifact.save(update_fields=["validation_status", "is_approved"])
        report["valid"] += 1
        report["artifacts"].append(str(artifact.pk))

        if create_records and not run.is_dry_run:
            ExtractedRecord.objects.create(
                source=source,
                ingestion_run=run,
                collected_artifact=artifact,
                record_type=ExtractedRecord.RecordType.EQUIPMENT_IMAGE,
                normalized_data_json={"image_url": artifact.original_url, "label_hint": label_hint, "validation": check},
                source_url=artifact.original_url,
                content_hash=short_hash(artifact.sha256, 32),
                confidence="low",
                verification_status=ExtractedRecord.VerificationStatus.RAW,
            )
            run.records_extracted += 1

    run.images_downloaded = report["downloaded"]
    run.records_extracted = run.records_extracted if create_records else 0
    run.save(update_fields=["images_downloaded", "records_extracted", "status"])
    return report


def _load_raw(artifact):
    try:
        with open(artifact.local_path, "rb") as handle:
            return handle.read()
    except OSError:
        return None


def import_manual_images(source, run, files, *, label_hint="", attribution="", license_note="", create_records=True):
    """Offline import of local image files (no network access ever).

    Requires ``source`` to be an approved ``manual_import`` source. Shorthand
    convenience used by the ``import_manual_dataset`` command and the manual
    import API endpoint.
    """
    if source.source_type != DataSource.SourceType.MANUAL_IMPORT:
        raise RuntimeError("manual import only permitted for manual_import sources")
    if not (source.approval_status == DataSource.ApprovalStatus.APPROVED and source.collection_enabled):
        raise RuntimeError(f"source {source.name!r} must be approved & collection-enabled for manual import")

    report = {"requested": len(files), "imported": 0, "invalid": 0, "duplicates": 0, "failures": [], "artifacts": []}
    min_dimension = getattr(settings, "DATA_INGESTION_MIN_IMAGE_DIMENSION", 320)
    max_bytes = getattr(settings, "DATA_INGESTION_MAX_IMAGE_SIZE_MB", 15) * 1024 * 1024

    for path_value in files:
        path = Path(path_value)
        if not path.is_file():
            report["failures"].append(f"{path_value}: not a file")
            report["invalid"] += 1
            continue
        data = path.read_bytes()
        check = validate_image(
            data,
            filename=path.name,
            max_bytes=max_bytes,
            min_dimension=min_dimension,
            allowed_extensions=getattr(settings, "DATA_INGESTION_ALLOWED_IMAGE_EXTENSIONS", None),
            allowed_mimes=getattr(settings, "DATA_INGESTION_ALLOWED_IMAGE_MIME_TYPES", None),
        )
        if check["status"] != CollectedArtifact.ValidationStatus.VALID:
            report["failures"].append(f"{path.name}: {check['errors']}")
            report["invalid"] += 1
            continue

        digest = check["sha256"]
        if CollectedArtifact.objects.filter(sha256=digest).exists():
            report["duplicates"] += 1
            run.duplicates_skipped += 1
            continue

        folder = _run_folder(run) / CollectedArtifact.ArtifactType.IMAGE
        folder.mkdir(parents=True, exist_ok=True)
        ext = path.suffix.lower() or ".img"
        target = folder / f"{digest[:24]}{ext}"
        target.write_bytes(data)

        from PIL import Image

        with Image.open(path) as img:
            width, height = img.size
        artifact = CollectedArtifact.objects.create(
            source=source,
            ingestion_run=run,
            artifact_type=CollectedArtifact.ArtifactType.IMAGE,
            original_url=f"file://import/{path.name}",
            final_url=f"file://import/{path.name}",
            local_path=str(target),
            sha256=digest,
            content_type=check["mime_type"],
            file_size=len(data),
            license_note=license_note,
            attribution=attribution,
            is_approved=True,
            validation_status=CollectedArtifact.ValidationStatus.VALID,
        )
        run.images_downloaded += 1
        report["imported"] += 1
        report["artifacts"].append(str(artifact.pk))

        if create_records and not run.is_dry_run:
            ExtractedRecord.objects.create(
                source=source,
                ingestion_run=run,
                collected_artifact=artifact,
                record_type=ExtractedRecord.RecordType.EQUIPMENT_IMAGE,
                normalized_data_json={
                    "image_url": artifact.original_url,
                    "label_hint": label_hint,
                    "width": width,
                    "height": height,
                    "validation": {k: check[k] for k in ("sha256", "mime_type", "blur_score", "dark_bright")},
                },
                source_url=artifact.original_url,
                content_hash=short_hash(digest, 32),
                confidence="low",
                verification_status=ExtractedRecord.VerificationStatus.RAW,
            )
            run.records_extracted += 1

    run.images_downloaded = report["imported"]
    run.records_extracted = run.records_extracted if create_records else 0
    run.save(update_fields=["images_downloaded", "records_extracted", "duplicates_skipped", "status"])
    return report


def _empty_report(extra):
    report = {
        "requested": 0,
        "downloaded": 0,
        "valid": 0,
        "invalid": 0,
        "duplicates": 0,
        "blocked": 0,
        "failures": [],
        "artifacts": [],
    }
    report.update(extra)
    return report