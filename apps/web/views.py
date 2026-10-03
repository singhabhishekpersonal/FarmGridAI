"""HTML page views.

The application is API-first: every number on every page is produced by
``/api/v1/`` and rendered client-side by ``static/js/*.js``. These views are
deliberately thin - they resolve the farm from the URL, hand the browser the
page context (``data-ks-page``, ``data-ks-farm-id``), and get out of the way.

Keeping this layer thin means there is exactly one implementation of the
analytics and one definition of the response contract, and it cannot drift
from the OpenAPI schema.
"""
from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.shortcuts import redirect, render
from django.contrib.auth.views import redirect_to_login
from django.conf import settings
from django.utils import translation
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_http_methods

from apps.accounts.models import UserLanguagePreference

from apps.equipment.models import FarmerEquipment
from apps.farms.models import Farm


# ---------------------------------------------------------------------------
# Shared context
# ---------------------------------------------------------------------------

def base_context(request, ks_page, *, require_auth=True, farm=None, extra=None):
    """Context every page template relies on via base.html."""
    user = request.user
    context = {
        "ks_page": ks_page,
        "require_auth": require_auth,
        "farm_id": str(farm.id) if farm else None,
        "farm": farm,
        # A login_required() bounce on an API-driven page leaves no visible
        # message, so the pages that redirect carry one.
        "equipment_id": None,
        "preferred_language": (user.preferred_language if user.is_authenticated else "en") or "en",
        "is_staff": bool(user.is_authenticated and user.is_staff),
    }
    if extra:
        context.update(extra)
    return context


def staff_required(view):
    """Gate a page to staff.

    Anonymous visitors are sent to the login page; an authenticated non-staff
    user gets a 403 rather than a redirect, because being logged in is not the
    problem and bouncing them to the dashboard hides why.
    """

    @wraps(view)
    def _wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path())
        if not request.user.is_staff:
            raise PermissionDenied("This area is for staff only.")
        return view(request, *args, **kwargs)

    return _wrapped


def _get_farm(request, farm_id):
    """Fetch a farm the signed-in user owns, or 404.

    Ownership is enforced server-side so a guessed UUID cannot expose another
    farmer's records through the page shell.
    """
    if not request.user.is_authenticated:
        return None
    farm = Farm.objects.filter(pk=farm_id, user=request.user).first()
    if farm is None:
        raise Http404("Farm not found.")
    return farm


def _get_equipment(request, farm, equipment_id):
    equipment = FarmerEquipment.objects.filter(pk=equipment_id, farm=farm).first()
    if equipment is None:
        raise Http404("Equipment not found.")
    return equipment


# ---------------------------------------------------------------------------
# Public
# ---------------------------------------------------------------------------

@ensure_csrf_cookie
@require_http_methods(["GET", "HEAD"])
def home(request):
    return render(
        request,
        "index.html",
        base_context(request, "home", require_auth=False),
    )


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------

def _landing_after_login(request):
    """Where to send someone who is already signed in and opens /login/.

    Only for a plain visit. When a ``next`` is present the browser got here from
    the client-side auth guard, and bouncing straight back would fight it: the
    guard redirects to /login/?next=<guarded page> whenever localStorage has no
    JWT, so an answer of 302 -> /dashboard/ produced an endless
    /dashboard/ <-> /login/ flicker. That state - live session, missing JWT -
    is exactly what a cleared or blocked storage produces, and it has to end on
    a page the guard will not redirect away from.
    """
    if not request.user.is_authenticated:
        return None
    if request.GET.get("next"):
        return None
    from django.shortcuts import redirect

    return redirect("web:dashboard")


@ensure_csrf_cookie
@require_http_methods(["GET", "HEAD"])
def login(request):
    landing = _landing_after_login(request)
    if landing is not None:
        return landing
    return render(
        request,
        "accounts/login.html",
        base_context(request, "login", require_auth=False),
    )


@require_http_methods(["GET", "HEAD"])
def logout(request):
    """Close the session and go to the sign-in page.

    This exists so signing out is a single navigation rather than an AJAX call
    followed by a redirect. Doing it in two steps raced: the client navigated to
    /login/ even when the POST had failed, /login/ then redirected an
    apparently-still-authenticated visitor to /dashboard/, whose auth guard
    bounced them back - a visible three-step flicker.

    Closing the session in the response that performs the redirect removes the
    race entirely. The JWT pair in localStorage is cleared by auth.logout()
    before it navigates here; the API endpoint /api/v1/auth/logout/ stays for
    non-browser clients.
    """
    from django.contrib.auth import logout as auth_logout
    from django.shortcuts import redirect

    auth_logout(request)
    return redirect("web:login")


