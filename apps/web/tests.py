"""Smoke and contract tests for the farmer-facing web layer.

Run with::

    python manage.py test apps.web

These are Django ``TestCase`` tests, so they run under ``manage.py test``. The
domain apps (farms, expenses, equipment, ml_engine, ...) are covered by a
separate pytest suite instead - run ``python -m pytest`` for those. The two
suites are disjoint; ``manage.py test`` will not collect the pytest files.

What is checked here:
  * every page route resolves and renders;
  * a farmer cannot open another farmer's farm or equipment through a page URL;
  * form <option> values match the choices on the model field they post to;
  * the JWT refresh round-trip the client's silent 401-retry depends on.

The analytics themselves are not re-tested here.
"""
import uuid

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from apps.farms.models import Farm

User = get_user_model()


class PageRouteTests(TestCase):
    """Every page renders, and every farm page is owner-only."""

    def setUp(self):
        self.owner = User.objects.create_user(
            username="owner", email="owner@example.com", password="Str0ngPassw0rd!"
        )
        self.other = User.objects.create_user(
            username="other", email="other@example.com", password="Str0ngPassw0rd!"
        )
        self.farm = FarmService_create_farm(self.owner)

        self.stranger_farm = FarmService_create_farm(self.other)

    # -- public ---------------------------------------------------------
    def test_public_pages_render(self):
        for name in ("home", "login", "register"):
            with self.subTest(page=name):
                url = reverse("web:" + name)
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)
                self.assertIn("FarmGrid", response.content.decode())

    # -- auth required --------------------------------------------------
    def test_authenticated_pages_redirect_when_anonymous(self):
        for name in ("dashboard", "profile", "chat"):
            with self.subTest(page=name):
                response = self.client.get(reverse("web:" + name))
                self.assertEqual(response.status_code, 302)
                self.assertIn("/login/", response["Location"])

    def test_farmer_pages_render(self):
        self.client.force_login(self.owner)
        farm_id = self.farm.id
        cases = [
            ("dashboard", None),
            ("profile", None),
            ("chat", None),
            ("farm_create", None),
            ("farm_detail", farm_id),
            ("land_parcel_form", farm_id),
            ("farm_crops", farm_id),
            ("expense_dashboard", farm_id),
            ("expense_entry", farm_id),
            ("equipment_list", farm_id),
            ("equipment_create", farm_id),
            ("recommendations", farm_id),
            ("subsidy_recommendations", farm_id),
            ("solar_comparison", farm_id),
            ("machinery_decision", farm_id),
        ]
        for name, arg in cases:
            with self.subTest(page=name):
                url = reverse("web:" + name, args=[arg] if arg else [])
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200, msg=name)

    def test_equipment_pages_render(self):
        self.client.force_login(self.owner)
        equipment = _make_equipment(self.owner, self.farm)
        for name in ("equipment_detail", "equipment_upload"):
            with self.subTest(page=name):
                url = reverse("web:" + name, args=[self.farm.id, equipment.id])
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200, msg=name)

    def test_unknown_farm_is_404(self):
        self.client.force_login(self.owner)
        response = self.client.get(reverse("web:farm_detail", args=[uuid.uuid4()]))
        self.assertEqual(response.status_code, 404)

    def test_cannot_open_another_farmers_page(self):
        """A guessed farm UUID must not expose another farmer's shell."""
        self.client.force_login(self.owner)
        response = self.client.get(
            reverse("web:farm_detail", args=[self.stranger_farm.id])
        )
        self.assertEqual(response.status_code, 404)

    def test_equipment_detail_rejects_foreign_equipment(self):
        self.client.force_login(self.owner)
        foreign = _make_equipment(self.other, self.stranger_farm)
        response = self.client.get(
            reverse("web:equipment_detail", args=[self.farm.id, foreign.id])
        )
        self.assertEqual(response.status_code, 404)

    def test_land_parcel_form_carries_farm_id(self):
        self.client.force_login(self.owner)
        response = self.client.get(reverse("web:land_parcel_form", args=[self.farm.id]))
        body = response.content.decode()
        self.assertIn('data-ks-farm-id="%s"' % self.farm.id, body)

    def test_equipment_upload_page_carries_equipment_id(self):
        """uploads.js reads dom.cfg('equipId'); base.html must emit it."""
        self.client.force_login(self.owner)
        equipment = _make_equipment(self.owner, self.farm)
        response = self.client.get(
            reverse("web:equipment_upload", args=[self.farm.id, equipment.id])
        )
        self.assertIn('data-ks-equip-id="%s"' % equipment.id, response.content.decode())

    def test_every_form_option_value_is_a_valid_server_choice(self):
        """Guards against template enums drifting from the model choices.

        A stale <option> is invisible in review and only fails when a farmer
        actually picks it, so every select is compared against the live choices
        on the model field it posts to.
        """
        from apps.accounts.models import FarmerProfile
        from apps.equipment.models import FarmerEquipment
        from apps.farms.models import LandParcel

        def choices(field):
            return {c[0] for c in field.choices}

        parcel = LandParcel._meta
        cases = [
            ("web:register", {"land_unit": choices(FarmerProfile._meta.get_field("land_unit"))}),
            (
                "web:land_parcel_form",
                {
                    "unit": choices(parcel.get_field("unit")),
                    "ownership": choices(parcel.get_field("ownership")),
                    "irrigated": choices(parcel.get_field("irrigated")),
                    "irrigation_source": choices(parcel.get_field("irrigation_source")),
                },
                [self.farm.id],
            ),
            (
                "web:farm_create",
                {"parcel_unit": choices(parcel.get_field("unit"))},
            ),
            (
                "web:equipment_create",
                {
                    "condition": choices(FarmerEquipment._meta.get_field("condition")),
                    "fuel_type": choices(FarmerEquipment._meta.get_field("fuel_type")),
                },
                [self.farm.id],
            ),
        ]

        for case in cases:
            url_name, expected = case[0], case[1]
            args = case[2] if len(case) > 2 else []
            # Register redirects a signed-in farmer away, so it is checked
            # anonymously; every other page needs a session.
            if url_name == "web:register":
                self.client.logout()
            else:
                self.client.force_login(self.owner)
            with self.subTest(page=url_name):
                response = self.client.get(reverse(url_name, args=args))
                self.assertEqual(response.status_code, 200, msg=url_name)
                found = _select_values(response.content.decode())

                # Only the fields we know about; a new select is not a failure.
                for field, allowed in expected.items():
                    options = found.get(field)
                    if options is None:
                        continue
                    invalid = options - allowed
                    self.assertEqual(
                        invalid, set(), msg="%s/%s offers invalid options" % (url_name, field)
                    )

    def test_csrf_token_is_exposed_for_the_api_layer(self):
        response = self.client.get(reverse("web:login"))
        self.assertIn("csrftoken", response.cookies)


