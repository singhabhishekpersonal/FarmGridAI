"""Contract tests for the staff data-ingestion console and the reference panels.

The console is the first frontend over the /api/v1/data-ingestion/ surface, so
these tests pin three things that can silently rot:

- the page is genuinely staff-gated (anon -> redirect, non-staff -> 403);
- the markup carries every hook the controller looks for;
- each endpoint accepts the field names the console actually sends.

The reference panels (bigha-rules, benchmarks, data-source-status) are covered
too, because those endpoints all filter is_verified=True and would otherwise be
assumed to work without ever being exercised.
"""
import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from rest_framework.test import APIClient

from apps.data_ingestion.models import DataSource
from apps.farms.models import FarmService

CONSOLE_URL = "/staff/data-ingestion/"


@pytest.fixture
def user(db):
    return get_user_model().objects.create_user(
        username="ingest_user", password="Str0ng!", phone="9876500555"
    )


@pytest.fixture
def staff(db):
    return get_user_model().objects.create_user(
        username="ingest_staff",
        password="Str0ng!",
        phone="9876500556",
        is_staff=True,
    )


@pytest.fixture
def farm(staff):
    return FarmService.create_farm(staff, "Console Farm", area=1, unit="acre", state="Punjab")


@pytest.fixture
def api(user):
    c = APIClient()
    c.force_authenticate(user=user)
    return c


@pytest.fixture
def staff_api(staff):
    c = APIClient()
    c.force_authenticate(user=staff)
    return c


# --------------------------------------------------------------------- gating


def test_console_redirects_anonymous():
    resp = Client().get(CONSOLE_URL)
    assert resp.status_code == 302
    assert "/login/" in resp["Location"]


def test_console_forbids_authenticated_non_staff(user):
    page = Client()
    page.force_login(user)
    assert page.get(CONSOLE_URL).status_code == 403


def test_console_renders_for_staff(staff):
    page = Client()
    page.force_login(staff)
    resp = page.get(CONSOLE_URL)
    assert resp.status_code == 200
    html = resp.content.decode()
    assert 'data-ks-page="staffDataIngestion"' in html


def test_nav_shows_staff_link_only_to_staff(staff, user):
    staff_page = Client()
    staff_page.force_login(staff)
    assert CONSOLE_URL in staff_page.get("/dashboard/").content.decode()

    user_page = Client()
    user_page.force_login(user)
    assert CONSOLE_URL not in user_page.get("/dashboard/").content.decode()


# -------------------------------------------------------------- markup hooks

REQUIRED_HOOKS = [
    'data-ks-source-form',
    'data-ks-sources',
    'data-ks-approved-sources',
    'data-ks-collect-form',
    'data-ks-collect-out',
    'data-ks-queue',
    'data-ks-runs',
    'data-ks-artifacts',
    'data-ks-records',
    'data-ks-dataset-report',
    'data-ks-provenance-form',
    'data-ks-provenance-out',
    'data-ks-src-filter',
    'data-ks-queue-filter',
    'data-ks-record-filter',
    'data-ks-src-detail',
    'data-ks-run-detail',
    'data-ks-artifact-detail',
    'data-ks-record-detail',
]


@pytest.mark.parametrize("hook", REQUIRED_HOOKS)
def test_console_markup_has_hook(staff, hook):
    page = Client()
    page.force_login(staff)
    html = page.get(CONSOLE_URL).content.decode()
    assert hook in html, f"missing {hook} - the controller would silently no-op"


# ------------------------------------------------------------- endpoint verbs

LIST_ENDPOINTS = [
    "/api/v1/data-ingestion/sources",
    "/api/v1/data-ingestion/runs",
    "/api/v1/data-ingestion/artifacts",
    "/api/v1/data-ingestion/records",
    "/api/v1/data-ingestion/review-queue",
    "/api/v1/data-ingestion/dataset-report",
    "/api/v1/system/data-source-status",
]


@pytest.mark.parametrize("path", LIST_ENDPOINTS)
def test_read_endpoints_reach_a_staff_user(staff_api, path):
    """Every read the console performs on load must answer a staff caller.

    Bare arrays are the documented shape; the console's asRows() tolerates
    {results: [...]} too, so accept either but require 200.
    """
    resp = staff_api.get(path)
    assert resp.status_code == 200, (path, resp.content[:200])
    body = resp.json()
    assert body["success"] is True
    data = body["data"]
    assert isinstance(data, (list, dict)), (path, type(data))


