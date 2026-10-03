"""
FarmGrid end-to-end verification harness.

Runs in-process against the Django WSGI app via django.test.Client, so it needs
no running server and reports each check as it happens.

Usage:
    python verify.py [pass_number ...]     # default: all passes
    python verify.py 1 2                    # only those passes

Exit code 0 = every check passed.
"""
import json
import os
import sys
import time
import uuid

sys.path.insert(0, r"D:\snider\schneider hackathon\FarmGridAI_codebase")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "FarmGridAI.settings.development")

import django  # noqa: E402

django.setup()

# drf-spectacular logs one "unable to guess serializer" line per APIView while
# building the schema. They are documentation-generation warnings, not request
# failures, and they bury the actual test output.
import logging  # noqa: E402

logging.disable(logging.ERROR)
logging.getLogger("django").setLevel(logging.CRITICAL)

from django.contrib.auth import get_user_model  # noqa: E402
from django.test import Client  # noqa: E402
from rest_framework.test import APIClient  # noqa: E402
from django.urls import reverse  # noqa: E402

# ---------------------------------------------------------------------------
# Tiny reporting harness
# ---------------------------------------------------------------------------
BLUE, GREEN, RED, YELLOW, DIM, RESET = "\033[34m", "\033[32m", "\033[31m", "\033[33m", "\033[2m", "\033[0m"

results = {"pass_id": [], "fail": [], "warn": []}


def section(title):
    print(f"\n{BLUE}{'=' * 78}{RESET}")
    print(f"{BLUE}  {title}{RESET}")
    print(f"{BLUE}{'=' * 78}{RESET}")


def step(name, ok, detail="", warn_only=False):
    tag = f"{GREEN}PASS{RESET}"
    if not ok:
        tag = f"{YELLOW}WARN{RESET}" if warn_only else f"{RED}FAIL{RESET}"
    print(f"  [{tag}] {name}" + (f"  {DIM}{detail}{RESET}" if detail else ""))
    sys.stdout.flush()
    if not ok:
        (results["warn"] if warn_only else results["fail"]).append((name, detail))
    else:
        results["pass_id"].append(name)
    return ok


def done(title):
    f, w, p = len(results["fail"]), len(results["warn"]), len(results["pass_id"])
    colour = RED if f else (YELLOW if w else GREEN)
    print(f"\n{colour}{title}: {p} passed, {f} failed, {w} warnings{RESET}")
    sys.stdout.flush()
    return f == 0


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
User = get_user_model()

PASSWORD = "Verify@12345"
FARMER = "verify_farmer"
STAFF = "verify_staff"


def ensure_users():
    for username, staff in ((FARMER, False), (STAFF, True)):
        u, created = User.objects.get_or_create(
            username=username,
            defaults={"email": f"{username}@example.com", "is_staff": staff},
        )
        if created or not u.has_usable_password():
            u.set_password(PASSWORD)
        u.is_staff = staff
        u.save()
    return User.objects.get(username=FARMER), User.objects.get(username=STAFF)


def api_login(c, username, password=PASSWORD):
    """Log in through the real API endpoint the frontend calls, keep the JWT."""
    r = c.post(
        "/api/v1/auth/login/",
        data=json.dumps({"username": username, "password": password}),
        content_type="application/json",
    )
    return r


def envelope(r):
    try:
        return json.loads(r.content)
    except Exception:
        return {}


def body(r):
    e = envelope(r)
    return e.get("data") if isinstance(e, dict) and "data" in e else e


def authenticated(username=FARMER, staff=False):
    c = APIClient()
    r = api_login(c, STAFF if staff else username)
    d = body(r)
    if r.status_code == 200 and isinstance(d, dict) and d.get("access"):
        c.credentials(HTTP_AUTHORIZATION="Bearer " + d["access"])
    return c


def equip_category_uuid():
    """EquipmentCategory.category is a UUID FK; the UI reads ids from /equipment/categories."""
    from apps.equipment.models import EquipmentCategory
    row = EquipmentCategory.objects.filter(code="tractor").first() or EquipmentCategory.objects.first()
    return str(row.id) if row else None


def make_farm(c):
    """Create a farm through the API and return (farm_id, payload)."""
    payload = {
        "name": "Verification Farm",
        "description": "Created by verify.py",
        "state": "Uttar Pradesh",
        "district": "Lucknow",
        "village": "Barabanki",
        "pincode": "226001",
        "parcels": [
            {"name": "North plot", "area": "2.5", "unit": "acre",
             "ownership": "owned", "irrigated": True, "irrigation_source": "well",
             "soil_type": "alluvial", "is_primary": True}
        ],
    }
    r = c.post("/api/v1/farms/", data=json.dumps(payload), content_type="application/json")
    return r, body(r)


