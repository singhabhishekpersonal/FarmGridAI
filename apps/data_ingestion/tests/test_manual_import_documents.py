"""Manual-import workflow tests (fully offline; never touch the network)."""
import io
import json
from datetime import date

import pytest
from django.conf import settings
from django.core.management import call_command

from apps.data_ingestion.management.commands import import_manual_documents as cmd
from apps.data_ingestion.models import (
    CollectedArtifact,
    DataReviewQueue,
    DataSource,
    ExtractedRecord,
    IngestionRun,
)
from apps.subsidies.models import SubsidyScheme


def make_pdf(text=b""):
    from pypdf import PdfWriter

    buffer = io.BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    writer.write(buffer)
    return buffer.getvalue()


def write_document(folder, name, pdf_bytes, manifest, manifest_name=None):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_bytes(pdf_bytes)
    path = folder / (manifest_name or name.replace(".pdf", ".manifest.json"))
    path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    return folder / name


def good_manifest(name, **overrides):
    manifest = {
        "file": name,
        "document_title": "Operational Guidelines for PM-KUSUM Component-A (Standalone Solar Pumps)",
        "source_url": "https://mnre.gov.in/bio-energy/schemes/pm-kusum",
        "document_url": "https://mnre.gov.in/sites/default/files/uploads/pm-kusum-guidelines-2023.pdf",
        "source_organization": "Ministry of New and Renewable Energy (MNRE), Government of India",
        "retrieval_date": "2026-09-24",
        "source_attribution": "MNRE PM-KUSUM operational guidelines (public government document)",
        "permission_license_note": "Public government document; freely downloadable; no reuse restrictions stated",
    }
    manifest.update(overrides)
    return manifest


class TestExtraction:
    def test_keys_are_whitelist_only(self):
        extracted = cmd.extract_official_scheme_fields("to farmers are eligible for subsidy", source_url="https://mnre.gov.in/x")
        assert set(extracted) == set(cmd.EXTRACT_FIELD_NAMES)
        assert not any("benefit_min" in k or "cost" in k for k in extracted)

    def test_no_inference_when_absent(self):
        extracted = cmd.extract_official_scheme_fields(
            "PM-KUSUM promotes solar pumps in rural India.",
            source_url="https://mnre.gov.in/x",
            document_title="Guidelines",
        )
        assert extracted["scheme_name"] == "Guidelines"
        for field in (
            "official_eligibility_wording",
            "official_benefit_subsidy_wording",
            "official_document_requirements",
            "official_application_procedure_wording",
            "amendment_version_information",
            "official_caveats_exceptions_wording",
        ):
            assert extracted[field] == []
        assert extracted["effective_date"] == ""

    def test_captures_verbatim_wording(self):
        text = (
            "Component-A Guidelines for standalone solar pumps.\n"
            "Farmer or group of farmers is eligible for the scheme.\n"
            "The commission shall provide subsidy of 30% of the capital cost.\n"
            "Applicant must submit self-attested documents and bank passbook.\n"
            "The application may be submitted online through the district portal.\n"
            "These guidelines are effective from 01/04/2023.\n"
            "Issued vide notification no. 12/2023 as amended."
        )
        extracted = cmd.extract_official_scheme_fields(text, source_url="https://mnre.gov.in/guidelines")
        assert extracted["scheme_component"] != []
        assert any("eligible" in s for s in extracted["official_eligibility_wording"])
        assert any("30% of the capital cost" in s for s in extracted["official_benefit_subsidy_wording"])
        assert any("bank passbook" in s for s in extracted["official_document_requirements"])
        assert any("online" in s for s in extracted["official_application_procedure_wording"])
        assert extracted["effective_date"] == "2023-04-01"
        assert any("amended" in s for s in extracted["amendment_version_information"])

    def test_does_not_invent_subsidy_amounts_in_absent_docs(self):
        # A subsidy percentage present in the source is copied verbatim; none
        # is ever computed/inferred when the document does not state one.
        text = "Farmers in drought-prone districts receive a grant under the solar pump scheme."
        extracted = cmd.extract_official_scheme_fields(text, source_url="https://mnre.gov.in/x")
        assert any("grant" in s for s in extracted["official_benefit_subsidy_wording"])

    def test_captures_caveats_and_exceptions_verbatim(self):
        text = (
            "Subject to the condition that the beneficiary owns the land.\n"
            "However, farmers who already hold an electric connection are not eligible.\n"
            "This exception applies only to scheduled areas.\n"
            "Subsidy is provided subject to budget availability."
        )
        extracted = cmd.extract_official_scheme_fields(text, source_url="https://mnre.gov.in/x")
        caveats = extracted["official_caveats_exceptions_wording"]
        assert caveats
        assert any("not eligible" in s for s in caveats)
        assert any("subject to" in s for s in caveats)


