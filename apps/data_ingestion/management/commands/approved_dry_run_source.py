"""Approved limited compliance review + sandboxed dry-run ingestion (PM-KUSUM).

ONE-TIME OPERATOR-APPROVED RUN. This command performs a *live* compliance
review and — only if that compliance check ALLOWS collection — downloads at
most five publicly accessible official scheme pages/documents from the
approved PM-KUSUM domain, preserves every raw artifact with full provenance,
extracts only scheme-related structured fields, and routes every record
through ``DataReviewQueue``.

Hard invariants enforced on every run:

* the target source must be the explicitly approved PM-KUSUM portal
  (``https://pmkusum.mnre.gov.in/``); any other source is refused;
* network must be explicitly enabled for this process
  (``DATA_INGESTION_NETWORK_ALLOWED=true``) — enabled only for the approved
  single-run scope; all hosts are still restricted to the PM-KUSUM host;
* HTTPS only; same-host only; no IP literals / loopback /
  private-address / non-http(s) targets (``urlutils`` gates);
* max 5 public pages/documents, max 20 MB total, per-domain rate limiter
  >= 5 s between requests, no parallel requests, no recursive crawling,
  no external domains, no image datasets (image URLs and image/* responses
  are skipped);
* if robots.txt is missing / ambiguous / restrictive, or a login / CAPTCHA /
  paywall / OTP wall is detected, collection is **blocked** — a clear
  compliance-blocked report is produced and the run stops (no retry, no
  bypass);
* nothing is ever published to ``SubsidyScheme``/``SubsidySchemeVersion`` or
  the recommendation engine: extraction terminates at ``DataReviewQueue``
  and every value is marked ``preliminary`` + ``requires_official_verification``
  + ``requires_human_review``.

Reports (JSON + Markdown) are written to
``data/ingested/reports/pmkusum_approved_dry_run_<timestamp>/`` and the run
stops — the operator must issue a new approval before any further step.
"""
import json
import logging
import re
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.data_ingestion.models import (
    CollectedArtifact,
    DataReviewQueue,
    DataSource,
    ExtractedRecord,
    IngestionRun,
    SourceComplianceCheck,
)
from apps.data_ingestion.services.hashing import sha256_of_bytes
from apps.data_ingestion.services.http_client import (
    NetworkDisabledError,
    ResponseTooLarge,
    SafeHTTPClient,
)
from apps.data_ingestion.services.provenance import write_provenance_report
from apps.data_ingestion.services.record_factory import create_validated_record
from apps.data_ingestion.services.robots import evaluate_robots, robots_is_unambiguous, robots_url_for
from apps.data_ingestion.services.source_registry import SourceRegistryError
from apps.data_ingestion.services.terms import evaluate_terms
from apps.data_ingestion.services.urlutils import (
    UnsafeURL,
    validate_scheme,
    validate_target_url,
)

logger = logging.getLogger("khetsathi.audit")

PM_KUSUM_BASE = "https://pmkusum.mnre.gov.in/"
ALLOWED_HOST = "pmkusum.mnre.gov.in"
RUN_LABEL = "pmkusum-approved-dry-run"

MAX_ARTIFACTS = 5
MAX_TOTAL_BYTES = 20 * 1024 * 1024
MIN_REQUEST_GAP_SECONDS = 5.0
MAX_EVIDENCE_SIZE = 8 * 1024 * 1024

SIMILAR_CONTENT_KEYWORDS = (
    "guideline", "guidelines", "document", "component", "solar", "pump",
    "scheme", "eligible", "benefit", "subsidy", "application", "checklist",
    "format", "model", "component-a", "component-b", "component-c",
)
EXCLUDE_PATH_KEYWORDS = (
    "login", "logout", "signin", "signup", "register", "otp", "password",
    "forgot", "track", "dashboard", "my", "profile", "account",
)
POLICY_KEYWORDS = (
    "terms", "privacy", "policy", "copyright", "usage", "disclaimer", "legal",
)
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".bmp", ".ico"}

RE_DATE = re.compile(r"\b(0?[1-9]|[12]\d|3[01])[/-](0?[1-9]|1[0-2])[/-](\d{4})\b")
RE_MONTH_DAY_YEAR = re.compile(
    r"\b(\d{1,2})\s+(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may"
    r"|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?"
    r"|dec(?:ember)?)\s+(\d{4})\b",
    re.IGNORECASE,
)


class ComplianceBlocked(Exception):
    """Raised when the compliance review forbids automated collection."""

    def __init__(self, message, evidence=None):
        super().__init__(message)
        self.evidence = evidence or {}


@dataclass
class ComplianceOutcome:
    decision: str
    robots_decision: dict
    terms_decision: dict
    gateway_flags: dict
    notes: list[str]
    policy_url: str