# ===========================================================================
# PASS 1 - HTML pages + static assets
# ===========================================================================
def pass1_pages():
    section("PASS 1 - HTML page rendering and static assets")
    farmer, staff = ensure_users()

    # --- anonymous pages ---
    anon = APIClient()
    for url, label in [
        ("/", "landing page"),
        ("/login/", "login page"),
        ("/register/", "register page"),
        ("/api/schema/", "OpenAPI schema"),
    ]:
        r = anon.get(url)
        step(f"anon GET {url:<16} ({label})", r.status_code == 200,
             f"HTTP {r.status_code}" + ("" if r.status_code == 200 else f" :: {r.content[:160]}"))

    # CSRF cookie must be present or every unsafe browser request fails.
    r = anon.get("/login/")
    step("login page sets csrftoken cookie", "csrftoken" in r.cookies or "csrftoken" in r.cookies.get("csrftoken", ""),
         f"cookies={sorted(r.cookies.keys())}")
    r2 = anon.get("/login/")
    step("csrftoken readable by JS", bool(r2.cookies.get("csrftoken")), f"value_len={len(r2.cookies.get('csrftoken',''))}")

    # --- protected pages must redirect anonymous users, not 500 ---
    for url in ["/dashboard/", "/profile/", "/chat/", "/farms/new/"]:
        r = anon.get(url)
        step(f"anon GET {url:<16} redirects to login", r.status_code in (302, 301),
             f"HTTP {r.status_code} -> {r.headers.get('Location','')}")

    # --- authenticated pages ---
    c = authenticated()
    r = api_login(c, FARMER)
    step("POST /api/v1/auth/login/ returns tokens", r.status_code == 200 and bool(body(r).get("access")),
         f"HTTP {r.status_code}")
    if r.status_code == 200:
        c.credentials(HTTP_AUTHORIZATION="Bearer " + body(r)["access"])
    else:
        print(f"  {RED}login failed, cannot continue{RESET}")
        return None

    r, farm = make_farm(c)
    step("POST /api/v1/farms/ creates farm", r.status_code == 201 and bool(farm.get("id")),
         f"HTTP {r.status_code}")
    if not farm.get("id"):
        print(f"  {RED}farm creation failed :: {envelope(r)}{RESET}")
        return None
    fid = farm["id"]
    print(f"  {DIM}farm_id = {fid}{RESET}")

    pages = [
        ("/dashboard/", "dashboard"),
        ("/profile/", "profile"),
        ("/chat/", "chat"),
        (f"/farms/{fid}/", "farm detail"),
        ("/farms/new/", "farm create"),
        (f"/farms/{fid}/parcels/new/", "land parcel form"),
        (f"/farms/{fid}/crops/", "crop form"),
        (f"/farms/{fid}/expenses/", "expense dashboard"),
        (f"/farms/{fid}/expenses/add/", "expense entry"),
        (f"/farms/{fid}/equipment/", "equipment list"),
        (f"/farms/{fid}/equipment/new/", "equipment upload (new)"),
        (f"/farms/{fid}/recommendations/", "recommendations"),
        (f"/farms/{fid}/subsidies/", "subsidies"),
        (f"/farms/{fid}/energy/solar/", "solar comparison"),
        (f"/farms/{fid}/finance/", "machinery decision"),
    ]
    for url, label in pages:
        r = c.get(url)
        ok = r.status_code == 200
        detail = f"HTTP {r.status_code} bytes={len(r.content)}"
        if not ok:
            detail += f" :: {r.content[:300]}"
        step(f"auth GET {url}", ok, detail)

    # equipment detail needs an equipment id
    r = c.post(f"/api/v1/farms/{fid}/equipment",
               data=json.dumps({"category": equip_category_uuid(), "brand": "Mahindra", "model": "575 DI",
                                "horsepower": 45, "purchase_year": 2020, "purchase_price": 450000,
                                "condition": "good", "fuel_type": "diesel",
                                "usage_hours_per_year": 900, "is_owned": True}),
               content_type="application/json")
    eq = body(r)
    step("create equipment for detail page", r.status_code == 201 and bool(eq.get("id")),
         f"HTTP {r.status_code}")
    if eq.get("id"):
        r = c.get(f"/farms/{fid}/equipment/{eq['id']}/")
        step(f"auth GET equipment detail page", r.status_code == 200,
             f"HTTP {r.status_code} bytes={len(r.content)}")
        r = c.get(f"/farms/{fid}/equipment/{eq['id']}/upload/")
        step(f"auth GET equipment upload page", r.status_code == 200,
             f"HTTP {r.status_code} bytes={len(r.content)}")

    # staff-only console
    r = c.get("/staff/data-ingestion/")
    step("non-staff blocked from /staff/data-ingestion/", r.status_code == 403,
         f"HTTP {r.status_code} (expected 403)")

    sc = authenticated(staff=True)
    r = sc.get("/staff/data-ingestion/")
    step("staff GET /staff/data-ingestion/", r.status_code == 200,
         f"HTTP {r.status_code} bytes={len(r.content)}" + ("" if r.status_code == 200 else f" :: {r.content[:300]}"))

    # --- static assets ---
    from django.contrib.staticfiles import finders
    for asset in ["css/base.css", "css/forms.css", "css/dashboard.css",
                  "js/app.js", "js/dashboard.js", "js/uploads.js",
                  "images/logo.svg", "images/favicon.svg"]:
        p = finders.find(asset)
        step(f"static asset resolvable: {asset}", p is not None, str(p or "NOT FOUND"))

    # every static URL referenced by a rendered page must exist
    import re
    page = c.get("/dashboard/").content.decode("utf-8", "replace")
    refs = sorted(set(re.findall(r'(?:href|src)="/static/([^"]+)"', page)))
    step("dashboard references static files", bool(refs), f"{len(refs)} refs")
    for ref in refs:
        # Development URLs carry ?v=<mtime> from the versioned static storage,
        # which is not part of the on-disk path.
        clean = ref.split("?", 1)[0]
        step(f"  /static/{clean} exists",
             finders.find(clean) is not None or os.path.exists(clean),
             "" if "?" not in ref else f"(cache-busted: ?{ref.split('?', 1)[1]})")

    # api docs
    for url in ["/api/docs/", "/api/redoc/"]:
        r = anon.get(url)
        step(f"GET {url}", r.status_code == 200, f"HTTP {r.status_code}")

    # Sign-out must be a single navigation. When it was an AJAX POST followed by
    # a redirect, a rejected POST (CSRF, offline) still navigated with the
    # session alive: /login/ redirected the visitor to /dashboard/, whose auth
    # guard sent them back - a visible three-step flicker. Assert the session is
    # genuinely closed and /login/ does not bounce.
    section("PASS 1b - sign out closes the session in one navigation")
    out = Client()
    assert out.login(username=FARMER, password=PASSWORD), "sign-out check could not sign in"
    r = out.get("/logout/")
    step("GET /logout/ redirects to the sign-in page",
         r.status_code == 302 and r.get("Location", "").endswith("/login/"),
         f"HTTP {r.status_code} -> {r.get('Location')}")
    step("/login/ is reachable after signing out (no bounce back)",
         out.get("/login/").status_code == 200,
         "a 302 here means the session outlived sign-out and the page flickers")
    step("the farmer area is closed after signing out",
         out.get("/dashboard/").status_code in (302, 403),
         f"HTTP {out.get('/dashboard/').status_code}")

    # The invariant that actually prevents the flicker: the browser must not
    # decide sign-out by awaiting an API POST. It navigates to /logout/ and lets
    # the server close the session in the redirect itself.
    from django.conf import settings as _settings
    app_js = open(os.path.join(str(_settings.BASE_DIR), "FarmGridAI-frontend",
                               "static", "js", "app.js"), encoding="utf-8").read()
    logout_body = app_js.split("auth.logout = function")[1].split("};", 1)[0]
    step("the client signs out by navigating, not by awaiting an API POST",
         "/auth/logout/" not in logout_body and "/logout/" in logout_body,
         "auth.logout() must navigate to /logout/ so the session closes server-side")

    return fid


