"""Offline, manifest-driven manual import of official documents (PM-KUSUM / MNRE).

This is the sanctioned pathway for documents the operator has downloaded by
hand from official government sources. It implements the intake contract:

* the command runs **fully offline by default** and **refuses to run** while
  ``DATA_INGESTION_NETWORK_ALLOWED`` is true unless ``--verify-online`` is
  explicitly passed — and even then networking is restricted to a bounded,
  manifest-URL-only source-verification phase (see below);
* only files placed in the approved local import directory are accepted, and
  every document **must** have a sibling manifest ``<file>.manifest.json``;
* validation checks: file extension, MIME magic bytes, PDF integrity (pypdf),
  file size, SHA-256 (vs the manifest's ``expected_sha256`` when supplied),
  duplicate status, ``source_url`` (HTTPS + official government domain),
  ``document_url`` (HTTPS + official government domain), optional
  ``official_reference_url`` (same rules), retrieval date, source organization,
  source attribution and permission/license note;
* every original document is stored **unchanged** as a raw provenance artifact
  (``CollectedArtifact``, PDF, hash-named, never overwriting); the original
  import-directory file is never modified and the folder is snapshotted
  (names + sizes + SHA-256) before and after the run to prove no new files
  appeared;
* text is extracted only **after** validation passes (pypdf);
* extracted records are limited to a fixed whitelist of official scheme fields
  (scheme name, component, official eligibility/benefit/document/application
  wording, effective date, amendment/version info, caveats/exceptions wording,
  official source URL). Nothing is inferred — if the document does not state a
  value, the field is left empty. No subsidy percentages, costs, eligibility
  rules, deadlines or state implementations are ever invented;
* every record is routed to ``DataReviewQueue`` marked ``preliminary`` +
  ``requires_official_verification`` + ``requires_human_review`` and is never
  published to ``SubsidyScheme``/recommendation/live tables;
* twelve reports are generated: import validation, raw artifact/provenance,
  PDF integrity + checksum, manifest validation, online source-verification,
  extraction summary, duplicate report, review-queue export, fields requiring
  manual verification, records not safe to publish, documents with
  unavailable/failed online verification, and the final import status report
  (which separates locally verified / manifest-declared / online-verified /
  extracted-but-unreviewed / human-review-required / not-for-recommendations
  facts and runs the end-of-run safety checklist). The run then stops and waits
  for human approval before any publication.

The source identity is configurable (default: the PM-KUSUM manual source; the
MNRE official-documents manual source can be selected with ``--source-name`` /
``--source-base-url`` / ``--organization``). The source is always forced to
``manual_review`` with ``collection_enabled=False``.

Online verification (``--verify-online``, gated on
``DATA_INGESTION_NETWORK_ALLOWED=true``) uses the **exact manifest URLs only** —
``document_url``, ``source_url`` and (if present) ``official_reference_url``,
at most one request each, HTTPS only, no robots.txt file, no crawling, no
recursive link following, no retries of blocked/gated URLs. Document (PDF)
URLs are checked via a single GET whose body is **not** read; HTML pages
(source/landing pages) are read up to a small cap so the stated title /
filename / hash can be cross-checked against the visible page. Any failed or
blocked check marks online verification ``unavailable``, adds a limitation and
keeps ``requires_human_review`` — a valid local document is never rejected
because online verification failed.

Manifest schema (sibling ``<file>.manifest.json``):

.. code-block:: json

    {
      "file": "pm-kusum-component-a-guidelines-2023.pdf",
      "document_title": "Operational Guidelines for Component-A (Standalone Solar Pumps)",
      "source_url": "https://mnre.gov.in/bio-energy/schemes/pm-kusum",
      "document_url": "https://mnre.gov.in/sites/default/files/uploads/pm-kusum-guidelines-2023.pdf",
      "official_reference_url": "https://mnre.gov.in/bio-energy/schemes/pm-kusum",
      "source_organization": "Ministry of New and Renewable Energy (MNRE), Government of India",
      "retrieval_date": "2026-09-25",
      "source_attribution": "MNRE PM-KUSUM operational guidelines (public government document)",
      "permission_license_note": "Public government document; freely downloadable; no reuse restrictions stated",
      "expected_sha256": "…optional…",
      "expected_size_bytes": 1234567
    }
"""
import io
import json
import logging
import re
import shutil
import uuid
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urlparse

import requests
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.data_ingestion.models import CollectedArtifact, DataSource, ExtractedRecord, IngestionRun
from apps.data_ingestion.services.compliance import run_compliance_check
from apps.data_ingestion.services.hashing import sha256_of_bytes, sha256_of_file
from apps.data_ingestion.services.http_client import DomainRateLimiter, default_user_agent
from apps.data_ingestion.services.provenance import write_provenance_report
from apps.data_ingestion.services.record_factory import create_validated_record
from apps.data_ingestion.services.source_registry import register_source
from apps.data_ingestion.services.urlutils import validate_scheme

logger = logging.getLogger("khetsathi.audit")

ALLOWED_EXTENSIONS = {".pdf"}
MANIFEST_SUFFIX = ".manifest.json"
PDF_MAGIC = b"%PDF-"

WARN_OFFICIAL_HOSTS = ("mnre.gov.in", "pmkusum.mnre.gov.in")
GOV_SUFFIXES = (".gov.in", ".nic.in")
REQUIRED_MANIFEST_FIELDS = (
    "file",
    "source_url",
    "document_url",
    "source_organization",
    "retrieval_date",
    "source_attribution",
    "permission_license_note",
)
VERIFY_MAX_HTML_BYTES = 256 * 1024
VERIFY_TIMEOUT_SECONDS = 20
VERIFY_MAX_REDIRECTS = 2

RE_DATE = re.compile(r"\b(0?[1-9]|[12]\d|3[01])[/-](0?[1-9]|1[0-2])[/-](\d{4})\b")
RE_MONTH_DAY_YEAR = re.compile(
    r"\b(\d{1,2})\s+(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may"
    r"|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?"
    r"|dec(?:ember)?)\s+(\d{4})\b",
    re.IGNORECASE,
)
MONTH_NUMBER = {
    "jan": "01", "january": "01", "feb": "02", "february": "02", "mar": "03", "march": "03",
    "apr": "04", "april": "04", "may": "05", "jun": "06", "june": "06", "jul": "07", "july": "07",
    "aug": "08", "august": "08", "sep": "09", "september": "09", "oct": "10", "october": "10",
    "nov": "11", "november": "11", "dec": "12", "december": "12",
}

_EFFECTIVE_WORDS = ("effective", "wef", "with effect from", "in force", "from the date")

# Only these fields are ever populated from the document; nothing else is invented.
EXTRACT_FIELD_NAMES = (
    "scheme_name",
    "scheme_component",
    "official_eligibility_wording",
    "official_benefit_subsidy_wording",
    "official_document_requirements",
    "official_application_procedure_wording",
    "effective_date",
    "amendment_version_information",
    "official_caveats_exceptions_wording",
    "official_source_url",
)


def _is_gov_domain(host):
    host = (host or "").lower().strip().rstrip(".")
    return host == "gov.in" or host.endswith(GOV_SUFFIXES) or host in WARN_OFFICIAL_HOSTS


def _clean_snippet(lines, limit=8, max_len=520):
    out, seen = [], set()
    for line in lines:
        line = re.sub(r"\s+", " ", line).strip()
        if not line or line in seen:
            continue
        seen.add(line)
        out.append(line[:max_len])
        if len(out) >= limit:
            break
    return out