def test_dataset_report_has_the_keys_the_console_reads(staff_api):
    data = staff_api.get("/api/v1/data-ingestion/dataset-report").json()["data"]
    assert "expanded_plan" in data
    plan = data["expanded_plan"]
    for key in ("current_total", "candidate_total", "rows", "recommendation"):
        assert key in plan, key
    assert "eligible_reviewed_records" in data
    if plan["rows"]:
        row = plan["rows"][0]
        for key in ("label", "target", "current", "approved_source_candidates_in_review",
                    "shortfall_after_candidates"):
            assert key in row, key


def test_data_source_status_has_by_approval_status(staff_api):
    data = staff_api.get("/api/v1/system/data-source-status").json()["data"]
    assert "sources_total" in data
    for key in ("pending", "approved", "rejected", "blocked", "manual_review"):
        assert key in data["by_approval_status"], key


def test_data_source_status_is_readable_by_a_plain_farmer(api):
    """The farmer solar page renders this aggregate, so it must not be staff-only."""
    resp = api.get("/api/v1/system/data-source-status")
    assert resp.status_code == 200, resp.content


def test_source_registration_accepts_the_console_payload(staff_api, db):
    """The register form's field names must be the ones the view reads."""
    resp = staff_api.post(
        "/api/v1/data-ingestion/sources",
        {
            "name": "Console test source",
            "base_url": "https://console-test.example.in",
            "source_type": "public_dataset",
            "category": "subsidy",
            "organization": "Test Org",
            "state": "Punjab",
            "rate_limit_per_minute": 5,
            "request_delay_seconds": 2.5,
            "allows_images": False,
            "allows_documents": False,
            "allows_structured_data": True,
        },
        format="json",
    )
    assert resp.status_code == 201, resp.content
    created = resp.json()["data"]
    assert created["name"] == "Console test source"
    assert created["approval_status"] == "pending"
    assert created["collection_enabled"] is False
    # The console reads these back off the list view to render the row.
    row = staff_api.get("/api/v1/data-ingestion/sources").json()["data"][0]
    assert row["allows_structured_data"] is True
    assert row["rate_limit_per_minute"] == 5
    assert DataSource.objects.filter(name="Console test source").exists()


def test_collect_requires_image_urls(staff_api):
    """The console always sends image_urls, and a dry run must not persist."""
    src = DataSource.objects.create(name="dry", base_url="https://dry.example.in")
    resp = staff_api.post(
        f"/api/v1/data-ingestion/sources/{src.pk}/collect",
        {"image_urls": [], "execute": False},
        format="json",
    )
    assert resp.status_code == 400
    assert resp.json()["errors"]


def test_manual_import_needs_source_and_path(staff_api):
    resp = staff_api.post("/api/v1/data-ingestion/manual-import", {}, format="json")
    assert resp.status_code == 400
    assert resp.json()["errors"]


def test_review_queue_decisions_require_a_real_item(staff_api):
    from uuid import uuid4

    resp = staff_api.post(
        f"/api/v1/data-ingestion/review-queue/{uuid4()}/approve", {"notes": "x"}, format="json"
    )
    assert resp.status_code == 404
    assert resp.json()["errors"]


def test_provenance_requires_exactly_one_lookup(staff_api):
    resp = staff_api.get("/api/v1/data-ingestion/provenance-report")
    assert resp.status_code == 400
    assert resp.json()["errors"]

    src = DataSource.objects.create(name="prov", base_url="https://prov.example.in")
    ok = staff_api.get("/api/v1/data-ingestion/provenance-report", {"source_id": str(src.pk)})
    assert ok.status_code == 200
    data = ok.json()["data"]
    for key in ("source", "compliance_checks", "runs"):
        assert key in data, key


def test_non_staff_cannot_use_the_console_endpoints(api):
    """The page gate is convenience; the API is the real boundary."""
    resp = api.get("/api/v1/data-ingestion/sources")
    # StaffOrReadOnly lets any authenticated user read, but not write.
    assert resp.status_code == 200
    assert api.post(
        "/api/v1/data-ingestion/sources", {"name": "x", "base_url": "https://x.example.in"},
        format="json",
    ).status_code == 403


