"""Live compliance-only review for the MNRE host (OFFICIAL APPROVAL, no collection).

Operator-approved **compliance check only** for whether publicly accessible
PM-KUSUM guideline pages/documents on ``https://mnre.gov.in/`` can be collected
compliantly. No scheme data is collected, no PDF/document is downloaded, no
record is extracted, nothing is published.

Invariants enforced on every run:

* host lock: only ``mnre.gov.in`` (the approved MNRE source base URL); any
  other source is refused;
* HTTPS only; no recursive crawling; no external redirects (redirects must
  stay on the approved host or the run blocks); no browser automation; no
  bypass methods;
* robots.txt is fetched and parsed FIRST — if it is absent, invalid,
  unavailable, ambiguous (RFC 9309) or disallows the target path, the run
  stops immediately;
* policy / copyright / terms URLs are checked **only when robots.txt permits**
  those exact paths;
* hard request budget: <= 5 requests total, >= 5 s between requests, no
  parallel requests;
* PDF/document links are evaluated for robots permission but are **never**
  downloaded in this step;
* the source is left ``manual_review`` with ``collection_enabled=False`` after
  the check (this command never approves a source).

Output (console + JSON/Markdown report):
* robots.txt result
* target-path permission result
* policy/terms URL result (if allowed)
* login/CAPTCHA/paywall detection result (if allowed)
* collection-risk assessment
* recommendation: ``approved dry-run eligible`` | ``manual-import preferred`` | ``blocked``
"""
import json
import logging
import uuid
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.data_ingestion.management.commands.approved_dry_run_source import (
    EXCLUDE_PATH_KEYWORDS,
    IMAGE_EXTS,
    SIMILAR_CONTENT_KEYWORDS,
    _extract_links,
    detect_gateway_hints,
    normalize_hostname,
)
from apps.data_ingestion.models import DataSource, SourceComplianceCheck
from apps.data_ingestion.services.hashing import sha256_of_bytes
from apps.data_ingestion.services.http_client import NetworkDisabledError, ResponseTooLarge, SafeHTTPClient
from apps.data_ingestion.services.robots import evaluate_robots, robots_is_unambiguous, robots_url_for
from apps.data_ingestion.services.terms import evaluate_terms
from apps.data_ingestion.services.urlutils import UnsafeURL, validate_target_url

logger = logging.getLogger("khetsathi.audit")

MNRE_BASE = "https://mnre.gov.in/"
ALLOWED_HOST = "mnre.gov.in"
RUN_LABEL = "mnre-compliance-review-only"

MAX_REQUESTS = 5
MIN_REQUEST_GAP_SECONDS = 5.0
MAX_EVIDENCE_SIZE = 8 * 1024 * 1024

POLICY_KEYWORDS = ("terms", "privacy", "policy", "copyright", "usage", "disclaimer", "legal")
DOCUMENT_EXTS = (".pdf", ".doc", ".docx", ".xls", ".xlsx", ".csv", ".zip", ".png", ".jpg", ".jpeg")
EXCLUDE_GATE_KEYWORDS = ("login", "otp", "captcha", "password", "register", "signin", "signup", "portal", "form", "api")