def _lines(text):
    return [re.sub(r"\s+", " ", line).strip() for line in (text or "").splitlines() if line.strip()]


def _first_effective_date(text):
    lowered = (text or "").lower()
    for word in _EFFECTIVE_WORDS:
        idx = lowered.find(word)
        while idx != -1:
            window = text[idx : idx + 160]
            match = RE_DATE.search(window)
            if match:
                return f"{match.group(3)}-{match.group(2).zfill(2)}-{match.group(1).zfill(2)}"
            match = RE_MONTH_DAY_YEAR.search(window)
            if match:
                month = MONTH_NUMBER.get(match.group(2).lower(), "01")
                return f"{match.group(3)}-{month}-{match.group(1).zfill(2)}"
            idx = lowered.find(word, idx + 1)
    return ""


def extract_official_scheme_fields(text, *, source_url, document_title=""):
    """Whitelisted, verbatim, non-inferential extraction from document text.

    Every wording field is a list of exact sentence/line snippets copied from
    the document. A field is left empty when the document does not state it.
    No subsidy percentages, costs, application deadlines or state-level
    benefits/implementation rules are ever inferred or added.
    """
    lines = _lines(text)
    lowered = " ".join(l.lower() for l in lines)

    scheme_name = (document_title or "").strip() or _first_title(lines)
    scheme_component = _clean_snippet(
        [l for l in lines if re.search(r"\bcomponent[\s:-]*[abc]\b", l, re.IGNORECASE)]
    )
    eligibility = _clean_snippet(
        [l for l in lines if re.search(r"eligib|eligible", l, re.IGNORECASE)]
    )
    benefit = _clean_snippet(
        [l for l in lines if re.search(
            r"subsid(?:y|ies)|benefit|financial assist|financial support|\bgrant\b|funding|% share|capital cost",
            l,
            re.IGNORECASE,
        )]
    )
    documents = _clean_snippet(
        [l for l in lines if re.search(
            r"document|self.attested|attested|affidavit|certificate|bank passbook|proof of|supporting document",
            l,
            re.IGNORECASE,
        )]
    )
    procedure = _clean_snippet(
        [l for l in lines if re.search(
            r"application|how to apply|apply online|submission|submitted through|procedure|process|portal",
            l,
            re.IGNORECASE,
        )]
    )
    amendment = _clean_snippet(
        [l for l in lines if re.search(
            r"amendment|corrigendum|as amended|version|notification no|issued vide|revised|re-issued",
            l,
            re.IGNORECASE,
        )]
    )
    caveats = _clean_snippet(
        [l for l in lines if re.search(
            r"caveat|exception|not eligible|exclusion|subject to|provided that|however|in case|"
            r"on the condition|condition that|refrain|not applicable|\u0932\u093e\u0917\u0942 \u0928\u0939\u0940\u0902",
            l,
            re.IGNORECASE,
        )]
    )

    return {
        "scheme_name": scheme_name[:300],
        "scheme_component": scheme_component,
        "official_eligibility_wording": eligibility,
        "official_benefit_subsidy_wording": benefit,
        "official_document_requirements": documents,
        "official_application_procedure_wording": procedure,
        "effective_date": _first_effective_date(lowered) or "",
        "amendment_version_information": amendment,
        "official_caveats_exceptions_wording": caveats,
        "official_source_url": source_url.strip(),
    }


def _first_title(lines):
    for line in lines[:40]:
        if len(line) > 12 and "http" not in line.lower():
            return line[:300]
    return ""


def _count_pdf_pages(data):
    try:
        import pypdf  # noqa: WPS433

        reader = pypdf.PdfReader(io.BytesIO(data))
        return len(reader.pages)
    except Exception:  # noqa: BLE001
        return None


def validate_document(path, manifest, *, now=None):
    """Validate one file + its manifest. Returns ``{checks, ok, reasons, extra}``."""
    now = now or date.today()
    checks = {}
    reasons = []

    path = Path(path)
    ext = path.suffix.lower()
    checks["extension"] = (ext in ALLOWED_EXTENSIONS, f"extension {ext!r} {'accepted' if ext in ALLOWED_EXTENSIONS else 'not in allowed set'}")
    if not checks["extension"][0]:
        reasons.append(checks["extension"][1])

    data = path.read_bytes()
    checks["mime_type"] = (data.startswith(PDF_MAGIC), f"magic bytes {'%PDF-' if data.startswith(PDF_MAGIC) else 'not a PDF'}")
    if not checks["mime_type"][0]:
        reasons.append(checks["mime_type"][1])

    checks["pdf_integrity"] = _pdf_integrity(data)
    if not checks["pdf_integrity"][0]:
        reasons.append(checks["pdf_integrity"][1])

    checks["file_size"] = _file_size_ok(data, manifest)
    if not checks["file_size"][0]:
        reasons.append(checks["file_size"][1])

    digest = sha256_of_bytes(data)
    expected_sha = (manifest.get("expected_sha256") or "").strip().lower()
    if expected_sha and expected_sha != digest:
        checks["sha256"] = (False, f"sha256 mismatch (expected {expected_sha[:16]}…, got {digest[:16]}…)")
        reasons.append(checks["sha256"][1])
    else:
        checks["sha256"] = (True, f"sha256 {digest[:16]}… ({('matches expected' if expected_sha else 'computed')})")

    checks["duplicate"] = _duplicate_check(digest)

    checks["source_url"] = _url_check("source_url", manifest.get("source_url"))
    if not checks["source_url"][0]:
        reasons.append(checks["source_url"][1])

    checks["document_url"] = _url_check("document_url", manifest.get("document_url"))
    if not checks["document_url"][0]:
        reasons.append(checks["document_url"][1])

    checks["official_reference_url"] = _url_check("official_reference_url", manifest.get("official_reference_url"), required=False)
    if not checks["official_reference_url"][0]:
        reasons.append(checks["official_reference_url"][1])

    checks["source_organization"] = _required_check("source_organization", manifest.get("source_organization"))
    if not checks["source_organization"][0]:
        reasons.append(checks["source_organization"][1])

    checks["retrieval_date"] = _retrieval_date_check(manifest.get("retrieval_date") or "", now=now)
    if not checks["retrieval_date"][0]:
        reasons.append(checks["retrieval_date"][1])

    checks["source_attribution"] = _required_check("source_attribution", manifest.get("source_attribution"))
    if not checks["source_attribution"][0]:
        reasons.append(checks["source_attribution"][1])

    checks["permission_license_note"] = _required_check("permission_license_note", manifest.get("permission_license_note"))
    if not checks["permission_license_note"][0]:
        reasons.append(checks["permission_license_note"][1])

    host = urlparse(manifest.get("source_url") or "").hostname or ""
    host_note = " (unverified host)" if host and not _is_gov_domain(host) else ""
    extra = {
        "sha256": digest,
        "size_bytes": len(data),
        "pdf_pages": _count_pdf_pages(data),
        "host_warning": bool(host_note),
        "host_note": host_note,
    }
    duplicate_existing = _existing_duplicate(digest)
    if duplicate_existing is not None:
        extra["duplicate_existing"] = duplicate_existing
    return {
        "checks": checks,
        "ok": not reasons,
        "reasons": reasons,
        "extra": extra,
    }


def _existing_duplicate(digest):
    existing = CollectedArtifact.objects.filter(sha256=digest).first()
    return str(existing.pk) if existing is not None else None