# ------------------------------------------------------- detail endpoints


def test_source_patch_updates_editable_fields_and_ignores_readonly(staff_api, db):
    """The console's edit form PATCHes a subset; approval_status must not move."""
    src = DataSource.objects.create(
        name="before", base_url="https://patch.example.in", rate_limit_per_minute=10
    )
    resp = staff_api.patch(
        f"/api/v1/data-ingestion/sources/{src.pk}",
        {
            "name": "after",
            "rate_limit_per_minute": 3,
            "allows_structured_data": True,
            "approval_status": "approved",  # read-only, must be ignored
            "collection_enabled": True,  # read-only, must be ignored
        },
        format="json",
    )
    assert resp.status_code == 200, resp.content
    src.refresh_from_db()
    assert src.name == "after"
    assert src.rate_limit_per_minute == 3
    assert src.allows_structured_data is True
    assert src.approval_status == DataSource.ApprovalStatus.PENDING
    assert src.collection_enabled is False


def test_source_patch_is_staff_only(api, db):
    src = DataSource.objects.create(name="mine", base_url="https://mine.example.in")
    resp = api.patch(
        f"/api/v1/data-ingestion/sources/{src.pk}", {"name": "hijack"}, format="json"
    )
    assert resp.status_code == 403


def test_artifact_detail_is_flat_plus_provenance(staff_api, db):
    from apps.data_ingestion.models import CollectedArtifact

    src = DataSource.objects.create(name="Art source", base_url="https://art.example.in")
    art = CollectedArtifact.objects.create(
        source=src,
        artifact_type="image",
        original_url="https://art.example.in/1.jpg",
        local_path="/srv/art/1.jpg",
        sha256="a" * 64,
        file_size=123,
    )
    resp = staff_api.get(f"/api/v1/data-ingestion/artifacts/{art.pk}")
    assert resp.status_code == 200, resp.content
    data = resp.json()["data"]
    # Flat serializer fields the console's artifact detail reads.
    assert str(data["pk"]) == str(art.pk)
    assert data["sha256"] == "a" * 64
    assert data["artifact_type"] == "image"
    assert data["validation_status"] == "pending"
    # Nested provenance the console renders underneath.
    assert str(data["provenance"]["artifact"]["id"]) == str(art.pk)
    assert data["provenance"]["source"]["name"] == "Art source"


def test_record_detail_is_flat_plus_provenance(staff_api, db):
    from apps.data_ingestion.models import ExtractedRecord

    src = DataSource.objects.create(name="Rec source", base_url="https://rec.example.in")
    rec = ExtractedRecord.objects.create(
        source=src,
        record_type="scheme",
        normalized_data_json={"name": "Pump Aid"},
        verification_status="raw",
    )
    resp = staff_api.get(f"/api/v1/data-ingestion/records/{rec.pk}")
    assert resp.status_code == 200, resp.content
    data = resp.json()["data"]
    assert str(data["pk"]) == str(rec.pk)
    assert data["record_type"] == "scheme"
    assert data["verification_status"] == "raw"
    assert data["normalized_data_json"] == {"name": "Pump Aid"}
    assert str(data["provenance"]["record"]["id"]) == str(rec.pk)


def test_run_detail_has_fields_the_console_reads(staff_api, db):
    from apps.data_ingestion.models import IngestionRun

    src = DataSource.objects.create(name="Run source", base_url="https://run.example.in")
    run = IngestionRun.objects.create(
        source=src, run_id="run-console", status="completed", pages_collected=2, pages_attempted=3
    )
    resp = staff_api.get(f"/api/v1/data-ingestion/runs/{run.pk}")
    assert resp.status_code == 200, resp.content
    data = resp.json()["data"]
    assert data["run_id"] == "run-console"
    for key in ("status", "started_at", "pages_collected", "pages_attempted", "records_extracted",
                "documents_downloaded", "images_downloaded", "duplicates_skipped",
                "validation_failures", "blocked_items", "warnings"):
        assert key in data, key