@ensure_csrf_cookie
@require_http_methods(["GET", "HEAD"])
def register(request):
    landing = _landing_after_login(request)
    if landing is not None:
        return landing
    return render(
        request,
        "accounts/register.html",
        base_context(request, "register", require_auth=False),
    )


# ---------------------------------------------------------------------------
# Farmer area
# ---------------------------------------------------------------------------

@login_required
@ensure_csrf_cookie
@require_http_methods(["GET", "HEAD"])
def dashboard(request):
    """Active farm is the caller's default, or their only farm."""
    farm = Farm.objects.filter(user=request.user).order_by("-is_default", "name").first()
    return render(
        request,
        "dashboard.html",
        base_context(request, "dashboard", farm=farm),
    )


@login_required
@ensure_csrf_cookie
@require_http_methods(["GET", "HEAD"])
def profile(request):
    return render(
        request,
        "accounts/profile.html",
        base_context(request, "profile"),
    )


@login_required
@ensure_csrf_cookie
@require_http_methods(["GET", "HEAD"])
def chat(request):
    farm = Farm.objects.filter(user=request.user).order_by("-is_default", "name").first()
    return render(
        request,
        "chatbot/chat.html",
        base_context(request, "chat", farm=farm),
    )


# ---------------------------------------------------------------------------
# Farms
# ---------------------------------------------------------------------------

@login_required
@ensure_csrf_cookie
@require_http_methods(["GET", "HEAD"])
def farm_create(request):
    return render(
        request,
        "farms/farm_create.html",
        base_context(request, "farmCreate"),
    )


@login_required
@ensure_csrf_cookie
@require_http_methods(["GET", "HEAD"])
def farm_detail(request, farm_id):
    farm = _get_farm(request, farm_id)
    return render(
        request,
        "farms/farm_detail.html",
        base_context(request, "farm", farm=farm),
    )


@login_required
@ensure_csrf_cookie
@require_http_methods(["GET", "HEAD"])
def land_parcel_form(request, farm_id):
    farm = _get_farm(request, farm_id)
    return render(
        request,
        "farms/land_parcel_form.html",
        base_context(request, "parcel", farm=farm),
    )


@login_required
@ensure_csrf_cookie
@require_http_methods(["GET", "HEAD"])
def farm_crops(request, farm_id):
    """Add a crop. The farm page's crops tab links here to create a new one."""
    farm = _get_farm(request, farm_id)
    return render(
        request,
        "farms/crop_form.html",
        base_context(request, "cropCreate", farm=farm),
    )


# ---------------------------------------------------------------------------
# Expenses
# ---------------------------------------------------------------------------

@login_required
@ensure_csrf_cookie
@require_http_methods(["GET", "HEAD"])
def expense_dashboard(request, farm_id):
    farm = _get_farm(request, farm_id)
    return render(
        request,
        "expenses/expense_dashboard.html",
        base_context(request, "expenses", farm=farm),
    )


@login_required
@ensure_csrf_cookie
@require_http_methods(["GET", "HEAD"])
def expense_entry(request, farm_id):
    farm = _get_farm(request, farm_id)
    return render(
        request,
        "expenses/expense_entry.html",
        base_context(request, "expenseEntry", farm=farm),
    )


# ---------------------------------------------------------------------------
# Equipment
# ---------------------------------------------------------------------------

@login_required
@ensure_csrf_cookie
@require_http_methods(["GET", "HEAD"])
def equipment_list(request, farm_id):
    farm = _get_farm(request, farm_id)
    return render(
        request,
        "equipment/equipment_list.html",
        base_context(request, "equipment", farm=farm),
    )


@login_required
@ensure_csrf_cookie
@require_http_methods(["GET", "HEAD"])
def equipment_detail(request, farm_id, equipment_id):
    farm = _get_farm(request, farm_id)
    equipment = _get_equipment(request, farm, equipment_id)
    return render(
        request,
        "equipment/equipment_detail.html",
        base_context(
            request,
            "equipmentDetail",
            farm=farm,
            extra={"equipment_id": str(equipment.id), "equipment": equipment},
        ),
    )


@login_required
@ensure_csrf_cookie
@require_http_methods(["GET", "HEAD"])
def equipment_upload(request, farm_id, equipment_id=None):
    """Add equipment, or add photos to an existing machine.

    With no ``equipment_id`` the page renders the "add equipment" form; with one
    it renders the photo uploader that drives the ML analysis.
    """
    farm = _get_farm(request, farm_id)
    equipment = _get_equipment(request, farm, equipment_id) if equipment_id else None
    return render(
        request,
        "equipment/equipment_upload.html",
        base_context(
            request,
            "equipmentUpload",
            farm=farm,
            extra={
                "equipment_id": str(equipment.id) if equipment else None,
                "equipment": equipment,
            },
        ),
    )


