"""Crop domain models and cost estimation."""
from django.conf import settings
from django.db import models

from apps.core.constants import DataSource
from apps.core.models import BaseModel
from apps.core.units import UnitConversionService
from apps.core.validators import validate_non_negative
from apps.farms.models import Farm


class Crop(BaseModel):
    """A crop catalog entry (e.g. wheat, rice)."""

    SEASON_CHOICES = [
        ("kharif", "Kharif"),
        ("rabi", "Rabi"),
        ("zaid", "Zaid"),
        ("annual", "Annual"),
    ]

    CATEGORY_CHOICES = [
        ("cereal", "Cereal"),
        ("pulse", "Pulse"),
        ("oilseed", "Oilseed"),
        ("commercial", "Commercial"),
        ("vegetable", "Vegetable"),
        ("fruit", "Fruit"),
        ("sugarcane", "Sugarcane"),
        ("fibre", "Fibre"),
    ]

    name = models.CharField(max_length=80, unique=True)
    local_name = models.CharField(max_length=80, blank=True)
    slug = models.SlugField(unique=True)
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES, default="cereal")
    primary_season = models.CharField(max_length=10, choices=SEASON_CHOICES, default="rabi")
    typical_days_to_harvest = models.PositiveIntegerField(null=True, blank=True)
    typical_yield_qtl_per_acre = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True, validators=[validate_non_negative])
    is_synthetic_benchmark = models.BooleanField(default=False)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class CropCostBenchmark(BaseModel):
    """Benchmark cost ranges per crop/input type.

    All benchmark seed records are explicitly labelled synthetic/benchmark and
    must be locally verified before being treated as authoritative.
    """

    INPUT_CHOICES = [
        ("seed", "Seed"),
        ("fertilizer", "Fertilizer"),
        ("pesticide", "Pesticide"),
        ("labour", "Labour"),
        ("machinery", "Machinery"),
        ("irrigation", "Irrigation"),
        ("transport", "Transport"),
        ("other", "Other"),
    ]

    UNIT_CHOICES = [("per_acre", "Per acre"), ("per_hectare", "Per hectare"), ("per_quintal", "Per quintal")]

    crop = models.ForeignKey(Crop, on_delete=models.CASCADE, related_name="cost_benchmarks")
    input_type = models.CharField(max_length=20, choices=INPUT_CHOICES)
    unit = models.CharField(max_length=12, choices=UNIT_CHOICES, default="per_acre")
    state = models.CharField(max_length=60, blank=True)
    min_cost = models.DecimalField(max_digits=12, decimal_places=2, validators=[validate_non_negative])
    max_cost = models.DecimalField(max_digits=12, decimal_places=2, validators=[validate_non_negative])
    expected_cost = models.DecimalField(max_digits=12, decimal_places=2, validators=[validate_non_negative])
    source = models.CharField(max_length=20, choices=DataSource.choices, default=DataSource.BENCHMARK)
    is_verified = models.BooleanField(default=False)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["crop", "input_type"]
        indexes = [models.Index(fields=["crop", "input_type", "state"])]

    def __str__(self):
        return f"{self.crop.name} {self.input_type} benchmark"

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)


class FarmCrop(BaseModel):
    """Which crop is grown on which farm portion in which season."""

    SEASON_CHOICES = Crop.SEASON_CHOICES

    farm = models.ForeignKey(Farm, on_delete=models.CASCADE, related_name="crops")
    crop = models.ForeignKey(Crop, on_delete=models.PROTECT, related_name="farm_crops")
    season = models.CharField(max_length=10, choices=SEASON_CHOICES)
    year = models.PositiveIntegerField()
    area = models.DecimalField(max_digits=12, decimal_places=3, validators=[validate_non_negative])
    area_unit = models.CharField(max_length=10, choices=[("acre", "Acre"), ("hectare", "Hectare"), ("bigha", "Bigha")], default="acre")
    area_hectares = models.DecimalField(max_digits=12, decimal_places=4, null=True, blank=True)
    expected_yield_qtl_per_acre = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True, validators=[validate_non_negative])
    is_planned = models.BooleanField(default=True)

    class Meta:
        ordering = ["year", "season", "crop__name"]
        constraints = [
            models.UniqueConstraint(
                fields=["farm", "crop", "season", "year"],
                condition=models.Q(deleted_at__isnull=True),
                name="uniq_farm_crop_season_year",
            )
        ]

    def __str__(self):
        return f"{self.farm_id} {self.crop.name} {self.season} {self.year}"

    def save(self, *args, **kwargs):
        if self.area is not None:
            result = UnitConversionService().to_hectares(float(self.area), self.area_unit)
            if result.get("value_ha") is not None:
                self.area_hectares = round(result["value_ha"], 4)
        super().save(*args, **kwargs)

    @property
    def area_acres(self):
        if self.area_hectares is None:
            return float(self.area)
        return round(float(self.area_hectares) * 2.471053814671653, 4)


class CropInputEstimate(BaseModel):
    """Persisted estimate produced by the crop cost estimation service."""

    farm_crop = models.ForeignKey(FarmCrop, on_delete=models.CASCADE, related_name="input_estimates")
    input_type = models.CharField(max_length=20, choices=CropCostBenchmark.INPUT_CHOICES)
    min_cost = models.DecimalField(max_digits=14, decimal_places=2)
    max_cost = models.DecimalField(max_digits=14, decimal_places=2)
    expected_cost = models.DecimalField(max_digits=14, decimal_places=2)
    per_acre = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    confidence = models.CharField(max_length=10, default="low")
    assumptions_json = models.JSONField(default=list, blank=True)

    class Meta:
        ordering = ["farm_crop", "input_type"]

    def __str__(self):
        return f"{self.farm_crop} {self.input_type}: Rs {self.min_cost}-{self.max_cost}"