def test_records_status_filter_maps_to_verification_status(staff_api, db):
    from apps.data_ingestion.models import ExtractedRecord

    src = DataSource.objects.create(name="Filter source", base_url="https://filter.example.in")
    ExtractedRecord.objects.create(source=src, record_type="scheme", verification_status="raw")
    published = ExtractedRecord.objects.create(
        source=src, record_type="scheme", verification_status="published"
    )
    resp = staff_api.get("/api/v1/data-ingestion/records", {"status": "published"})
    assert resp.status_code == 200
    rows = resp.json()["data"]
    assert [str(r["pk"]) for r in rows] == [str(published.pk)]


def test_artifact_and_record_detail_missing_ids_404(staff_api):
    from uuid import uuid4

    assert staff_api.get(f"/api/v1/data-ingestion/artifacts/{uuid4()}").status_code == 404
    assert staff_api.get(f"/api/v1/data-ingestion/records/{uuid4()}").status_code == 404
    assert staff_api.get(f"/api/v1/data-ingestion/runs/{uuid4()}").status_code == 404


# --------------------------------------------------------- reference panels


def test_bigha_rules_shape(staff_api):
    data = staff_api.get("/api/v1/bigha-rules").json()["data"]
    assert isinstance(data, list)
    if data:
        for key in ("state", "district", "sq_meters_per_bigha", "is_verified", "last_verified_at"):
            assert key in data[0], key


def test_benchmark_endpoints_are_lists(staff_api):
    tariffs = staff_api.get("/api/v1/energy/tariff-benchmarks").json()["data"]
    diesel = staff_api.get("/api/v1/energy/diesel-price-benchmarks").json()["data"]
    assert isinstance(tariffs, list)
    assert isinstance(diesel, list)


def test_equipment_catalog_is_a_list_joinable_on_category_code(staff_api, db):
    """The catalog picker maps category_code -> the category UUID the POST wants.

    Both endpoints filter differently (categories never filter is_verified,
    catalog filters is_verified=True), so the test creates its own rows rather
    than depending on seed data.
    """
    from apps.equipment.models import EquipmentCatalog, EquipmentCategory

    cat = EquipmentCategory.objects.create(code="tractor", name="Tractor")
    unverified = EquipmentCatalog.objects.create(
        category=cat, brand="HiddenBrand", model="HiddenModel", is_verified=False
    )
    verified = EquipmentCatalog.objects.create(
        category=cat,
        brand="Mahindra",
        model="575 DI",
        hp="45.0",
        fuel_type="diesel",
        price_expected=750000,
        is_verified=True,
    )

    cats = staff_api.get("/api/v1/equipment/categories").json()["data"]
    assert cats, "categories endpoint must return rows"
    assert {"id", "code", "name"} <= set(cats[0])

    catalog = staff_api.get("/api/v1/equipment/catalog").json()["data"]
    assert isinstance(catalog, list)
    # Compare as strings: over the wire the pk is a UUID string, and the
    # picker echoes row["id"] straight back into a URL path.
    ids = {str(row["id"]) for row in catalog}
    # is_verified=True is the filter, so the unverified row must not appear.
    assert str(verified.pk) in ids
    assert str(unverified.pk) not in ids

    row = next(r for r in catalog if str(r["id"]) == str(verified.pk))
    assert {"id", "brand", "model", "category_code", "category_name"} <= set(row)
    assert row["category_code"] == "tractor"
    assert row["category_name"] == "Tractor"
    # The picker's category_code -> id join must resolve.
    assert row["category_code"] in {c["code"] for c in cats}
    assert str(row["category"]) == str(cat.pk)


def test_land_unit_convert_round_trip(staff_api):
    resp = staff_api.post(
        "/api/v1/land-units/convert", {"value": 2.5, "unit": "acre"}, format="json"
    )
    assert resp.status_code == 200
    result = resp.json()["data"]["result"]
    for key in ("value_ha", "value_acre", "requires_confirmation", "method"):
        assert key in result, key
    # 2.5 acre is 2.5 acre, and roughly 2.53 ha.
    assert result["value_acre"] == pytest.approx(2.5, rel=0.001)
    assert result["value_ha"] == pytest.approx(2.5 * 0.404686, rel=0.01)
    assert result["requires_confirmation"] is False


def test_land_unit_convert_rejects_unknown_unit(staff_api):
    resp = staff_api.post(
        "/api/v1/land-units/convert", {"value": 1, "unit": "furlong"}, format="json"
    )
    assert resp.status_code == 400