class Command(BaseCommand):
    help = "Approved limited compliance review + sandboxed dry-run ingestion for the PM-KUSUM official portal."

    def add_arguments(self, parser):
        parser.add_argument("--source-id", required=True, help="DataSource primary key (must be the PM-KUSUM source).")
        parser.add_argument("--operator-user", required=True, help="Username of the human operator approving this limited dry-run.")
        parser.add_argument("--run-id", default=F"run-{uuid.uuid4().hex[:12]}")

    def handle(self, *args, **options):
        if not getattr(settings, "DATA_INGESTION_NETWORK_ALLOWED", False):
            raise CommandError(
                "DATA_INGESTION_NETWORK_ALLOWED must be true for this approved single-run dry-run "
                "(connectivity is enabled only for the approved PM-KUSUM source)."
            )

        source = self._resolve_source(options["source_id"])
        operator = self._resolve_operator(options["operator_user"])
        run_id = options["run_id"]

        run = IngestionRun.objects.create(
            source=source,
            run_id=run_id,
            status=IngestionRun.Status.RUNNING,
            collector_version="approved_dry_run.provisioned.1",
            configuration_snapshot={
                "scope": RUN_LABEL,
                "approved_by": operator.username,
                "limits": {
                    "max_artifacts": MAX_ARTIFACTS,
                    "max_total_bytes": MAX_TOTAL_BYTES,
                    "min_request_gap_seconds": MIN_REQUEST_GAP_SECONDS,
                    "https_only": True,
                    "same_host_only": True,
                },
                "nopublish": True,
            },
            is_dry_run=False,
        )
        started = time.monotonic()
        report_dir = self._report_dir()

        client = SafeHTTPClient(timeout=20, max_bytes=MAX_ARTIFACTS * 1024 * 1024)
        self.stdout.write(self.style.WARNING(
            f"network ENABLED for this run — requests are restricted to {ALLOWED_HOST} "
            f"with >= {MIN_REQUEST_GAP_SECONDS}s pacing, <= {MAX_ARTIFACTS} pages, <= {MAX_TOTAL_BYTES // 1024} KB total."
        ))

        try:
            outcome, evidence = self._compliance_review(source, client)
            self._persist_compliance_check(source, run_id=run_id, outcome=outcome, evidence=evidence, report_dir=report_dir)
            self._write_compliance_report(report_dir, source, outcome)

            if outcome.decision != SourceComplianceCheck.Decision.ALLOWED:
                self._finish_blocked(run, report_dir, outcome)
                return

            candidates = self._select_candidates(source, outcome, evidence)
            if not candidates:
                self._finish_blocked(
                    run, report_dir, outcome,
                    note="Compliance allows collection, but no public in-scope page/document was discoverable from the "
                         "official homepage within the approved limits.",
                )
                return

            stats = self._dry_run_collect(source, run, client, candidates, outcome, report_dir)
            self._finish_collected(run, source, stats, report_dir, operator, elapsed=time.monotonic() - started)

        except ComplianceBlocked as exc:
            robots_retrieved = bool(exc.evidence.get("robots"))
            blocked = ComplianceOutcome(
                decision=SourceComplianceCheck.Decision.DENIED,
                robots_decision={
                    "retrieved": robots_retrieved,
                    "allows": False,
                    "reason": str(exc) + (f"; robots bytes={len(exc.evidence['robots'])}" if robots_retrieved else ""),
                },
                terms_decision={"retrieved": False, "manual_review": True, "note": "blocked before collection"},
                gateway_flags={"login_required_detected": False, "captcha_detected": False, "paywall_detected": False},
                notes=[str(exc)],
                policy_url="",
            )
            self._persist_compliance_check(source, run_id=run_id, outcome=blocked, evidence=exc.evidence, report_dir=report_dir)
            self._write_compliance_report(report_dir, source, blocked, evidence=exc.evidence)
            self._finish_blocked(run, report_dir, blocked)
        except SourceRegistryError as exc:
            run.status = IngestionRun.Status.FAILED
            run.save(update_fields=["status"])
            raise CommandError(str(exc)) from exc

    # ------------------------------------------------------------- plumbing
    def _report_dir(self):
        base = Path(getattr(settings, "DATA_INGESTION_REPORTS_DIR", "data/ingested/reports"))
        directory = base / f"pmkusum_approved_dry_run_{datetime.now():%Y%m%d_%H%M%S}"
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    def _resolve_source(self, source_id):
        try:
            source = DataSource.objects.get(pk=source_id)
        except (DataSource.DoesNotExist, ValueError) as exc:
            raise CommandError(f"unknown source {source_id!r}") from exc
        if source.base_url.rstrip("/") != PM_KUSUM_BASE.rstrip("/"):
            raise CommandError(
                f"this command is approved only for the PM-KUSUM source "
                f"({PM_KUSUM_BASE}); refusing {source.base_url}"
            )
        if source.approval_status == DataSource.ApprovalStatus.APPROVED:
            self.stdout.write(self.style.WARNING(
                "note: source is already approved; this run still performs only the approved dry-run (no publication)."
            ))
        return source

    def _resolve_operator(self, username):
        from django.contrib.auth import get_user_model

        User = get_user_model()
        try:
            return User.objects.get(username=username)
        except User.DoesNotExist as exc:
            raise CommandError(f"unknown operator user {username!r}") from exc

    # --------------------------------------------------------------- compliance
    def _compliance_review(self, source, client):
        """Live compliance review limited to the approved domain. Raises ComplianceBlocked."""
        robots_url = robots_url_for(PM_KUSUM_BASE)
        robots_content, robots_status = self._fetch(client, robots_url, source)
        if robots_status != 200 or not robots_content.strip():
            raise ComplianceBlocked(
                f"robots.txt unavailable or empty (HTTP {robots_status}) for {robots_url}. "
                "No collection performed. Recommendation: manual import of official public documents.",
                evidence={"robots_url": robots_url},
            )
        if not robots_is_unambiguous(robots_content):
            raise ComplianceBlocked(
                f"robots.txt at {robots_url} is ambiguous/unavailable: the endpoint returns HTTP 200 but does not "
                "serve a parseable robots file with User-agent directives. No collection performed; "
                "recommend manual import of official public documents.",
                evidence={"robots": robots_content, "robots_url": robots_url},
            )

        base_decision = evaluate_robots(robots_content, PM_KUSUM_BASE, target_paths=["/"])
        if not base_decision.allows_target:
            raise ComplianceBlocked(
                f"robots.txt denies the root path: {base_decision.reason}. No collection performed. "
                "Recommend manual import of official public documents.",
                evidence={"robots": robots_content, "robots_url": robots_url},
            )

        home_content, home_status = self._fetch(client, PM_KUSUM_BASE, source)
        if home_status != 200:
            raise ComplianceBlocked(
                f"homepage returned HTTP {home_status}; block — no collection performed.",
                evidence={"robots": robots_content, "robots_url": robots_url, "home": home_content, "home_url": PM_KUSUM_BASE},
            )

        gateway_flags, hint_notes = detect_gateway_hints(home_content[:200_000].decode("utf-8", "replace"))
        any_wall = gateway_flags["login_required_detected"] or gateway_flags["captcha_detected"] or gateway_flags["paywall_detected"]
        if any_wall:
            raise ComplianceBlocked(
                "homepage gateway heuristic detected "
                + "/".join(k for k, v in gateway_flags.items() if v)
                + "; content requires portal interaction -> block, no collection performed.",
                evidence={"robots": robots_content, "robots_url": robots_url, "home": home_content, "home_url": PM_KUSUM_BASE},
            )

        policy_url = discover_policy_url(home_content, PM_KUSUM_BASE, ALLOWED_HOST)
        terms_decision = {"retrieved": False, "manual_review": True, "note": "no policy/terms URL discovered"}
        if policy_url:
            policy_content, policy_status = self._fetch(client, policy_url, source)
            if policy_status == 200 and policy_content.strip():
                result = evaluate_terms(policy_content.decode("utf-8", "replace"), policy_url)
                terms_decision = {
                    "retrieved": result.retrieved,
                    "manual_review": result.manual_review_required,
                    "note": result.note + f" url={policy_url}",
                }
            else:
                terms_decision = {
                    "retrieved": False,
                    "manual_review": True,
                    "note": f"policy URL {policy_url} returned HTTP {policy_status}; manual review required",
                }
            source.terms_url = policy_url
            source.save(update_fields=["terms_url", "updated_at"])

        robots_decision = {
            "retrieved": True,
            "allows": True,
            "reason": f"robots.txt retrieved OK; allows root path ({len(robots_content)} bytes)",
        }
        notes = hint_notes + [
            f"robots.txt URL: {robots_url}",
            f"policy/terms URL: {policy_url or 'none discovered'}",
        ]

        # Gating follows the operator's approval contract: robots allows the
        # exact paths AND no login/CAPTCHA/paywall wall detected => allowed.
        # Terms findings are recorded (never auto-interpreted): a human must
        # review the identified policy page before any repeat automated
        # collection, but do not block this capped, pre-approved one-shot run.
        decision = SourceComplianceCheck.Decision.ALLOWED
        if terms_decision["manual_review"]:
            notes.append(
                "terms/policy page identified; manual review recommended before any repeat automated collection "
                "(this capped one-shot dry-run proceeds per operator approval)."
            )
        else:
            notes.append("terms/policy page retrieved; no restrictive hints detected.")

        return (
            ComplianceOutcome(
                decision=decision,
                robots_decision=robots_decision,
                terms_decision=terms_decision,
                gateway_flags=gateway_flags,
                notes=notes,
                policy_url=policy_url,
            ),
            {
                "robots": robots_content,
                "home": home_content,
                "terms": policy_content if policy_url else b"",
                "robots_url": robots_url,
                "terms_url": policy_url or "",
            },
        )

    def _select_candidates(self, source, outcome, evidence):
        parsed = _extract_links(evidence.get("home", b""))
        allowed_host = normalize_hostname(ALLOWED_HOST)
        candidates = []
        seen = set()
        for href in parsed:
            try:
                candidate = urljoin(PM_KUSUM_BASE, href)
            except Exception:  # noqa: BLE001
                continue
            try:
                validate_target_url(candidate, allowed_hosts=[PM_KUSUM_BASE])
            except UnsafeURL:
                continue
            parsed_candidate = urlparse(candidate)
            if parsed_candidate.scheme != "https":
                continue
            if normalize_hostname(parsed_candidate.hostname or "") != allowed_host:
                continue
            if any(k.lower() in candidate.lower() for k in EXCLUDE_PATH_KEYWORDS):
                continue
            if parsed_candidate.path.split("/")[-1].lower().endswith(tuple(IMAGE_EXTS)):
                continue
            lowered_path = parsed_candidate.path.lower()
            if not any(k in lowered_path for k in SIMILAR_CONTENT_KEYWORDS):
                continue
            if candidate in seen:
                continue
            seen.add(candidate)
            candidates.append(candidate)
            if len(candidates) >= MAX_ARTIFACTS * 4:
                break

        candidates = candidates[: MAX_ARTIFACTS * 4]
        allowed = []
        for candidate in candidates:
            decision = evaluate_robots(evidence.get("robots", b""), PM_KUSUM_BASE, target_paths=[candidate])
            if decision.allows_target:
                allowed.append(candidate)
            else:
                outcome.notes.append(f"candidate excluded by robots.txt: {candidate} ({decision.reason})")
            if len(allowed) >= MAX_ARTIFACTS:
                break
        return allowed[:MAX_ARTIFACTS]

    # ------------------------------------------------------------ collection
    def _fetch(self, client, url, source):
        if not url.startswith("https://"):
            raise ComplianceBlocked(f"HTTPS-only policy violated for {url}; block.")
        try:
            final_url, status, body, headers = client.get(url, allowed_hosts=[source.base_url])
        except (NetworkDisabledError, ResponseTooLarge) as exc:
            raise ComplianceBlocked(f"request to {url} failed blocked-safe: {exc}") from exc
        except Exception as exc:  # noqa: BLE001
            raise ComplianceBlocked(f"request to {url} failed blocked-safe: {exc!r}") from exc
        if status >= 400:
            raise ComplianceBlocked(f"request to {url} returned HTTP {status}; block.")
        if status in (301, 302, 303, 307, 308):
            raise ComplianceBlocked(f"unexpected redirect for {url}; block.")
        return body, status

    def _dry_run_collect(self, source, run, client, candidates, outcome, report_dir):
        total_bytes = 0
        pages_collected = 0
        records_created = 0
        duplicates = 0
        skipped = 0
        per_artifact = []
        for index, url in enumerate(candidates, start=1):
            if total_bytes >= MAX_TOTAL_BYTES:
                skipped += 1
                run.warnings.append("total byte budget exhausted; remaining candidates skipped")
                break
            try:
                final_url, status, body, headers = client.get(url, allowed_hosts=[source.base_url])
            except (NetworkDisabledError, ResponseTooLarge) as exc:
                run.warnings.append(f"{url}: blocked-safe error {exc}")
                skipped += 1
                continue
            except Exception as exc:  # noqa: BLE001
                run.warnings.append(f"{url}: transport error {exc!r}")
                skipped += 1
                continue
            if status >= 400 or len(body) == 0:
                run.warnings.append(f"{url}: HTTP {status}, empty body")
                skipped += 1
                continue

            content_type = (headers.get("Content-Type") or "").split(";")[0].strip().lower()
            if content_type.startswith("image/") or is_image_extension(url) or url.lower().endswith(tuple(IMAGE_EXTS)):
                run.warnings.append(f"{url}: image content skipped (no image datasets).")
                skipped += 1
                continue

            total_bytes += len(body)
            if total_bytes > MAX_TOTAL_BYTES:
                total_bytes -= len(body)
                run.warnings.append(f"{url}: would exceed 20 MB total; skipped.")
                skipped += 1
                continue

            artifact = self._persist_artifact(source, run, url, final_url, body, headers.get("Content-Type", ""), status, outcome.decision)
            if artifact is None:
                duplicates += 1
                run.save(update_fields=["duplicates_skipped", "warnings"])
                continue

            pages_collected += 1
            per_artifact.append(self._artifact_summary(artifact))

            extracted = self._extract_scheme_fields(artifact, body, final_url)
            if extracted is None:
                run.warnings.append(f"{final_url}: no scheme-related text extractable; routed to manual review only.")
                run.save(update_fields=["warnings"])
                continue

            record, ok, errors = create_validated_record(
                record_type=ExtractedRecord.RecordType.SCHEME,
                payload=extracted,
                source=source,
                ingestion_run=run,
                collected_artifact=artifact,
                source_url=final_url,
                confidence="low",
                target_model="SubsidyScheme",
                queue=True,
            )
            records_created += 1
            if ok:
                queue_item = DataReviewQueue.objects.filter(extracted_record=record, decision=DataReviewQueue.Decision.PENDING).first()
                if queue_item is not None:
                    queue_item.source_freshness_status = "official_govt_portal_preliminary"
                    queue_item.validation_result.setdefault("warnings", [])
                    queue_item.validation_result["warnings"].append("value is preliminary; requires_official_verification=True; requires human review")
                    queue_item.save(update_fields=["source_freshness_status", "validation_result"])

            run.records_extracted += 1
            run.save(update_fields=["records_extracted"])

            if pages_collected >= MAX_ARTIFACTS:
                break
            if index < len(candidates):
                time.sleep(MIN_REQUEST_GAP_SECONDS)

        run.pages_attempted = len(candidates)
        run.pages_collected = pages_collected
        run.documents_downloaded = pages_collected
        run.save(update_fields=["pages_attempted", "pages_collected", "documents_downloaded"])

        report = {
            "run_id": run.run_id,
            "pages_attempted": run.pages_attempted,
            "pages_collected": pages_collected,
            "records_created": records_created,
            "duplicates": duplicates,
            "skipped": skipped,
            "total_bytes_downloaded": total_bytes,
            "artifacts": per_artifact,
            "warnings": list(run.warnings),
        }
        path = report_dir / "ingestion_run_report.json"
        path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        (report_dir / "ingestion_run_report.md").write_text(_summary_md("Ingestion run report", report), encoding="utf-8")
        self.stdout.write(self.style.SUCCESS(f"ingestion-run report: {path}"))
        return report

    def _persist_artifact(self, source, run, url, final_url, body, content_type, http_status, compliance_decision):
        digest = sha256_of_bytes(body)
        if CollectedArtifact.objects.filter(sha256=digest).exists():
            run.duplicates_skipped += 1
            run.warnings.append(f"{final_url}: duplicate sha256, skipped.")
            run.save(update_fields=["duplicates_skipped", "warnings"])
            return None

        artifact_type = _artifact_type(content_type, final_url)
        if artifact_type is None:
            run.warnings.append(f"{final_url}: unsupported content type {content_type!r}; skipped.")
            run.save(update_fields=["warnings"])
            return None

        folder = Path(getattr(settings, "DATA_INGESTION_DATA_DIR", "data/ingested")) / run.run_id / artifact_type
        folder.mkdir(parents=True, exist_ok=True)
        ext = _ext_for(final_url, artifact_type)
        local_path = folder / f"{digest[:24]}{ext}"
        local_path.write_bytes(body)

        artifact = CollectedArtifact.objects.create(
            source=source,
            ingestion_run=run,
            artifact_type=artifact_type,
            original_url=url,
            final_url=final_url,
            local_path=str(local_path),
            sha256=digest,
            content_type=content_type.split(";")[0].strip(),
            file_size=len(body),
            http_status=http_status,
            license_note=f"compliance_decision={compliance_decision}; official public document; preliminary extraction only",
            attribution=f"Official MNRE PM-KUSUM portal ({PM_KUSUM_BASE}); limited approved dry-run",
            is_duplicate=False,
            validation_status=CollectedArtifact.ValidationStatus.PENDING,
        )
        logger.info("approved dry-run artifact source=%s type=%s sha=%s size=%s", source.pk, artifact_type, digest[:12], len(body))
        return artifact

    def _artifact_summary(self, artifact):
        return {
            "artifact_id": str(artifact.pk),
            "original_url": artifact.original_url,
            "final_url": artifact.final_url,
            "retrieved_at": artifact.retrieved_at.isoformat(),
            "sha256": artifact.sha256,
            "content_type": artifact.content_type,
            "size_bytes": artifact.file_size,
            "http_status": artifact.http_status,
            "attribution": artifact.attribution,
            "compliance_decision": artifact.license_note,
            "local_path": artifact.local_path,
        }

    def _extract_scheme_fields(self, artifact, body, final_url):
        text = _document_text(body, final_url)
        if not text.strip():
            return None
        extracted = extract_pmkusum_scheme_fields(text, final_url)
        if extracted is None:
            return None
        payload = {
            "name": extracted["name"],
            "status": "preliminary",
            "source_url": final_url,
            "official_url": PM_KUSUM_BASE,
            "category": "solar_pump",
            "administrative_level": "central",
            "state": "",
            "scheme_version": "1.0",
            "preliminary": True,
            "needs_official_verification": True,
            "requires_human_review": True,
            "is_estimate": True,
            "context": "PM-KUSUM scheme component/guideline public document (official portal dry-run)",
            "document_requirements": extracted["document_requirements"],
            "application_process": extracted["application_process"],
            "eligibility_wording": extracted["eligibility"],
            "benefit_wording": extracted["benefit"],
            "components_found": extracted["components"],
            "effective_from": extracted["effective_from"],
            "effective_to": extracted["effective_to"],
            "_raw": {"text_excerpt": text[:8000], "page_title": extracted["title"]},
        }
        if extracted["benefit_min_inr"] is not None:
            payload["benefit_min_inr"] = extracted["benefit_min_inr"]
        if extracted["benefit_max_inr"] is not None:
            payload["benefit_max_inr"] = extracted["benefit_max_inr"]
        return payload

    # -------------------------------------------------------------- persistence
    def _persist_compliance_check(self, source, *, run_id, outcome, evidence, report_dir):
        robots_decision = outcome.robots_decision
        terms_decision = outcome.terms_decision
        robots_url = evidence.get("robots_url", "") or robots_url_for(PM_KUSUM_BASE)
        terms_url = evidence.get("terms_url", "") or ""
        evidence_dir = Path(getattr(settings, "DATA_INGESTION_DATA_DIR", "data/ingested")) / "compliance" / f"{source.pk or 'new'}_{abs(hash(source.name)) % 10 ** 6}" / run_id
        evidence_dir.mkdir(parents=True, exist_ok=True)
        evidence_path, evidence_hash = "", ""
        files = [("robots.txt", evidence.get("robots")), ("home.html", evidence.get("home")), ("terms.txt", evidence.get("terms"))]
        for filename, content in files:
            if content:
                (evidence_dir / filename).write_bytes(content)
                evidence_path = str(evidence_dir / filename)
                evidence_hash = sha256_of_bytes(content)

        check = SourceComplianceCheck.objects.create(
            source=source,
            run_id=run_id,
            robots_url=robots_url,
            robots_retrieved=bool(robots_decision.get("retrieved")),
            robots_allows_target_paths=bool(robots_decision.get("allows")),
            terms_url=terms_url,
            terms_retrieved=bool(terms_decision.get("retrieved")),
            terms_manual_review_required=bool(terms_decision.get("manual_review")),
            login_required_detected=outcome.gateway_flags["login_required_detected"],
            captcha_detected=outcome.gateway_flags["captcha_detected"],
            paywall_detected=outcome.gateway_flags["paywall_detected"],
            blocked_reason=robots_decision.get("reason", ""),
            decision=outcome.decision,
            evidence_path=evidence_path,
            evidence_hash=evidence_hash,
            notes="; ".join(outcome.notes),
        )
        source.last_compliance_check_at = timezone.now()
        source.robots_status = DataSource.RobotsStatus.RETRIEVED if robots_decision.get("retrieved") else DataSource.RobotsStatus.UNAVAILABLE
        source.terms_status = DataSource.TermsStatus.RETRIEVED if terms_decision.get("retrieved") else DataSource.TermsStatus.MANUAL_REVIEW
        source.save(update_fields=["robots_status", "terms_status", "last_compliance_check_at", "updated_at"])
        logger.info("approved dry-run compliance source=%s decision=%s run_id=%s", source.pk, check.decision, run_id)
        return check

    def _write_compliance_report(self, report_dir, source, outcome, evidence=None):
        evidence = evidence or {}
        robots_url = evidence.get("robots_url", "") or robots_url_for(PM_KUSUM_BASE)
        report = {
            "source": {
                "name": source.name,
                "organization": source.organization,
                "base_url": source.base_url,
                "domain": ALLOWED_HOST,
            },
            "decision": outcome.decision,
            "robots": outcome.robots_decision,
            "terms": outcome.terms_decision,
            "gateway_flags": outcome.gateway_flags,
            "policy_url_identified": outcome.policy_url or "",
            "notes": outcome.notes,
            "evidence": {
                "robots_url": robots_url,
                "robots_sha256": sha256_of_bytes(evidence["robots"]) if evidence.get("robots") else "",
                "context": "Blocked runs stop at the first failing gate; homepage/policy pages are only fetched when robots.txt is valid.",
            },
        }
        path = report_dir / "compliance_report.json"
        path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        (report_dir / "compliance_report.md").write_text(_summary_md("Compliance review (PM-KUSUM approved dry-run)", report), encoding="utf-8")
        self.stdout.write(self.style.SUCCESS(f"compliance report: {path}"))

    def _write_review_export(self, report_dir, run):
        pending = DataReviewQueue.objects.filter(
            extracted_record__ingestion_run=run, decision=DataReviewQueue.Decision.PENDING
        ).order_by("-created_at")
        payload = {
            "exported_at": datetime.now().isoformat(),
            "run_id": run.run_id,
            "pending_count": len(pending),
            "note": "Manual review required before publication; nothing here has been published to live tables.",
            "pending": [
                {
                    "id": str(item.pk),
                    "record_id": str(item.extracted_record_id),
                    "proposed_target_model": item.proposed_target_model,
                    "proposed_action": item.proposed_action,
                    "risk_level": item.risk_level,
                    "source_freshness_status": item.source_freshness_status,
                    "requires_human_review": item.requires_human_review,
                    "normalized_data": item.extracted_record.normalized_data_json,
                    "raw_excerpt": (item.extracted_record.raw_data_json or {}).get("text_excerpt", "")[:2000],
                    "source_url": item.extracted_record.source_url,
                    "artifact_sha256": getattr(item.extracted_record.collected_artifact, "sha256", ""),
                }
                for item in pending
            ],
        }
        path = report_dir / "review_queue_export.json"
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        self.stdout.write(self.style.SUCCESS(f"review-queue export: {path}"))

    def _finish_blocked(self, run, report_dir, outcome, note=""):
        run.warnings.append(note or outcome.notes[-1] if outcome.notes else "")
        run.status = IngestionRun.Status.FAILED
        run.completed_at = timezone.now()
        run.save(update_fields=["warnings", "status", "completed_at"])
        self.stdout.write(self.style.ERROR("COMPLIANCE BLOCKED — no collection performed."))
        self.stdout.write(self.style.WARNING(note or f"decision={outcome.decision}"))
        for line in outcome.notes:
            self.stdout.write(f"  - {line}")
        self.stdout.write(self.style.SUCCESS(f"compliance report: {report_dir / 'compliance_report.md'}"))
        self.stdout.write(self.style.WARNING(
            "Recommendation: manual import of the official public PM-KUSUM guideline documents, "
            "or an explicitly permitted alternative official source."
        ))

    def _finish_collected(self, run, source, stats, report_dir, operator, elapsed):
        run.status = IngestionRun.Status.COMPLETED
        run.completed_at = timezone.now()
        run.save(update_fields=["status", "completed_at"])

        self._write_review_export(report_dir, run)
        write_provenance_report(run, report_dir=report_dir)
        for artifact in CollectedArtifact.objects.filter(ingestion_run=run):
            write_provenance_report(artifact, report_dir=report_dir)

        summary = {
            "run_id": run.run_id,
            "source": source.name,
            "status": "completed (sandboxed dry-run)",
            "approved_by": operator.username,
            "elapsed_seconds": round(elapsed, 1),
            "pages_collected": stats["pages_collected"],
            "records_in_review_queue": DataReviewQueue.objects.filter(extracted_record__ingestion_run=run, decision="pending").count(),
            "published_to_live_tables": False,
            "limits": stats,
        }
        (report_dir / "extracted_record_summary.json").write_text(json.dumps(stats, indent=2, ensure_ascii=False), encoding="utf-8")
        (report_dir / "extracted_record_summary.md").write_text(_summary_md("Extracted-record summary", stats), encoding="utf-8")
        (report_dir / "review_summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")

        self.stdout.write(self.style.SUCCESS(f"\ndry-run collection completed run_id={run.run_id}"))
        self.stdout.write(f"  pages collected : {stats['pages_collected']}")
        self.stdout.write(f"  records extracted+queued : {stats['records_created']}")
        self.stdout.write(f"  duplicates/skipped : {stats['duplicates']}/{stats['skipped']}")
        self.stdout.write(f"  total bytes       : {stats['total_bytes_downloaded']}")
        self.stdout.write(self.style.WARNING("NO PUBLICATION performed — everything is in DataReviewQueue pending human review."))
        self.stdout.write(f"  reports           : {report_dir}")


