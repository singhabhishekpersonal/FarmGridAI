"""Auth and profile API views."""
from django.contrib.auth import login as django_login
from django.contrib.auth import logout as django_logout
from django.db import transaction
from rest_framework import serializers, status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.throttling import AnonRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer, TokenRefreshSerializer
from drf_spectacular.utils import inline_serializer

from apps.accounts.models import ConsentRecord, UserLanguagePreference
from apps.accounts.serializers import (
    ConsentRecordSerializer,
    FarmerProfileSerializer,
    RegisterSerializer,
    UserLanguagePreferenceSerializer,
    UserSerializer,
)
from apps.accounts.services import ensure_farmer_profile, grant_consent, register_user, revoke_consent
from apps.api.docs import envelope, envelope_list, error_envelope, extend_schema, token_envelope, token_pair
from apps.api.mixins import ApiResponseMixin

_CONSENT_REQUEST = inline_serializer(
    name="ConsentRequest",
    fields={
        "purpose": serializers.CharField(help_text="One of the entries in ConsentRecord.PURPOSES."),
        "granted": serializers.BooleanField(required=False, default=True),
        "version": serializers.CharField(required=False, allow_blank=True),
    },
)

_LANGUAGE_REQUEST = inline_serializer(
    name="LanguagePreferenceRequest",
    fields={"language_code": serializers.CharField(help_text="'en' or 'hi'.", default="en")},
)


class RegisterThrottle(AnonRateThrottle):
    rate = "10/hour"


class LoginThrottle(AnonRateThrottle):
    rate = "20/hour"


def _start_django_session(request, user):
    """Attach a Django session for ``user`` alongside the JWT.

    ``login()`` needs the underlying ``HttpRequest`` (it mutates
    ``request.user`` and rotates the CSRF token), so unwrap the DRF request.
    """
    django_request = getattr(request, "_request", request)
    django_login(django_request, user, backend="django.contrib.auth.backends.ModelBackend")


class RegisterView(ApiResponseMixin, APIView):
    """Create a user and farmer profile, and return the first JWT pair.

    Atomic: the user, profile and a pre-seeded ungranted profile-purpose consent
    are written together. Password rules are Django's ``validate_password``
    (minimum length 8), and the response also opens a Django session so the
    server-rendered pages are reachable. Anonymous-only, capped at 10/hour.
    """

    permission_classes = [AllowAny]
    throttle_classes = [RegisterThrottle]

    @extend_schema(
        operation_id="auth_register",
        summary="Register a new farmer",
        request=RegisterSerializer,
        responses={
            201: envelope(
                inline_serializer(
                    name="RegistrationResult",
                    fields={
                        "user": UserSerializer(),
                        "profile": FarmerProfileSerializer(),
                        "tokens": token_pair(),
                    },
                )
            ),
            400: error_envelope("Validation failed."),
        },
    )
    @transaction.atomic
    def post(self, request):
        serializer = RegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        user, profile = register_user(
            username=data["username"],
            email=data["email"],
            password=data["password"],
            phone=data.get("phone", ""),
            full_name=data.get("full_name", ""),
            state=data.get("state", ""),
            district=data.get("district", ""),
            village=data.get("village", ""),
            pincode=data.get("pincode", ""),
            land_size=data.get("land_size"),
            land_unit=data.get("land_unit", "acre"),
        )

        tokens = TokenObtainPairSerializer().validate(
            {"username": data["username"], "password": data["password"]}
        )
        _start_django_session(request, user)
        return self.respond(
            data={"user": UserSerializer(user).data, "profile": FarmerProfileSerializer(profile).data, "tokens": tokens},
            message="Registration successful.",
            status_code=status.HTTP_201_CREATED,
        )


class LoginView(ApiResponseMixin, APIView):
    """Exchange credentials for a JWT pair and start a Django session.

    The session is not a convenience: the SPA pages gate on Django session auth,
    which a bearer token alone cannot satisfy. Rate limited to 20/hour per
    anonymous client, shared with the refresh endpoint.
    """

    permission_classes = [AllowAny]
    throttle_classes = [LoginThrottle]

    @extend_schema(
        operation_id="auth_login",
        summary="Obtain JWT pair and start a Django session",
        request=TokenObtainPairSerializer,
        responses={200: token_envelope(), 400: error_envelope("Invalid credentials.")},
    )
    def post(self, request):
        serializer = TokenObtainPairSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        # The SPA is server-rendered: every page view gates on
        # ``request.user.is_authenticated``, which only Django's session auth
        # satisfies. A JWT in localStorage cannot satisfy it (a page navigation
        # does not send an Authorization header), so issuing the session here is
        # what makes the HTML pages reachable at all.
        _start_django_session(request, serializer.user)
        return self.respond(data=serializer.validated_data, message="Login successful.")


class LogoutView(ApiResponseMixin, APIView):
    """Close the Django session opened at login.

    Server-side this only invalidates the session cookie; the JWTs are stateless
    and must be discarded by the client, so the response is advisory rather than
    a true revocation.
    """

    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="auth_logout",
        summary="Close the Django session and discard tokens",
        request=None,
        responses={200: envelope(serializers.DictField(), name="logout_envelope")},
    )
    def post(self, request):
        # LoginView opens a Django session, so logout has to close it again -
        # otherwise the session cookie outlives the discarded tokens and the
        # server-rendered pages stay reachable after "logout".
        django_logout(getattr(request, "_request", request))
        return self.respond(data={}, message="Logged out. Discard the client-side tokens.")