# ---------------------------------------------------------------------------
# Analytics
# ---------------------------------------------------------------------------

@login_required
@ensure_csrf_cookie
@require_http_methods(["GET", "HEAD"])
def recommendations(request, farm_id):
    farm = _get_farm(request, farm_id)
    return render(
        request,
        "recommendations/recommendations.html",
        base_context(request, "recommendations", farm=farm),
    )


@login_required
@ensure_csrf_cookie
@require_http_methods(["GET", "HEAD"])
def subsidy_recommendations(request, farm_id):
    farm = _get_farm(request, farm_id)
    return render(
        request,
        "subsidies/subsidy_recommendations.html",
        base_context(request, "subsidies", farm=farm),
    )


@login_required
@ensure_csrf_cookie
@require_http_methods(["GET", "HEAD"])
def solar_comparison(request, farm_id):
    farm = _get_farm(request, farm_id)
    # Tariff benchmarks are state-scoped, and the state lives on FarmLocation
    # rather than Farm, so resolve it here instead of in the template (which
    # would run a query per render). create_farm() backfills a placeholder
    # "Unknown" state, which would match no benchmark rows, so treat it and
    # blank values as "no state" and let the panel fall back to the national list.
    location = farm.locations.order_by("created_at").first()
    state = (location.state if location else "").strip()
    if state.lower() == "unknown":
        state = ""
    return render(
        request,
        "energy/solar_comparison.html",
        base_context(request, "solar", farm=farm, extra={"farm_state": state}),
    )


@login_required
@ensure_csrf_cookie
@require_http_methods(["GET", "HEAD"])
def machinery_decision(request, farm_id):
    farm = _get_farm(request, farm_id)
    return render(
        request,
        "finance/machinery_decision.html",
        base_context(request, "finance", farm=farm),
    )


# ---------------------------------------------------------------------------
# Staff area
# ---------------------------------------------------------------------------

@staff_required
@ensure_csrf_cookie
@require_http_methods(["GET", "HEAD"])
def staff_data_ingestion(request):
    """Internal data-ops console for the ``/api/v1/data-ingestion/`` surface.

    These endpoints are permission-gated to staff server-side, so this page
    only has to agree with them: an authenticated non-staff user never gets
    here, and anything they could reach by guessing a UUID is refused again by
    the API itself.
    """
    return render(
        request,
        "data_ingestion/console.html",
        base_context(request, "staffDataIngestion"),
    )


# ---------------------------------------------------------------------------
# Language switching
# ---------------------------------------------------------------------------


def set_language(request, code=None):
    """Switch the active language and return the user to where they were.

    The EN / हिंदी control has to cause a full server re-render, because most of
    the page copy lives in templates. Changing only ``localStorage`` would leave
    the already-painted text in the old language.

    Django 6 activates the request language from a cookie
    (``settings.LANGUAGE_COOKIE_NAME``), so that cookie is what we set; the
    choice is also stored on the user record when signed in so it follows the
    farmer to another browser.
    """
    code = (code or request.POST.get("language") or request.GET.get("language") or "").strip()
    if code not in dict(settings.LANGUAGES):
        code = settings.LANGUAGE_CODE

    translation.activate(code)
    request.LANGUAGE_CODE = code

    if request.user.is_authenticated:
        request.user.preferred_language = code
        request.user.save(update_fields=["preferred_language"])
        UserLanguagePreference.objects.update_or_create(
            user=request.user,
            language_code=code,
            defaults={"is_primary": True},
        )

    destination = (
        request.POST.get("next")
        or request.GET.get("next")
        or request.META.get("HTTP_REFERER")
        or "/"
    )
    # Only ever redirect within this site: an open redirect here would hand an
    # attacker a working phishing link off a trusted origin.
    if not destination.startswith("/") or destination.startswith("//"):
        destination = "/"

    response = redirect(destination)
    # A year, matching Django's own language cookie. SameSite=Lax so the switch
    # works from a normal in-app link while still blocking cross-site POSTs.
    response.set_cookie(
        settings.LANGUAGE_COOKIE_NAME,
        code,
        max_age=365 * 24 * 60 * 60,
        samesite="Lax",
        secure=settings.SESSION_COOKIE_SECURE,
    )
    return response
