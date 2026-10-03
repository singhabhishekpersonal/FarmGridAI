"""Account services: registration, profile normalization, consent handling."""
import logging

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DJangoValidationError
from django.utils import timezone

from apps.accounts.models import ConsentRecord, FarmerProfile, User
from apps.core.units import UnitConversionService

logger = logging.getLogger("FarmGrid")


class RegistrationError(Exception):
    """Raised when registration input is invalid."""


def register_user(username, email, password, phone="", full_name="", **profile_kwargs):
    """Create a user plus a farmer profile in one transaction-safe call.

    Returns ``(user, profile)``. Validation errors are raised as Django
    ValidationError so DRF serializers can render them properly.
    """
    if User.objects.filter(email__iexact=email).exists():
        raise DJangoValidationError({"email": "A user with this email already exists."})
    if User.objects.filter(username=username).exists():
        raise DJangoValidationError({"username": "A user with this username already exists."})

    validate_password(password)

    user = User(username=username, email=email, phone=phone)
    user.set_password(password)

    land_unit = profile_kwargs.get("land_unit", "acre")
    land_size = profile_kwargs.get("land_size")

    profile = FarmerProfile(
        user=user,
        full_name=full_name or username,
        phone=phone,
        state=profile_kwargs.get("state", ""),
        district=profile_kwargs.get("district", ""),
        village=profile_kwargs.get("village", ""),
        pincode=profile_kwargs.get("pincode", ""),
        land_size=land_size,
        land_unit=land_unit,
        land_ownership=profile_kwargs.get("land_ownership", "owned"),
        irrigated=profile_kwargs.get("irrigated", "rainfed"),
        irrigation_source=profile_kwargs.get("irrigation_source", "other"),
        yearly_farm_income_min=profile_kwargs.get("yearly_farm_income_min"),
        yearly_farm_income_max=profile_kwargs.get("yearly_farm_income_max"),
    )

    if land_size is not None:
        result = UnitConversionService().to_hectares(float(land_size), land_unit)
        profile.normalized_land_hectares = result.get("value_ha")

    user.save()
    profile.save()

    ConsentRecord.objects.get_or_create(user=user, purpose=ConsentRecord.PURPOSE_PROFILE, defaults={"granted": False})
    return user, profile


def ensure_farmer_profile(user):
    """Return the user's farmer profile, creating a blank one when absent.

    ``register_user`` always builds a profile, but superusers, staff accounts
    and any account created directly through the ORM or ``createsuperuser``
    have none. Touching ``user.farmer_profile`` for those raises
    ``RelatedObjectDoesNotExist``, which used to turn GET/PATCH
    ``/api/v1/auth/profile/`` into a 500 - and that endpoint runs on every
    authenticated page load. The row is created with the same fallback name
    rule as registration so behaviour stays consistent.
    """
    profile, _ = FarmerProfile.objects.get_or_create(
        user=user,
        defaults={"full_name": user.get_full_name() or user.username, "phone": user.phone or ""},
    )
    return profile


def grant_consent(user, purpose, version="1.0", ip=None):
    """Grant or update a consent record for a purpose."""
    consent, _ = ConsentRecord.objects.get_or_create(user=user, purpose=purpose)
    consent.granted = True
    consent.granted_at = timezone.now()
    consent.revoked_at = None
    consent.consent_version = version
    consent.ip_at_consent = ip
    consent.save()
    return consent


def revoke_consent(user, purpose):
    consent = ConsentRecord.objects.filter(user=user, purpose=purpose).first()
    if consent:
        consent.granted = False
        consent.revoked_at = timezone.now()
        consent.save(update_fields=["granted", "revoked_at", "updated_at"])
    return consent


def has_consent(user, purpose) -> bool:
    consent = ConsentRecord.objects.filter(user=user, purpose=purpose, granted=True).first()
    return consent is not None


class ProfileCompleteness:
    """Score 0..1 describing how much data is available for recommendations."""

    FIELD_WEIGHTS = {
        "full_name": 0.05,
        "state": 0.10,
        "district": 0.10,
        "pincode": 0.05,
        "land_size": 0.15,
        "land_ownership": 0.05,
        "irrigated": 0.05,
        "yearly_farm_income_min": 0.10,
    }

    @staticmethod
    def score(profile: FarmerProfile) -> dict:
        filled = 0.0
        missing = []
        for field, weight in ProfileCompleteness.FIELD_WEIGHTS.items():
            value = getattr(profile, field, None)
            if value:
                filled += weight
            else:
                missing.append(field)

        from apps.crops.models import FarmCrop

        if FarmCrop.objects.filter(farm__user=profile.user).exists():
            filled += 0.10
        if profile.user.farms.exists():
            filled += 0.10
        return {
            "score": round(min(1.0, filled), 2),
            "missing_fields": missing,
        }