class TokenRefreshTests(TestCase):
    """The client's silent 401-retry depends on this route existing."""

    def setUp(self):
        self.user = User.objects.create_user(
            username="refresher", email="r@example.com", password="Str0ngPassw0rd!"
        )
        self.client_api = APIClient()

    def _login(self):
        response = self.client_api.post(
            reverse("auth-login"), {"username": "refresher", "password": "Str0ngPassw0rd!"}
        )
        self.assertEqual(response.status_code, 200, msg=response.content)
        return response.data["data"]

    def test_refresh_returns_a_new_access_token_in_the_standard_envelope(self):
        tokens = self._login()
        response = self.client_api.post(
            reverse("auth-refresh"), {"refresh": tokens["refresh"]}
        )
        self.assertEqual(response.status_code, 200, msg=response.content)
        self.assertTrue(response.data["success"])
        self.assertIn("access", response.data["data"])

    def test_refresh_token_is_rotated(self):
        """ROTATE_REFRESH_TOKENS is on, so a new refresh token comes back."""
        tokens = self._login()
        response = self.client_api.post(
            reverse("auth-refresh"), {"refresh": tokens["refresh"]}
        )
        self.assertIn("refresh", response.data["data"])

    def test_missing_refresh_token_is_rejected(self):
        response = self.client_api.post(reverse("auth-refresh"), {})
        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.data["success"])

    def test_garbage_refresh_token_is_401(self):
        response = self.client_api.post(reverse("auth-refresh"), {"refresh": "not-a-token"})
        self.assertEqual(response.status_code, 401)
        self.assertFalse(response.data["success"])


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def FarmService_create_farm(user):
    from apps.farms.models import FarmService

    return FarmService.create_farm(user=user, name="Test farm", state="Maharashtra")


def _make_equipment(user, farm):
    from apps.equipment.models import EquipmentCategory, FarmerEquipment

    category, _ = EquipmentCategory.objects.get_or_create(
        code="tractor", defaults={"name": "Tractor"}
    )
    return FarmerEquipment.objects.create(
        farm=farm,
        category=category,
        custom_brand="Mahindra",
        custom_model="575 DI",
        horsepower=45,
        purchase_year=2018,
        condition="good",
        fuel_type="diesel",
        is_owned=True,
        is_operational=True,
        created_by=user,
    )


def _select_values(html):
    """Map each <select name="..."> to the set of its <option value="...">.

    Deliberately regex-based: the templates are hand-written HTML, not Django
    form widgets, and this is only a contract check.
    """
    import re

    out = {}
    for select in re.findall(r"<select\b[^>]*>.*?</select>", html, re.S | re.I):
        name_match = re.search(r'name="([^"]+)"', select)
        if not name_match:
            continue
        options = re.findall(r'<option\b[^>]*value="([^"]*)"', select, re.I)
        out.setdefault(name_match.group(1), set()).update(options)
    return out