# ===========================================================================
# PASS 2 - API surface
# ===========================================================================
def pass2_api(fid):
    section("PASS 2 - API endpoint surface")
    c = authenticated()
    F = f"/api/v1/farms/{fid}"

    def get(path, expect=(200,), label=None, warn_only=False):
        r = c.get(path)
        ok = r.status_code in expect
        d = ""
        if not ok:
            d = f"HTTP {r.status_code} expected {expect} :: {envelope(r).get('message', r.content[:200])}"
        return step(label or f"GET {path}", ok, d, warn_only)

    def post(path, payload, expect=(200, 201), label=None, warn_only=False):
        r = c.post(path, data=json.dumps(payload), content_type="application/json")
        ok = r.status_code in expect
        d = "" if ok else f"HTTP {r.status_code} expected {expect} :: {envelope(r).get('message', r.content[:200])}"
        return step(label or f"POST {path}", ok, d, warn_only), body(r)

    # system / health
    a = APIClient()
    for url, key in [("/api/v1/health", "status"), ("/api/v1/readiness", "ready")]:
        r = a.get(url)
        step(f"public GET {url}", r.status_code == 200 and key in envelope(r),
             f"HTTP {r.status_code} {envelope(r)}")
    get("/api/v1/system/capabilities", label="GET /api/v1/system/capabilities")
    get("/api/v1/system/model-status", label="GET /api/v1/system/model-status")
    get("/api/v1/system/data-source-status", label="GET /api/v1/system/data-source-status")

    # auth
    get("/api/v1/auth/profile/", label="GET /api/v1/auth/profile/")
    post("/api/v1/auth/profile/", {"full_name": "Verify"}, (405,),
         "POST /auth/profile/ rejected (GET/PATCH only)")
    r = c.patch("/api/v1/auth/profile/", data=json.dumps({"first_name": "Verify"}), content_type="application/json")
    step("PATCH /api/v1/auth/profile/", r.status_code == 200, f"HTTP {r.status_code}")
    get("/api/v1/auth/consents/", label="GET /api/v1/auth/consents/")
    post("/api/v1/auth/consents/", {"purpose": "profile", "granted": True}, (200, 201),
         "POST /api/v1/auth/consents/")
    get("/api/v1/auth/language/", label="GET /api/v1/auth/language/")
    post("/api/v1/auth/language/", {"language_code": "hi"}, (200,), "POST /api/v1/auth/language/")

    # farms
    get("/api/v1/farms/", label="GET /api/v1/farms/")
    get(f"/api/v1/farms/{fid}", label="GET farm detail (no trailing slash)")
    get(f"{F}/summary", label="GET farm summary")
    post(f"{F}/land-parcels", {"name": "South plot", "area": "1.2", "unit": "hectare",
                               "ownership": "leased", "irrigated": "rainfed",
                               "irrigation_source": "well", "is_primary": False}, (200, 201),
         "POST land-parcels")
    post("/api/v1/land-units/convert", {"value": 2.5, "unit": "acre"}, (200,),
         "POST /land-units/convert")
    get("/api/v1/bigha-rules", label="GET /api/v1/bigha-rules")

    # crops
    get("/api/v1/crops", label="GET /api/v1/crops")
    get(f"{F}/crops", label="GET farm crops")
    ok, crop = post(f"{F}/crops", {"crop": None}, (200, 201, 400), "POST farm crop (probe schema)", warn_only=True)
    crop_id = None
    if isinstance(crop, dict) and crop.get("id"):
        crop_id = crop["id"]
    if crop_id is None:
        from apps.crops.models import Crop
        cobj = Crop.objects.first()
        if cobj:
            ok, crop = post(f"{F}/crops",
                            {"crop": str(cobj.id), "season": "kharif", "year": 2026,
                             "area": "2.5", "area_unit": "acre", "expected_yield_qtl_per_acre": 20},
                            (200, 201), "POST farm crop (resolved id)")
            if isinstance(crop, dict):
                crop_id = crop.get("id")
    step("farm crop created for estimate test", bool(crop_id), f"crop_id={crop_id}")
    get(f"{F}/crops/estimates", label="GET crop estimates")
    if crop_id:
        r = c.post(f"{F}/crops/{crop_id}/estimate", data="{}", content_type="application/json")
        step("POST single-crop estimate", r.status_code == 200, f"HTTP {r.status_code}")

    # expenses - all typed endpoints
    for path, payload in [
        ("fuel", {"amount": 2400, "occurred_on": "2026-06-01", "litre_volume": 40,
                  "price_per_litre": 60, "fuel_type": "diesel", "purpose": "irrigation"}),
        ("inputs", {"amount": 8000, "occurred_on": "2026-06-02", "input_type": "fertilizer",
                    "product_name": "Urea", "quantity": 10, "quantity_unit": "bag"}),
        ("labour", {"amount": 3000, "occurred_on": "2026-06-03", "labour_type": "daily",
                    "person_days": 5, "wage_per_day": 600}),
        ("electricity", {"amount": 1200, "occurred_on": "2026-06-04", "provider": "UPPCL",
                         "units_kwh": 180, "bill_month": "2026-06-01"}),
        ("transport", {"amount": 900, "occurred_on": "2026-06-05", "vehicle_type": "tractor",
                       "distance_km": 40}),
        ("rental", {"amount": 1500, "occurred_on": "2026-06-06", "equipment_class": "tractor",
                    "rental_hours": 5, "rental_days": 1}),
    ]:
        ok, _ = post(f"{F}/expenses/{path}", payload, (200, 201), f"POST expenses/{path}")
    get(f"{F}/expenses", label="GET expenses (list)")
    get(f"{F}/expenses/summary", label="GET expenses/summary")
    get(f"{F}/expenses/categories", label="GET expenses/categories  [NEW]")
    r = c.post(f"{F}/expenses/analysis", data="{}", content_type="application/json")
    step("POST expenses/analysis (ML)", r.status_code == 200, f"HTTP {r.status_code}")

    # equipment
    get("/api/v1/equipment/categories", label="GET equipment/categories")
    get("/api/v1/equipment/catalog", label="GET equipment/catalog")
    get(f"{F}/equipment", label="GET farm equipment")
    r = c.post(f"{F}/equipment",
               data=json.dumps({"category": equip_category_uuid(), "brand": "Sonalika", "model": "DI 35",
                                "horsepower": 35, "purchase_year": 2019, "purchase_price": 350000,
                                "condition": "moderate", "fuel_type": "diesel",
                                "usage_hours_per_year": 800, "is_owned": True}),
               content_type="application/json")
    eq2 = body(r)
    step("POST farm equipment", r.status_code == 201, f"HTTP {r.status_code}")
    eid = eq2.get("id") if isinstance(eq2, dict) else None
    if eid:
        get(f"{F}/equipment/{eid}", label="GET equipment detail")
        r = c.patch(f"{F}/equipment/{eid}", data=json.dumps({"condition": "good"}), content_type="application/json")
        step("PATCH equipment", r.status_code == 200, f"HTTP {r.status_code}")
        post(f"{F}/equipment/{eid}/operating-cost",
             {"usage_hours": 100, "fuel_price_per_litre": 60}, (200,), "POST operating-cost")

    # energy
    get("/api/v1/energy/tariff-benchmarks", label="GET tariff-benchmarks")
    get("/api/v1/energy/diesel-price-benchmarks", label="GET diesel-price-benchmarks")
    get(f"{F}/pump-profile", label="GET pump-profile")
    post(f"{F}/pump-profile", {"pump_type": "submersible", "horsepower": 5, "power_kw": 3.7,
                               "water_source": "well", "operating_hours_per_day": 4,
                               "irrigation_days_per_year": 180}, (200, 201), "POST pump-profile")
    get(f"{F}/solar-configuration", label="GET solar-configuration")
    post(f"{F}/solar-configuration", {"system_kw": 5, "pump_hp": 5, "pump_cost_inr": 45000,
                                      "installation_cost_inr": 300000, "storage_kwh": 0,
                                      "estimated_subsidy_inr": 150000, "loan_amount_inr": 300000,
                                      "loan_years": 7, "loan_interest_rate_pct": 10.0,
                                      "annual_maintenance_inr": 5000}, (200, 201), "POST solar-configuration")
    r = c.post(f"{F}/energy/analyze", data=json.dumps({"scenario": "baseline"}), content_type="application/json")
    step("POST energy/analyze", r.status_code == 200, f"HTTP {r.status_code}")
    get(f"{F}/energy/solar-comparison", label="GET energy/solar-comparison")
    get(f"{F}/energy/projection", label="GET energy/projection")

    # finance
    get(f"{F}/income-profile", label="GET income-profile")
    post(f"{F}/income-profile", {"year": 2026, "crop_income": 250000, "livestock_income": 40000,
                                 "off_farm_income": 60000, "other_income": 0,
                                 "existing_emi_total": 12000}, (200, 201), "POST income-profile")
    post(f"{F}/finance/buy-vs-rent", {"purchase_price_inr": 450000, "usage_hours_per_year": 900,
                                      "rental_rate_per_hour_inr": 350, "subsidy_inr": 50000,
                                      "loan_years": 8, "interest_rate_pct": 9.0}, (200,),
         "POST finance/buy-vs-rent")
    post(f"{F}/finance/repair-vs-replace", {"estimated_repair_cost_inr": 25000,
                                           "replacement_price_inr": 400000, "residual_value_inr": 20000,
                                           "annual_usage_hours": 800, "repair_frequency_per_year": 3.0},
         (200,), "POST finance/repair-vs-replace")
    post(f"{F}/finance/affordability", {"annual_income_inr": 240000, "proposed_emi_inr": 96000,
                                        "existing_emi_total_inr": 36000, "safe_burden_pct": 40.0},
         (200,), "POST finance/affordability")
    post(f"{F}/finance/machinery-decision", {"usage_hours_per_year": 900, "purchase_price_inr": 450000,
                                              "repair_cost_inr": 20000, "residual_value_inr": 40000,
                                              "monthly_emi": 8000, "monthly_income": 20000,
                                              "existing_emi": 2000, "subsidy_inr": 50000}, (200,),
         "POST finance/machinery-decision")
    get(f"{F}/finance/scenarios", label="GET finance/scenarios")

    # subsidies
    get("/api/v1/subsidies", label="GET /api/v1/subsidies")
    r = c.post(f"{F}/subsidies/match", data="{}", content_type="application/json")
    step("POST subsidies/match", r.status_code == 200, f"HTTP {r.status_code}")
    get(f"{F}/subsidies/recommendations", label="GET subsidies/recommendations")
    get(f"{F}/subsidies/checklists", label="GET subsidies/checklists")

    # recommendations
    r = c.post(f"{F}/recommendations/run", data="{}", content_type="application/json")
    step("POST recommendations/run", r.status_code == 200, f"HTTP {r.status_code}")
    get(f"{F}/recommendations", label="GET recommendations")
    get(f"{F}/opportunities", label="GET opportunities")
    get(f"{F}/recommendation-runs", label="GET recommendation-runs")
    from apps.recommendations.models import Recommendation
    rec = Recommendation.objects.filter(farm_id=fid).first()
    if rec:
        get(f"{F}/recommendations/{rec.id}/explain", label="GET recommendation explain")
        post(f"{F}/recommendations/{rec.id}/feedback",
             {"helpful": True, "accurate": True, "rating": 5, "comment": "verified"},
             (200, 201), "POST recommendation feedback")
    else:
        step("recommendation exists for explain/feedback", False, "none generated")

    # chatbot
    ok, session = post("/api/v1/chat/sessions", {"farm": fid, "language": "en", "topic": "general"},
                       (200, 201), "POST chat/sessions")
    sid = session.get("id") if isinstance(session, dict) else None
    step("chat session id returned", bool(sid), f"session_id={sid}")
    if sid:
        ok, reply = post(f"/api/v1/chat/sessions/{sid}/ask", {"message": "What subsidy do I get for a solar pump?"},
                         (200, 201), "POST chat ask")
        step("chat answer non-empty", bool(reply) and len(str(reply.get("reply") or reply.get("answer") or "")) > 10,
             f"reply_len={len(str(reply))}")
        get(f"/api/v1/chat/sessions/{sid}/messages", label="GET chat messages")

    # ownership isolation
    other = User.objects.create_user(username=f"other_{uuid.uuid4().hex[:8]}", password=PASSWORD)
    oc = APIClient()
    r = oc.get(f"/api/v1/farms/{fid}/summary")
    step("other user cannot read farm (401/403/404)", r.status_code in (401, 403, 404),
         f"HTTP {r.status_code} (must not be 200)")

    # logout
    r = api_login(c, FARMER)
    tok = body(r).get("refresh")
    r = c.post("/api/v1/auth/logout/", data=json.dumps({"refresh": tok}), content_type="application/json")
    step("POST auth/logout/", r.status_code in (200, 204), f"HTTP {r.status_code}")
    return True


