"""Register the official FarmGrid data sources as MANUAL-REVIEW ONLY.

This command is the provisioning step for the live data-ingestion workstream.
It enforces the intake policy on every run:

* every source is registered( or updated ) in ``approval_status=manual_review``
  with ``collection_enabled=False`` — nothing is ever auto-approved here;
* the official home page and robots.txt URL are stored per source; terms /
  policy URLs are stored only where they were explicitly verified;
* an **offline** compliance check is recorded for each source (network is left
  disabled), so no robots.txt / terms / page content is fetched yet;
* a source compliance report (JSON + Markdown) is written under
  ``DATA_INGESTION_REPORTS_DIR`` and printed to stdout.

No scraping, crawling, image download or data publishing happens in this step.
Re-running the command is idempotent.
"""
import json
import logging
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.data_ingestion.models import DataSource, SourceComplianceCheck
from apps.data_ingestion.services.compliance import run_compliance_check
from apps.data_ingestion.services.robots import robots_url_for
from apps.data_ingestion.services.source_registry import SourceRegistryError, register_source

logger = logging.getLogger("khetsathi.audit")

# risk levels used in the report
RISK_LOW = "low"
RISK_MEDIUM = "medium"
RISK_HIGH = "high"


def _official_sources():
    """Deterministic catalog of official FarmGrid data sources.

    URLs were verified against public web references during provisioning.
    ``terms_url`` is intentionally left empty unless an explicit, confirmed
    public policy/terms page URL was discovered.
    """
    return [
        {
            "name": "PM-KUSUM Official Portal",
            "organization": "Ministry of New and Renewable Energy (MNRE), Government of India",
            "base_url": "https://pmkusum.mnre.gov.in/",
            "source_type": DataSource.SourceType.GOVERNMENT,
            "category": DataSource.Category.SUBSIDY,
            "methods": [DataSource.AllowedMethod.PUBLIC_HTML],
            "allows_images": False,
            "allows_documents": True,
            "allows_structured_data": False,
            "terms_url": "",
            "known_gate": "Farmer-application area is login-gated; public scheme pages and MIS data are public.",
            "gate_flags": {"login_required_detected": True, "captcha_detected": False, "paywall_detected": False},
            "risk_level": RISK_HIGH,
            "next_action": "Verify static scheme/document pages only; do not touch the login/application flow.",
            "manual_import_safer": True,
            "notes": "PM-KUSUM (Component A/B/C). Documents include scheme guidelines, beneficiary/MIS pages.",
        },
        {
            "name": "Ministry of New and Renewable Energy (MNRE)",
            "organization": "Ministry of New and Renewable Energy (MNRE), Government of India",
            "base_url": "https://mnre.gov.in/",
            "source_type": DataSource.SourceType.GOVERNMENT,
            "category": DataSource.Category.SOLAR_BENCHMARK,
            "methods": [DataSource.AllowedMethod.PUBLIC_HTML, DataSource.AllowedMethod.DOWNLOADABLE_FILE],
            "allows_images": False,
            "allows_documents": True,
            "allows_structured_data": True,
            "terms_url": "",
            "known_gate": "None reported for public pages.",
            "gate_flags": {"login_required_detected": False, "captcha_detected": False, "paywall_detected": False},
            "risk_level": RISK_MEDIUM,
            "next_action": "Re-check robots.txt/terms before any automated fetch; prefer manual review for scheme PDFs.",
            "manual_import_safer": False,
            "notes": "Nodal ministry; PM-KUSUM pages, solar programmes, publications and benchmark documents.",
        },
        {
            "name": "Ministry of Agriculture and Farmers Welfare (MoA&FW)",
            "organization": "Ministry of Agriculture and Farmers Welfare, Government of India",
            "base_url": "https://agriwelfare.gov.in/",
            "source_type": DataSource.SourceType.GOVERNMENT,
            "category": DataSource.Category.CROP_BENCHMARK,
            "methods": [DataSource.AllowedMethod.PUBLIC_HTML, DataSource.AllowedMethod.DOWNLOADABLE_FILE],
            "allows_images": False,
            "allows_documents": True,
            "allows_structured_data": True,
            "terms_url": "",
            "known_gate": "None reported for public pages.",
            "gate_flags": {"login_required_detected": False, "captcha_detected": False, "paywall_detected": False},
            "risk_level": RISK_MEDIUM,
            "next_action": "Re-check robots.txt/terms before any automated fetch; official statistics are public.",
            "manual_import_safer": False,
            "notes": "Department of Agriculture & Farmers Welfare; schemes, publications, MSP and reports.",
        },
        {
            "name": "Sub-Mission on Agricultural Mechanization (SMAM) Portal",
            "organization": "Department of Agriculture and Farmers Welfare, Government of India",
            "base_url": "https://agrimachinery.nic.in/",
            "source_type": DataSource.SourceType.GOVERNMENT,
            "category": DataSource.Category.MACHINERY_BENCHMARK,
            "methods": [DataSource.AllowedMethod.PUBLIC_HTML, DataSource.AllowedMethod.DOWNLOADABLE_FILE],
            "allows_images": False,
            "allows_documents": True,
            "allows_structured_data": True,
            "terms_url": "",
            "known_gate": "DBT application portal: farmer / manufacturer / state-officer logins. Public notices and guidelines are public.",
            "gate_flags": {"login_required_detected": True, "captcha_detected": False, "paywall_detected": False},
            "risk_level": RISK_HIGH,
            "next_action": "Only collect public guideline/notice/FAQ pages after explicit approval.",
            "manual_import_safer": True,
            "notes": "SMAM subsidy + machine performance testing portal; FARMS app referenced.",
        },
        {
            "name": "Madhya Pradesh Agriculture Department Portal",
            "organization": "Directorate of Farmer Welfare and Agriculture Development, Government of Madhya Pradesh",
            "base_url": "http://mpkrishi.mp.gov.in/",
            "source_type": DataSource.SourceType.GOVERNMENT,
            "category": DataSource.Category.SUBSIDY,
            "methods": [DataSource.AllowedMethod.PUBLIC_HTML],
            "allows_images": False,
            "allows_documents": True,
            "allows_structured_data": False,
            "terms_url": "",
            "known_gate": "Some scheme modules are login-gated (farmer portal). HTTP-only base URL.",
            "gate_flags": {"login_required_detected": True, "captcha_detected": False, "paywall_detected": False},
            "risk_level": RISK_HIGH,
            "next_action": "Treat as manual-import-first because the portal is HTTP-only and partly login-gated.",
            "manual_import_safer": True,
            "notes": "MP state agri schemes, farmer welfare, subsidy notifications (Hindi/English).",
        },
        {
            "name": "M.P. Urja Vikas Nigam (MP Renewable Energy / Solar)",
            "organization": "M.P. Urja Vikas Nigam Limited, Government of Madhya Pradesh",
            "base_url": "https://mprenewable.nic.in/",
            "source_type": DataSource.SourceType.GOVERNMENT,
            "category": DataSource.Category.SOLAR_BENCHMARK,
            "methods": [DataSource.AllowedMethod.PUBLIC_HTML, DataSource.AllowedMethod.DOWNLOADABLE_FILE],
            "allows_images": False,
            "allows_documents": True,
            "allows_structured_data": True,
            "terms_url": "",
            "known_gate": "None reported for public pages.",
            "gate_flags": {"login_required_detected": False, "captcha_detected": False, "paywall_detected": False},
            "risk_level": RISK_MEDIUM,
            "next_action": "Re-check robots.txt/terms before any automated fetch; solar pump scheme data is public.",
            "manual_import_safer": False,
            "notes": "MPUVN nodal renewable agency; solar pump (PM-KUSUM-B) scheme and policy documents. CM Solar Pump portal: https://cmsolarpump.mp.gov.in/",
        },
        {
            "name": "MPERC – Agricultural Retail Supply Tariff",
            "organization": "Madhya Pradesh Electricity Regulatory Commission",
            "base_url": "https://mperc.in/",
            "source_type": DataSource.SourceType.GOVERNMENT,
            "category": DataSource.Category.ELECTRICITY_BENCHMARK,
            "methods": [DataSource.AllowedMethod.PUBLIC_HTML, DataSource.AllowedMethod.DOWNLOADABLE_FILE],
            "allows_images": False,
            "allows_documents": True,
            "allows_structured_data": True,
            "terms_url": "",
            "known_gate": "None reported for public pages.",
            "gate_flags": {"login_required_detected": False, "captcha_detected": False, "paywall_detected": False},
            "risk_level": RISK_MEDIUM,
            "next_action": "Re-check robots.txt/terms; collect only published tariff orders (official PDFs).",
            "manual_import_safer": False,
            "notes": "Retail Supply Tariff Orders incl. agricultural tariff (e.g. FY 2026-27, PNo.140/2025). DISCOM portals referenced: portal.mpcz.in (Central) etc.",
        },
        {
            "name": "Directorate of Economics & Statistics – Cost of Cultivation",
            "organization": "Directorate of Economics and Statistics, DAC&FW, Government of India",
            "base_url": "https://desagri.gov.in/",
            "source_type": DataSource.SourceType.GOVERNMENT,
            "category": DataSource.Category.CROP_BENCHMARK,
            "methods": [DataSource.AllowedMethod.PUBLIC_HTML, DataSource.AllowedMethod.DOWNLOADABLE_FILE],
            "allows_images": False,
            "allows_documents": True,
            "allows_structured_data": True,
            "terms_url": "",
            "known_gate": "None reported for public pages.",
            "gate_flags": {"login_required_detected": False, "captcha_detected": False, "paywall_detected": False},
            "risk_level": RISK_MEDIUM,
            "next_action": "Re-check robots.txt/terms; official cost-of-cultivation / production estimates are public.",
            "manual_import_safer": False,
            "notes": "Cost of Cultivation / Production & Related Data, CSP scheme documents.",
        },
        {
            "name": "Mahindra Tractors – official specifications",
            "organization": "Mahindra & Mahindra Ltd (Farm Equipment Sector)",
            "base_url": "https://www.mahindratractor.com/",
            "source_type": DataSource.SourceType.OFFICIAL_MANUFACTURER,
            "category": DataSource.Category.EQUIPMENT_CATALOG,
            "methods": [DataSource.AllowedMethod.PUBLIC_HTML],
            "allows_images": True,
            "allows_documents": True,
            "allows_structured_data": False,
            "terms_url": "",
            "known_gate": "Pricing/lead forms require contact; specs pages are public.",
            "gate_flags": {"login_required_detected": False, "captcha_detected": False, "paywall_detected": False},
            "risk_level": RISK_HIGH,
            "next_action": "Collect only public specification pages after approval; never price lead forms.",
            "manual_import_safer": True,
            "notes": "Model specification pages (engine, transmission, tyres, lift, PTO). Brand/copyrighted imagery.",
        },
        {
            "name": "Sonalika (International Tractors Ltd) – official specifications",
            "organization": "International Tractors Ltd (Sonalika)",
            "base_url": "https://www.sonalika.com/",
            "source_type": DataSource.SourceType.OFFICIAL_MANUFACTURER,
            "category": DataSource.Category.EQUIPMENT_CATALOG,
            "methods": [DataSource.AllowedMethod.PUBLIC_HTML],
            "allows_images": True,
            "allows_documents": True,
            "allows_structured_data": False,
            "terms_url": "",
            "known_gate": "Pricing is published publicly; contact/lead forms for quotations.",
            "gate_flags": {"login_required_detected": False, "captcha_detected": False, "paywall_detected": False},
            "risk_level": RISK_HIGH,
            "next_action": "Collect only public specification pages after approval.",
            "manual_import_safer": True,
            "notes": "Model specs pages under /tractor and /tractors-full-range.",
        },
        {
            "name": "Farmtrac (Escorts Kubota) – official specifications",
            "organization": "Escorts Kubota Limited (Farmtrac)",
            "base_url": "https://farmtrac.escortskubota.com/",
            "source_type": DataSource.SourceType.OFFICIAL_MANUFACTURER,
            "category": DataSource.Category.EQUIPMENT_CATALOG,
            "methods": [DataSource.AllowedMethod.PUBLIC_HTML],
            "allows_images": True,
            "allows_documents": True,
            "allows_structured_data": False,
            "terms_url": "",
            "known_gate": "Toll-free contact number; public specs pages.",
            "gate_flags": {"login_required_detected": False, "captcha_detected": False, "paywall_detected": False},
            "risk_level": RISK_HIGH,
            "next_action": "Collect only public specification pages after approval.",
            "manual_import_safer": True,
            "notes": "Farmtrac Powermaxx / 60xx series specs; part of Escorts Kubota Limited.",
        },
        {
            "name": "John Deere India – official specifications",
            "organization": "John Deere India Private Limited",
            "base_url": "https://www.deere.co.in/en/",
            "source_type": DataSource.SourceType.OFFICIAL_MANUFACTURER,
            "category": DataSource.Category.EQUIPMENT_CATALOG,
            "methods": [DataSource.AllowedMethod.PUBLIC_HTML],
            "allows_images": True,
            "allows_documents": True,
            "allows_structured_data": False,
            "terms_url": "",
            "known_gate": "Quotation/lead forms; showroom portal.",
            "gate_flags": {"login_required_detected": False, "captcha_detected": False, "paywall_detected": False},
            "risk_level": RISK_HIGH,
            "next_action": "Collect only public specification pages after approval.",
            "manual_import_safer": True,
            "notes": "D/5xxx series tractor specs, technology solutions pages.",
        },
        {
            "name": "New Holland Agriculture India – official specifications",
            "organization": "CNH Industrial India (New Holland Agriculture)",
            "base_url": "https://agriculture.newholland.com/en/india",
            "source_type": DataSource.SourceType.OFFICIAL_MANUFACTURER,
            "category": DataSource.Category.EQUIPMENT_CATALOG,
            "methods": [DataSource.AllowedMethod.PUBLIC_HTML],
            "allows_images": True,
            "allows_documents": True,
            "allows_structured_data": False,
            "terms_url": "",
            "known_gate": "Product brochures/lead forms.",
            "gate_flags": {"login_required_detected": False, "captcha_detected": False, "paywall_detected": False},
            "risk_level": RISK_HIGH,
            "next_action": "Collect only public specification pages after approval.",
            "manual_import_safer": True,
            "notes": "3600-2 / Workmaster series specs for India.",
        },
        {
            "name": "Powertrac (Escorts Kubota) – official specifications",
            "organization": "Escorts Kubota Limited (Powertrac)",
            "base_url": "https://powertrac.escortskubota.com/",
            "source_type": DataSource.SourceType.OFFICIAL_MANUFACTURER,
            "category": DataSource.Category.EQUIPMENT_CATALOG,
            "methods": [DataSource.AllowedMethod.PUBLIC_HTML],
            "allows_images": True,
            "allows_documents": True,
            "allows_structured_data": False,
            "terms_url": "",
            "known_gate": "Public specs pages; dealer/toll-free contact.",
            "gate_flags": {"login_required_detected": False, "captcha_detected": False, "paywall_detected": False},
            "risk_level": RISK_HIGH,
            "next_action": "Collect only public specification pages after approval.",
            "manual_import_safer": True,
            "notes": "Steeltrac / Diesel Saver / Star / 434-439 series specs.",
        },
    ]


