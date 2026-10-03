"""Finance domain models: income, financing, scenarios and analyses."""
from django.db import models

from apps.core.constants import ConfidenceLevel
from apps.core.models import BaseModel
from apps.core.validators import validate_non_negative
from apps.equipment.models import FarmerEquipment
from apps.farms.models import Farm


class IncomeProfile(BaseModel):
    """Farm income profile used for affordability checks."""

    farm = models.ForeignKey(Farm, on_delete=models.CASCADE, related_name="income_profiles")
    year = models.PositiveIntegerField()
    crop_income = models.PositiveIntegerField(null=True, blank=True, validators=[validate_non_negative])
    livestock_income = models.PositiveIntegerField(null=True, blank=True, validators=[validate_non_negative])
    off_farm_income = models.PositiveIntegerField(null=True, blank=True, validators=[validate_non_negative])
    other_income = models.PositiveIntegerField(null=True, blank=True, validators=[validate_non_negative])
    existing_emi_total = models.PositiveIntegerField(default=0, validators=[validate_non_negative])

    class Meta:
        ordering = ["-year"]

    def __str__(self):
        return f"{self.farm_id} income {self.year}"

    @property
    def total_income(self):
        return sum(x or 0 for x in [self.crop_income, self.livestock_income, self.off_farm_income, self.other_income])

    @property
    def disposable_capacity(self):
        return max(0, self.total_income - self.existing_emi_total)


class FinancingOption(BaseModel):
    """A financing product (loan/lease); illustrative benchmark records."""

    FIN_CHOICES = [("loan", "Loan"), ("lease", "Lease"), ("subsidy_scheme", "Subsidy scheme"), ("custom_hiring", "Custom hiring")]

    name = models.CharField(max_length=120)
    kind = models.CharField(max_length=20, choices=FIN_CHOICES, default="loan")
    provider = models.CharField(max_length=80, blank=True)
    interest_rate_pct = models.DecimalField(max_digits=5, decimal_places=2, default=10.0, validators=[validate_non_negative])
    tenure_months = models.PositiveIntegerField(default=60)
    is_illustrative = models.BooleanField(default=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class LoanCalculation(BaseModel):
    """A loan/EMI calculation snapshot."""

    principal_inr = models.PositiveIntegerField(validators=[validate_non_negative])
    annual_interest_rate_pct = models.DecimalField(max_digits=6, decimal_places=3, validators=[validate_non_negative])
    tenure_months = models.PositiveIntegerField()
    emi_inr = models.DecimalField(max_digits=12, decimal_places=2)
    interest_total_inr = models.DecimalField(max_digits=14, decimal_places=2)
    total_payable_inr = models.DecimalField(max_digits=14, decimal_places=2)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"EMI Rs {self.emi_inr} over {self.tenure_months} months"


class MachineryPurchaseScenario(BaseModel):
    """A stored buy/replace scenario with its computed outcome."""

    OPTION_CHOICES = [
        ("buy_new", "Buy new"),
        ("buy_used", "Buy used"),
        ("repair_existing", "Repair existing"),
        ("rent_when_needed", "Rent when needed"),
        ("shared_ownership", "Shared ownership"),
        ("custom_hiring_center", "Custom hiring center"),
        ("gather_more_information", "Gather more information"),
    ]

    farm = models.ForeignKey(Farm, on_delete=models.CASCADE, related_name="machinery_scenarios")
    equipment = models.ForeignKey(FarmerEquipment, on_delete=models.SET_NULL, null=True, blank=True, related_name="scenarios")
    option = models.CharField(max_length=30, choices=OPTION_CHOICES)
    purchase_price_inr = models.PositiveIntegerField(null=True, blank=True, validators=[validate_non_negative])
    estimated_subsidy_inr = models.PositiveIntegerField(default=0, validators=[validate_non_negative])
    result_json = models.JSONField(default=dict)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.farm_id}: {self.option}"


class BuyRentAnalysis(BaseModel):
    """Buy vs rent comparison output."""

    farm = models.ForeignKey(Farm, on_delete=models.CASCADE, related_name="buy_rent_analyses")
    equipment = models.ForeignKey(FarmerEquipment, on_delete=models.SET_NULL, null=True, blank=True, related_name="buy_rent_analyses")
    purchase_price_inr = models.PositiveIntegerField(validators=[validate_non_negative])
    usage_hours_per_year = models.PositiveIntegerField(validators=[validate_non_negative])
    rental_rate_per_hour_inr = models.PositiveIntegerField(validators=[validate_non_negative])
    result_json = models.JSONField(default=dict)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Buy vs rent ({self.farm_id})"


class RepairReplaceAnalysis(BaseModel):
    """Repair vs replace decision output."""

    farm = models.ForeignKey(Farm, on_delete=models.CASCADE, related_name="repair_replace_analyses")
    equipment = models.ForeignKey(FarmerEquipment, on_delete=models.SET_NULL, null=True, blank=True, related_name="repair_replace_analyses")
    estimated_repair_cost_inr = models.PositiveIntegerField(validators=[validate_non_negative])
    replacement_price_inr = models.PositiveIntegerField(validators=[validate_non_negative])
    residual_value_inr = models.PositiveIntegerField(default=0, validators=[validate_non_negative])
    result_json = models.JSONField(default=dict)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Repair vs replace ({self.farm_id})"


class AffordabilityAssessment(BaseModel):
    """Machinery affordability check based on farm income and usage."""

    farm = models.ForeignKey(Farm, on_delete=models.CASCADE, related_name="affordability_assessments")
    equipment = models.ForeignKey(FarmerEquipment, on_delete=models.SET_NULL, null=True, blank=True, related_name="affordability_assessments")
    annual_income_inr = models.PositiveIntegerField(validators=[validate_non_negative])
    proposed_emi_inr = models.PositiveIntegerField(validators=[validate_non_negative])
    income_burden_pct = models.FloatField(default=0.0)
    result_json = models.JSONField(default=dict)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Affordability ({self.farm_id}) {self.income_burden_pct:.0f}%"