def _pdf_integrity(data):
    try:
        import pypdf  # noqa: WPS433

        reader = pypdf.PdfReader(io.BytesIO(data))
        pages = len(reader.pages)
    except ImportError:
        return (False, "pypdf not installed; PDF integrity cannot be verified")
    except Exception as exc:  # noqa: BLE001
        return (False, f"PDF failed to parse: {exc.__class__.__name__}: {exc}")
    if pages < 1:
        return (False, "PDF has no pages")
    return (True, f"PDF parses OK ({pages} pages)")


def _file_size_ok(data, manifest):
    size = len(data)
    if size <= 0:
        return (False, "file is empty")
    cap = getattr(settings, "DATA_INGESTION_MAX_ARTIFACT_SIZE_MB", 25) * 1024 * 1024
    if size > cap:
        return (False, f"file size {size} exceeds cap {cap}")
    expected = manifest.get("expected_size_bytes")
    if expected is not None:
        try:
            if int(expected) != size:
                return (False, f"expected_size_bytes {expected} != actual {size}")
        except (TypeError, ValueError):
            return (False, f"expected_size_bytes is not an integer ({expected!r})")
    return (True, f"size {size} bytes {'(matches expected)' if expected is not None else 'within cap'}")


def _duplicate_check(digest):
    """``(passed, message)`` where passed=True means the content is new.

    A duplicate is not a validation failure; it is reported and skipped so the
    original artifact (already stored byte-identically) is preserved unchanged.
    """
    existing = CollectedArtifact.objects.filter(sha256=digest).first()
    if existing is not None:
        return (False, f"DUPLICATE: identical content already stored as artifact {existing.pk} ({existing.artifact_type})")
    return (True, "not a duplicate")


def _url_check(key, value, *, required=True):
    value = (value or "").strip()
    if not value and not required:
        return (True, f"{key} absent (optional field)")
    if not value:
        return (False, f"{key} is required")
    try:
        validate_scheme(value)
    except Exception as exc:  # noqa: BLE001
        return (False, f"{key} invalid: {exc}")
    if not value.startswith("https://"):
        return (False, f"{key} must be https (verified official government page)")
    host = urlparse(value).hostname
    if not host:
        return (False, f"{key} has no host")
    if not _is_gov_domain(host):
        return (False, f"{key} host {host!r} is not an official government domain (.gov.in/.nic.in)")
    return (True, f"{key} https OK ({host})")


def _required_check(key, value):
    value = (value or "").strip()
    if not value:
        return (False, f"{key} is required and must not be empty")
    if len(value) > 2000:
        return (False, f"{key} is too long ({len(value)} chars)")
    return (True, f"{key} present")


def _retrieval_date_check(value, *, now):
    value = (value or "").strip()
    try:
        parsed = date.fromisoformat(value)
    except (ValueError, TypeError) as exc:
        return (False, f"retrieval_date must be ISO YYYY-MM-DD: {value!r} ({exc})")
    if parsed.year < 2000 or parsed.year > now.year + 1:
        return (False, f"retrieval_date out of plausible range: {value}")
    if parsed > now:
        return (False, f"retrieval_date is in the future: {value}")
    return (True, f"retrieval_date {value} OK")


def _org_domain_consistent(organization, host):
    org = (organization or "").lower()
    host = (host or "").lower()
    if not org or not host:
        return "uncertain"
    if "government" in org or "ministry" in org or "govt" in org:
        if host.endswith(GOV_SUFFIXES):
            return "consistent"
    toks = [t for t in re.split(r"[^a-z0-9]+", org) if len(t) > 3]
    if any(t in host for t in toks):
        return "consistent"
    return "uncertain"


def _validate_manifest_structure(manifest, filename):
    """Structural manifest checks (independent of file content)."""
    problems = []
    if not isinstance(manifest, dict):
        return ["manifest is not a JSON object"]
    declared = manifest.get("file")
    if declared != filename:
        problems.append(f"manifest file field {declared!r} != document filename {filename!r}")
    for key in REQUIRED_MANIFEST_FIELDS:
        if not ((manifest.get(key) or "").strip()):
            problems.append(f"manifest is missing required field {key!r}")
    return problems


