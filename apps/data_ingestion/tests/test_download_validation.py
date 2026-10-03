"""URL safety + download validation tests (never touch the network)."""
import pytest

from apps.data_ingestion.models import DataSource, IngestionRun
from apps.data_ingestion.services.downloader import (
    SourceNotCollectable,
    download_url,
    make_ingestion_run,
)
from apps.data_ingestion.services.http_client import NetworkDisabledError, SafeHTTPClient
from apps.data_ingestion.services.source_registry import approve_source, register_source
from apps.data_ingestion.services.urlutils import (
    UnsafeURL,
    hostname_allowed,
    validate_no_private_target,
    validate_scheme,
    validate_target_url,
)
from django.contrib.auth import get_user_model


class TestURLValidation:
    def test_non_http_scheme_rejected(self):
        with pytest.raises(UnsafeURL):
            validate_scheme("ftp://x.example/a")

    def test_data_and_blob_urls_rejected(self):
        with pytest.raises(UnsafeURL):
            validate_scheme("data:image/png;base64,AAAA")
        with pytest.raises(UnsafeURL):
            validate_scheme("blob:https://x.example/id")

    def test_loopback_ip_literal_rejected(self):
        with pytest.raises(UnsafeURL):
            validate_no_private_target("http://127.0.0.1/robots.txt")
        with pytest.raises(UnsafeURL):
            validate_no_private_target("http://10.0.0.5/x")
        with pytest.raises(UnsafeURL):
            validate_no_private_target("http://localhost/robots.txt")

    def test_public_ip_literal_ok(self):
        validate_no_private_target("https://8.8.8.8/x", resolve=False)

    def test_hostname_allowed_exact_match(self):
        target = "https://approved.example/data.csv"
        hostname_allowed(target, ["https://approved.example"])
        with pytest.raises(UnsafeURL):
            hostname_allowed(target, ["https://other.example"])

    def test_validate_target_url_all_checks(self):
        validate_target_url("https://ok.example/a", allowed_hosts=["https://ok.example"], resolve=False)


class TestHTTPClientOffline:
    def test_get_refuses_when_network_disabled(self):
        client = SafeHTTPClient(network_allowed=False)
        with pytest.raises(NetworkDisabledError):
            client.get(
                "https://approved.example/x",
                allowed_hosts=["https://approved.example"],
            )

    def test_get_rejects_private_target_even_when_enabled(self):
        client = SafeHTTPClient(network_allowed=True)
        with pytest.raises(UnsafeURL):
            client.get("http://127.0.0.1/robots.txt", allowed_hosts=["http://127.0.0.1"])

    def test_get_rejects_unapproved_host(self):
        client = SafeHTTPClient(network_allowed=True)
        with pytest.raises(UnsafeURL):
            client.get("https://evil.example/x", allowed_hosts=["https://good.example"])

    def test_full_base_url_in_allowed_hosts_matches_its_host(self):
        # An approved `source.base_url` (full URL) must approve its own host.
        client = SafeHTTPClient(network_allowed=True)
        client._validate_target("https://approved.example/scheme.pdf", allowed_hosts=["https://approved.example/"])
        with pytest.raises(UnsafeURL):
            client._validate_target("https://evil.example/scheme.pdf", allowed_hosts=["https://approved.example/"])


class TestDownloader:
    @pytest.fixture
    def source(self, db):
        src = register_source(
            name="Approved Images",
            base_url="https://images.example.in",
            source_type="official_manufacturer",
            category="equipment_images",
        )
        return src

    @pytest.fixture
    def approve(self, source):
        staff = get_user_model().objects.create_user(username="s", password="Str0ng!", is_staff=True)
        approve_source(source, staff)

    def test_unapproved_source_blocks_download(self, db, source):
        source.approval_status = DataSource.ApprovalStatus.PENDING
        source.save(update_fields=["approval_status"])
        run = make_ingestion_run(source, dry_run=True)
        with pytest.raises(SourceNotCollectable):
            download_url(
                source,
                run,
                "https://images.example.in/a.jpg",
                "image",
                client=SafeHTTPClient(network_allowed=False),
            )

    def test_make_ingestion_run_respects_dry_run_flag(self, db, source):
        dry = make_ingestion_run(source, dry_run=True)
        assert dry.is_dry_run is True
        assert dry.status == IngestionRun.Status.DRY_RUN
        live = make_ingestion_run(source, dry_run=False)
        assert live.is_dry_run is False
        assert live.status == IngestionRun.Status.PENDING

    def test_download_reports_network_disabled(self, db, source, approve):
        run = make_ingestion_run(source, dry_run=False)
        artifact, reason = download_url(
            source,
            run,
            "https://images.example.in/a.jpg",
            "image",
            client=SafeHTTPClient(network_allowed=False),
        )
        assert artifact is None
        assert "disabled" in reason