def test_land_unit_convert_requires_value_and_unit(staff_api):
    resp = staff_api.post("/api/v1/land-units/convert", {}, format="json")
    assert resp.status_code == 400
    assert resp.json()["errors"]


def test_land_unit_convert_bigha_without_rule_needs_confirmation(staff_api):
    """No verified bigha rule must come back as "confirm", never a guessed value.

    This is the whole reason /land-units/convert exists as an API instead of a
    hard-coded multiplier, and it is what the parcel disclosure renders.
    """
    resp = staff_api.post(
        "/api/v1/land-units/convert",
        {"value": 1, "unit": "bigha", "state": "Nowhere"},
        format="json",
    )
    assert resp.status_code == 200
    result = resp.json()["data"]["result"]
    assert result["requires_confirmation"] is True
    assert result["value_ha"] is None
    assert result["value_acre"] is None


def test_land_unit_convert_bigha_with_rule_is_authoritative(staff_api, db):
    from apps.farms.models import BighaConversionRule

    BighaConversionRule.objects.create(
        state="Bihar",
        district="Patna",
        sq_meters_per_bigha="2529.29",
        is_verified=True,
        last_verified_at="2026-01-01",
    )
    resp = staff_api.post(
        "/api/v1/land-units/convert",
        {"value": 2, "unit": "bigha", "state": "Bihar", "district": "Patna"},
        format="json",
    )
    assert resp.status_code == 200
    result = resp.json()["data"]["result"]
    assert result["requires_confirmation"] is False
    assert result["value_ha"] == pytest.approx(2 * 2529.29 / 10000, rel=0.001)
    assert result["value_acre"] is not None


def test_parcel_page_has_land_converter_hooks(staff, farm):
    page = Client()
    page.force_login(staff)
    html = page.get(f"/farms/{farm.id}/parcels/new/").content.decode()
    # The apply button is injected by the controller after a result, so only the
    # static mounts and inputs belong in this check.
    for hook in ("data-ks-land-convert", "data-ks-convert-form", "data-ks-convert-out",
                 'name="value"', 'name="unit"'):
        assert hook in html, hook


def test_solar_page_exposes_farm_state_for_benchmarks(staff, farm):
    """Tariff benchmarks are state-scoped and the state lives on FarmLocation.

    The view must resolve it into the section, or the panel silently queries
    the unfiltered national list.
    """
    from apps.farms.models import FarmLocation

    FarmLocation.objects.create(farm=farm, state="Punjab", district="Ludhiana")

    page = Client()
    page.force_login(staff)
    resp = page.get(f"/farms/{farm.id}/energy/solar/")
    assert resp.status_code == 200
    html = resp.content.decode()
    assert 'data-ks-farm-state="Punjab"' in html
    assert "data-ks-rates" in html


def test_solar_page_omits_placeholder_unknown_state(staff, farm):
    """create_farm() backfills state="Unknown", which matches no benchmark row.

    Passing it through would filter every tariff out, so the view must treat it
    as "no state" and leave the panel on the unfiltered list.
    """
    farm.locations.update(state="Unknown")

    page = Client()
    page.force_login(staff)
    resp = page.get(f"/farms/{farm.id}/energy/solar/")
    assert resp.status_code == 200
    assert "data-ks-farm-state" not in resp.content.decode()


def test_solar_page_renders_without_any_location(staff, farm):
    """A farm with no FarmLocation at all must still render."""
    farm.locations.all().delete()

    page = Client()
    page.force_login(staff)
    resp = page.get(f"/farms/{farm.id}/energy/solar/")
    assert resp.status_code == 200
    assert "data-ks-farm-state" not in resp.content.decode()


def test_disclosure_panels_exist_in_templates(staff, farm):
    page = Client()
    page.force_login(staff)
    solar = page.get(f"/farms/{farm.id}/energy/solar/").content.decode()
    assert "data-ks-rates" in solar
    parcel = page.get(f"/farms/{farm.id}/parcels/new/").content.decode()
    assert "data-ks-bigha-rules" in parcel
    equip = page.get(f"/farms/{farm.id}/equipment/new/").content.decode()
    assert "data-ks-catalog-picker" in equip