class TokenRefreshView(ApiResponseMixin, APIView):
    """Exchange a refresh token for a new access token.

    SIMPLE_JWT sets ROTATE_REFRESH_TOKENS = True, so a rotated refresh token is
    returned when rotation happens and the client must replace its stored one.
    Keeping the standard {success, data: {access, refresh?}} envelope means the
    web client's api layer can treat login and refresh identically.
    """

    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [LoginThrottle]

    @extend_schema(
        operation_id="auth_token_refresh",
        summary="Exchange a refresh token for a new access token",
        request=TokenRefreshSerializer,
        responses={200: token_envelope(), 401: error_envelope("Session expired.")},
    )
    def post(self, request):
        refresh = request.data.get("refresh")
        if not refresh:
            return self.respond_error([{"field": "refresh", "message": "refresh token is required."}])
        try:
            data = TokenRefreshSerializer().validate({"refresh": refresh})
        except TokenError:
            return self.respond_error(
                [{"field": "refresh", "message": "Invalid or expired refresh token. Please sign in again."}],
                "Session expired.",
                status_code=status.HTTP_401_UNAUTHORIZED,
            )
        return self.respond(data=data, message="Access token refreshed.")


class ProfileView(ApiResponseMixin, APIView):
    """Read or partially update the caller's own farmer profile.

    A missing profile is created lazily on first access, which is what keeps
    superuser and ORM-created accounts from 500ing here. PATCH is partial and
    stamps ``updated_by`` with the caller.
    """

    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="auth_profile_retrieve",
        summary="Retrieve the farmer profile",
        responses={200: envelope(FarmerProfileSerializer)},
    )
    def get(self, request):
        profile = ensure_farmer_profile(request.user)
        return self.respond(data=FarmerProfileSerializer(profile).data, message="Profile retrieved.")

    @extend_schema(
        operation_id="auth_profile_partial_update",
        summary="Partially update the farmer profile",
        request=FarmerProfileSerializer,
        responses={200: envelope(FarmerProfileSerializer), 400: error_envelope("Validation failed.")},
    )
    def patch(self, request):
        profile = ensure_farmer_profile(request.user)
        serializer = FarmerProfileSerializer(profile, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save(updated_by=request.user)
        return self.respond(data=serializer.data, message="Profile updated.")


def _strict_bool(value, default=False):
    """Parse a boolean sent as bool/number/string without treating 'false' as True."""
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


class ConsentsView(ApiResponseMixin, APIView):
    """List the caller's consent records, or grant/revoke one purpose.

    ``purpose`` must be a known entry in ``ConsentRecord.PURPOSES`` or the
    request is rejected with 400. ``granted`` is parsed leniently as
    bool/number/string so a literal ``"false"`` does not register as consent;
    granting stamps the timestamp, version and remote IP.
    """

    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="auth_consents_list",
        summary="List the caller's consent records",
        responses={200: envelope_list(ConsentRecordSerializer)},
    )
    def get(self, request):
        consents = request.user.consents.all()
        return self.respond(data=ConsentRecordSerializer(consents, many=True).data, message="Consents retrieved.")

    @extend_schema(
        operation_id="auth_consents_grant",
        summary="Grant or revoke consent for one purpose",
        request=_CONSENT_REQUEST,
        responses={
            200: envelope(ConsentRecordSerializer),
            400: error_envelope("Invalid consent purpose."),
        },
    )
    def post(self, request):
        purpose = request.data.get("purpose")
        granted = _strict_bool(request.data.get("granted"), default=True)
        if purpose not in dict(ConsentRecord.PURPOSES):
            return self.respond_error([{"field": "purpose", "message": "Unknown consent purpose."}], "Invalid consent purpose.")

        if granted:
            consent = grant_consent(request.user, purpose, version=request.data.get("version", "1.0"), ip=request.META.get("REMOTE_ADDR"))
        else:
            consent = revoke_consent(request.user, purpose)
        return self.respond(data=ConsentRecordSerializer(consent).data, message="Consent updated.")


class LanguagePreferenceView(ApiResponseMixin, APIView):
    """List language preferences, or set the caller's active language.

    Only 'en' and 'hi' are accepted (400 otherwise); the choice is written both
    to ``user.preferred_language``, which is what the rest of the app reads, and
    as a primary UserLanguagePreference row.
    """

    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="auth_language_list",
        summary="List the caller's language preferences",
        responses={200: envelope_list(UserLanguagePreferenceSerializer)},
    )
    def get(self, request):
        return self.respond(data=UserLanguagePreferenceSerializer(request.user.language_preferences, many=True).data)

    @extend_schema(
        operation_id="auth_language_set",
        summary="Set the caller's active language",
        request=_LANGUAGE_REQUEST,
        responses={200: envelope(UserLanguagePreferenceSerializer), 400: error_envelope("Unsupported language.")},
    )
    def post(self, request):
        code = request.data.get("language_code", "en")
        if code not in ("en", "hi"):
            return self.respond_error([{"field": "language_code", "message": "Language must be 'en' or 'hi'."}])
        request.user.preferred_language = code
        request.user.save(update_fields=["preferred_language"])
        pref, _ = UserLanguagePreference.objects.update_or_create(
            user=request.user, language_code=code, defaults={"is_primary": True}
        )
        return self.respond(data=UserLanguagePreferenceSerializer(pref).data, message="Language preference saved.")