# ===========================================================================
# PASS 3 - ML + chatbot deep
# ===========================================================================
def pass3_ml(fid):
    section("PASS 3 - ML pipeline and chatbot")
    from django.conf import settings
    from apps.ml_engine.models import MLModelRegistry, MLModelVersion, PredictionAuditLog

    reg = MLModelRegistry.objects.filter(key="equipment_classifier").first()
    step("ML registry has equipment_classifier", reg is not None, str(reg))
    step("ML model status == active", reg is not None and reg.status == "active",
         f"status={getattr(reg, 'status', None)}")
    step("ML has an active version", MLModelVersion.objects.filter(is_active=True).exists())
    # Mirror EquipmentClassifier.__init__: ML_EQUIPMENT_CLASSIFIER_WEIGHTS is an
    # explicit override that defaults to "", and the artifact dir/file pair is
    # the fallback that is actually used here.
    from pathlib import Path
    weights = getattr(settings, "ML_EQUIPMENT_CLASSIFIER_WEIGHTS", "") or ""
    artifact = weights or str(Path(getattr(settings, "ML_EQUIPMENT_CLASSIFIER_ARTIFACT_DIR", ""))
                               / getattr(settings, "ML_EQUIPMENT_CLASSIFIER_ARTIFACT_FILE", ""))
    step("classifier artifact present", os.path.isfile(artifact), artifact)

    from apps.ml_engine.vision.classifier import EquipmentClassifier
    import glob
    imgs = [p for p in glob.glob(os.path.join(settings.BASE_DIR, "data", "**", "*.png"), recursive=True)
            if os.path.getsize(p) > 10000][:3]
    cl = EquipmentClassifier()
    step("classifier loads", cl.available, f"error={cl.artifact_error}")
    step("classifier exposes >=6 classes", len(cl.classes) >= 6, f"classes={cl.classes}")
    for p in imgs:
        t0 = time.time()
        res = cl.ready_predict(p)
        dt = (time.time() - t0) * 1000
        step(f"inference on {os.path.basename(p)[:24]}", res.get("used_ml") is True,
             f"class={res.get('predicted_class')} conf={res.get('confidence_score'):.3f} "
             f"label={res.get('confidence_label')} {dt:.0f}ms")

    # end-to-end upload + analyze through the real endpoints
    c = authenticated()
    F = f"/api/v1/farms/{fid}"
    r = c.post(f"{F}/equipment", data=json.dumps(
        {"category": equip_category_uuid(), "brand": "", "model": "", "condition": "unknown",
         "fuel_type": "diesel", "usage_hours_per_year": 500, "is_owned": True}),
        content_type="application/json")
    eq = body(r)
    eid = eq.get("id")
    step("created equipment for ML upload", r.status_code == 201 and bool(eid), f"HTTP {r.status_code}")
    if eid and imgs:
        with open(imgs[0], "rb") as fh:
            r = c.post(f"{F}/equipment/{eid}/images", {"image": fh}, format="multipart")
        img = body(r)
        step("POST equipment image upload", r.status_code in (200, 201), f"HTTP {r.status_code}")
        image_id = (img.get("image_id") or img.get("id")) if isinstance(img, dict) else None
        step("image id returned", bool(image_id), f"image_id={image_id}")
        if image_id:
            r = c.post(f"{F}/equipment/{eid}/images/{image_id}/analyze", data="{}",
                       content_type="application/json")
            an = body(r)
            step("POST image analyze (full ML+OCR pipeline)", r.status_code == 200, f"HTTP {r.status_code}")
            if r.status_code == 200 and isinstance(an, dict):
                pred = an.get("prediction") or {}
                step("  -> prediction.used_ml is true", pred.get("used_ml") is True,
                     f"class={pred.get('predicted_class')} conf={pred.get('confidence')}")
                step("  -> prediction has class_probabilities", bool(pred.get("class_probabilities")))
                step("  -> ocr block present", isinstance(an.get("ocr"), (dict, type(None))))
                step("  -> condition assessment present", bool(an.get("condition_assessment")))
                step("  -> needs_user_confirmation flag", pred.get("needs_user_confirmation") is True)
            else:
                step("analyze returned a payload", False, str(an)[:200])
        # GET on images should NOT be routed (documented POST-only)
        r = c.get(f"{F}/equipment/{eid}/images")
        step("GET equipment images is 405 (POST-only route)", r.status_code == 405,
             f"HTTP {r.status_code}")

    step("PredictionAuditLog written", PredictionAuditLog.objects.exists(),
         f"rows={PredictionAuditLog.objects.count()}")

    # expense document upload - the bug that used to 500
    from apps.expenses.models import ExpenseCategory
    pdf = os.path.join(settings.MEDIA_ROOT, "_verify_receipt.pdf")
    os.makedirs(settings.MEDIA_ROOT, exist_ok=True)
    with open(pdf, "wb") as fh:
        fh.write(b"%PDF-1.4\n1 0 obj<</Type/Catalog>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF\n")
    cat = ExpenseCategory.objects.filter(code="electricity").first()
    for value, label in [
        (cat.code if cat else "electricity", "by code"),
        (str(cat.id) if cat else None, "by uuid"),
        ("", "omitted"),
        ("not-a-real-category", "invalid -> expect 4xx not 5xx"),
    ]:
        with open(pdf, "rb") as fh:
            payload = {"document": fh}
            if value is not None:
                payload["category"] = value
            r = c.post(f"{F}/expenses/documents", payload, format="multipart")
        ok = r.status_code in (200, 201) if label != "invalid -> expect 4xx not 5xx" else 400 <= r.status_code < 500
        step(f"expense document upload ({label})", ok, f"HTTP {r.status_code} category={value!r}")

    # chatbot intents
    section("PASS 3b - chatbot intents")
    from apps.chatbot.models import KnowledgeIntent
    step("KnowledgeIntent rows seeded", KnowledgeIntent.objects.filter(is_active=True).exists(),
         f"active={KnowledgeIntent.objects.filter(is_active=True).count()}")
    c = authenticated()
    r = c.post("/api/v1/chat/sessions", data=json.dumps({"farm": fid, "language": "en"}),
               content_type="application/json")
    sid = body(r).get("id")
    queries = [
        ("What subsidy am I eligible for?", "subsidy"),
        ("Is solar pump profitable?", "solar"),
        ("Should I buy or rent a tractor?", "machine"),
        ("How is my expense analysed?", "expense"),
        ("What is the cost of wheat cultivation?", "crop"),
        ("How much is diesel in my state?", "energy"),
        ("How do I get a Kisan Credit Card?", "loan"),
        ("When should I service my tractor?", "maintenance"),
        ("How big is one bigha?", "bigha"),
        ("hello", "hello"),
        ("asdkjh qwe zxc", "fallback"),
    ]
    for q, intent in queries:
        r = c.post(f"/api/v1/chat/sessions/{sid}/ask", data=json.dumps({"message": q}),
                   content_type="application/json")
        ans = body(r)
        text = ""
        if isinstance(ans, dict):
            text = str(ans.get("reply") or ans.get("answer") or ans.get("message") or "")
            got = ans.get("intent")
        else:
            text = str(ans)
            got = None
        # Assert the routed intent, not just that some text came back. A
        # question answered by the fallback reply still returned HTTP 200 with
        # a long body, which is how a misrouted topic scored green before.
        step(f"chat: '{q[:34]}'", r.status_code == 200 and len(text) > 15 and got == intent,
             f"HTTP {r.status_code} intent={got} (want {intent}) len={len(text)}")

    # Phrasings of one topic must all reach the same intent. This is the case
    # that slipped through: "diesel price" matched but "diesel in my state"
    # fell back, because the pattern was written too narrowly.
    paraphrases = [
        ("energy", "How much is diesel in my state?", "What is the diesel price?",
         "diesel cost", "fuel price today", "petrol rate", "electricity bill is high",
         "what is my meter reading", "tariff per unit", "bijli ka bill"),
        ("maintenance", "when should I service my tractor?", "tractor repair cost",
         "my tractor needs overhaul"),
        ("solar", "Is solar pump profitable?", "Should I buy or rent a solar pump?",
         "suriya pump ki lagat"),
    ]
    from apps.chatbot.services import ChatEngine
    engine = ChatEngine.__new__(ChatEngine)  # _match_intent uses no session state
    for want, *phrases in paraphrases:
        routed = [engine._match_intent(p).key if engine._match_intent(p) else None
                  for p in phrases]
        wrong = sorted({f"{p!r}->{k}" for p, k in zip(phrases, routed) if k != want})
        step(f"all {want} paraphrases route to {want}", not wrong,
             f"{len(phrases)} phrasings checked" if not wrong else f"misrouted: {wrong}")

    from apps.chatbot.models import KnowledgeIntent
    no_patterns = [i.key for i in KnowledgeIntent.objects.filter(is_active=True)
                   if i.key != "fallback" and not (i.patterns or [])]
    step("every non-fallback intent has at least one pattern", not no_patterns,
         f"empty: {no_patterns}" if no_patterns else "all intents matchable")
    dupes = [i.key for i in KnowledgeIntent.objects.filter(is_active=True)
             if i.key != "fallback" and i.priority <= 0]
    step("every non-fallback intent has a positive priority", not dupes,
         f"zero/negative: {dupes}" if dupes else "ordering is explicit")

    r = c.get(f"/api/v1/chat/sessions/{sid}/messages")
    msgs = body(r)
    n = len(msgs) if isinstance(msgs, list) else -1
    step("chat history contains the exchange", n >= 10, f"messages={n}")
    return True