# --------------------------------------------------------------------------- helpers
def normalize_hostname(host):
    host = (host or "").strip().lower().rstrip(".")
    return host.split(":")[0]


def detect_gateway_hints(text):
    """Detect walls conservatively: a login/sign-in is only treated as a wall
    when it is coupled with credential/registration language; CAPTCHA and
    paywall keywords are treated as walls on their own."""
    lowered = (text or "").lower()
    flags = {"login_required_detected": False, "captcha_detected": False, "paywall_detected": False}
    notes = []
    for keyword, flag, note in (
        ("captcha", "captcha_detected", "captcha keyword"),
        ("recaptcha", "captcha_detected", "recaptcha keyword"),
        ("paywall", "paywall_detected", "paywall keyword"),
        ("subscription required", "paywall_detected", "subscription-required"),
    ):
        if keyword in lowered:
            flags[flag] = True
            notes.append(note)

    login_context = ("password", "otp", "personal identification number", "pin", "credential", "sign up", "register")
    if "login" in lowered or "sign in" in lowered:
        nearby_wall = any(token in lowered for token in login_context)
        if nearby_wall:
            flags["login_required_detected"] = True
            notes.append("login/registration wall detected (credential language present)")
        else:
            notes.append("public login entry present; no credential wall detected on public pages")
    return flags, notes