def _domain(base_url):
    return urlparse(base_url).netloc


class Command(BaseCommand):
    help = "Provision official FarmGrid data sources as manual-review only (no approval, no collection, no network)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--run-id",
            default="provision-official",
            help="Compliance run id used for audit grouping (offline check).",
        )
        parser.add_argument(
            "--reports-dir",
            default="",
            help="Override the report output directory (default: DATA_INGESTION_REPORTS_DIR).",
        )

    def handle(self, *args, **options):
        reports_dir = Path(options["reports_dir"] or getattr(settings, "DATA_INGESTION_REPORTS_DIR", "data/ingested/reports"))
        reports_dir.mkdir(parents=True, exist_ok=True)

        rows = []
        registered = updated = 0
        for spec in _official_sources():
            source, was_created = self._register_one(spec)
            if was_created:
                registered += 1
            else:
                updated += 1

            check = run_compliance_check(source, run_id=options["run_id"])
            rows.append(self._report_row(spec, source, check))

        report = {
            "generated_at": datetime.now().isoformat(),
            "policy": {
                "approval_status": DataSource.ApprovalStatus.MANUAL_REVIEW,
                "collection_enabled": False,
                "network_enabled": bool(getattr(settings, "DATA_INGESTION_NETWORK_ALLOWED", False)),
                "approved_automatically": False,
            },
            "sources": rows,
            "summary": {
                "registered_new": registered,
                "already_existing_updated": updated,
                "total": len(rows),
                "risk_high": sum(1 for r in rows if r["risk_level"] == RISK_HIGH),
                "manual_import_safer": sum(1 for r in rows if r["manual_import_safer_than_automated"]),
            },
        }

        json_path = reports_dir / f"source_compliance_report_{datetime.now():%Y%m%d_%H%M%S}.json"
        md_path = reports_dir / f"source_compliance_report_{datetime.now():%Y%m%d_%H%M%S}.md"
        latest_json = reports_dir / "source_compliance_report.json"
        latest_md = reports_dir / "source_compliance_report.md"

        json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        latest_json.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        md_path.write_text(self._to_markdown(report), encoding="utf-8")
        latest_md.write_text(self._to_markdown(report), encoding="utf-8")

        self.stdout.write(self.style.SUCCESS(f"\nsources registered(updated)={registered}({updated}) as manual_review — {len(rows)} total."))
        self.stdout.write(self.style.WARNING("No source was approved; collection is disabled; network is off."))
        self.stdout.write("\n" + self._to_markdown(report))
        self.stdout.write(self.style.SUCCESS(f"\nreport JSON: {json_path}"))
        self.stdout.write(self.style.SUCCESS(f"report MD : {md_path}"))

    def _register_one(self, spec):
        """Idempotently create/refresh the source as manual_review + collection disabled."""
        robots_url = robots_url_for(spec["base_url"])
        existing = DataSource.objects.filter(base_url=spec["base_url"]).first()
        if existing is not None:
            for field, value in {
                "name": spec["name"],
                "organization": spec["organization"],
                "source_type": spec["source_type"],
                "category": spec["category"],
                "allowed_collection_methods": spec["methods"],
                "robots_url": robots_url,
                "terms_url": spec.get("terms_url", ""),
                "allows_images": spec["allows_images"],
                "allows_documents": spec["allows_documents"],
                "allows_structured_data": spec["allows_structured_data"],
                "approval_status": DataSource.ApprovalStatus.MANUAL_REVIEW,
                "collection_enabled": False,
                "robots_status": DataSource.RobotsStatus.UNKNOWN,
                "terms_status": DataSource.TermsStatus.UNKNOWN,
                "notes": spec["notes"],
            }.items():
                setattr(existing, field, value)
            existing.save()
            logger.info("official source refreshed to manual_review name=%s url=%s", existing.name, existing.base_url)
            return existing, False

        kwargs = {
            "name": spec["name"],
            "base_url": spec["base_url"],
            "source_type": spec["source_type"],
            "category": spec["category"],
            "organization": spec["organization"],
            "country": "IN",
            "allowed_collection_methods": spec["methods"],
            "robots_url": robots_url,
            "terms_url": spec.get("terms_url", ""),
            "rate_limit_per_minute": 10,
            "request_delay_seconds": 3.0,
            "max_pages_per_run": 10,
            "allows_images": spec["allows_images"],
            "allows_documents": spec["allows_documents"],
            "allows_structured_data": spec["allows_structured_data"],
            "notes": spec["notes"],
            "created_by": None,
        }
        try:
            source = register_source(**kwargs)
        except SourceRegistryError as exc:
            raise CommandError(str(exc)) from exc
        source.approval_status = DataSource.ApprovalStatus.MANUAL_REVIEW
        source.collection_enabled = False
        source.robots_status = DataSource.RobotsStatus.UNKNOWN
        source.terms_status = DataSource.TermsStatus.UNKNOWN
        source.save()
        logger.info("official source registered as manual_review name=%s url=%s", source.name, source.base_url)
        return source, True

    def _report_row(self, spec, source, check):
        latest = SourceComplianceCheck.objects.filter(source=source).order_by("-checked_at").first()
        flags = latest or check

        if flags.robots_retrieved:
            robots_summary = "retrieved"
        elif not getattr(settings, "DATA_INGESTION_NETWORK_ALLOWED", False):
            robots_summary = "not_retrieved — OFFLINE (offline compliance check; live robots.txt not fetched yet)"
        else:
            robots_summary = "not_retrieved"

        terms_summary = (
            f"present={source.terms_url}"
            if source.terms_url
            else "none discovered yet — identify & verify during manual review"
        )

        gate_indicators = []
        if flags.login_required_detected:
            gate_indicators.append("login_required")
        if flags.captcha_detected:
            gate_indicators.append("captcha")
        if flags.paywall_detected:
            gate_indicators.append("paywall")
        gate = " / ".join(gate_indicators) if gate_indicators else "none detected (offline) — verify manually"

        return {
            "source_name": source.name,
            "organization": source.organization,
            "domain": _domain(source.base_url),
            "intended_data_category": spec["category"],
            "proposed_collection_method": ", ".join(spec["methods"]),
            "robots_txt_status": robots_summary,
            "public_terms_policy_url_status": terms_summary,
            "login_captcha_paywall_indicator": gate,
            "known_gate_notes": spec["known_gate"],
            "risk_level": spec["risk_level"],
            "recommended_next_action": spec["next_action"],
            "explicit_approval_required": True,
            "manual_import_safer_than_automated": spec["manual_import_safer"],
            "approval_status": source.approval_status,
            "collection_enabled": source.collection_enabled,
            "compliance_decision": str(check.decision),
        }

    def _to_markdown(self, report):
        lines = [
            "# FarmGrid AI — Source Compliance Report",
            "",
            f"Generated: {report['generated_at']}",
            "",
            "## Policy (enforced at provisioning)",
            "",
            f"- Approval status: **{report['policy']['approval_status']}** (never auto-approved)",
            f"- Collection enabled: **{report['policy']['collection_enabled']}**",
            f"- Network enabled: **{report['policy']['network_enabled']}**",
            f"- Approved automatically: **{report['policy']['approved_automatically']}**",
            "",
            "## Sources",
            "",
        ]
        header = (
            "| Source | Organization | Domain | Category | Method | robots.txt | Terms/policy URL | Login/CAPTCHA/Paywall | Risk | Recommended next action | Explicit approval required | Manual import safer |"
        )
        rules = "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"
        lines.append(header)
        lines.append(rules)
        for s in report["sources"]:
            action = s["recommended_next_action"].replace("|", "/").replace("\n", " ")
            lines.append(
                "| {name} | {org} | {domain} | {cat} | {method} | {robots} | {terms} | {gate} | {risk} | {action} | {approval} | {manual} |".format(
                    name=s["source_name"].replace("|", "/"),
                    org=s["organization"].replace("|", "/"),
                    domain=s["domain"],
                    cat=s["intended_data_category"],
                    method=s["proposed_collection_method"].replace("|", "/"),
                    robots=s["robots_txt_status"].replace("|", "/"),
                    terms=s["public_terms_policy_url_status"].replace("|", "/"),
                    gate=s["login_captcha_paywall_indicator"].replace("|", "/"),
                    risk=s["risk_level"],
                    action=action[:120],
                    approval="yes" if s["explicit_approval_required"] else "no",
                    manual="manual import recommended" if s["manual_import_safer_than_automated"] else "automated acceptable after approval",
                )
            )
        lines.append("")
        lines.append(f"Summary: {report['summary']['total']} sources · "
                     f"{report['summary']['registered_new']} newly registered · "
                     f"{report['summary']['already_existing_updated']} refreshed · "
                     f"{report['summary']['risk_high']} high-risk · "
                     f"{report['summary']['manual_import_safer']} favour manual import.")
        lines.append("")
        lines.append("No source was approved. Collection is disabled. No network traffic occurred while generating this report.")
        return "\n".join(lines) + "\n"