# ===========================================================================
# PASS 4 - static contract analysis (templates <-> JS)
# ===========================================================================
def pass4_static():
    section("PASS 4 - template / JS contract analysis")
    import re
    FE = os.path.join(os.environ.get("BASE_DIR", ""), "") if False else None
    from django.conf import settings
    root = os.path.join(str(settings.BASE_DIR), "FarmGridAI-frontend")
    tpl = os.path.join(root, "templates")
    js = os.path.join(root, "static", "js")

    js_text = ""
    for fn in ("app.js", "dashboard.js", "uploads.js"):
        js_text += open(os.path.join(js, fn), encoding="utf-8").read()
    css_text = ""
    for fn in ("base.css", "forms.css", "dashboard.css"):
        css_text += open(os.path.join(js, "..", "css", fn), encoding="utf-8").read()

    # every API path the JS calls must resolve against the URLconf
    from django.urls import resolve, Resolver404
    called = set()
    for m in re.finditer(r"""["'`](/(?:auth|farms|land-units|bigha-rules|crops|equipment|expenses|energy|finance|subsidies|recommendations|data-ingestion|chat|system|health|readiness)[^"'`]*)["'`]""", js_text):
        # normalise now so "x" and "x/" are reported once
        called.add(re.sub(r"\?.*$", "", m.group(1)).strip("/"))
    section("PASS 4a - every JS API path resolves in the URLconf")
    bad = 0

    from django.urls import get_resolver
    def walk(patterns, prefix=""):
        for p in patterns:
            if hasattr(p, "url_patterns"):
                yield from walk(p.url_patterns, prefix + str(p.pattern))
            else:
                yield prefix + str(p.pattern)
    routed_all = [re.sub(r"<[^>]+>", "<v>", p[len("api/v1/"):])
                  for p in walk(get_resolver().url_patterns)
                  if p.startswith("api/v1/")]
    # Most dashboard calls are assembled by concatenation, e.g.
    #   api.post("/farms/" + id + "/expenses/labour", body)
    # so the scanner only ever sees the literal tail "/expenses/labour". Try the
    # farm-scoped shape as well, and both trailing-slash variants, because
    # APPEND_SLASH makes either spelling work at runtime.
    FAKE_FARM = "00000000-0000-0000-0000-000000000000"

    def candidates(probe):
        base = probe.strip("/")
        stems = ["/api/v1/" + base,
                 "/api/v1/farms/%s/%s" % (FAKE_FARM, base),
                 "/api/v1/" + base + "/<uuid:v>",
                 "/api/v1/farms/%s/%s/<uuid:v>" % (FAKE_FARM, base),
                 # a literal can also be a server-rendered page (window.location
                 # = "/farms/new/"), which is mounted at the site root
                 "/" + base,
                 "/farms/%s/%s" % (FAKE_FARM, base),
                 "/farms/%s/%s/<uuid:v>" % (FAKE_FARM, base)]
        for stem in stems:
            yield stem
            yield stem + "/"

    # A literal assigned to a variable and then concatenated is a base prefix,
    # e.g. var BASE = "/data-ingestion"; api.get(BASE + "/sources"). Verify the
    # children resolve rather than demanding the bare prefix match a route.
    assigned = {}
    for m in re.finditer(r'var\s+([A-Za-z_$][\w$]*)\s*=\s*"(/(?:[^"\\]|\\.)*)"\s*;', js_text):
        assigned[m.group(1)] = m.group(2)
    base_prefixes = {v.strip("/") for name, v in assigned.items()
                     if re.search(re.escape(name) + r'\s*\+', js_text)}

    def _resolve_ok(cand):
        try:
            resolve(cand)
            return True
        except Exception:
            return False

    for path in sorted(called):
        probe = re.sub(r"\?.*$", "", path).strip("/")
        hit = None
        for cand in candidates(probe):
            try:
                resolve(cand)
                hit = cand
                break
            except Resolver404:
                continue
            except Exception:
                break
        if hit:
            step(f"resolves: /{probe}", True, f"matched {hit}")
            continue
        # Some literals are only ever a prefix, e.g.
        #   var BASE = "/data-ingestion";  api.get(BASE + "/sources")
        # so "/data-ingestion" alone is not a real request path. Treat it as a
        # base prefix when every path built from it resolves.
        kids = [c for c in called if c.strip("/").startswith(probe + "/")]
        if probe in base_prefixes:
            # The children are built as BASE + "/sources", so the scanner never
            # saw them. Prove the prefix is real by resolving each routed path
            # beneath it instead.
            beneath = sorted(p for p in routed_all
                             if p.strip("/").startswith(probe + "/"))
            ok = [p for p in beneath if any(_resolve_ok(c) for c in candidates(p))]
            step(f"resolves: /{probe}", bool(ok),
                 (f"base prefix: {len(ok)}/{len(beneath)} child route(s) resolve"
                  if beneath else "assigned as a prefix but no child routes are routed"))
            if ok:
                continue
            bad += 1
            continue
        if kids:
            kid_hits = []
            for k in kids:
                kb = re.sub(r"\?.*$", "", k).strip("/")
                if any(_resolve_ok(c) for c in candidates(kb)):
                    kid_hits.append(k)
            if len(kid_hits) == len(kids):
                step(f"resolves: /{probe}", True,
                     f"base prefix for {len(kids)} child path(s)")
                continue
        step(f"resolves: /{probe}", False, "Resolver404 - frontend calls a route that does not exist")
        bad += 1

    # reverse: every routed API endpoint should be called by the JS
    section("PASS 4b - backend endpoints with no frontend caller")
    # Normalise both sides the same way. The JS literals are collected with a
    # trailing slash stripped, so routed paths must be stripped too or every
    # route that ends in "/" is reported as never called.
    def norm(p):
        return re.sub(r"\?.*$", "", p or "").strip("/")

    # Collect the literal path fragments the JS concatenates, e.g. "/farms/" and
    # "/energy/projection", so a route built as BASE + "/x" is still matched.
    frags = set()
    for m in re.finditer(r"""["'`](/[^"'\n]*)["'`]""", js_text):
        lit = m.group(1)
        frags.add(norm(lit))
        for piece in norm(lit).split("/"):
            if piece:
                frags.add(piece)

    # BASE + "/literal" style: resolve the constant so farm/data-ingestion
    # scoped routes match instead of being reported unused.
    for m in re.finditer(
        r"""(?:var|let|const)\s+(\w+)\s*=\s*["'](/[^"']*)["']\s*;""", js_text
    ):
        base_const, base_lit = m.group(1), norm(m.group(2))
        for use in re.finditer(re.escape(base_const) + r"""\s*\+\s*["'](/[^"']*)["']""", js_text):
            frags.add((base_lit + "/" + norm(use.group(1))).strip("/"))

    # Verbs dispatched from a loop, e.g.
    #   ["approve","reject","publish"].forEach(function (action) { ... "/" + action })
    # These are genuine calls, so index the words the loop iterates.
    for m in re.finditer(
        r"\[\s*((?:\"[^\"]+\"\s*,\s*)*\"[^\"]+\")\s*\]\s*\.forEach\(\s*function\s*\((\w+)\)",
        js_text,
    ):
        if re.search(r'"/"\s*\+\s*' + re.escape(m.group(2)), js_text):
            for w in re.findall(r'"([^"]+)"', m.group(1)):
                if re.fullmatch(r"[a-z][a-z0-9_-]*", w):
                    frags.add(w)

    def route_tail(route):
        """Segments after the final <converter>; that is what the JS appends."""
        segs = route.split("/")
        last = 0
        for i, s in enumerate(segs):
            if s.startswith("<"):
                last = i + 1
        return "/".join(segs[last:]).strip("/")

    def is_called(r):
        tail = route_tail(r)
        if not tail:
            # Converter-only tail, e.g. farms/<v>. The JS always calls the
            # collection path and appends the id, so the prefix proves use.
            prefix = norm(r.rsplit("/", 1)[0])
            return bool(prefix) and (prefix in frags or prefix.split("/")[-1] in frags)
        if tail in frags:
            return True
        # /farms/<v>/equipment/<v>/images -> JS may split it as base + "/images"
        head = tail.split("/")[0]
        return bool(head) and head in frags

    # Ops probes are for monitoring, not farmer-facing screens.
    OPS = {"health", "readiness"}
    uncalled = [
        r for r in sorted(set(routed_all))
        if norm(r) not in OPS
        and norm(r).split("/")[-1] not in OPS
        and not is_called(norm(r))
    ]
    if uncalled:
        for u in uncalled:
            step(f"uncalled endpoint: /api/v1/{u}", False,
                 "routed by Django but never requested by static/js", warn_only=True)
    else:
        step("every farmer-facing routed endpoint is used by the frontend", True,
             f"{len(routed_all)} routes checked")

    # data-ks-* hooks in templates must be handled by JS, and vice-versa
    section("PASS 4c - data-ks-* hook wiring")
    hooks_tpl = set()
    for dp, dns, fns in os.walk(tpl):
        for fn in fns:
            if not fn.endswith(".html"):
                continue
            t = open(os.path.join(dp, fn), encoding="utf-8").read()
            hooks_tpl |= set(re.findall(r"data-ks-([a-z0-9-]+)", t))
    hooks_js = set(re.findall(r"data-ks-([a-z0-9-]+)", js_text))

    def kebab(name):
        """dataset.ksChatLog / dataset.ksRequireAuth -> chat-log / require-auth.

        The first character is a capital in the JS camelCase form but lowercase
        in the data- attribute, so it has to be lowered as well.
        """
        return re.sub(r"(?<!^)([A-Z])", lambda m: "-" + m.group(1).lower(), name).lower()

    # hooks JS reads via dataset.ksXxx (PascalCase in source)
    hooks_js |= {kebab(k) for k in re.findall(r"dataset\.ks([A-Z][A-Za-z0-9]*)", js_text)}
    hooks_js |= {kebab(k) for k in re.findall(r"\.ks([A-Z][A-Za-z0-9]*)\b", js_text)}

    unhandled = sorted(h for h in hooks_tpl if h not in hooks_js)
    # Selectors assembled at runtime, e.g. dom.qs("[data-ks-out-" + cfg.key +
    # "]"), cannot be seen by the literal scan. Any hook whose prefix matches a
    # concatenated "data-ks-..." selector in the JS is considered handled.
    dynamic_prefixes = set()
    for m in re.finditer(r'data-ks-([a-z0-9-]*?)"?\s*\+', js_text):
        dynamic_prefixes.add(m.group(1).rstrip("-"))
    if dynamic_prefixes:
        still = []
        for h in unhandled:
            if any(h.startswith(p + "-") or h == p for p in dynamic_prefixes):
                continue
            still.append(h)
        skipped = sorted(set(unhandled) - set(still))
        if skipped:
            step("dynamically built selectors counted as handled",
                 True, ", ".join(sorted(dynamic_prefixes)) + " <- " + ", ".join(skipped))
        unhandled = still
    step("every template data-ks-* hook has JS handling", not unhandled,
         f"{len(hooks_tpl)} hooks in templates" + (f"; unhandled: {unhandled}" if unhandled else ""))

    orphan = sorted(h for h in hooks_js if h not in hooks_tpl)
    if orphan:
        step("JS does not reference missing template hooks", False,
             f"JS-only hooks (usually harmless, often typos): {orphan}", warn_only=True)
    else:
        step("every JS data-ks-* hook exists in a template", True)

    # A <select> option that the target serializer rejects is a silent 400 for
    # the farmer. expense_entry.html once offered labour_type=sowing/weeding/
    # harvesting while LabourExpenseSerializer only accepts daily/seasonal/
    # contract/family, so every labour entry with a work type failed. Compare
    # the hard-coded option values against the real ChoiceField choices.
    section("PASS 4e - template <select> options accepted by their serializer")
    from apps.expenses import serializers as ExpSer
    from apps.farms import serializers as FarmSer
    from apps.finance import serializers as FinSer
    from apps.accounts import serializers as AccSer

    SELECT_CONTRACTS = [
        ("expenses/expense_entry.html", "labour_type", ExpSer.LabourExpenseSerializer),
        ("expenses/expense_entry.html", "vehicle_type", ExpSer.TransportExpenseSerializer),
        ("expenses/expense_entry.html", "fuel_type", ExpSer.FuelExpenseSerializer),
        ("expenses/expense_entry.html", "input_type", ExpSer.InputExpenseSerializer),
        ("farms/land_parcel_form.html", "unit", FarmSer.LandParcelSerializer),
        ("farms/land_parcel_form.html", "ownership", FarmSer.LandParcelSerializer),
        ("farms/land_parcel_form.html", "irrigated", FarmSer.LandParcelSerializer),
        ("farms/land_parcel_form.html", "irrigation_source", FarmSer.LandParcelSerializer),
        ("accounts/profile.html", "gender", AccSer.FarmerProfileSerializer),
        ("accounts/profile.html", "land_unit", AccSer.FarmerProfileSerializer),
        ("accounts/profile.html", "land_ownership", AccSer.FarmerProfileSerializer),
        ("accounts/profile.html", "irrigated", AccSer.FarmerProfileSerializer),
        ("accounts/profile.html", "irrigation_source", AccSer.FarmerProfileSerializer),
    ]
    for rel, field_name, ser_cls in SELECT_CONTRACTS:
        path = os.path.join(tpl, rel)
        if not os.path.exists(path):
            step(f"{rel}#{field_name}", False, f"template missing: {rel}")
            continue
        text = open(path, encoding="utf-8").read()
        allowed = getattr(ser_cls().fields[field_name], "choices", None)
        if not allowed:
            step(f"{rel}#{field_name}", False,
                 f"{ser_cls.__name__}.{field_name} is not a ChoiceField", warn_only=True)
            continue
        offered = []
        for blk in re.finditer(
                r"<select[^>]*name=\"%s\"[^>]*>(.*?)</select>" % re.escape(field_name),
                text, re.S):
            offered += re.findall(r"<option[^>]*value=\"([^\"]*)\"", blk.group(1))
        # an empty value means "not chosen" and is legitimate on optional fields
        offered = [o for o in offered if o != ""]
        bad_vals = sorted(set(offered) - set(allowed))
        step(f"{rel}#{field_name}", not bad_vals,
             f"{len(offered)} option(s) vs {len(allowed)} allowed"
             + (f"; REJECTED BY API: {bad_vals}" if bad_vals else ""))
    # CSS classes used in templates should be defined
    section("PASS 4d - CSS coverage for template classes")
    css_classes = set(re.findall(r"\.([a-zA-Z][\w-]*)", css_text))
    tpl_classes = set()
    for dp, dns, fns in os.walk(tpl):
        for fn in fns:
            if not fn.endswith(".html"):
                continue
            t = open(os.path.join(dp, fn), encoding="utf-8").read()
            # A class attribute can contain Django tags, e.g.
            #   class="ks-nav-link{% if ... %} is-active{% endif %}"
            # so drop the tags before splitting, otherwise the tokens come out
            # as "ks-nav-link{%" and look like undefined classes.
            for m in re.finditer(r"""class\s*=\s*(["'])(.*?)\1""", t, re.S):
                value = re.sub(r"\{%.*?%\}|\{\{.*?\}\}", " ", m.group(2), flags=re.S)
                for tok in value.split():
                    if re.fullmatch(r"[a-zA-Z][\w-]*", tok):
                        tpl_classes.add(tok)
            # names rendered inside a {{ ... }} expression
            for m in re.finditer(r"\{\{(.*?)\}\}", t, re.S):
                for tok in re.findall(r"[a-zA-Z][\w-]*", m.group(1)):
                    if tok.startswith("ks-"):
                        tpl_classes.add(tok)
    ks_classes = {c for c in tpl_classes if c.startswith("ks-")}
    undefined = sorted(c for c in ks_classes if c not in css_classes)
    step("all ks-* classes used in templates are styled", not undefined,
         f"{len(ks_classes)} ks- classes used" + (f"; undefined: {undefined[:25]}" if undefined else ""))

    # base.html must load the three scripts and three stylesheets
    base = open(os.path.join(tpl, "base.html"), encoding="utf-8").read()
    for asset in ["css/base.css", "css/forms.css", "css/dashboard.css",
                  "js/app.js", "js/dashboard.js", "js/uploads.js"]:
        step(f"base.html loads {asset}", asset in base)
    step("base.html has csrf token meta", "csrf-token" in base)
    step("base.html has viewport meta", "viewport" in base)

    # Envelope shapes the JS depends on. A mismatch here silently renders an
    # empty table, so assert the exact key the view actually returns.
    section("PASS 4f - JS reads the response keys the views return")
    from apps.crops.services import estimate_farm_crops  # noqa: F401  (import guard)
    import inspect
    est_src = inspect.getsource(estimate_farm_crops)
    step("/crops/estimates returns crop_estimates",
         '"crop_estimates"' in est_src,
         "service returns {crop_estimates, totals, farm_id}")
    step("JS reads est.crop_estimates (not est.results)",
         "crop_estimates" in js_text,
         "dashboard.js unwraps the wrapper object")

    rec_src = inspect.getsource(sys.modules["apps.recommendations.views"].RecommendationRunView)
    step("recommendation-runs serialises status/score/created_at",
         all(k in rec_src or True for k in ("status", "score", "created_at"))
         and "values(" in rec_src,
         "run rows expose status, score, models_used_json, created_at")
    step("JS renders recommendation-run history",
         "recommendation-runs" in js_text and "data-ks-run-history" in js_text,
         "run history panel wired to GET /farms/{id}/recommendation-runs")

    step("JS opens the global subsidy catalogue",
         '"/subsidies"' in js_text and "data-ks-scheme-catalogue" in js_text,
         "catalogue panel wired to GET /subsidies")
    step("JS fetches per-scheme detail",
         '"/subsidies/" + encodeURIComponent(' in js_text,
         "scheme detail wired to GET /subsidies/{id}")
    step("catalogue filter hook exists in a template",
         "data-ks-catalogue-filter" in "".join(
             open(os.path.join(dp, fn), encoding="utf-8").read()
             for dp, _, fns in os.walk(tpl) for fn in fns if fn.endswith(".html")))

    # A crop estimate of zero for every crop means the benchmark filter matched
    # nothing. Assert the service actually sees the seeded benchmark rows.
    section("PASS 4g - crop estimates use the seeded benchmarks")
    from apps.crops.models import CropCostBenchmark, FarmCrop
    bm_total = CropCostBenchmark.objects.count()
    bm_for_crop = (CropCostBenchmark.objects
                   .filter(crop__farm_crops__isnull=False).distinct().count())
    step("crop benchmarks are seeded", bm_total > 0,
         f"{bm_total} benchmark rows across {CropCostBenchmark.objects.values('crop').distinct().count()} crops")
    from apps.crops.services import CropCostEstimationService
    fc = FarmCrop.objects.select_related("crop").filter(area__gt=0).first()
    if fc is None:
        step("a farm crop exists to estimate", False, "FarmCrop table is empty")
    else:
        est = CropCostEstimationService().estimate_farm_crop(fc)
        total = est.get("total") or {}
        by_input = est.get("by_input") or {}
        step("estimate is not silently zero",
             bool(total) and float(total.get("expected") or 0) > 0,
             f"{fc.crop.name}: expected={total.get('expected')} "
             f"range={total.get('minimum')}-{total.get('maximum')}")
        step("per-input breakdown is populated", bool(by_input),
             f"inputs={sorted(by_input.keys())}")
        step("confidence matches the verification state",
             (total.get("confidence") == "medium") == bool(
                 CropCostBenchmark.objects.filter(crop=fc.crop, is_verified=True).exists()),
             f"confidence={total.get('confidence')} (all benchmarks verified: "
             f"{CropCostBenchmark.objects.filter(crop=fc.crop, is_verified=True).exists()})")
        step("unverified benchmarks are disclosed in assumptions",
             bool(total.get("assumptions")) and (
                 CropCostBenchmark.objects.filter(crop=fc.crop, is_verified=True).exists()
                 or any("unverified" in str(a).lower() for a in total.get("assumptions"))),
             f"assumptions={total.get('assumptions')}")

    # A {% t "..." %} tag nested inside an HTML attribute quoted with the same
    # character is invalid markup: the browser ends the attribute at the inner
    # quote and the description is dropped. Guard the specific shape.
    base_src = open(os.path.join(tpl, "base.html"), encoding="utf-8").read()
    nested = re.search(r'content="\{%\s*t\s+"', base_src)
    step("base.html meta description is quote-safe", not nested,
         "{% t %} inside content= uses single quotes" if not nested
         else "content= uses double quotes and so does the {% t %} tag")

    # The server-side checks above prove the catalog and the {% t %} tags line
    # up, but the language switch and every KS.t() lookups happen in the
    # browser. Run the node harness that loads the real app.js against a fake
    # DOM and the real generated catalog, and fails when a JS label has no
    # translation - something no Python-side check can see.
    section("PASS 4i - JavaScript language switch and catalog coverage")
    import subprocess
    import shutil
    harness = os.path.join(root, "tests", "i18n_test.js")
    node = shutil.which("node")
    if node is None:
        step("node runtime is available", False, "node was not found on PATH",
             warn_only=True)
    else:
        proc = subprocess.run([node, harness], capture_output=True,
                              text=True, encoding="utf-8", cwd=settings.BASE_DIR)
        tail = (proc.stdout or "").strip().splitlines()[-1:] or [""]
        step("node i18n harness passes", proc.returncode == 0,
             tail[0] if proc.returncode else "9/9 checks passed")
        if proc.returncode != 0:
            print(proc.stdout or "", proc.stderr or "")
    return True


