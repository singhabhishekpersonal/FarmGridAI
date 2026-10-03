"""Expense domain models."""
from django.db import models

from apps.core.constants import DataSource
from apps.core.models import BaseModel
from apps.core.validators import validate_non_negative
from apps.farms.models import Farm


class ExpenseCategory(BaseModel):
    """Expense classification used across all expense types."""

    code = models.CharField(max_length=40, unique=True)
    name = models.CharField(max_length=80)
    is_custom = models.BooleanField(default=False)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class ExpenseBase(BaseModel):
    """Abstract base for all expense records."""

    farm = models.ForeignKey(Farm, on_delete=models.CASCADE, related_name="%(class)ss")
    occurred_on = models.DateField()
    amount = models.DecimalField(max_digits=14, decimal_places=2, validators=[validate_non_negative])
    category = models.ForeignKey(ExpenseCategory, on_delete=models.SET_NULL, null=True, blank=True)
    note = models.TextField(blank=True)

    class Meta:
        abstract = True
        ordering = ["-occurred_on"]

    @property
    def year(self):
        return self.occurred_on.year


class FarmExpense(ExpenseBase):
    """Generic expense row used for manual totals not covered by typed rows."""

    expense_type = models.CharField(max_length=30, default="other")

    def __str__(self):
        return f"Rs {self.amount} on {self.occurred_on}"


class ElectricityBill(ExpenseBase):
    """Grid electricity usage and amount for a billing period."""

    provider = models.CharField(max_length=80, blank=True)
    units_kwh = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True, validators=[validate_non_negative])
    bill_month = models.DateField(null=True, blank=True)
    tariff_effective_per_kwh = models.DecimalField(max_digits=8, decimal_places=3, null=True, blank=True, validators=[validate_non_negative])

    def __str__(self):
        return f"Electricity {self.occurred_on}: {self.units_kwh} kWh Rs {self.amount}"

    def save(self, *args, **kwargs):
        if self.units_kwh and self.amount and not self.tariff_effective_per_kwh:
            self.tariff_effective_per_kwh = round(float(self.amount) / float(self.units_kwh), 3)
        super().save(*args, **kwargs)


class FuelExpense(ExpenseBase):
    """Diesel/petrol purchases."""

    FUEL_CHOICES = [
        ("diesel", "Diesel"),
        ("petrol", "Petrol"),
        ("cng", "CNG"),
        ("lpg", "LPG"),
        ("electric", "Electric"),
    ]
    litre_volume = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, validators=[validate_non_negative])
    price_per_litre = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True, validators=[validate_non_negative])
    fuel_type = models.CharField(max_length=10, choices=FUEL_CHOICES, default="diesel")
    purpose = models.CharField(max_length=60, blank=True)

    def __str__(self):
        return f"{self.fuel_type} {self.litre_volume}L Rs {self.amount}"


class InputExpense(ExpenseBase):
    """Fertilizer / seed / pesticide purchases."""

    INPUT_CHOICES = [
        ("general", "General"),
        ("seed", "Seed"),
        ("fertilizer", "Fertilizer"),
        ("pesticide", "Pesticide"),
        ("manure", "Manure / organic"),
        ("other", "Other"),
    ]
    input_type = models.CharField(max_length=20, choices=INPUT_CHOICES, default="fertilizer")
    product_name = models.CharField(max_length=120, blank=True)
    quantity = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, validators=[validate_non_negative])
    quantity_unit = models.CharField(max_length=20, blank=True)

    def __str__(self):
        return f"{self.input_type}: {self.product_name} Rs {self.amount}"


class LabourExpense(ExpenseBase):
    """Labour payment record."""

    LABOUR_CHOICES = [("daily", "Daily"), ("seasonal", "Seasonal"), ("contract", "Contract"), ("family", "Family")]
    labour_type = models.CharField(max_length=12, choices=LABOUR_CHOICES, default="daily")
    person_days = models.DecimalField(max_digits=8, decimal_places=1, null=True, blank=True, validators=[validate_non_negative])
    wage_per_day = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, validators=[validate_non_negative])

    def __str__(self):
        return f"Labour Rs {self.amount} ({self.labour_type})"


class TransportExpense(ExpenseBase):
    VEHICLE_CHOICES = [
        ("tractor", "Tractor"),
        ("truck", "Truck"),
        ("trolley", "Trolley"),
        ("tempo", "Tempo"),
        ("auto", "Auto / jeep"),
        ("van", "Van"),
        ("other", "Other"),
    ]
    vehicle_type = models.CharField(max_length=12, choices=VEHICLE_CHOICES, default="tractor")
    distance_km = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True, validators=[validate_non_negative])

    def __str__(self):
        return f"Transport Rs {self.amount}"


class RentalExpense(ExpenseBase):
    """Machinery/equipment rental cost."""

    equipment_class = models.CharField(max_length=30, blank=True)
    rental_hours = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True, validators=[validate_non_negative])
    rental_days = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True, validators=[validate_non_negative])

    def __str__(self):
        return f"Rental Rs {self.amount}"


class ExpenseDocument(BaseModel):
    """Uploaded bill/receipt with secure storage and metadata."""

    farm = models.ForeignKey(Farm, on_delete=models.CASCADE, related_name="expense_documents")
    document = models.FileField(upload_to="bills/%Y/%m/")
    original_name = models.CharField(max_length=255)
    content_hash = models.CharField(max_length=64)
    file_size = models.PositiveIntegerField(default=0)
    category = models.ForeignKey(ExpenseCategory, on_delete=models.SET_NULL, null=True, blank=True)
    status = models.CharField(max_length=12, default="uploaded")

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.original_name


class FarmExpenseSummary(BaseModel):
    """Aggregated annual expense summary with per-category totals."""

    farm = models.ForeignKey(Farm, on_delete=models.CASCADE, related_name="expense_summaries")
    year = models.PositiveIntegerField()
    total_min = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    total_max = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    total_expected = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    by_category = models.JSONField(default=dict)
    data_completeness = models.FloatField(default=0.0)
    confidence = models.CharField(max_length=10, default="medium")
    assumptions_json = models.JSONField(default=list, blank=True)
    limitations_json = models.JSONField(default=list, blank=True)

    class Meta:
        ordering = ["-year"]
        constraints = [
            models.UniqueConstraint(
                fields=["farm", "year"],
                condition=models.Q(deleted_at__isnull=True),
                name="uniq_farm_expense_summary_year",
            )
        ]

    def __str__(self):
        return f"{self.farm_id} {self.year}: Rs {self.total_expected}"

    @property
    def per_hectare(self):
        ha = self.farm.total_hectares
        if not ha:
            return None
        return round(float(self.total_expected) / ha, 2)