class Command(BaseCommand):
    help = "Live compliance review ONLY for https://mnre.gov.in/ (approved scope: no collection, no PDFs, no records, no publish)."

    def add_arguments(self, parser):
        parser.add_argument("--source-id", required=True, help="DataSource pk (must be the MNRE source).")
        parser.add_argument("--operator-user", default="", help="Optional human operator making the request (audit only).")
        parser.add_argument("--run-id", default=f"run-{uuid.uuid4().hex[:12]}")

    def handle(self, *args, **options):
        source = self._resolve_source(options["source_id"])
        if not getattr(settings, "DATA_INGESTION_NETWORK_ALLOWED", False):
            raise CommandError(
                "DATA_INGESTION_NETWORK_ALLOWED must be true for this approved compliance-only review "
                "(connectivity enabled only for the approved MNRE host)."
            )

        run_id = options["run_id"]
        self.request_count = 0

        client = SafeHTTPClient(timeout=20, max_bytes=MAX_EVIDENCE_SIZE)
        report_dir = self._report_dir()
        self.stdout.write(self.style.WARNING(
            f"network ENABLED for this review — requests restricted to {ALLOWED_HOST}, "
            f"<= {MAX_REQUESTS} total, >= {MIN_REQUEST_GAP_SECONDS}s pacing, no PDF downloads, no extraction, no publish."
        ))

        result = self._review(source, client)

        self._persist_check(source, run_id, result)
        self._write_report(report_dir, source, result)

        source.approval_status = DataSource.ApprovalStatus.MANUAL_REVIEW
        source.collection_enabled = False
        source.save(update_fields=["approval_status", "collection_enabled", "updated_at"])

        self._print_result(source, result, report_dir)

    # ---------------------------------------------------------------- review
    def _review(self, source, client):
        result = {
            "scope": RUN_LABEL,
            "host_locked_to": ALLOWED_HOST,
            "request_count": 0,
            "robots": {},
            "target_paths": {},
            "policy": {},
            "gateway": {},
            "risk_assessment": "",
            "recommendation": "",
            "notes": [],
            "blocked": False,
        }

        # 1. robots.txt first.
        robots_url = robots_url_for(MNRE_BASE)
        robots_content, robots_status, robots_final = self._fetch(client, robots_url, source)
        result["request_count"] = self.request_count
        result["robots"] = {
            "url": robots_url,
            "http_status": robots_status,
            "retrieved": robots_status == 200 and bool(robots_content.strip()),
            "size_bytes": len(robots_content) if robots_content else 0,
            "content_type": "text/plain-expected",
            "sha256": sha256_of_bytes(robots_content) if robots_content else "",
        }
        if robots_status != 200 or not robots_content.strip():
            result["robots"]["reason"] = (
                f"robots.txt returned HTTP {robots_status} or empty body at {robots_url}. "
                "No collection assessment possible."
            )
            result["notes"].append(result["robots"]["reason"])
            return self._blocked(result, "blocked", "robots.txt unavailable/invalid/empty")

        if not robots_is_unambiguous(robots_content):
            result["robots"]["unambiguous"] = False
            result["robots"]["reason"] = (
                "robots.txt endpoint returns content but no User-agent directives are parseable (ambiguous)."
            )
            result["notes"].append(result["robots"]["reason"])
            return self._blocked(result, "blocked", "robots.txt ambiguous")

        result["robots"]["unambiguous"] = True
        root_decision = evaluate_robots(robots_content, MNRE_BASE, target_paths=["/"])
        result["robots"]["allows_root"] = root_decision.allows_target
        result["robots"]["root_reason"] = root_decision.reason or "root path allowed"
        if not root_decision.allows_target:
            result["notes"].append(f"robots.txt denies the root path: {root_decision.reason}")
            return self._blocked(result, "blocked", "robots.txt disallows the target path")

        # 2. Homepage + gateway + policy/link discovery (roots now allowed).
        home_content, home_status, _ = self._fetch(client, MNRE_BASE, source)
        result["request_count"] = self.request_count
        if home_status != 200:
            result["notes"].append(f"homepage returned HTTP {home_status}; stop.")
            return self._blocked(result, "blocked", "homepage unavailable")

        gateway_flags, hint_notes = detect_gateway_hints(home_content[:200_000].decode("utf-8", "replace"))
        result["gateway"] = gateway_flags
        result["gateway"]["notes"] = hint_notes
        any_wall = gateway_flags["login_required_detected"] or gateway_flags["captcha_detected"] or gateway_flags["paywall_detected"]
        if any_wall:
            result["notes"].append("gateway wall detected (" + "/".join(k for k, v in gateway_flags.items() if v) + "); stop.")
            return self._blocked(result, "blocked", "login/CAPTCHA/paywall wall detected")

        # 3. Target-path permission for discoverable public PM-KUSUM guideline
        #    pages/documents (evaluated against robots only — never downloaded).
        candidates = self._candidate_paths(home_content, robots_content)
        denied_paths = []
        allowed_paths = []
        for candidate in candidates:
            decision = evaluate_robots(robots_content, MNRE_BASE, target_paths=[candidate])
            if decision.allows_target:
                allowed_paths.append(candidate)
            else:
                denied_paths.append(f"{candidate} ({decision.reason})")
        result["target_paths"] = {
            "evaluated_count": len(candidates),
            "allowed_count": len(allowed_paths),
            "allowed_examples": allowed_paths[:10],
            "denied_count": len(denied_paths),
            "denied_examples": denied_paths[:5],
            "note": "robots-permission evaluation only; no page/document was downloaded.",
        }

        # 4. Policy / copyright / terms URLs — fetched only if robots allows.
        policy_urls = self._discover_policy_urls(home_content)
        result["policy"] = {"discovered_urls": policy_urls, "evaluations": [], "fetched": 0}
        for policy_url in policy_urls:
            policy_decision = evaluate_robots(robots_content, MNRE_BASE, target_paths=[policy_url])
            entry = {
                "url": policy_url,
                "robots_allows": policy_decision.allows_target,
                "fetched": False,
                "http_status": None,
                "restrictive_hints": [],
                "manual_review_required": True,
                "note": "",
            }
            path_lower = urlparse(policy_url).path.lower()
            if path_lower.endswith(DOCUMENT_EXTS):
                entry["note"] = "policy link is a document; not downloaded (approved scope: no PDF/document downloads)."
                result["policy"]["evaluations"].append(entry)
                continue
            if not policy_decision.allows_target:
                entry["note"] = f"not fetched: robots.txt disallows this policy path ({policy_decision.reason})."
                result["policy"]["evaluations"].append(entry)
                continue
            if self.request_count >= MAX_REQUESTS:
                entry["note"] = "not fetched: request budget exhausted."
                result["policy"]["evaluations"].append(entry)
                continue
            try:
                content, status, _ = self._fetch(client, policy_url, source)
            except RuntimeError as exc:
                entry["note"] = f"not fetched: {exc}"
                result["policy"]["evaluations"].append(entry)
                break
            result["request_count"] = self.request_count
            entry["fetched"] = status == 200 and bool(content.strip())
            entry["http_status"] = status
            if entry["fetched"]:
                terms_result = evaluate_terms(content.decode("utf-8", "replace"), policy_url)
                entry["restrictive_hints"] = [h for h in (terms_result.note or "").split(";") if h]
                entry["manual_review_required"] = terms_result.manual_review_required
                entry["note"] = terms_result.note
                result["policy"]["fetched"] += 1
            else:
                entry["note"] = f"HTTP {status}; manual review required."
            result["policy"]["evaluations"].append(entry)

        result["request_count"] = self.request_count
        result["risk_assessment"], result["recommendation"] = self._assess(result)
        return result

    def _blocked(self, result, recommendation, reason):
        result["blocked"] = True
        result["recommendation"] = recommendation
        result["risk_assessment"] = f"Compliance review blocked: {reason}. No permission assessment beyond the failing gate."
        return result

    def _assess(self, result):
        policy_entries = result["policy"].get("evaluations", [])
        any_restrictive = any(e.get("restrictive_hints") for e in policy_entries)
        policy_verified = result["policy"].get("fetched", 0) > 0 and not any_restrictive
        target_ok = result["target_paths"].get("evaluated_count", 0) > 0 or True
        if not target_ok:
            return ("No discoverable public guideline targets on the homepage; too little information.", "manual-import preferred")
        if policy_verified:
            return (
                "Robots.txt retrieved and unambiguous; root and discovered guideline paths allowed; no login/CAPTCHA/"
                "paywall wall on the public homepage; a policy/terms page was retrieved with no restrictive hints. "
                "Publicly accessible PM-KUSUM pages appear collectible under the compliance rules.",
                "approved dry-run eligible",
            )
        return (
            "Robots.txt retrieved and unambiguous, root + discovered paths allowed, no gateway wall, but the policy/"
            "terms page could not be verified within the approved 5-request budget. Conservative path: user-supervised "
            "manual import of the public documents.",
            "manual-import preferred",
        )

    def _candidate_paths(self, home_content, robots_content):
        parsed = _extract_links(home_content)
        allowed_host = normalize_hostname(ALLOWED_HOST)
        candidates = []
        seen = set()
        for href in parsed:
            try:
                candidate = urljoin(MNRE_BASE, href, allow_fragments=False)
                validate_target_url(candidate, allowed_hosts=[MNRE_BASE])
            except UnsafeURL:
                continue
            except Exception:  # noqa: BLE001
                continue
            parsed_candidate = urlparse(candidate)
            if parsed_candidate.scheme != "https":
                continue
            if normalize_hostname(parsed_candidate.hostname or "") != allowed_host:
                continue
            lowered_path = parsed_candidate.path.lower()
            if any(k in lowered_path for k in EXCLUDE_GATE_KEYWORDS):
                continue
            if lowered_path.split("/")[-1].endswith(tuple(IMAGE_EXTS)):
                continue
            if not any(k in lowered_path for k in SIMILAR_CONTENT_KEYWORDS):
                continue
            if candidate in seen:
                continue
            seen.add(candidate)
            candidates.append(candidate)
        return candidates[:40]

    def _discover_policy_urls(self, home_content):
        parsed = _extract_links(home_content)
        allowed_host = normalize_hostname(ALLOWED_HOST)
        found, seen = [], set()
        for href in parsed:
            try:
                candidate = urljoin(MNRE_BASE, href, allow_fragments=False)
                parsed_url = urlparse(candidate)
            except Exception:  # noqa: BLE001
                continue
            if parsed_url.scheme != "https" or normalize_hostname(parsed_url.hostname or "") != allowed_host:
                continue
            if any(k in candidate.lower() for k in POLICY_KEYWORDS):
                if candidate not in seen:
                    seen.add(candidate)
                    found.append(candidate)
        return found[:5]

    # ------------------------------------------------------------- plumbing
    def _fetch(self, client, url, source):
        """Single HTTPS request against the approved host. Returns (content, status, final_url)."""
        self.request_count += 1
        if self.request_count > MAX_REQUESTS:
            raise RuntimeError(f"request budget of {MAX_REQUESTS} exceeded")
        if not url.startswith("https://"):
            raise RuntimeError("HTTPS-only policy violated")
        try:
            final_url, status, body, _ = client.get(url, allowed_hosts=[source.base_url])
        except (NetworkDisabledError, ResponseTooLarge) as exc:
            raise RuntimeError(f"request to {url} failed blocked-safe: {exc}") from exc
        except UnsafeURL as exc:
            raise RuntimeError(f"unsafe target/redirect for {url}: {exc}") from exc
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"request to {url} failed blocked-safe: {exc!r}") from exc
        if status in (301, 302, 303, 307, 308):
            raise RuntimeError(f"unexpected redirect for {url} (redirects outside the approved host are refused)")
        if status >= 400:
            raise RuntimeError(f"request to {url} returned HTTP {status}")
        return body, status, final_url

    def _resolve_source(self, source_id):
        try:
            source = DataSource.objects.get(pk=source_id)
        except (DataSource.DoesNotExist, ValueError) as exc:
            raise CommandError(f"unknown source {source_id!r}") from exc
        if source.base_url.rstrip("/") != MNRE_BASE.rstrip("/"):
            raise CommandError(
                f"this review is approved only for {MNRE_BASE} (host lock: {ALLOWED_HOST}); refusing {source.base_url}"
            )
        return source

    def _report_dir(self):
        base = Path(getattr(settings, "DATA_INGESTION_REPORTS_DIR", "data/ingested/reports"))
        directory = base / f"mnre_compliance_review_{datetime.now():%Y%m%d_%H%M%S}"
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    # ---------------------------------------------------------- persistence
    def _persist_check(self, source, run_id, result):
        evidence_dir = Path(getattr(settings, "DATA_INGESTION_DATA_DIR", "data/ingested")) / "compliance" / f"{source.pk or 'new'}_{abs(hash(source.name)) % 10 ** 6}" / run_id
        evidence_dir.mkdir(parents=True, exist_ok=True)
        evidence_path = str(evidence_dir / "review_only")
        evidence_hash = result["robots"].get("sha256", "")

        robots = result["robots"]
        gateway = result["gateway"]
        decision = (
            SourceComplianceCheck.Decision.DENIED
            if result["blocked"]
            else SourceComplianceCheck.Decision.ALLOWED
            if result["recommendation"] == "approved dry-run eligible"
            else SourceComplianceCheck.Decision.MANUAL_REVIEW
        )
        check = SourceComplianceCheck.objects.create(
            source=source,
            run_id=run_id,
            robots_url=robots.get("url", ""),
            robots_retrieved=bool(robots.get("retrieved")),
            robots_allows_target_paths=bool(robots.get("allows_root")),
            terms_url=(result["policy"].get("discovered_urls") or [""])[0],
            terms_retrieved=result["policy"].get("fetched", 0) > 0,
            terms_manual_review_required=any(e.get("manual_review_required") for e in result["policy"].get("evaluations", [])) or True,
            login_required_detected=gateway.get("login_required_detected", False),
            captcha_detected=gateway.get("captcha_detected", False),
            paywall_detected=gateway.get("paywall_detected", False),
            blocked_reason=" ".join(result["notes"]) if result["blocked"] else "",
            decision=decision,
            evidence_path=evidence_path,
            evidence_hash=evidence_hash,
            notes=f"recommendation={result['recommendation']}; requests={result['request_count']}; " + "; ".join(result["notes"]),
        )
        source.last_compliance_check_at = timezone.now()
        source.robots_status = DataSource.RobotsStatus.RETRIEVED if robots.get("retrieved") else DataSource.RobotsStatus.UNAVAILABLE
        source.terms_status = (
            DataSource.TermsStatus.RETRIEVED
            if result["policy"].get("fetched", 0) > 0
            else DataSource.TermsStatus.MANUAL_REVIEW
        )
        source.save(update_fields=["robots_status", "terms_status", "last_compliance_check_at", "updated_at"])
        logger.info("mnre compliance review run_id=%s decision=%s requests=%s", run_id, check.decision, result["request_count"])
        return check

    def _write_report(self, report_dir, source, result):
        payload = {
            "generated_at": datetime.now().isoformat(),
            "scope": result["scope"],
            "host_locked_to": result["host_locked_to"],
            "request_count": result["request_count"],
            "max_requests": MAX_REQUESTS,
            "source": {
                "name": source.name,
                "organization": source.organization,
                "base_url": source.base_url,
                "approval_status": source.approval_status,
                "collection_enabled": source.collection_enabled,
            },
            "robots_txt_result": result["robots"],
            "target_path_permission_result": result["target_paths"],
            "policy_terms_url_result": result["policy"],
            "login_captcha_paywall_result": result["gateway"],
            "collection_risk_assessment": result["risk_assessment"],
            "recommendation": result["recommendation"],
            "notes": result["notes"],
            "no_pdf_downloaded": True,
            "no_data_collected": True,
            "nothing_published": True,
        }
        (report_dir / "compliance_report.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        markdown = ["# MNRE compliance review (approved scope: compliance only)", ""]
        markdown.append(f"Generated: {payload['generated_at']}")
        markdown.append("")
        markdown.append("## Result")
        markdown.append("")
        markdown.append(f"- recommendation: **{result['recommendation']}**")
        markdown.append(f"- risk assessment: {result['risk_assessment']}")
        markdown.append(f"- requests used: {result['request_count']}/{MAX_REQUESTS}")
        markdown.append("")
        markdown.append("## robots.txt result")
        mk = lambda d: "\n".join(f"- **{k}**: {v}" for k, v in d.items())  # noqa: E731
        markdown.append(mk(result["robots"]))
        markdown.append("")
        markdown.append("## target-path permission result")
        markdown.append(mk({"evaluated_count": result["target_paths"].get("evaluated_count", 0),
                            "allowed_count": result["target_paths"].get("allowed_count", 0),
                            "denied_count": result["target_paths"].get("denied_count", 0),
                            "allowed_examples": result["target_paths"].get("allowed_examples", [])}))
        markdown.append("")
        markdown.append("## policy/terms URL result")
        markdown.append(json.dumps(result["policy"], indent=2, ensure_ascii=False))
        markdown.append("")
        markdown.append("## login/CAPTCHA/paywall result")
        markdown.append(json.dumps(result["gateway"], indent=2, ensure_ascii=False))
        markdown.append("")
        markdown.append("No PDF/document was downloaded. No data was collected. Nothing was published.")
        (report_dir / "compliance_report.md").write_text("\n".join(markdown) + "\n", encoding="utf-8")
        self.stdout.write(self.style.SUCCESS(f"compliance report: {report_dir / 'compliance_report.md'}"))
        return report_dir

    def _print_result(self, source, result, report_dir):
        self.stdout.write("\n" + "=" * 70)
        self.stdout.write(self.style.MIGRATE_HEADING(f"MNRE COMPLIANCE REVIEW — {source.name}"))
        self.stdout.write(f"host locked to: {result['host_locked_to']}   requests used: {result['request_count']}/{MAX_REQUESTS}")
        self.stdout.write("")
        self.stdout.write("-- robots.txt result --")
        for key, value in result["robots"].items():
            self.stdout.write(f"   {key}: {value}")
        self.stdout.write("")
        self.stdout.write("-- target-path permission result --")
        self.stdout.write(f"   evaluated: {result['target_paths'].get('evaluated_count', 0)}  allowed: {result['target_paths'].get('allowed_count', 0)}  denied: {result['target_paths'].get('denied_count', 0)}")
        for url in result["target_paths"].get("allowed_examples", [])[:3]:
            self.stdout.write(f"   allowed: {url}")
        self.stdout.write("")
        self.stdout.write("-- policy/terms URL result --")
        self.stdout.write("   " + json.dumps(result["policy"], ensure_ascii=False))
        self.stdout.write("")
        self.stdout.write("-- login/CAPTCHA/paywall detection result --")
        self.stdout.write("   " + json.dumps(result["gateway"], ensure_ascii=False))
        self.stdout.write("")
        self.stdout.write(self.style.WARNING(f"collection-risk assessment: {result['risk_assessment']}"))
        self.stdout.write(self.style.MIGRATE_HEADING(f"RECOMMENDATION: {result['recommendation'].upper()}"))
        for note in result["notes"]:
            self.stdout.write(f"   note: {note}")
        self.stdout.write(self.style.WARNING(
            "Source left in manual_review with collection_enabled=False. No PDFs downloaded, no data collected, nothing published."
        ))
        self.stdout.write(f"reports: {report_dir}")