class TestValidation:
    pytestmark = pytest.mark.django_db

    def test_rejects_non_pdf_extension(self, tmp_path):
        p = tmp_path / "doc.txt"
        p.write_bytes(make_pdf())
        result = cmd.validate_document(p, good_manifest("doc.txt"))
        assert result["ok"] is False
        assert not result["checks"]["extension"][0]

    def test_rejects_bad_magic_bytes(self, tmp_path):
        p = tmp_path / "doc.pdf"
        p.write_bytes(b"NOT A PDF AT ALL")
        result = cmd.validate_document(p, good_manifest("doc.pdf"))
        assert not result["checks"]["mime_type"][0]
        assert not result["checks"]["pdf_integrity"][0]

    def test_rejects_sha_mismatch(self, tmp_path):
        pdf = make_pdf()
        p = tmp_path / "doc.pdf"
        p.write_bytes(pdf)
        manifest = good_manifest("doc.pdf", expected_sha256="0" * 64)
        result = cmd.validate_document(p, manifest)
        assert not result["checks"]["sha256"][0]

    def test_sha256_matches(self, tmp_path):
        pdf = make_pdf()
        p = tmp_path / "doc.pdf"
        p.write_bytes(pdf)
        from apps.data_ingestion.services.hashing import sha256_of_bytes

        manifest = good_manifest("doc.pdf", expected_sha256=sha256_of_bytes(pdf))
        result = cmd.validate_document(p, manifest)
        assert result["ok"] is True
        assert result["checks"]["sha256"][0]

    def test_rejects_future_retrieval_date(self, tmp_path):
        p = tmp_path / "doc.pdf"
        p.write_bytes(make_pdf())
        result = cmd.validate_document(p, good_manifest("doc.pdf", retrieval_date="2099-01-01"))
        assert not result["checks"]["retrieval_date"][0]

    def test_rejects_http_source_url(self, tmp_path):
        p = tmp_path / "doc.pdf"
        p.write_bytes(make_pdf())
        result = cmd.validate_document(p, good_manifest("doc.pdf", source_url="http://mnre.gov.in/x"))
        assert not result["checks"]["source_url"][0]

    def test_requires_every_attribution_field(self, tmp_path):
        p = tmp_path / "doc.pdf"
        p.write_bytes(make_pdf())
        result = cmd.validate_document(p, good_manifest("doc.pdf", source_attribution="", permission_license_note=""))
        assert result["ok"] is False
        assert any(not result["checks"][k][0] for k in ("source_attribution", "permission_license_note"))

    def test_valid_document_passes(self, tmp_path):
        p = tmp_path / "doc.pdf"
        p.write_bytes(make_pdf())
        result = cmd.validate_document(p, good_manifest("doc.pdf"), now=date(2026, 9, 24))
        assert result["ok"] is True
        for key, (passed, _) in result["checks"].items():
            assert passed, key

    def test_requires_document_url(self, tmp_path):
        p = tmp_path / "doc.pdf"
        p.write_bytes(make_pdf())
        result = cmd.validate_document(p, good_manifest("doc.pdf", document_url=""))
        assert result["ok"] is False
        assert not result["checks"]["document_url"][0]

    def test_rejects_non_gov_document_url(self, tmp_path):
        p = tmp_path / "doc.pdf"
        p.write_bytes(make_pdf())
        result = cmd.validate_document(p, good_manifest("doc.pdf", document_url="https://example.com/doc.pdf"))
        assert result["ok"] is False
        assert not result["checks"]["document_url"][0]

    def test_optional_official_reference_url_absent_ok(self, tmp_path):
        p = tmp_path / "doc.pdf"
        p.write_bytes(make_pdf())
        result = cmd.validate_document(p, good_manifest("doc.pdf", official_reference_url=""))
        assert result["ok"] is True

    def test_official_reference_url_requires_gov_domain(self, tmp_path):
        p = tmp_path / "doc.pdf"
        p.write_bytes(make_pdf())
        result = cmd.validate_document(p, good_manifest("doc.pdf", official_reference_url="https://cdn.example.net/ref.pdf"))
        assert not result["checks"]["official_reference_url"][0]


