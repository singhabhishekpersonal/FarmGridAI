"""Energy models: pump profiles, benchmarks, solar configurations and analyses."""
from django.db import models

from apps.core.constants import DataSource
from apps.core.models import BaseModel, ConfidenceMixin
from apps.core.validators import validate_non_negative
from apps.farms.models import Farm


class PumpProfile(BaseModel):
    """The irrigation pump driving the energy decision."""

    PUMP_CHOICES = [
        ("submersible", "Submersible (electric)"),
        ("centrifugal", "Centrifugal (electric)"),
        ("diesel", "Diesel pump"),
        ("solar", "Solar pump"),
        ("other", "Other"),
    ]

    farm = models.ForeignKey(Farm, on_delete=models.CASCADE, related_name="pump_profiles")
    pump_type = models.CharField(max_length=20, choices=PUMP_CHOICES, default="submersible")
    horsepower = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True, validators=[validate_non_negative])
    power_kw = models.DecimalField(max_digits=7, decimal_places=3, null=True, blank=True, validators=[validate_non_negative])
    water_source = models.CharField(max_length=40, blank=True)
    operating_hours_per_day = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True, validators=[validate_non_negative])
    irrigation_days_per_year = models.PositiveIntegerField(null=True, blank=True)
    existing_annual_maintenance = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True, validators=[validate_non_negative])

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.get_pump_type_display()} ({self.horsepower or self.power_kw})"


class EnergyTariffBenchmark(BaseModel):
    """Electricity tariff reference per state/provider.

    Benchmark only - verify with the local DISCOM before relying on it.
    """

    state = models.CharField(max_length=60)
    provider = models.CharField(max_length=80, blank=True)
    slab_name = models.CharField(max_length=60, blank=True)
    per_kwh_inr = models.DecimalField(max_digits=8, decimal_places=3, validators=[validate_non_negative])
    effective_from = models.DateField(null=True, blank=True)
    source = models.CharField(max_length=20, choices=DataSource.choices, default=DataSource.BENCHMARK)
    is_verified = models.BooleanField(default=False)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["state", "per_kwh_inr"]

    def __str__(self):
        return f"{self.state}: Rs {self.per_kwh_inr}/kWh"


class DieselPriceBenchmark(BaseModel):
    """Diesel price reference record."""

    state = models.CharField(max_length=60, blank=True)
    district = models.CharField(max_length=60, blank=True)
    price_per_litre = models.DecimalField(max_digits=8, decimal_places=2, validators=[validate_non_negative])
    observed_on = models.DateField()
    source = models.CharField(max_length=20, choices=DataSource.choices, default=DataSource.BENCHMARK)
    is_verified = models.BooleanField(default=False)

    class Meta:
        ordering = ["-observed_on"]

    def __str__(self):
        return f"Diesel Rs {self.price_per_litre} @ {self.observed_on}"


class SolarSystemConfiguration(BaseModel):
    """Configuration for a prospective solar irrigation system."""

    farm = models.ForeignKey(Farm, on_delete=models.CASCADE, related_name="solar_configurations")
    system_kw = models.DecimalField(max_digits=6, decimal_places=2, validators=[validate_non_negative])
    pump_hp = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True, validators=[validate_non_negative])
    pump_cost_inr = models.PositiveIntegerField(null=True, blank=True)
    installation_cost_inr = models.PositiveIntegerField(null=True, blank=True)
    panel_types = models.CharField(max_length=60, blank=True)
    storage_kwh = models.DecimalField(max_digits=6, decimal_places=2, default=0, validators=[validate_non_negative])
    estimated_subsidy_inr = models.PositiveIntegerField(default=0)
    loan_amount_inr = models.PositiveIntegerField(default=0)
    loan_years = models.PositiveIntegerField(default=0)
    loan_interest_rate_pct = models.DecimalField(max_digits=5, decimal_places=2, default=10.0)
    annual_maintenance_inr = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Solar {self.system_kw} kW @ {self.farm_id}"

    @property
    def total_upfront(self):
        return (self.pump_cost_inr or 0) + (self.installation_cost_inr or 0)


class SolarCostBenchmark(BaseModel):
    """Capital cost benchmark for solar systems, Rs per kWp."""

    state = models.CharField(max_length=60, blank=True)
    min_inr_per_kw = models.PositiveIntegerField(validators=[validate_non_negative])
    max_inr_per_kw = models.PositiveIntegerField(validators=[validate_non_negative])
    source = models.CharField(max_length=20, choices=DataSource.choices, default=DataSource.BENCHMARK)
    is_verified = models.BooleanField(default=False)

    class Meta:
        ordering = ["state"]

    def __str__(self):
        return f"Solar Rs {self.min_inr_per_kw}-{self.max_inr_per_kw}/kW"


class SolarAnalysis(BaseModel, ConfidenceMixin):
    """Persisted result of the solar vs grid vs diesel comparison."""

    farm = models.ForeignKey(Farm, on_delete=models.CASCADE, related_name="solar_analyses")
    configuration = models.ForeignKey(SolarSystemConfiguration, on_delete=models.SET_NULL, null=True, blank=True)
    scenario = models.CharField(max_length=30, default="expected")
    break_even_year = models.PositiveIntegerField(null=True, blank=True)
    payback_years = models.FloatField(null=True, blank=True)
    npv_inr = models.FloatField(null=True, blank=True)
    calculations_json = models.JSONField(default=dict)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.farm_id}: break-even {self.break_even_year}"


class TimeStampModelMixin(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class SolarProjectionYear(TimeStampModelMixin):
    """Year-by-year projection row belonging to a SolarAnalysis."""

    analysis = models.ForeignKey(SolarAnalysis, on_delete=models.CASCADE, related_name="projection")
    year_index = models.PositiveSmallIntegerField()
    year_label = models.CharField(max_length=20, blank=True)
    grid_cost = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    diesel_cost = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    solar_cumulative = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    solar_maintenance = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    cumulative_savings = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    is_break_even = models.BooleanField(default=False)

    class Meta:
        ordering = ["analysis", "year_index"]
        constraints = [
            models.UniqueConstraint(fields=["analysis", "year_index"], name="uniq_solar_projection_year")
        ]

    def __str__(self):
        return f"{self.analysis_id} year {self.year_index}"