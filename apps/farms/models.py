"""Farm domain models: farm, location, land parcels, irrigation and seasons."""
import uuid

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models

from apps.core.constants import (
    IRRIGATION_TYPE_MAX_LENGTH,
    IrrigationSource,
    IrrigationType,
    LandUnit,
    OwnershipStatus,
)
from apps.core.models import BaseModel
from apps.core.units import UnitConversionService
from apps.core.validators import validate_non_negative, validate_pincode


class Farm(BaseModel):
    """A farmer's farm. A user can own multiple farms."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="farms")
    name = models.CharField(max_length=120)
    description = models.TextField(blank=True)
    is_default = models.BooleanField(default=False)
    active_season_year = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        ordering = ["-is_default", "-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["user"],
                condition=models.Q(deleted_at__isnull=True) & models.Q(is_default=True),
                name="uniq_default_farm_per_user",
            )
        ]

    def __str__(self):
        return f"{self.name} ({self.user_id})"

    @property
    def total_hectares(self):
        total = sum(p.area_hectares for p in self.land_parcels.filter(deleted_at__isnull=True) if p.area_hectares)
        if total:
            return total
        parcels = self.land_parcels.all()
        return sum(p.area_hectares for p in parcels if p.area_hectares)

    @property
    def location(self):
        return self.locations.order_by("-created_at").first()


class FarmLocation(BaseModel):
    """Location details for a farm, including address and optional geo-coords."""

    farm = models.ForeignKey(Farm, on_delete=models.CASCADE, related_name="locations")
    state = models.CharField(max_length=60)
    district = models.CharField(max_length=60, blank=True)
    tehsil = models.CharField(max_length=60, blank=True)
    village = models.CharField(max_length=80, blank=True)
    pincode = models.CharField(max_length=6, blank=True, validators=[validate_pincode])
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)

    class Meta:
        indexes = [models.Index(fields=["state", "district"])]

    def __str__(self):
        pieces = [p for p in [self.village, self.district, self.state] if p]
        return ", ".join(pieces) or str(self.farm_id)


class LandParcel(BaseModel):
    """A cultivable plot. Stores the original entered value/unit AND the
    normalized canonical area (hectares)."""

    farm = models.ForeignKey(Farm, on_delete=models.CASCADE, related_name="land_parcels")
    name = models.CharField(max_length=80, default="")
    area = models.DecimalField(
        max_digits=12, decimal_places=3, validators=[MinValueValidator(0)], default=0
    )
    unit = models.CharField(max_length=10, choices=LandUnit.choices, default=LandUnit.ACRE)
    area_hectares = models.DecimalField(max_digits=12, decimal_places=4, null=True, blank=True)
    area_requires_confirmation = models.BooleanField(default=False)
    conversion_note = models.CharField(max_length=200, blank=True)

    ownership = models.CharField(max_length=10, choices=OwnershipStatus.choices, default=OwnershipStatus.OWNED)
    irrigated = models.CharField(
        max_length=IRRIGATION_TYPE_MAX_LENGTH,
        choices=IrrigationType.choices,
        default=IrrigationType.RAINFED,
    )
    irrigation_source = models.CharField(max_length=20, choices=IrrigationSource.choices, default=IrrigationSource.OTHER)
    soil_type = models.CharField(max_length=40, blank=True)
    is_primary = models.BooleanField(default=False)

    class Meta:
        ordering = ["-is_primary", "name"]

    def __str__(self):
        return f"{self.name or self.id} ({self.area} {self.unit})"

    def save(self, *args, **kwargs):
        if self.area is not None:
            farm_state = self.farm.location.state if self.farm.location else ""
            farm_district = self.farm.location.district if self.farm.location else ""
            rule = BighaConversionRule.objects.filter(state=farm_state).order_by("-last_verified_at").first()
            result = UnitConversionService().to_hectares(float(self.area or 0), self.unit, rule=rule, state=farm_state, district=farm_district)
            if result.get("value_ha") is not None:
                self.area_hectares = round(result["value_ha"], 4)
                self.area_requires_confirmation = False
                self.conversion_note = result.get("method", "")
            else:
                self.area_hectares = None
                self.area_requires_confirmation = True
                self.conversion_note = result.get("method", "")
        super().save(*args, **kwargs)

    @property
    def area_acre(self):
        if self.area_hectares is None:
            return None
        return round(float(self.area_hectares) * 2.471053814671653, 4)

    @property
    def area_value_display(self):
        return float(self.area) if self.area is not None else None


class LandUnitConversion(BaseModel):
    """Audit record of every land-unit conversion performed by services."""

    farm = models.ForeignKey(Farm, on_delete=models.CASCADE, null=True, blank=True, related_name="unit_conversions")
    parcel = models.ForeignKey(LandParcel, on_delete=models.CASCADE, null=True, blank=True, related_name="conversions")
    original_value = models.DecimalField(max_digits=12, decimal_places=4)
    original_unit = models.CharField(max_length=10, choices=LandUnit.choices)
    result_hectares = models.DecimalField(max_digits=12, decimal_places=4, null=True, blank=True)
    method = models.CharField(max_length=200)
    requires_confirmation = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.original_value} {self.original_unit} -> {self.result_hectares} ha"


class BighaConversionRule(BaseModel):
    """Region-specific bigha conversion factor.

    Bigha has NO universal value; different states/districts define it
    differently. Rules are seeded from benchmark collections and should be
    verified before trust.
    """

    state = models.CharField(max_length=60)
    district = models.CharField(max_length=60, blank=True)
    label = models.CharField(max_length=120)
    sq_meters_per_bigha = models.DecimalField(max_digits=12, decimal_places=3, validators=[validate_non_negative])
    source = models.CharField(max_length=120, default="benchmark")
    is_verified = models.BooleanField(default=False)
    last_verified_at = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["state", "district"]
        constraints = [
            models.UniqueConstraint(
                fields=["state", "district"],
                condition=models.Q(deleted_at__isnull=True),
                name="uniq_bigha_rule_state_district",
            )
        ]

    def __str__(self):
        location = self.district or "All districts"
        return f"{self.state}/{location}: {self.sq_meters_per_bigha} sqm/bigha"


class IrrigationProfile(BaseModel):
    """How the farm is irrigated plus observed water/energy characteristics."""

    farm = models.ForeignKey(Farm, on_delete=models.CASCADE, related_name="irrigation_profiles")
    source = models.CharField(max_length=20, choices=IrrigationSource.choices, default=IrrigationSource.OTHER)
    availability = models.CharField(max_length=40, blank=True)
    typical_hours_per_day = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True, validators=[validate_non_negative])
    monthly_electricity_kwh = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, validators=[validate_non_negative])
    notes = models.TextField(blank=True)

    def __str__(self):
        return f"{self.farm_id}: {self.source}"


class FarmCropSeason(BaseModel):
    """Seasons in which the farm grows crops (Kharif/Rabi/Zaid)."""

    SEASON_CHOICES = [
        ("kharif", "Kharif"),
        ("rabi", "Rabi"),
        ("zaid", "Zaid"),
        ("annual", "Annual"),
    ]

    farm = models.ForeignKey(Farm, on_delete=models.CASCADE, related_name="crop_seasons")
    season = models.CharField(max_length=10, choices=SEASON_CHOICES)
    year = models.PositiveIntegerField()
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["-year", "season"]
        constraints = [
            models.UniqueConstraint(
                fields=["farm", "season", "year"],
                condition=models.Q(deleted_at__isnull=True),
                name="uniq_farm_season_year",
            )
        ]

    def __str__(self):
        return f"{self.farm_id} {self.season} {self.year}"


class FarmService:
    """Service operations for farms."""

    @staticmethod
    def create_farm(user, name, description="", state="", district="", village="", pincode="", is_default=None, **parcel_data):
        farms = user.farms.all()
        set_default = (is_default is True) or (not farms.exists())
        if set_default:
            Farm.objects.filter(user=user, is_default=True).update(is_default=False)
        farm = Farm.objects.create(user=user, name=name, description=description, is_default=set_default)
        FarmLocation.objects.create(farm=farm, state=state or "Unknown", district=district, village=village, pincode=pincode)
        if parcel_data.get("area") is not None:
            FarmService.add_parcel(
                farm,
                name=parcel_data.get("name", "Main parcel"),
                area=parcel_data["area"],
                unit=parcel_data.get("unit", "acre"),
                ownership=parcel_data.get("ownership", "owned"),
                irrigated=parcel_data.get("irrigated", "rainfed"),
                irrigation_source=parcel_data.get("irrigation_source", "other"),
            )
        return farm

    @staticmethod
    def add_parcel(farm, name="", area=0, unit="acre", ownership="owned", irrigated="rainfed", irrigation_source="other", is_primary=False):
        parcel = LandParcel(farm=farm, name=name, area=area, unit=unit, ownership=ownership, irrigated=irrigated, irrigation_source=irrigation_source, is_primary=is_primary)
        parcel.save()
        return parcel

    @staticmethod
    def summary(farm):
        parcels = list(farm.land_parcels.all())
        total_ha = sum(float(p.area_hectares or 0) for p in parcels)
        return {
            "farm_id": str(farm.id),
            "name": farm.name,
            "parcel_count": len(parcels),
            "total_hectares": round(total_ha, 4),
            "total_acres": round(total_ha * 2.471053814671653, 4),
            "parcels_requiring_confirmation": [str(p.id) for p in parcels if p.area_requires_confirmation],
            "location": {
                "state": farm.location.state if farm.location else "",
                "district": farm.location.district if farm.location else "",
                "village": farm.location.village if farm.location else "",
                "pincode": farm.location.pincode if farm.location else "",
            },
        }