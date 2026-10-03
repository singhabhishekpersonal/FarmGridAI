"""Accounts domain models: users, farmer profiles, consents, languages."""
import uuid

from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.core.validators import RegexValidator
from django.db import models

from apps.core.constants import (
    IRRIGATION_TYPE_MAX_LENGTH,
    IrrigationSource,
    IrrigationType,
    LandUnit,
    OwnershipStatus,
)
from apps.core.models import BaseModel, TimeStampedModel
from apps.core.units import UnitConversionService
from apps.core.validators import validate_non_negative, validate_pincode

PHONE_VALIDATOR = RegexValidator(
    regex=r"^[0-9]{10}$",
    message="Enter a valid 10-digit Indian mobile number.",
)


class User(AbstractUser):
    """Platform user. Roles are inferred from related models:

    - user.farmer_profile exists  -> farmer
    - user.is_staff                -> CMS / admin
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    phone = models.CharField(max_length=15, blank=True, validators=[PHONE_VALIDATOR])
    preferred_language = models.CharField(max_length=5, default="en", choices=[("en", "English"), ("hi", "Hindi")])

    class Meta:
        ordering = ["-date_joined"]

    def __str__(self):
        return self.email or self.username

    @property
    def is_farmer(self):
        return hasattr(self, "farmer_profile")

    def log_audit(self, actor=None):
        """Explicit audit hook used by admin/service layers."""
        logger = __import__("logging").getLogger("khetsathi.audit")
        logger.info(
            "USER_AUDIT user_id=%s actor=%s",
            self.pk,
            getattr(actor, "pk", None),
        )


class FarmerProfile(BaseModel):
    """A farmer's primary profile and personal data.

    Land information entered here duplicates the farm-level parcels for
    convenience; the farms app owns the authoritative land parcel records.
    """

    GENDER_CHOICES = [("male", "Male"), ("female", "Female"), ("other", "Other"), ("undisclosed", "Prefer not to say")]

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="farmer_profile")
    full_name = models.CharField(max_length=120)
    phone = models.CharField(max_length=15, blank=True, validators=[PHONE_VALIDATOR])
    gender = models.CharField(max_length=20, choices=GENDER_CHOICES, default="undisclosed")

    state = models.CharField(max_length=60, blank=True)
    district = models.CharField(max_length=60, blank=True)
    village = models.CharField(max_length=80, blank=True)
    pincode = models.CharField(max_length=6, blank=True, validators=[validate_pincode])

    # Land summary (canonical storage is Farm/LandParcel).
    land_size = models.DecimalField(max_digits=10, decimal_places=3, null=True, blank=True, validators=[validate_non_negative])
    land_unit = models.CharField(max_length=10, choices=LandUnit.choices, default=LandUnit.ACRE)
    normalized_land_hectares = models.DecimalField(max_digits=12, decimal_places=4, null=True, blank=True)
    land_ownership = models.CharField(max_length=10, choices=OwnershipStatus.choices, default=OwnershipStatus.OWNED)
    irrigated = models.CharField(
        max_length=IRRIGATION_TYPE_MAX_LENGTH,
        choices=IrrigationType.choices,
        default=IrrigationType.RAINFED,
    )
    irrigation_source = models.CharField(max_length=20, choices=IrrigationSource.choices, default=IrrigationSource.OTHER)

    yearly_farm_income_min = models.PositiveIntegerField(null=True, blank=True)
    yearly_farm_income_max = models.PositiveIntegerField(null=True, blank=True)
    household_income_min = models.PositiveIntegerField(null=True, blank=True)
    household_income_max = models.PositiveIntegerField(null=True, blank=True)

    consent_accepted = models.BooleanField(default=False)
    consent_accepted_at = models.DateTimeField(null=True, blank=True)
    onboard_complete = models.BooleanField(default=False)

    class Meta:
        verbose_name = "Farmer profile"
        verbose_name_plural = "Farmer profiles"
        indexes = [models.Index(fields=["state", "district"])]

    def __str__(self):
        return self.full_name or str(self.user)

    def save(self, *args, **kwargs):
        if self.land_size is not None:
            conversion = UnitConversionService().to_hectares(float(self.land_size), self.land_unit)
            if conversion.get("value_ha") is not None:
                self.normalized_land_hectares = round(conversion["value_ha"], 4)
        super().save(*args, **kwargs)

    @property
    def area_in_hectares(self):
        return float(self.normalized_land_hectares or 0)


class ConsentRecord(BaseModel):
    """Explicit, versioned consent grants for processing farmer data.

    No sensitive processing may happen for a consent purpose without a
    matching granted record.
    """

    PURPOSE_PROFILE = "profile"
    PURPOSE_EXPENSES = "expenses"
    PURPOSE_UPLOADS = "uploads"
    PURPOSE_LOCATION = "location"
    PURPOSE_SHARE_BENCHMARKS = "share_benchmarks"

    PURPOSES = [
        (PURPOSE_PROFILE, "Store and process profile data"),
        (PURPOSE_EXPENSES, "Store and analyze expenses/bills"),
        (PURPOSE_UPLOADS, "Process uploaded equipment photos"),
        (PURPOSE_LOCATION, "Use location for scheme matching"),
        (PURPOSE_SHARE_BENCHMARKS, "Optionally share anonymized benchmarks"),
    ]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="consents")
    purpose = models.CharField(max_length=30, choices=PURPOSES)
    granted = models.BooleanField(default=False)
    granted_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    consent_version = models.CharField(max_length=20, default="1.0")
    ip_at_consent = models.GenericIPAddressField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "purpose"],
                name="uniq_user_consent_purpose",
                condition=models.Q(deleted_at__isnull=True),
            )
        ]

    def __str__(self):
        return f"{self.user_id} -> {self.purpose}: {self.granted}"


class UserLanguagePreference(TimeStampedModel):
    """Explicit language preference for English/Hindi-ready architecture."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="language_preferences")
    language_code = models.CharField(max_length=5, choices=[("en", "English"), ("hi", "Hindi")])
    is_primary = models.BooleanField(default=False)

    class Meta:
        ordering = ["-is_primary"]

    def __str__(self):
        return f"{self.user_id}: {self.language_code}"