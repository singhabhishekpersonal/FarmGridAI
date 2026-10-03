"""Provenance chain tests: source -> run -> artifact -> record -> queue."""
import pytest
from django.contrib.auth import get_user_model

from apps.data_ingestion.models import (
    CollectedArtifact,
    DataReviewQueue,
    DataSource,
    ExtractedRecord,
    IngestionRun,
    SourceComplianceCheck,
)
from apps.data_ingestion.services.downloader import make_ingestion_run
from apps.data_ingestion.services.provenance import (
    artifact_provenance,
    record_provenance,
    source_history,
    write_provenance_report,
)


@pytest.fixture
def chain(db, tmp_path):
    source = DataSource.objects.create(
        name="Provenance Source",
        base_url="https://prov.example.in",
        source_type="government",
        category="subsidy",
        approval_status=DataSource.ApprovalStatus.APPROVED,
        collection_enabled=True,
    )
    run = make_ingestion_run(source, dry_run=False)
    run.status = IngestionRun.Status.COMPLETED
    run.save(update_fields=["status"])
    artifact = CollectedArtifact.objects.create(
        source=source,
        ingestion_run=run,
        artifact_type=CollectedArtifact.ArtifactType.JSON,
        original_url="https://prov.example.in/schemes.json",
        final_url="https://prov.example.in/schemes.json",
        local_path=str(tmp_path / "schemes.json"),
        sha256="a" * 64,
        content_type="application/json",
        file_size=12,
        validation_status=CollectedArtifact.ValidationStatus.VALID,
    )
    record = ExtractedRecord.objects.create(
        source=source,
        ingestion_run=run,
        collected_artifact=artifact,
        record_type=ExtractedRecord.RecordType.SCHEME,
        normalized_data_json={"name": "Pump", "status": "preliminary", "source_url": "https://prov.example.in/scheme"},
        source_url="https://prov.example.in/scheme",
        content_hash="b" * 32,
        verification_status=ExtractedRecord.VerificationStatus.VALIDATED,
    )
    queue = DataReviewQueue.objects.create(
        extracted_record=record,
        proposed_target_model="SubsidyScheme",
        risk_level=DataReviewQueue.RiskLevel.HIGH,
        validation_result={"ok": True},
    )
    return {"source": source, "run": run, "artifact": artifact, "record": record, "queue": queue}


class TestProvenance:
    def test_artifact_provenance_reaches_source_and_run(self, chain):
        data = artifact_provenance(chain["artifact"])
        assert data["artifact"]["sha256"] == "a" * 64
        assert data["source"]["name"] == "Provenance Source"
        assert data["source"]["approved_by"] == ""
        assert data["run"]["run_id"] == chain["run"].run_id

    def test_record_provenance_includes_review_queue(self, chain):
        data = record_provenance(chain["record"])
        assert data["record"]["content_hash"] == "b" * 32
        assert data["source"]["base_url"] == "https://prov.example.in"
        assert data["review_queue"]["proposed_target_model"] == "SubsidyScheme"
        assert data["review_queue"]["decision"] == DataReviewQueue.Decision.PENDING

    def test_source_history_tracks_checks_and_runs(self, chain):
        SourceComplianceCheck.objects.create(
            source=chain["source"],
            run_id="ck-1",
            robots_retrieved=True,
            robots_allows_target_paths=True,
            decision=SourceComplianceCheck.Decision.ALLOWED,
        )
        history = source_history(chain["source"])
        assert len(history["compliance_checks"]) == 1
        assert history["compliance_checks"][0]["decision"] == "allowed"
        assert len(history["runs"]) == 1

    def test_write_report_returns_markdown_string(self, chain):
        report = write_provenance_report(chain["record"])
        assert "Provenance" in report
        assert "Provenance Source" in report


class TestProvenanceAuditApproval:
    def test_approved_by_surfaces_when_set(self, db, chain):
        user = get_user_model().objects.create_user(username="boss", password="Str0ng!", is_staff=True)
        source = chain["source"]
        source.approved_by = user
        source.save(update_fields=["approved_by"])
        data = artifact_provenance(chain["artifact"])
        assert data["source"]["approved_by"] == "boss"