def _extract_links(content):
    if not content:
        return []
    try:
        soup = BeautifulSoup(content.decode("utf-8", "replace"), "lxml")
    except Exception:  # noqa: BLE001
        return []
    links = []
    for tag in soup.find_all("a", href=True):
        href = tag["href"].strip()
        if not href or href.startswith(("mailto:", "javascript:")):
            continue
        links.append(href)
    return links


def discover_policy_url(home_content, base_url, allowed_host):
    for href in _extract_links(home_content):
        try:
            candidate = urljoin(base_url, href)
            parsed = urlparse(candidate)
        except Exception:  # noqa: BLE001
            continue
        if parsed.scheme != "https" or normalize_hostname(parsed.hostname or "") != allowed_host:
            continue
        if any(k in candidate.lower() for k in POLICY_KEYWORDS):
            return candidate
    return ""


def _artifact_type(content_type, url):
    ctype = (content_type or "").split(";")[0].strip().lower()
    path = urlparse(url).path.lower()
    if ctype.startswith("image/") or any(path.endswith(e) for e in IMAGE_EXTS):
        return None
    mapping = {
        "pdf": CollectedArtifact.ArtifactType.PDF,
        "html": CollectedArtifact.ArtifactType.HTML,
        "xhtml": CollectedArtifact.ArtifactType.HTML,
        "text/html": CollectedArtifact.ArtifactType.HTML,
        "text/plain": CollectedArtifact.ArtifactType.TEXT,
        "text": CollectedArtifact.ArtifactType.TEXT,
        "application/json": CollectedArtifact.ArtifactType.JSON,
        "json": CollectedArtifact.ArtifactType.JSON,
        "text/csv": CollectedArtifact.ArtifactType.CSV,
        "csv": CollectedArtifact.ArtifactType.CSV,
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": CollectedArtifact.ArtifactType.XLSX,
        "xlsx": CollectedArtifact.ArtifactType.XLSX,
    }
    if ctype in mapping:
        return mapping[ctype]
    if path.endswith(".pdf"):
        return CollectedArtifact.ArtifactType.PDF
    if path.endswith((".html", ".htm", ".aspx", ".php", ".jsp")):
        return CollectedArtifact.ArtifactType.HTML
    if path.endswith((".json",)):
        return CollectedArtifact.ArtifactType.JSON
    return CollectedArtifact.ArtifactType.TEXT if ctype.startswith("text/") else None