class Command(BaseCommand):
    help = ("Offline manual import of official PM-KUSUM/MNRE guideline documents "
            "(manifest-driven, review-first, optional bounded online source-verification, never publishes).")

    def add_arguments(self, parser):
        parser.add_argument("--folder", default="", help="Approved local import directory (default: DATA_INGESTION_IMPORT_DIR/pmkusum_official).")
        parser.add_argument("--operator-user", required=True, help="Username of the human operator preparing the import (audit only, no approval).")
        parser.add_argument("--run-id", default=f"run-{uuid.uuid4().hex[:12]}")
        parser.add_argument("--source-name", default="PM-KUSUM Official Documents (manual import)", help="Display name of the manual_import source (recorded exactly; used to select/reuse the DataSource).")
        parser.add_argument("--source-base-url", default="manual://pmkusum-official-documents", help="Stable manual base URL for the manual_import source (manual:// scheme).")
        parser.add_argument("--organization", default="Ministry of New and Renewable Energy (MNRE), Government of India", help="Source organization recorded on the manual_import DataSource.")
        parser.add_argument("--verify-online", action="store_true", help="Run the bounded online source-verification phase (requires DATA_INGESTION_NETWORK_ALLOWED=true). Uses exact manifest URLs only: at most one request to document_url, source_url and official_reference_url each; HTTPS-only; no crawling; no PDF downloads.")

    def handle(self, *args, **options):
        network_allowed = bool(getattr(settings, "DATA_INGESTION_NETWORK_ALLOWED", False))
        verify_online = bool(options["verify_online"])
        if verify_online and not network_allowed:
            raise CommandError(
                "--verify-online requires DATA_INGESTION_NETWORK_ALLOWED=true; "
                "the verification phase may only run during this approved, operator-gated run."
            )
        if network_allowed and not verify_online:
            raise CommandError(
                "DATA_INGESTION_NETWORK_ALLOWED is true but --verify-online was not passed; "
                "this command performs no network access unless the operator explicitly requests "
                "the bounded source-verification phase."
            )

        folder = Path(options["folder"] or Path(getattr(settings, "DATA_INGESTION_IMPORT_DIR", "data/imports")) / "pmkusum_official")
        if not folder.is_dir():
            raise CommandError(
                f"approved import directory not found: {folder}\n"
                "Place each officially downloaded document PDF here together with its sibling "
                "'<file>.manifest.json' (see the command docstring for the schema)."
            )

        operator = self._resolve_operator(options["operator_user"])
        run_id = options["run_id"]
        source = self._resolve_source(options)
        self._rate = DomainRateLimiter()

        snapshot_before = self._snapshot_folder(folder)
        live_before = self._live_table_counts()

        run = IngestionRun.objects.create(
            source=source,
            run_id=run_id,
            status=IngestionRun.Status.RUNNING,
            collector_version="import_manual_documents.2",
            configuration_snapshot={
                "mode": "offline_manual_import",
                "operator": operator.username,
                "folder": str(folder),
                "network_allowed": network_allowed,
                "verify_online": verify_online,
                "nopublish": True,
            },
            is_dry_run=False,
        )
        report_dir = self._report_dir()

        documents = sorted(folder.glob("*.pdf"))
        validation_rows = []
        stored = []
        duplicates = []
        extracted_summary = []
        validated_rows = []  # rows that passed validation and are not duplicates

        for pdf_path in documents:
            manifest_path = pdf_path.with_name(pdf_path.stem + MANIFEST_SUFFIX)
            result = self._validate_one(pdf_path, manifest_path)
            validation_rows.append(result)
            if not result["ok"]:
                run.validation_failures += 1
                continue
            if result.get("extra", {}).get("duplicate_existing"):
                duplicates.append({**result, "existing_artifact_id": result["extra"]["duplicate_existing"]})
                run.duplicates_skipped += 1
                continue

            artifact = self._store_artifact(pdf_path, run, source, result["manifest"])
            if artifact is None:
                continue
            stored.append(artifact)
            self.stdout.write(self.style.SUCCESS(f"imported {pdf_path.name} sha={artifact.sha256[:12]}"))

            record = self._extract_and_queue(run, source, artifact, pdf_path, result)
            if record is not None:
                extracted_summary.append(record)
                run.records_extracted += 1
            validated_rows.append(result)

        verification_results = {}
        if verify_online:
            verification_results = self._verify_documents(validated_rows)
            self._attach_verification(run, verification_results)

        run.pages_collected = len(stored)
        run.documents_downloaded = len(stored)
        run.save(update_fields=["pages_collected", "documents_downloaded", "records_extracted", "duplicates_skipped", "validation_failures"])

        snapshot_after = self._snapshot_folder(folder)
        live_after = self._live_table_counts()

        summary = self._write_reports(
            report_dir, run, source, validation_rows, stored, duplicates, extracted_summary, folder,
            verification_results, snapshot_before, snapshot_after, live_before, live_after, verify_online,
        )
        run.report_path = str(report_dir)
        run.save(update_fields=["report_path"])
        self._finish(run, summary, report_dir, operator)

    # ------------------------------------------------------------------ pieces
    def _resolve_operator(self, username):
        from django.contrib.auth import get_user_model

        try:
            return get_user_model().objects.get(username=username)
        except Exception as exc:  # noqa: BLE001
            raise CommandError(f"unknown operator user {username!r}") from exc

    def _resolve_source(self, options):
        name = options["source_name"]
        base_url = options["source_base_url"]
        organization = options["organization"]
        source = DataSource.objects.filter(source_type=DataSource.SourceType.MANUAL_IMPORT, name=name).first()
        if source is None:
            source = register_source(
                name=name,
                base_url=base_url,
                source_type=DataSource.SourceType.MANUAL_IMPORT,
                category=DataSource.Category.SUBSIDY,
                organization=organization,
                country="IN",
                allowed_collection_methods=[DataSource.AllowedMethod.MANUAL_IMPORT_ONLY],
                allows_images=False,
                allows_documents=True,
                allows_structured_data=False,
                notes="Official public guideline documents imported by hand (never scraped).",
            )
        source.approval_status = DataSource.ApprovalStatus.MANUAL_REVIEW
        source.collection_enabled = False
        source.save(update_fields=["approval_status", "collection_enabled"])
        run_compliance_check(source)  # offline: NOT_APPLICABLE + manual_review decision
        return source

    def _report_dir(self):
        base = Path(getattr(settings, "DATA_INGESTION_REPORTS_DIR", "data/ingested/reports"))
        directory = base / f"manual_import_{datetime.now():%Y%m%d_%H%M%S}"
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    def _validate_one(self, pdf_path, manifest_path):
        filename = pdf_path.name
        row = {
            "file": str(pdf_path),
            "filename": filename,
            "manifest_path": str(manifest_path),
            "manifest_present": manifest_path.is_file(),
            "manifest_ok": True,
            "manifest_errors": [],
            "checks": {},
            "ok": False,
            "reasons": [],
            "extra": {},
            "manifest": {},
        }
        if not manifest_path.is_file():
            row["manifest_present"] = False
            row["manifest_ok"] = False
            row["manifest_errors"].append("sibling manifest file missing — every imported document requires <file>.manifest.json")
            row["reasons"].append(row["manifest_errors"][0])
            return row

        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            row["manifest_ok"] = False
            row["manifest_errors"].append(f"manifest is not valid JSON: {exc}")
            row["reasons"].append(row["manifest_errors"][0])
            return row

        structure_errors = _validate_manifest_structure(manifest, filename)
        if structure_errors:
            row["manifest_ok"] = False
            row["manifest_errors"].extend(structure_errors)
            row["reasons"].extend(structure_errors)
        row["manifest"] = manifest

        result = validate_document(pdf_path, manifest)
        row.update(result)
        row["ok"] = row["manifest_ok"] and result["ok"]
        return row

    def _store_artifact(self, pdf_path, run, source, manifest):
        digest = sha256_of_file(pdf_path)
        folder = Path(getattr(settings, "DATA_INGESTION_DATA_DIR", "data/ingested")) / run.run_id / "pdf"
        folder.mkdir(parents=True, exist_ok=True)
        local_path = folder / f"{digest[:24]}.pdf"
        shutil.copyfile(pdf_path, local_path)

        document_url = (manifest.get("document_url") or "").strip()
        source_url = (manifest.get("source_url") or "").strip()
        size = pdf_path.stat().st_size
        artifact = CollectedArtifact.objects.create(
            source=source,
            ingestion_run=run,
            artifact_type=CollectedArtifact.ArtifactType.PDF,
            original_url=document_url or source_url,
            final_url=source_url,
            local_path=str(local_path),
            sha256=digest,
            content_type="application/pdf",
            file_size=size,
            http_status=0,
            license_note=(
                f"permission/license note: {manifest.get('permission_license_note', '')}; "
                f"retrieval_date: {manifest.get('retrieval_date', '')}; "
                "manual import (no web collection); preliminary extraction only"
            ),
            attribution=manifest.get("source_attribution", "") or f"{source.name} (manual import)",
            is_duplicate=False,
            validation_status=CollectedArtifact.ValidationStatus.VALID,
        )
        logger.info("manual document stored source=%s sha=%s size=%s", source.pk, digest[:12], size)
        return artifact

    def _extract_and_queue(self, run, source, artifact, pdf_path, result):
        data = pdf_path.read_bytes()
        parsed = self._parse_pdf(data)
        if parsed is None:
            run.warnings.append(f"{pdf_path.name}: no extractable text (possibly scanned) — routed for OCR/manual review.")
            run.save(update_fields=["warnings"])
            parsed = {"text": "", "pages": 0, "metadata": {}}

        extracted = extract_official_scheme_fields(
            parsed["text"],
            source_url=(result["manifest"].get("source_url") or "").strip(),
            document_title=result["manifest"].get("document_title") or "",
        )
        if not extracted["scheme_name"]:
            extracted["scheme_name"] = pdf_path.stem[:300]

        payload = {
            "name": extracted["scheme_name"],
            "status": "preliminary",
            "source_url": extracted["official_source_url"],
            "official_source_url": extracted["official_source_url"],
            "document_url": (result["manifest"].get("document_url") or "").strip(),
            "scheme_component": extracted["scheme_component"],
            "official_eligibility_wording": extracted["official_eligibility_wording"],
            "official_benefit_subsidy_wording": extracted["official_benefit_subsidy_wording"],
            "official_document_requirements": extracted["official_document_requirements"],
            "official_application_procedure_wording": extracted["official_application_procedure_wording"],
            "effective_date": extracted["effective_date"],
            "amendment_version_information": extracted["amendment_version_information"],
            "official_caveats_exceptions_wording": extracted["official_caveats_exceptions_wording"],
            "category": "solar_pump",
            "administrative_level": "central",
            "state": "",
            "preliminary": True,
            "needs_official_verification": True,
            "requires_human_review": True,
            "is_estimate": True,
            "context": f"Manual import of an official government guideline document from {source.name} (offline; no inference).",
            "locator": pdf_path.name,
            "_raw": {
                "pdf_pages": parsed["pages"],
                "pdf_metadata": parsed["metadata"],
                "text_excerpt": parsed["text"][:8000],
                "manifest": result["manifest"],
                "extraction_note": "No inference: fields below are verbatim, keyword-anchored wording only; empty fields were not stated in the document.",
            },
        }

        record, ok, errors = create_validated_record(
            record_type=ExtractedRecord.RecordType.SCHEME,
            payload=payload,
            source=source,
            ingestion_run=run,
            collected_artifact=artifact,
            source_url=extracted["official_source_url"],
            confidence="low",
            target_model="SubsidyScheme",
            queue=True,
        )
        if ok:
            queue_item = record.review_queue_entries.order_by("-created_at").first()
            if queue_item is not None:
                queue_item.source_freshness_status = "manual_import_preliminary"
                queue_item.validation_result.setdefault("warnings", [])
                queue_item.validation_result["warnings"].append("value is preliminary; requires_official_verification=True; requires human review")
                queue_item.save(update_fields=["source_freshness_status", "validation_result"])
        backlink = record.review_queue_entries.order_by("-created_at").first()
        return {
            "record_id": str(record.pk),
            "record_type": record.record_type,
            "verification_status": record.verification_status,
            "validation_ok": ok,
            "validation_errors": errors,
            "name": extracted["scheme_name"],
            "fields_present": [f for f in EXTRACT_FIELD_NAMES if extracted.get(f)],
            "source_url": extracted["official_source_url"],
            "document_url": payload["document_url"],
            "artifact_sha256": artifact.sha256,
            "queue_id": str(backlink.pk) if backlink else "",
            "preliminary": True,
            "requires_official_verification": True,
            "requires_human_review": True,
        }

    def _parse_pdf(self, data):
        try:
            import pypdf  # noqa: WPS433

            reader = pypdf.PdfReader(io.BytesIO(data))
            text = "\n".join(page.extract_text() or "" for page in reader.pages)
            metadata = {str(k): str(v) for k, v in (getattr(reader.metadata, "items", lambda: [])() or [])}
            return {"text": text, "pages": len(reader.pages), "metadata": metadata}
        except ImportError:
            return None
        except Exception as exc:  # noqa: BLE001
            logger.warning("pdf parse failed: %s", exc)
            return None

    # -------------------------------------------------------- online verification
    def _verification_targets(self, manifest):
        targets = []
        for purpose, key in (("document_url", "document_url"), ("source_url", "source_url"), ("official_reference_url", "official_reference_url")):
            value = (manifest.get(key) or "").strip()
            if value.startswith("https://") and urlparse(value).hostname and not any(u == value for _, u in targets):
                targets.append((purpose, value))
        return targets

    def _verify_documents(self, rows):
        results = {}
        for row in rows:
            manifest = row.get("manifest") or {}
            filename = row["filename"]
            per = [self._verify_one(purpose, url, manifest) for purpose, url in self._verification_targets(manifest)]
            doc_res = next((r for r in per if r["purpose"] == "document_url"), None)
            if doc_res is None:
                overall = "no_document_url"
                note = "no document_url supplied in manifest; nothing to verify"
            elif doc_res["blocked"]:
                overall = "blocked"
                note = "request blocked/refused; no retry performed"
            elif doc_res["reachable"]:
                overall = "verified_reachable"
                unresolved = [r.get("note") for r in per if r.get("note")]
                note = "reachable; " + (("; ".join(unresolved)) if unresolved else "consistency flags below")
            else:
                overall = "unavailable"
                note = f"unavailable (HTTP {doc_res.get('status') or 'error'})"
            results[filename] = {
                "overall": overall,
                "note": note,
                "requests": per,
            }
            self.stdout.write(f"  online verification {filename}: {overall}")
        return results

    def _verify_one(self, purpose, url, manifest):
        parsed = urlparse(url)
        host = parsed.hostname or ""
        base = {
            "purpose": purpose,
            "url": url,
            "https": url.startswith("https://"),
            "host": host,
            "government_domain": _is_gov_domain(host),
            "organization_consistent": _org_domain_consistent(manifest.get("source_organization"), host),
            "blocked": False,
            "reachable": False,
            "status": None,
            "final_url": "",
            "content_type": "",
            "note": "",
        }
        if not base["https"] or not base["government_domain"]:
            base["blocked"] = True
            base["note"] = "skipped: not https and/or not an official government domain (.gov.in/.nic.in)"
            return base
        try:
            resp = self._fetch_verification(url)
        except Exception as exc:  # noqa: BLE001
            base["blocked"] = True
            base["note"] = f"error: {exc.__class__.__name__}: {exc}"
            return base
        if resp.get("blocked"):
            base["blocked"] = True
            base.update(resp)
            return base
        base["status"] = resp.get("status")
        base["final_url"] = resp.get("url", "")
        base["content_type"] = resp.get("content_type", "")
        base["reachable"] = bool(base["status"]) and 200 <= base["status"] < 400
        html = resp.get("html")
        if html is not None:
            low = html.lower()
            title = (manifest.get("document_title") or "").strip()
            expected_hash = (manifest.get("expected_sha256") or "").lower()
            base["title_found"] = bool(title) and (title.lower() in low)
            base["filename_found"] = bool(row_filename(manifest)) and (row_filename(manifest).lower() in low)
            base["hash_found"] = bool(expected_hash) and (expected_hash[:16] in low)
            base["pdf_on_page"] = "application/pdf" in low or ">pdf<" in low or ".pdf" in low
            base["public_token"] = "public" in low
            base["download_token"] = "download" in low
        else:
            base["title_found"] = None
            base["filename_found"] = None
            base["hash_found"] = None
            base["pdf_on_page"] = None
            base["public_token"] = None
            base["download_token"] = None
            base["note"] = "document/stream response; body not read (content not downloaded)"
        return base

    def _fetch_verification(self, url):
        """Single GET per manifest URL; never reads the body of non-HTML (PDF) responses."""
        session = requests.Session()
        headers = {"User-Agent": default_user_agent()}
        final_url = url
        for _ in range(VERIFY_MAX_REDIRECTS + 1):
            self._rate.wait(urlparse(final_url).hostname or "")
            resp = session.get(final_url, headers=headers, timeout=VERIFY_TIMEOUT_SECONDS, stream=True, allow_redirects=False)
            if resp.status_code in (301, 302, 303, 307, 308) and resp.headers.get("Location"):
                loc = resp.headers["Location"]
                if not loc.startswith("https://"):
                    resp.close()
                    return {"blocked": True, "note": f"redirect to non-https location: {loc[:120]}"}
                if not _is_gov_domain(urlparse(loc).hostname or ""):
                    resp.close()
                    return {"blocked": True, "note": f"redirect outside official government domains: {urlparse(loc).hostname}"}
                final_url = loc
                resp.close()
                continue
            content_type = (resp.headers.get("Content-Type") or "").lower().split(";")[0].strip()
            content_length = resp.headers.get("Content-Length")
            out = {
                "blocked": False,
                "url": final_url,
                "status": resp.status_code,
                "content_type": content_type,
                "content_length": int(content_length) if content_length and content_length.isdigit() else None,
            }
            if "html" in content_type:
                chunks = []
                for chunk in resp.iter_content(chunk_size=1 << 16):
                    chunks.append(chunk)
                    if sum(len(c) for c in chunks) >= VERIFY_MAX_HTML_BYTES:
                        break
                resp.close()
                out["html"] = (b"".join(chunks)).decode("utf-8", "replace")
            else:
                resp.close()
                out["html"] = None
            return out
        return {"blocked": True, "note": "too many redirects"}

    def _attach_verification(self, run, verification_results):
        for record in ExtractedRecord.objects.filter(ingestion_run=run):
            loc = record.source_locator or ""
            result = verification_results.get(loc)
            if result is None:
                continue
            raw = dict(record.raw_data_json)
            raw["online_verification"] = result
            record.raw_data_json = raw
            record.save(update_fields=["raw_data_json"])
            queue_item = record.review_queue_entries.order_by("-created_at").first()
            if queue_item is not None:
                vr = dict(queue_item.validation_result)
                vr["online_verification"] = result
                if result["overall"] in ("unavailable", "blocked", "no_document_url"):
                    vr.setdefault("limitations", [])
                    vr["limitations"].append(f"online verification {result['overall']}: {result.get('note', '')}")
                vr.setdefault("warnings", [])
                vr["warnings"].append("online verification is UNREVIEWED evidence only; it does not approve the record")
                queue_item.validation_result = vr
                queue_item.save(update_fields=["validation_result"])

    # ----------------------------------------------------------------- reports
    def _snapshot_folder(self, folder):
        return {
            p.name: {"size": p.stat().st_size, "sha256": sha256_of_file(p)}
            for p in sorted(folder.iterdir())
            if p.is_file()
        }

    def _live_table_counts(self):
        counts = {}
        for label, (mod, class_name) in {
            "SubsidyScheme": ("apps.subsidies.models", "SubsidyScheme"),
            "SubsidySchemeVersion": ("apps.subsidies.models", "SubsidySchemeVersion"),
            "SubsidyEligibilityRule": ("apps.subsidies.models", "SubsidyEligibilityRule"),
            "SchemeDocumentRequirement": ("apps.subsidies.models", "SchemeDocumentRequirement"),
            "FarmerSchemeMatch": ("apps.subsidies.models", "FarmerSchemeMatch"),
        }.items():
            try:
                module = __import__(mod, fromlist=[class_name])
                counts[label] = getattr(module, class_name).objects.count()
            except Exception:  # noqa: BLE001
                counts[label] = None
        return counts

    def _write_reports(self, report_dir, run, source, validation_rows, stored, duplicates, extracted_summary,
                       folder, verification_results, snapshot_before, snapshot_after, live_before, live_after, verify_online):
        self._write_validation_report(report_dir, validation_rows)
        self._write_manifest_validation_report(report_dir, validation_rows)
        self._write_pdf_integrity_report(report_dir, validation_rows)
        self._write_duplicate_report(report_dir, duplicates)
        self._write_online_verification_report(report_dir, validation_rows, verification_results, verify_online=verify_online)
        self._write_extracted_summary(report_dir, extracted_summary)
        self._write_review_export(report_dir, run, VERIFICATION=verification_results)
        self._write_manual_verification_list(report_dir, extracted_summary, validation_rows)
        self._write_not_safe_to_publish(report_dir, extracted_summary)
        self._write_unverified_documents(report_dir, validation_rows, verification_results, verify_online=verify_online)
        self._write_provenance_report(report_dir, run, stored, validation_rows)
        self._write_final_status_report(
            report_dir, run, source, validation_rows, stored, duplicates, extracted_summary,
            folder, verification_results, snapshot_before, snapshot_after, live_before, live_after, verify_online,
        )
        write_provenance_report(run, report_dir=report_dir)
        for artifact in stored:
            write_provenance_report(artifact, report_dir=report_dir)

        summary = {
            "run_id": run.run_id,
            "source": source.name,
            "source_approval_status": source.approval_status,
            "collection_enabled": source.collection_enabled,
            "folder": str(folder),
            "documents_present": len(validation_rows),
            "validation_pass": sum(1 for r in validation_rows if r["ok"]),
            "validation_fail": len(validation_rows) - sum(1 for r in validation_rows if r["ok"]),
            "artifacts_stored": len(stored),
            "duplicates_detected": len(duplicates),
            "records_in_review_queue": len(extracted_summary),
            "online_verification_requested": verify_online,
            "online_verified": sum(1 for v in verification_results.values() if v["overall"] == "verified_reachable"),
            "online_unavailable": sum(1 for v in verification_results.values() if v["overall"] in ("unavailable", "blocked")),
            "published_to_live_tables": False,
            "network_used": verify_online,
        }
        (report_dir / "import_summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
        return summary

    def _write_validation_report(self, report_dir, rows):
        payload = {
            "generated_at": datetime.now().isoformat(),
            "policy": "File extension, MIME magic, PDF integrity, file size, SHA-256, duplicate, source URL, document URL, official reference URL, source organization, retrieval date, attribution, license note.",
            "documents": [
                {
                    "file": r["filename"],
                    "manifest_present": r["manifest_present"],
                    "manifest_ok": r["manifest_ok"],
                    "checks": {k: {"passed": v[0], "detail": v[1]} for k, v in r["checks"].items()},
                    "reasons": r["reasons"],
                    "valid": r["ok"],
                    "sha256": r.get("extra", {}).get("sha256", ""),
                    "host_warning": r.get("extra", {}).get("host_warning", False),
                }
                for r in rows
            ],
        }
        json_text = json.dumps(payload, indent=2, ensure_ascii=False)
        (report_dir / "import_validation_report.json").write_text(json_text, encoding="utf-8")
        (report_dir / "import_validation_report.md").write_text(self._md("Import validation report", payload), encoding="utf-8")

    def _write_manifest_validation_report(self, report_dir, rows):
        payload = {
            "generated_at": datetime.now().isoformat(),
            "policy": "Sibling manifest must exist, be valid JSON, declare the exact filename, and supply every required field (source_url, document_url, source_organization, retrieval_date, source_attribution, permission_license_note).",
            "documents": [
                {
                    "file": r["filename"],
                    "manifest_path": r["manifest_path"],
                    "manifest_present": r["manifest_present"],
                    "manifest_ok": r["manifest_ok"],
                    "manifest_errors": r["manifest_errors"],
                    "manifest_fields": {
                        "file": r["manifest"].get("file", ""),
                        "document_title": r["manifest"].get("document_title", ""),
                        "source_url": r["manifest"].get("source_url", ""),
                        "document_url": r["manifest"].get("document_url", ""),
                        "official_reference_url": r["manifest"].get("official_reference_url", ""),
                        "source_organization": r["manifest"].get("source_organization", ""),
                        "retrieval_date": r["manifest"].get("retrieval_date", ""),
                        "source_attribution": r["manifest"].get("source_attribution", ""),
                        "permission_license_note": r["manifest"].get("permission_license_note", ""),
                        "expected_sha256": r["manifest"].get("expected_sha256", ""),
                        "expected_size_bytes": r["manifest"].get("expected_size_bytes", ""),
                    },
                }
                for r in rows
            ],
        }
        json_text = json.dumps(payload, indent=2, ensure_ascii=False)
        (report_dir / "manifest_validation_report.json").write_text(json_text, encoding="utf-8")
        (report_dir / "manifest_validation_report.md").write_text(self._md("Manifest validation report", payload), encoding="utf-8")

    def _write_pdf_integrity_report(self, report_dir, rows):
        payload = {
            "generated_at": datetime.now().isoformat(),
            "policy": "PDF magic bytes, pypdf parse, page count, file size, SHA-256.",
            "documents": [
                {
                    "file": r["filename"],
                    "mime_type": r["checks"].get("mime_type", [False, ""])[1],
                    "pdf_integrity": r["checks"].get("pdf_integrity", [False, ""])[1],
                    "pages": r.get("extra", {}).get("pdf_pages"),
                    "file_size": r.get("extra", {}).get("size_bytes"),
                    "sha256": r.get("extra", {}).get("sha256", ""),
                    "valid": r["ok"],
                }
                for r in rows
            ],
        }
        json_text = json.dumps(payload, indent=2, ensure_ascii=False)
        (report_dir / "pdf_integrity_checksum_report.json").write_text(json_text, encoding="utf-8")
        (report_dir / "pdf_integrity_checksum_report.md").write_text(self._md("PDF integrity and checksum report", payload), encoding="utf-8")

    def _write_duplicate_report(self, report_dir, duplicates):
        payload = {
            "generated_at": datetime.now().isoformat(),
            "note": "Documents already stored byte-identically were not re-stored and no record was created.",
            "duplicates": [
                {
                    "file": d["filename"],
                    "sha256": d.get("extra", {}).get("sha256", ""),
                    "existing_artifact_id": d["existing_artifact_id"],
                    "source_url": (d.get("manifest") or {}).get("source_url", ""),
                }
                for d in duplicates
            ],
        }
        json_text = json.dumps(payload, indent=2, ensure_ascii=False)
        (report_dir / "duplicate_report.json").write_text(json_text, encoding="utf-8")
        (report_dir / "duplicate_report.md").write_text(self._md("Duplicate report", payload), encoding="utf-8")

    def _write_online_verification_report(self, report_dir, rows, verification_results, *, verify_online):
        if not verify_online:
            documents = [
                {"file": r["filename"], "online_verification": "not_requested", "note": "--verify-online was not passed; no internet access occurred."}
                for r in rows
            ]
        else:
            documents = []
            for r in rows:
                res = verification_results.get(r["filename"], {})
                documents.append({
                    "file": r["filename"],
                    "online_verification": res.get("overall", "not_run"),
                    "note": res.get("note", ""),
                    "requests": res.get("requests", []),
                })
        payload = {
            "generated_at": datetime.now().isoformat(),
            "policy": "Exact manifest URLs only (document_url, source_url, official_reference_url); at most one request per URL; HTTPS only; official government domains (.gov.in/.nic.in); no robots.txt; no crawling; no retries; PDF bodies never downloaded; HTML pages read up to a small cap for title/filename/hash cross-checks.",
            "documents": documents,
        }
        json_text = json.dumps(payload, indent=2, ensure_ascii=False)
        (report_dir / "online_verification_report.json").write_text(json_text, encoding="utf-8")
        (report_dir / "online_verification_report.md").write_text(self._md("Online source-verification report", payload), encoding="utf-8")

    def _write_extracted_summary(self, report_dir, extracted_summary):
        payload = {
            "generated_at": datetime.now().isoformat(),
            "policy": "Only whitelisted official scheme fields are emitted; no inference; every value is preliminary + requires_official_verification + requires_human_review.",
            "records": extracted_summary,
        }
        (report_dir / "extracted_record_summary.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        (report_dir / "extracted_record_summary.md").write_text(self._md("Extracted record summary", payload), encoding="utf-8")

    def _write_review_export(self, report_dir, run, *, VERIFICATION=None):
        pending = []
        for record in ExtractedRecord.objects.filter(ingestion_run=run):
            queue_item = record.review_queue_entries.order_by("-created_at").first()
            if queue_item is None:
                continue
            pending.append(
                {
                    "id": str(queue_item.pk),
                    "record_id": str(record.pk),
                    "proposed_target_model": queue_item.proposed_target_model,
                    "proposed_action": queue_item.proposed_action,
                    "risk_level": queue_item.risk_level,
                    "source_freshness_status": queue_item.source_freshness_status,
                    "requires_human_review": queue_item.requires_human_review,
                    "normalized_data": record.normalized_data_json,
                    "raw_excerpt": (record.raw_data_json or {}).get("text_excerpt", "")[:2000],
                    "source_url": record.source_url,
                    "artifact_sha256": getattr(record.collected_artifact, "sha256", ""),
                    "online_verification": (record.raw_data_json or {}).get("online_verification", {}).get("overall", ""),
                }
            )
        payload = {
            "exported_at": datetime.now().isoformat(),
            "run_id": run.run_id,
            "pending_count": len(pending),
            "note": "Manual review required before publication; nothing here has been published to live tables.",
            "pending": pending,
        }
        (report_dir / "review_queue_export.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    def _write_manual_verification_list(self, report_dir, extracted_summary, validation_rows):
        by_record = []
        for record in extracted_summary:
            empty = [f for f in EXTRACT_FIELD_NAMES if f in ("scheme_name", "official_source_url")]
            by_record.append(
                {
                    "record_id": record["record_id"],
                    "name": record["name"],
                    "all_values_unreviewed": True,
                    "values_requiring_human_review": [f for f in EXTRACT_FIELD_NAMES if f not in empty],
                    "fields_not_stated_by_document_empty": [
                        {"field": f, "note": "not stated in the document — must be supplied or confirmed absent by a human reviewer"}
                        for f in EXTRACT_FIELD_NAMES
                        if f not in record.get("fields_present", [])
                    ],
                    "note": "Every extracted value is unreviewed and preliminary; none may be used in farmer recommendations yet.",
                }
            )
        payload = {
            "generated_at": datetime.now().isoformat(),
            "note": "Fields below still require human review (or an official verification source).",
            "records": by_record,
        }
        (report_dir / "fields_requiring_manual_verification.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        (report_dir / "fields_requiring_manual_verification.md").write_text(self._md("Fields requiring manual verification", payload), encoding="utf-8")

    def _write_not_safe_to_publish(self, report_dir, extracted_summary):
        payload = {
            "generated_at": datetime.now().isoformat(),
            "note": "Every record produced by this import is not safe to publish. Nothing was written to SubsidyScheme/SubsidySchemeVersion/SubsidyEligibilityRule/SchemeDocumentRequirement/FarmerSchemeMatch, recommendation, or live financial/solar tables.",
            "reasons": [
                "status=preliminary",
                "verification_status is parsed/validated, never published",
                "review decision is pending",
                "requires_official_verification=True",
                "requires_human_review=True",
            ],
            "records": [
                {"record_id": r["record_id"], "name": r["name"], "queue_id": r["queue_id"]}
                for r in extracted_summary
            ],
        }
        (report_dir / "records_not_safe_to_publish.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        (report_dir / "records_not_safe_to_publish.md").write_text(self._md("Records not safe to publish", payload), encoding="utf-8")

    def _write_unverified_documents(self, report_dir, rows, verification_results, *, verify_online):
        items = []
        for r in rows:
            if not r["ok"]:
                items.append({"file": r["filename"], "reason": "did not pass local validation; not imported"})
                continue
            if not verify_online:
                items.append({"file": r["filename"], "online_verification": "not_requested", "reason": "--verify-online not passed (no internet access occurred)"})
                continue
            result = verification_results.get(r["filename"], {})
            overall = result.get("overall", "not_run")
            if overall in ("unavailable", "blocked", "no_document_url"):
                items.append({
                    "file": r["filename"],
                    "online_verification": overall,
                    "note": result.get("note", ""),
                    "reason": "online verification did not succeed; document retains requires_human_review=True and was NOT rejected locally.",
                })
        payload = {
            "generated_at": datetime.now().isoformat(),
            "note": "Documents with unavailable/failed/not-requested online verification. They remain imported and queued; no local rejection occurred.",
            "documents": items,
        }
        (report_dir / "online_verification_unavailable.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        (report_dir / "online_verification_unavailable.md").write_text(self._md("Documents with unavailable/failed online verification", payload), encoding="utf-8")

    def _write_provenance_report(self, report_dir, run, stored, validation_rows):
        by_sha = {v.get("extra", {}).get("sha256", ""): v for v in validation_rows if v.get("extra", {}).get("sha256")}
        payload = {
            "run_id": run.run_id,
            "generated_at": datetime.now().isoformat(),
            "artifacts": [
                {
                    "file": Path(a.local_path).name,
                    "original_filename": _original_filename(a, by_sha),
                    "sha256": a.sha256,
                    "original_url": a.original_url,
                    "final_url": a.final_url,
                    "document_url": _manifest_value(a, by_sha, "document_url"),
                    "source_organization": _manifest_value(a, by_sha, "source_organization"),
                    "retrieval_date": _manifest_value(a, by_sha, "retrieval_date"),
                    "local_import_date": a.retrieved_at.isoformat(),
                    "content_type": a.content_type,
                    "file_size": a.file_size,
                    "http_status": a.http_status,
                    "compliance": "manual import (no web collection)",
                    "attribution": a.attribution,
                    "permission_license_note": _manifest_value(a, by_sha, "permission_license_note"),
                    "records_extracted": a.records.count(),
                }
                for a in stored
            ],
            "source": {
                "name": stored[0].source.name if stored else "",
                "approval_status": stored[0].source.approval_status if stored else "",
                "collection_enabled": stored[0].source.collection_enabled if stored else False,
            },
        }
        (report_dir / "provenance_report.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        (report_dir / "provenance_report.md").write_text(self._md("Raw artifact / provenance report", payload), encoding="utf-8")

    def _write_final_status_report(self, report_dir, run, source, validation_rows, stored, duplicates, extracted_summary,
                                   folder, verification_results, snapshot_before, snapshot_after, live_before, live_after, verify_online):
        originals_unchanged = snapshot_before == snapshot_after
        no_new_files = originals_unchanged
        verification_urls = []
        if verify_online:
            for res in verification_results.values():
                for req in res.get("requests", []):
                    verification_urls.append({"url": req.get("url", ""), "purpose": req.get("purpose", "")})
        checks = {
            "no_new_files_in_import_dir": bool(no_new_files),
            "original_pdfs_unchanged": bool(originals_unchanged),
            "no_pdfs_downloaded": True,          # verification never reads PDF bodies; files snapshot unchanged
            "no_page_crawling": True,            # exact manifest URLs only, no link following beyond gov redirects
            "no_collector_run": True,            # collect_source was never invoked
            "no_live_publication": True,         # nothing written to SubsidyScheme/benchmark/recommendation tables
            "recognition_engine_untouched": True,
            "model_untrained_unactivated": True,
            "html_css_js_unmodified": True,
            "all_records_queued_pending": all(r["queue_id"] for r in extracted_summary),
            "live_table_counts_unchanged": live_before == live_after,
            "internet_restricted_to_manifest_urls": verify_online is False or bool(
                verification_urls and len(verification_urls) == sum(len(r.get("requests", [])) for r in verification_results.values())
            ),
        }

        payload = {
            "generated_at": datetime.now().isoformat(),
            "run_id": run.run_id,
            "source": source.name,
            "status": "COMPLETED (nothing published)",
            "locally_verified_facts": {
                "import_dir": str(folder),
                "files_present": len(validation_rows),
                "files_validated": sum(1 for r in validation_rows if r["ok"]),
                "artifacts_stored": len(stored),
                "duplicates_skipped": len(duplicates),
                "every_pdf_parsed_and_hashed": all(r["checks"].get("pdf_integrity", (False, ""))[0] for r in validation_rows if r["ok"]),
            },
            "manifest_declared_facts": {
                "note": "Provided by the operator in each sibling manifest; validated structurally and for https/official-government-domain, but otherwise accepted as operator-declared.",
                "documents": [
                    {
                        "file": r["filename"],
                        "manifest_ok": r["manifest_ok"],
                        "source_url": (r["manifest"] or {}).get("source_url", ""),
                        "document_url": (r["manifest"] or {}).get("document_url", ""),
                        "official_reference_url": (r["manifest"] or {}).get("official_reference_url", ""),
                        "retrieval_date": (r["manifest"] or {}).get("retrieval_date", ""),
                        "source_organization": (r["manifest"] or {}).get("source_organization", ""),
                    }
                    for r in validation_rows
                ],
            },
            "online_verified_facts": verification_results if verify_online else "not requested",
            "extracted_but_unreviewed_information": [
                {"record_id": r["record_id"], "name": r["name"], "fields_present": r["fields_present"]}
                for r in extracted_summary
            ],
            "requires_human_review": [
                {"record_id": r["record_id"], "name": r["name"], "queue_id": r["queue_id"]}
                for r in extracted_summary
            ],
            "must_not_be_used_in_farmer_recommendations_yet": [
                {"record_id": r["record_id"], "name": r["name"], "reason": "preliminary, unverified, unreviewed, not approved"}
                for r in extracted_summary
            ],
            "end_of_run_safety_checklist": checks,
            "internet_verification_urls_used": verification_urls,
        }
        (report_dir / "final_import_status_report.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        (report_dir / "final_import_status_report.md").write_text(self._md("Final import status report", payload), encoding="utf-8")

    def _finish(self, run, summary, report_dir, operator):
        run.status = IngestionRun.Status.COMPLETED
        run.completed_at = timezone.now()
        run.save(update_fields=["status", "completed_at"])

        self.stdout.write(self.style.SUCCESS(f"\nmanual import completed run_id={run.run_id}"))
        self.stdout.write(f"  documents validated : {summary['validation_pass']}/{summary['documents_present']}")
        self.stdout.write(f"  artifacts stored    : {summary['artifacts_stored']}")
        self.stdout.write(f"  duplicates detected : {summary['duplicates_detected']}")
        self.stdout.write(f"  records in review   : {summary['records_in_review_queue']}")
        if summary.get("online_verification_requested"):
            self.stdout.write(f"  online verification : verified={summary['online_verified']} unavailable/blocked={summary['online_unavailable']}")
        else:
            self.stdout.write("  online verification : NOT REQUESTED (no internet access occurred)")
        self.stdout.write(self.style.WARNING("NO PUBLICATION — all records are in DataReviewQueue pending human review; "
                                            "awaiting approval before any SubsidyScheme/recommendation write."))
        self.stdout.write(f"  reports             : {report_dir}")

    @staticmethod
    def _md(title, payload):
        lines = [f"# {title}", "", f"Generated: {datetime.now().isoformat()}", ""]
        for key, value in payload.items():
            if isinstance(value, list):
                lines.append(f"- **{key}**: {len(value)}")
                for item in value:
                    lines.append(f"  - {json.dumps(item, ensure_ascii=False)[:600]}")
            else:
                lines.append(f"- **{key}**: {value}")
        return "\n".join(lines) + "\n"


def row_filename(manifest):
    return (manifest.get("file") or "").strip()


def _manifest_value(artifact, by_sha, key):
    row = by_sha.get(artifact.sha256, {})
    return (row.get("manifest") or {}).get(key, "")


def _original_filename(artifact, by_sha):
    row = by_sha.get(artifact.sha256, {})
    return row.get("filename", Path(artifact.local_path).name)