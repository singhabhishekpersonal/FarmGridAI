"""Artifact downloader: fetches raw files and persists them verbatim.

Only artifacts from an **approved + collection-enabled** source are accepted.
Every artifact is stored to disk (hash-named, never overwriting) and recorded
as a :class:`CollectedArtifact` with full provenance. The module never
overwrites an existing file; byte-identical content is deduplicated instead.
"""
import logging
import time
import uuid
from pathlib import Path
from urllib.parse import urlparse

from django.conf import settings

from apps.data_ingestion.models import CollectedArtifact, DataSource, IngestionRun
from apps.data_ingestion.services.hashing import sha256_of_bytes
from apps.data_ingestion.services.http_client import NetworkDisabledError, ResponseTooLarge, SafeHTTPClient
from apps.data_ingestion.services.source_registry import is_collectable
from apps.data_ingestion.services.urlutils import safe_filename_component, validate_target_url

logger = logging.getLogger("khetsathi.audit")

_EXT_BY_TYPE = {
    CollectedArtifact.ArtifactType.HTML: ".html",
    CollectedArtifact.ArtifactType.JSON: ".json",
    CollectedArtifact.ArtifactType.CSV: ".csv",
    CollectedArtifact.ArtifactType.PDF: ".pdf",
    CollectedArtifact.ArtifactType.IMAGE: ".img",
    CollectedArtifact.ArtifactType.XLSX: ".xlsx",
    CollectedArtifact.ArtifactType.TEXT: ".txt",
}


class DownloaderError(Exception):
    pass


class SourceNotCollectable(DownloaderError):
    pass


def _run_folder(run):
    return Path(getattr(settings, "DATA_INGESTION_DATA_DIR", "data/ingested")) / run.run_id


def download_url(
    source,
    run,
    url,
    artifact_type,
    *,
    client=None,
    allowed_extensions=None,
    max_bytes=None,
    license_note="",
    attribution="",
):
    """Download one URL and persist it as a deduplicated CollectedArtifact.

    Returns ``(artifact_or_None, reason)`` where a non-empty ``reason`` is the
    reason the download was skipped/blocked.
    """
    if not is_collectable(source):
        raise SourceNotCollectable(f"Source {source.name!r} is not approved & collection-enabled")
    validate_target_url(url, allowed_hosts=[source.base_url])
    client = client or SafeHTTPClient(
        timeout=getattr(settings, "DATA_INGESTION_DEFAULT_HTTP_TIMEOUT_SECONDS", 15),
        max_bytes=max_bytes or getattr(settings, "DATA_INGESTION_MAX_ARTIFACT_SIZE_MB", 25) * 1024 * 1024,
    )
    try:
        final_url, status, body, headers = client.get(url, allowed_hosts=[source.base_url])
    except (NetworkDisabledError, ResponseTooLarge) as exc:
        return None, str(exc)
    except Exception as exc:  # noqa: BLE001 - translate any transport error
        return None, f"transport error: {exc}"

    if status >= 400:
        return None, f"HTTP {status} for {url}"
    if status in (301, 302, 303, 307, 308):
        return None, "unsupported redirect"

    digest = sha256_of_bytes(body)
    if CollectedArtifact.objects.filter(sha256=digest).exists():
        run.duplicates_skipped += 1
        run.save(update_fields=["duplicates_skipped"])
        return None, "duplicate sha256"

    folder = _run_folder(run) / artifact_type
    folder.mkdir(parents=True, exist_ok=True)
    ext = Path(urlparse(url).path).suffix.lower() or _EXT_BY_TYPE.get(artifact_type, ".bin")
    if allowed_extensions and ext not in allowed_extensions:
        return None, f"extension {ext!r} not in allowed set"
    filename = f"{digest[:24]}{ext}"
    target = folder / filename
    target.write_bytes(body)

    artifact = CollectedArtifact.objects.create(
        source=source,
        ingestion_run=run,
        artifact_type=artifact_type,
        original_url=url,
        final_url=final_url,
        local_path=str(target),
        sha256=digest,
        content_type=headers.get("Content-Type", "").split(";")[0],
        file_size=len(body),
        http_status=status,
        license_note=license_note,
        attribution=attribution,
        is_duplicate=False,
    )
    logger.info("artifact downloaded source=%s type=%s sha=%s size=%s", source.pk, artifact_type, digest[:12], len(body))
    return artifact, ""


def make_ingestion_run(source, *, dry_run=True, config=None, collector_version=""):
    """Create a run record. Dry-run runs never persist artifacts/records."""
    run_id = f"run-{uuid.uuid4().hex[:12]}"
    return IngestionRun.objects.create(
        source=source,
        run_id=run_id,
        status=IngestionRun.Status.DRY_RUN if dry_run else IngestionRun.Status.PENDING,
        configuration_snapshot=config or {},
        collector_version=collector_version or "",
        is_dry_run=bool(dry_run),
    )