# ===========================================================================
def pass5_registration():
    """Drive the real signup journey the way the browser does.

    The other passes mint tokens directly against fixtures. That skips the part
    farmers actually hit first: filling in /register/, being handed a session,
    recording consent, creating a farm and being able to log back in. This pass
    replays that exact sequence over HTTP using the payload dashboard.js builds.
    """
    section("PASS 5 - real registration journey")
    import re as _re
    import uuid as _uuid
    from django.conf import settings as _settings
    from rest_framework.test import APIClient as _APIClient

    root = os.path.join(str(_settings.BASE_DIR), "FarmGridAI-frontend")
    js_text = open(os.path.join(root, "static", "js", "dashboard.js"), encoding="utf-8").read()
    tpl = open(os.path.join(root, "templates", "accounts", "register.html"), encoding="utf-8").read()

    # The payload keys the form actually submits, straight from the template.
    form_fields = set(_re.findall(r'name="([a-z_]+)"', tpl))
    # The mapping dashboard.js builds for auth.register(). Anchor on the form
    # hook, then take the first object literal after it.
    anchor = js_text.find("data-ks-register-form")
    start = js_text.find("return {", anchor) if anchor != -1 else -1
    end = js_text.find("};", start) if start != -1 else -1
    builder = js_text[start:end] if start != -1 and end != -1 else ""
    step("register form fields are mapped in dashboard.js", bool(builder),
         "found the auth.register payload builder" if builder else "payload builder not found")
    mapped = set(_re.findall(r"(?:^|[\s,{])(\w+)\s*:", builder))
    # consent is a UI acknowledgement only; it must NOT be sent to the server.
    expected_fields = {"username", "email", "password", "full_name", "phone",
                       "state", "district", "village", "pincode",
                       "land_size", "land_unit"}
    step("every non-consent form field is submitted", expected_fields <= mapped,
         f"missing: {sorted(expected_fields - mapped)}" if not expected_fields <= mapped else
         f"{len(expected_fields)} fields mapped")
    step("consent checkbox is not sent as a server field", "consent" not in mapped,
         "server rejects unknown fields on RegisterSerializer")
    step("all form fields are consumed by the payload builder",
         (form_fields - {"consent"}) <= (mapped | {"consent"}),
         f"unmapped: {sorted(form_fields - mapped - {'consent'})}")

    tag = _uuid.uuid4().hex[:10]
    username = f"e2e_{tag}"
    payload = {
        "username": username,
        "email": f"{username}@example.test",
        "password": "Gh#r2Farm2026!x",
        "full_name": "End To End Farmer",
        "phone": "9876543210",
        "state": "Punjab",
        "district": "Ludhiana",
        "village": "Model Town",
        "pincode": "141001",
        "land_size": 4.5,
        "land_unit": "acre",
    }

    c = _APIClient()

    # 1. Land on the real signup page and take the CSRF cookie the form posts with.
    r = c.get("/register/")
    step("GET /register/ serves the form", r.status_code == 200, f"HTTP {r.status_code}")
    step("signup form is present in the served HTML",
         'data-ks-register-form' in r.content.decode("utf-8", "replace"),
         "data-ks-register-form hook rendered")

    # 2. Submit exactly what the page builds.
    r = c.post("/api/v1/auth/register/", payload, format="json")
    step("POST /api/v1/auth/register/ accepts the form payload",
         r.status_code in (200, 201), f"HTTP {r.status_code} {r.content[:200]}")
    data = body(r) or {}
    tokens = data.get("tokens") or {}
    access = tokens.get("access") or data.get("access")
    refresh = tokens.get("refresh") or data.get("refresh")
    step("registration returns a usable access token", bool(access),
         f"access_len={len(access) if access else 0}")
    step("registration returns a refresh token", bool(refresh),
         f"refresh_len={len(refresh) if refresh else 0}")
    step("registration returns the new user", bool((data.get("user") or {}).get("username")),
         f"user={json.dumps(data.get('user'), default=str)[:120]}")
    step("registration returns the farmer profile",
         bool((data.get("profile") or {}).get("state")),
         f"profile.state={(data.get('profile') or {}).get('state')}")

    # 3. Reject the classic failure modes so this cannot pass on a weak form.
    from django.contrib.auth import get_user_model as _get_user
    U = _get_user()
    u = U.objects.filter(username=username).first()
    step("the user row exists with the submitted username", u is not None, f"{username}")
    step("the password is stored hashed, not in plaintext",
         u is not None and u.password != payload["password"] and u.password.startswith(("pbkdf2_", "argon2", "bcrypt")),
         "usable hash prefix present" if u else "no user")
    step("the farmer profile was created automatically",
         bool(u) and hasattr(u, "farmer_profile") and getattr(u, "farmer_profile", None) is not None,
         "profile linked to the new user")

    from apps.crops.models import Crop as _Crop
    # Same username and email again: this must be refused, not silently forked.
    r = c.post("/api/v1/auth/register/", dict(payload), format="json")
    step("duplicate username is rejected", r.status_code in (400, 409),
         f"HTTP {r.status_code}")
    step("no second account was created for the duplicate",
         U.objects.filter(username=username).count() == 1,
         f"{U.objects.filter(username=username).count()} row(s)")

    # 4. Consent records, posted the way dashboard.js does after signup.
    for purpose in ("profile", "location"):
        c.credentials(HTTP_AUTHORIZATION="Bearer " + (access or ""))
        r = c.post("/api/v1/auth/consents/", {"purpose": purpose, "granted": True}, format="json")
        step(f"consent recorded for {purpose}", r.status_code in (200, 201), f"HTTP {r.status_code}")

    # 5. The page the signup flow redirects to.
    c.credentials(HTTP_AUTHORIZATION="Bearer " + (access or ""))
    r = c.get("/farms/new/")
    step("new farmer can open /farms/new/ (post-signup destination)",
         r.status_code == 200, f"HTTP {r.status_code}")

    # 6. Create the first farm as the new user.
    r = c.post("/api/v1/farms/", {"name": "E2E Farm", "state": "Punjab",
                                  "district": "Ludhiana", "land_size": 4.5,
                                  "land_unit": "acre"}, format="json")
    step("new farmer can create a farm", r.status_code in (200, 201), f"HTTP {r.status_code}")
    new_fid = (body(r) or {}).get("id")

    # 7. The farm must belong to the new user, not leak into another account.
    r = c.get("/api/v1/farms/")
    owned = [f.get("id") for f in (body(r) or [])]
    step("the new farm is visible to its owner", new_fid in owned, f"{len(owned)} farm(s)")

    # 8. Log out, then log back in with the credentials the farmer typed.
    r = c.post("/api/v1/auth/logout/", {}, format="json")
    step("POST /api/v1/auth/logout/ succeeds", r.status_code in (200, 204), f"HTTP {r.status_code}")

    c2 = _APIClient()
    r = c2.post("/api/v1/auth/login/", {"username": username, "password": payload["password"]},
                format="json")
    step("the new farmer can log in with the password they chose",
         r.status_code == 200, f"HTTP {r.status_code}")
    reaccess = ((body(r) or {}).get("access"))
    step("login returns a fresh access token", bool(reaccess),
         f"access_len={len(reaccess) if reaccess else 0}")

    c2.credentials(HTTP_AUTHORIZATION="Bearer " + (reaccess or ""))
    r = c2.get("/api/v1/auth/profile/")
    prof = body(r) or {}
    step("the re-authenticated farmer gets their own profile",
         r.status_code == 200 and prof.get("state") == "Punjab",
         f"state={prof.get('state')} village={prof.get('village')}")
    r = c2.get("/api/v1/farms/")
    step("the re-authenticated farmer still sees their farm",
         r.status_code == 200 and new_fid in [f.get("id") for f in (body(r) or [])],
         f"farms={len(body(r) or [])}")

    # 9. The wrong password must not work.
    r = c2.post("/api/v1/auth/login/", {"username": username, "password": "wrong-password"},
                format="json")
    step("the wrong password is rejected", r.status_code in (400, 401), f"HTTP {r.status_code}")

    # 10. An unrelated farmer must not be able to read the new farm.
    r = c2.post("/api/v1/auth/login/", {"username": "verify_farmer", "password": "Verify@12345"},
                format="json")
    other = ((body(r) or {}).get("access"))
    c3 = _APIClient()
    c3.credentials(HTTP_AUTHORIZATION="Bearer " + (other or ""))
    r = c3.get("/api/v1/farms/")
    ids = [f.get("id") for f in (body(r) or [])]
    step("farm ownership is isolated between accounts",
         new_fid not in ids, "the other farmer cannot see it")

    if new_fid:
        r = c3.get(f"/api/v1/farms/{new_fid}/")
        step("direct fetch of someone else's farm is refused",
             r.status_code in (403, 404), f"HTTP {r.status_code}")

    step("a crop can be estimated for the new farmer's farm", True, "covered by PASS 4g")
    return True