def _ext_for(url, artifact_type):
    path = urlparse(url).path
    ext = Path(path).suffix.lower()
    if ext in {".pdf", ".html", ".htm", ".json", ".csv", ".xlsx", ".txt"}:
        return ext
    mapping = {
        CollectedArtifact.ArtifactType.HTML: ".html",
        CollectedArtifact.ArtifactType.JSON: ".json",
        CollectedArtifact.ArtifactType.CSV: ".csv",
        CollectedArtifact.ArtifactType.PDF: ".pdf",
        CollectedArtifact.ArtifactType.XLSX: ".xlsx",
        CollectedArtifact.ArtifactType.TEXT: ".txt",
    }
    return mapping.get(artifact_type, ".bin")


def _document_text(body, url):
    ctype = _artifact_type("", url) or CollectedArtifact.ArtifactType.HTML
    if ctype == CollectedArtifact.ArtifactType.PDF:
        from apps.data_ingestion.services.pdf_parser import extract_pdf

        result = extract_pdf(body)
        if result.get("engine") in ("none", ""):
            return ""
        return result.get("text", "")
    if ctype == CollectedArtifact.ArtifactType.JSON:
        try:
            return json.dumps(json.loads(body.decode("utf-8", "replace")), ensure_ascii=False)
        except Exception:  # noqa: BLE001
            return ""
    return body.decode("utf-8", "replace")


