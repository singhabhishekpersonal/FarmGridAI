"""Compliance orchestration for a DataSource.

Runs the full compliance pipeline (robots.txt + terms + landing-page heuristics)
and persists the result as a :class:`SourceComplianceCheck`. The module is
fully offline-capable: with networking disabled it records a ``manual_review``
decision with a clear reason, so tests and dry-run flows never touch the wire.
"""
import logging
import re
import time
from pathlib import Path

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage

from apps.data_ingestion.models import DataSource, SourceComplianceCheck
from apps.data_ingestion.services.hashing import sha256_of_bytes
from apps.data_ingestion.services.http_client import NetworkDisabledError, SafeHTTPClient, ResponseTooLarge
from apps.data_ingestion.services.robots import evaluate_robots, robots_url_for
from apps.data_ingestion.services.terms import evaluate_terms
from django.utils import timezone

logger = logging.getLogger("khetsathi.audit")

_SAFE_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,119}$")


def _evidence_dir(source, run_id):
    base = Path(getattr(settings, "DATA_INGESTION_DATA_DIR", "data/ingested"))
    directory = base / "compliance" / f"{source.pk or 'new'}"

    run_id = run_id or str(time.time()).replace(".", "_")
    if not (isinstance(run_id, str) and _SAFE_RUN_ID.match(run_id) and ".." not in run_id):
        run_id = str(time.time()).replace(".", "_")
    return directory, run_id


def _store_evidence(relative_path, content):
    """Persist raw evidence (robots/terms/homepage) so provenance is auditable."""
    if not content:
        return "", ""
    path = default_storage.path(relative_path) if hasattr(default_storage, "path") else str(relative_path)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_bytes(content if isinstance(content, bytes) else content.encode("utf-8"))
    return relative_path, sha256_of_bytes(content if isinstance(content, bytes) else content.encode("utf-8"))


_HOME_HINTS = {
    "login": ("login_required_detected", "login form keyword(s) found"),
    "sign in": ("login_required_detected", "sign-in keyword(s) found"),
    "captcha": ("captcha_detected", "captcha keyword(s) found"),
    "recaptcha": ("captcha_detected", "recaptcha keyword(s) found"),
    "paywall": ("paywall_detected", "paywall keyword(s) found"),
    "subscription required": ("paywall_detected", "subscription-required text found"),
}


def detect_gateway_hints(text):
    """Best-effort keyword heuristics; never blocks anything on its own."""
    lowered = (text or "").lower()
    flags = {"login_required_detected": False, "captcha_detected": False, "paywall_detected": False}
    notes = []
    for keyword, (flag, note) in _HOME_HINTS.items():
        if keyword in lowered:
            flags[flag] = True
            notes.append(note)
    return flags, notes


def _homepage_url(source):
    url = source.base_url.rstrip("/")
    return url + "/"