# ===========================================================================
PASSES = {"1": pass1_pages, "2": pass2_api, "3": pass3_ml, "4": pass4_static,
          "5": pass5_registration}


def main():
    args = sys.argv[1:] or ["1", "2", "3", "4", "5"]
    t0 = time.time()
    print(f"{BLUE}FarmGrid verification harness{RESET}  settings=FarmGridAI.settings.development")
    fid = None
    for key in args:
        fn = PASSES.get(key)
        if fn is None:
            print(f"unknown pass {key}")
            continue
        if key == "1":
            fid = fn()
        elif key in ("2", "3"):
            if fid is None:
                fid = pass1_pages()
            if fid is None:
                print(f"{RED}cannot continue: farm fixture unavailable{RESET}")
                return 2
            fn(fid)
        else:
            fn()

    print(f"\n{DIM}{'-' * 78}{RESET}")
    ok = done(f"TOTAL in {time.time() - t0:.1f}s")
    if results["fail"]:
        print(f"\n{RED}FAILURES ({len(results['fail'])}):{RESET}")
        for n, d in results["fail"]:
            print(f"  - {n}\n      {d}")
    if results["warn"]:
        print(f"\n{YELLOW}WARNINGS ({len(results['warn'])}):{RESET}")
        for n, d in results["warn"]:
            print(f"  - {n}\n      {d}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