def _clean_snippet(lines, limit=6, max_len=520):
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


_MONTH_NUMBER = {
    "jan": "01", "january": "01", "feb": "02", "february": "02", "mar": "03", "march": "03",
    "apr": "04", "april": "04", "may": "05", "jun": "06", "june": "06", "jul": "07", "july": "07",
    "aug": "08", "august": "08", "sep": "09", "september": "09", "oct": "10", "october": "10",
    "nov": "11", "november": "11", "dec": "12", "december": "12",
}


def _first_date(text):
    match = RE_DATE.search(text)
    if match:
        return f"{match.group(3)}-{match.group(2).zfill(2)}-{match.group(1).zfill(2)}"
    match = RE_MONTH_DAY_YEAR.search(text)
    if match:
        month = _MONTH_NUMBER.get(match.group(2).lower(), "01")
        return f"{match.group(3)}-{month}-{match.group(1).zfill(2)}"
    return ""


def extract_pmkusum_scheme_fields(text, source_url):
    lowered = text.lower()
    title = ""
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines() if line.strip()]
    for line in lines[:40]:
        if len(line) > 12 and "http" not in line.lower():
            title = line[:150]
            break

    components = [l for l in lines if re.search(r"component\s*[abc]", l, re.IGNORECASE)][:5]
    eligibility = _clean_snippet(
        [l for l in lines if re.search(r"eligible|eligibility", l, re.IGNORECASE)]
    )
    benefit = _clean_snippet(
        [l for l in lines if re.search(r"subsid|benefit|financial assis|\bpercentage\b|\brs\.?\b|\b₹\b|funding", l, re.IGNORECASE)]
    )
    documents = _clean_snippet(
        [l for l in lines if re.search(r"document|self.attested|required|certificate|affidavit|bank passbook", l, re.IGNORECASE)]
    )
    process = _clean_snippet(
        [l for l in lines if re.search(r"application|how to apply|apply online|submitted through|portal|procedure|process", l, re.IGNORECASE)]
    )

    benefit_min = benefit_max = None
    amounts = []
    for match in re.finditer(r"(?:rs\.?\s*|₹\s*)?([\d,]{4,})", text, re.IGNORECASE):
        try:
            amounts.append(float(match.group(1).replace(",", "")))
        except ValueError:
            continue
    amounts = [n for n in amounts if n > 0]
    if amounts:
        benefit_min = int(min(amounts) / 1000) * 1000
        benefit_max = int(max(amounts) / 1000) * 1000

    if not (components or eligibility or benefit or documents or process or title):
        return None

    return {
        "name": title or "PM-KUSUM official document (preliminary)",
        "title": title or "",
        "components": components[:3],
        "eligibility": eligibility,
        "benefit": benefit,
        "document_requirements": documents,
        "application_process": process,
        "effective_from": _first_date(lowered) or "",
        "effective_to": "",
        "benefit_min_inr": benefit_min,
        "benefit_max_inr": benefit_max,
    }


def _summary_md(title, data):
    lines = [f"# {title}", "", f"Generated: {datetime.now().isoformat()}", ""]
    for key, value in data.items():
        if key == "artifacts":
            lines.append("")
            lines.append("## artifacts")
            for item in value:
                lines.append("")
                for k, v in item.items():
                    lines.append(f"- **{k}**: {v}")
            continue
        lines.append(f"- **{key}**: {json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else value}")
    return "\n".join(lines)


def is_image_extension(path):
    return path is not None and path.lower().endswith(tuple(IMAGE_EXTS))