class TestCommandWorkflow:
    def _make_import_dir(self, tmp_path, pdf_bytes, manifest):
        folder = tmp_path / "imports"
        write_document(folder, "guidelines-a.pdf", pdf_bytes, manifest)
        return folder

    @pytest.fixture(autouse=True)
    def _sandbox_settings(self, tmp_path, monkeypatch, db):
        monkeypatch.setattr(settings, "DATA_INGESTION_NETWORK_ALLOWED", False)
        monkeypatch.setattr(settings, "DATA_INGESTION_REPORTS_DIR", str(tmp_path / "reports"))
        monkeypatch.setattr(settings, "DATA_INGESTION_DATA_DIR", str(tmp_path / "ingested"))

    def test_import_creates_artifact_record_queue_no_publish(self, tmp_path, monkeypatch):
        from django.contrib.auth import get_user_model

        get_user_model().objects.create_user(username="op1", password="Str0ng!")
        folder = self._make_import_dir(tmp_path, make_pdf(), good_manifest("guidelines-a.pdf"))
        call_command("import_manual_documents", "--folder", str(folder), "--operator-user", "op1")

        source = DataSource.objects.get(source_type="manual_import", name="PM-KUSUM Official Documents (manual import)")
        assert source.approval_status == DataSource.ApprovalStatus.MANUAL_REVIEW
        assert source.collection_enabled is False

        artifact = CollectedArtifact.objects.get(source=source)
        assert artifact.artifact_type == "pdf"
        assert artifact.validation_status == CollectedArtifact.ValidationStatus.VALID
        assert artifact.http_status == 0
        pdf_bytes = make_pdf()
        with open(artifact.local_path, "rb") as handle:
            stored = handle.read()
        assert stored == pdf_bytes

        record = ExtractedRecord.objects.get(source=source)
        payload = record.normalized_data_json
        assert payload["preliminary"] is True
        assert payload["needs_official_verification"] is True
        assert payload["requires_human_review"] is True
        assert payload["status"] == "preliminary"
        assert payload["source_url"].startswith("https://")

        queue = DataReviewQueue.objects.get(extracted_record=record)
        assert queue.decision == DataReviewQueue.Decision.PENDING
        assert queue.requires_human_review is True
        assert queue.risk_level == DataReviewQueue.RiskLevel.HIGH
        assert queue.proposed_target_model == "SubsidyScheme"
        assert SubsidyScheme.objects.count() == 0

        assert list((tmp_path / "reports").rglob("extracted_record_summary.json"))
        assert list((tmp_path / "reports").rglob("provenance_report.json"))
        assert list((tmp_path / "reports").rglob("import_validation_report.json"))
        assert list((tmp_path / "reports").rglob("duplicate_report.json"))
        assert list((tmp_path / "reports").rglob("review_queue_export.json"))
        assert list((tmp_path / "reports").rglob("manifest_validation_report.json"))
        assert list((tmp_path / "reports").rglob("pdf_integrity_checksum_report.json"))
        assert list((tmp_path / "reports").rglob("online_verification_report.json"))
        assert list((tmp_path / "reports").rglob("fields_requiring_manual_verification.json"))
        assert list((tmp_path / "reports").rglob("records_not_safe_to_publish.json"))
        assert list((tmp_path / "reports").rglob("online_verification_unavailable.json"))
        assert list((tmp_path / "reports").rglob("final_import_status_report.json"))

        final = json.loads(next((tmp_path / "reports").rglob("final_import_status_report.json").__iter__()).read_text(encoding="utf-8"))
        assert final["end_of_run_safety_checklist"]["no_live_publication"] is True
        assert final["end_of_run_safety_checklist"]["original_pdfs_unchanged"] is True

    def test_duplicate_document_not_reimported(self, tmp_path):
        from django.contrib.auth import get_user_model

        get_user_model().objects.create_user(username="op2", password="Str0ng!")
        folder = self._make_import_dir(tmp_path, make_pdf(), good_manifest("guidelines-a.pdf"))
        call_command("import_manual_documents", "--folder", str(folder), "--operator-user", "op2")
        call_command("import_manual_documents", "--folder", str(folder), "--operator-user", "op2")

        source = DataSource.objects.get(source_type="manual_import", name="PM-KUSUM Official Documents (manual import)")
        assert CollectedArtifact.objects.filter(source=source).count() == 1
        assert ExtractedRecord.objects.filter(source=source).count() == 1
        latest_run = IngestionRun.objects.filter(source=source).order_by("-started_at").first()
        assert latest_run.duplicates_skipped == 1

    def test_missing_manifest_is_validation_failure(self, tmp_path):
        from django.contrib.auth import get_user_model

        get_user_model().objects.create_user(username="op3", password="Str0ng!")
        folder = tmp_path / "imports"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "guidelines-a.pdf").write_bytes(make_pdf())
        call_command("import_manual_documents", "--folder", str(folder), "--operator-user", "op3")

        source = DataSource.objects.filter(name="PM-KUSUM Official Documents (manual import)").first()
        assert CollectedArtifact.objects.filter(source=source).count() == 0
        run = IngestionRun.objects.filter(source=source).order_by("-started_at").first()
        assert run.validation_failures == 1

    def test_refuses_to_run_with_network_enabled(self, tmp_path, monkeypatch):
        monkeypatch.setattr(settings, "DATA_INGESTION_NETWORK_ALLOWED", True)
        from django.core.management import CommandError

        with pytest.raises(CommandError):
            call_command("import_manual_documents", "--folder", str(tmp_path))

    def test_verify_online_without_network_is_refused(self, tmp_path, monkeypatch):
        from django.core.management import CommandError

        with pytest.raises(CommandError):
            call_command(
                "import_manual_documents", "--folder", str(tmp_path), "--operator-user", "nobody",
                "--verify-online",
            )

    def test_verify_online_blocked_urls_still_import(self, tmp_path, monkeypatch):
        from django.contrib.auth import get_user_model

        get_user_model().objects.create_user(username="op5", password="Str0ng!")
        monkeypatch.setattr(settings, "DATA_INGESTION_NETWORK_ALLOWED", True)

        def _raise(url):
            raise ConnectionError("simulated blocked host")

        monkeypatch.setattr(cmd.Command, "_fetch_verification", staticmethod(_raise))

        folder = self._make_import_dir(tmp_path, make_pdf(), good_manifest("guidelines-a.pdf"))
        call_command(
            "import_manual_documents", "--folder", str(folder), "--operator-user", "op5",
            "--verify-online",
        )

        source = DataSource.objects.get(source_type="manual_import", name="PM-KUSUM Official Documents (manual import)")
        record = ExtractedRecord.objects.get(source=source)
        queue = DataReviewQueue.objects.get(extracted_record=record)
        online = queue.validation_result["online_verification"]
        assert online["overall"] == "blocked"
        assert any("online verification" in lim for lim in queue.validation_result.get("limitations", []))
        assert SubsidyScheme.objects.count() == 0

        report = json.loads(next((tmp_path / "reports").rglob("online_verification_report.json").__iter__()).read_text(encoding="utf-8"))
        assert report["documents"][0]["online_verification"] == "blocked"
        unverified = json.loads(next((tmp_path / "reports").rglob("online_verification_unavailable.json").__iter__()).read_text(encoding="utf-8"))
        assert unverified["documents"][0]["file"] == "guidelines-a.pdf"

    def test_custom_source_name_registers_isolated_manual_source(self, tmp_path):
        from django.contrib.auth import get_user_model

        get_user_model().objects.create_user(username="op4", password="Str0ng!")
        folder = self._make_import_dir(tmp_path, make_pdf(), good_manifest("guidelines-a.pdf"))
        call_command(
            "import_manual_documents",
            "--folder", str(folder),
            "--operator-user", "op4",
            "--source-name", "MNRE Official Documents (manual import)",
            "--source-base-url", "manual://mnre-official-documents",
            "--organization", "Ministry of New and Renewable Energy (MNRE), Government of India",
        )

        source = DataSource.objects.get(source_type="manual_import", name="MNRE Official Documents (manual import)")
        assert source.base_url == "manual://mnre-official-documents"
        assert source.approval_status == DataSource.ApprovalStatus.MANUAL_REVIEW
        assert source.collection_enabled is False

        artifact = CollectedArtifact.objects.get(source=source)
        assert artifact.original_url.startswith("https://")
        record = ExtractedRecord.objects.get(source=source)
        assert record.normalized_data_json["context"].endswith("MNRE Official Documents (manual import) (offline; no inference).")
        assert DataSource.objects.filter(source_type="manual_import").count() == 1
        assert SubsidyScheme.objects.count() == 0