def run_compliance_check(source, run_id="", client=None):
    """Run (or, offline, record) a compliance check for ``source``."""
    client = client or SafeHTTPClient()
    directory, run_id = _evidence_dir(source, run_id)
    source.last_compliance_check_at = timezone.now()

    robots_decision = {"retrieved": False, "allows": False, "reason": ""}
    terms_decision = {"retrieved": False, "manual_review": True, "note": ""}
    gateway_flags = {"login_required_detected": False, "captcha_detected": False, "paywall_detected": False}
    notes = []
    evidence_path = ""
    evidence_hash = ""

    if source.source_type == DataSource.SourceType.MANUAL_IMPORT:
        robots_decision = {"retrieved": False, "allows": False, "reason": "manual_import_only sources do no automated fetching"}
        terms_decision = {"retrieved": False, "manual_review": True, "note": "manual import: terms review required before import"}
        notes.append("Manual-import-only source: no automated collection permitted.")
        decision = SourceComplianceCheck.Decision.MANUAL_REVIEW
        source.robots_status = DataSource.RobotsStatus.NOT_APPLICABLE
        source.terms_status = DataSource.TermsStatus.MANUAL_REVIEW
        source.save(update_fields=["robots_status", "terms_status", "last_compliance_check_at", "updated_at"])

    else:
        try:
            robots_url = source.robots_url or robots_url_for(source.base_url)
            final_url, status, content, _ = client.get(
                robots_url,
                allowed_hosts=[source.base_url],
            )
            if status == 200 and content.strip():
                path, digest = _store_evidence(f"{directory}/{run_id}/robots.txt", content)
                evidence_path, evidence_hash = path, digest
                result = evaluate_robots(content, source.base_url)
                robots_decision = {
                    "retrieved": result.retrieved,
                    "allows": result.allows_target,
                    "reason": result.reason,
                }
                if result.allows_target:
                    try:
                        home_url = source.base_url
                        _, _, body, headers = client.get(home_url, allowed_hosts=[source.base_url])
                        path, digest = _store_evidence(f"{directory}/{run_id}/home.html", body)
                        gateway_flags, hint_notes = detect_gateway_hints(body[:200_000])
                        notes.extend(hint_notes)
                    except (NetworkDisabledError, ResponseTooLarge, Exception) as exc:  # noqa: BLE001
                        notes.append(f"homepage heuristic fetch failed: {exc}")
            else:
                robots_decision = {"retrieved": False, "allows": False, "reason": f"robots.txt HTTP {status}"}
                notes.append(robots_decision["reason"])
        except NetworkDisabledError as exc:
            notes.append(f"Network disabled: {exc}")

        if source.terms_url:
            try:
                _, tstatus, tbody, _ = client.get(source.terms_url, allowed_hosts=[source.base_url])
                if tstatus == 200:
                    path, digest = _store_evidence(f"{directory}/{run_id}/terms.txt", tbody)
                    terms_result = evaluate_terms(tbody, source.terms_url)
                    terms_decision = {
                        "retrieved": terms_result.retrieved,
                        "manual_review": terms_result.manual_review_required,
                        "note": terms_result.note,
                    }
                else:
                    terms_decision = {"retrieved": False, "manual_review": True, "note": f"terms HTTP {tstatus}"}
            except (NetworkDisabledError, Exception) as exc:  # noqa: BLE001
                terms_decision = {"retrieved": False, "manual_review": True, "note": f"terms fetch failed: {exc}"}
        else:
            terms_decision = {"retrieved": False, "manual_review": True, "note": "no terms URL configured; manual review required"}

        if robotics_confirms_allowed(robots_decision) and not terms_decision["manual_review"]:
            decision = SourceComplianceCheck.Decision.ALLOWED
        elif robotics_confirms_allowed(robots_decision):
            decision = SourceComplianceCheck.Decision.MANUAL_REVIEW
            notes.append("robots allows collection, but terms still require human review.")
        else:
            decision = SourceComplianceCheck.Decision.MANUAL_REVIEW if not robots_decision["retrieved"] else SourceComplianceCheck.Decision.DENIED

        source.robots_status = (
            DataSource.RobotsStatus.RETRIEVED
            if robots_decision["retrieved"]
            else DataSource.RobotsStatus.UNAVAILABLE
        )
        source.terms_status = (
            DataSource.TermsStatus.RETRIEVED if terms_decision["retrieved"] else DataSource.TermsStatus.UNAVAILABLE
        )
        source.save(update_fields=["robots_status", "terms_status", "last_compliance_check_at", "updated_at"])

    blocked_reason = robots_decision.get("reason", "")
    check = SourceComplianceCheck.objects.create(
        source=source,
        run_id=run_id,
        robots_url=source.robots_url or robots_url_for(source.base_url) if source.source_type != DataSource.SourceType.MANUAL_IMPORT else "",
        robots_retrieved=robots_decision["retrieved"],
        robots_allows_target_paths=robots_decision["allows"],
        terms_url=source.terms_url or "",
        terms_retrieved=terms_decision["retrieved"],
        terms_manual_review_required=terms_decision["manual_review"],
        login_required_detected=gateway_flags["login_required_detected"],
        captcha_detected=gateway_flags["captcha_detected"],
        paywall_detected=gateway_flags["paywall_detected"],
        blocked_reason=blocked_reason,
        decision=decision,
        evidence_path=evidence_path,
        evidence_hash=evidence_hash,
        notes="; ".join(notes),
    )
    logger.info("compliance check run_id=%s source=%s decision=%s", run_id, source.name, decision)
    return check


def robotics_confirms_allowed(robots_decision):
    return bool(robots_decision.get("retrieved") and robots_decision.get("allows"))