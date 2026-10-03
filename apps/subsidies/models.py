"""Subsidy scheme database and eligibility rule models.

Scheme data is preliminary/illustrative unless marked verified. Official
verification is always required before relying on any scheme.
"""
from django.db import models

from apps.core.models import BaseModel
from apps.farms.models import Farm


class SubsidyScheme(BaseModel):
    """A government subsidy / financial support scheme record."""

    DESIGNATION_CHOICES = [
        ("central", "Central"),
        ("state", "State"),
        ("central_state", "Central+State"),
    ]
    CATEGORY_CHOICES = [
        ("solar_pump", "Solar pump support"),
        ("farm_mechanization", "Farm mechanization"),
        ("custom_hiring", "Custom hiring center"),
        ("irrigation", "Irrigation support"),
        ("micro_irrigation", "Micro-irrigation"),
        ("crop_insurance", "Crop insurance"),
        ("credit_finance", "Credit / finance"),
        ("others", "Other"),
    ]

    name = models.CharField(max_length=150)
    slug = models.SlugField(max_length=170, unique=True)
    category = models.CharField(max_length=25, choices=CATEGORY_CHOICES, default="farm_mechanization")
    administrative_level = models.CharField(max_length=15, choices=DESIGNATION_CHOICES, default="central")
    state = models.CharField(max_length=60, blank=True)
    district = models.CharField(max_length=60, blank=True)
    is_active = models.BooleanField(default=True)
    effective_from = models.DateField(null=True, blank=True)
    effective_to = models.DateField(null=True, blank=True)
    benefit_type = models.CharField(max_length=80, blank=True)
    benefit_min_inr = models.PositiveIntegerField(null=True, blank=True)
    benefit_max_inr = models.PositiveIntegerField(null=True, blank=True)
    official_url = models.URLField(blank=True)
    application_steps = models.JSONField(default=list)
    last_verified_at = models.DateField(null=True, blank=True)
    scheme_version = models.CharField(max_length=20, default="1.0")
    is_illustrative = models.BooleanField(default=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-is_active", "name"]
        indexes = [models.Index(fields=["category", "state", "is_active"])]

    def __str__(self):
        return self.name


class SubsidySchemeVersion(BaseModel):
    """Versioned change history for a scheme record."""

    scheme = models.ForeignKey(SubsidyScheme, on_delete=models.CASCADE, related_name="versions")
    version = models.CharField(max_length=20)
    changes_json = models.JSONField(default=dict)
    verified_at = models.DateField(null=True, blank=True)
    supersedes_on = models.DateField(null=True, blank=True)

    class Meta:
        ordering = ["scheme", "-verified_at"]

    def __str__(self):
        return f"{self.scheme.name} v{self.version}"


class SubsidyEligibilityRule(BaseModel):
    """Declarative eligibility rule. Evaluated with a safe rule engine (no eval)."""

    OPERATOR_CHOICES = [
        ("eq", "Equals"),
        ("neq", "Not equals"),
        ("gt", "Greater than"),
        ("gte", "Greater than or equal"),
        ("lt", "Less than"),
        ("lte", "Less than or equal"),
        ("contains", "Contains"),
        ("in", "In list"),
        ("always", "Always"),
    ]
    FIELD_CHOICES = [
        ("state", "Farmer state"),
        ("district", "Farmer district"),
        ("land_hectares", "Total land (hectares)"),
        ("land_unit", "Land unit"),
        ("irrigated", "Irrigation status"),
        ("irrigation_source", "Irrigation source"),
        ("equipment_category", "Equipment category interested"),
        ("farming_category", "Farming category"),
        ("income_farm", "Farm income"),
        ("gender", "Gender"),
        ("yearly_farm_income_min", "Minimum farm income"),
        ("user_manual_match", "Manual/other match"),
    ]

    scheme = models.ForeignKey(SubsidyScheme, on_delete=models.CASCADE, related_name="rules")
    field = models.CharField(max_length=40, choices=FIELD_CHOICES)
    operator = models.CharField(max_length=12, choices=OPERATOR_CHOICES)
    value = models.JSONField(default=dict)
    reason = models.CharField(max_length=200, default="")
    sequence = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["scheme", "sequence"]

    def __str__(self):
        return f"{self.scheme.name}: {self.field} {self.operator} {self.value}"


class SchemeDocumentRequirement(BaseModel):
    """A document needed to apply for a scheme."""

    scheme = models.ForeignKey(SubsidyScheme, on_delete=models.CASCADE, related_name="documents")
    document_name = models.CharField(max_length=120)
    required = models.BooleanField(default=True)
    notes = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ["scheme", "document_name"]

    def __str__(self):
        return f"{self.scheme.name}: {self.document_name}"


class FarmerSchemeMatch(BaseModel):
    """Result of matching a farm/farmer profile against a scheme."""

    farm = models.ForeignKey(Farm, on_delete=models.CASCADE, related_name="scheme_matches")
    scheme = models.ForeignKey(SubsidyScheme, on_delete=models.CASCADE, related_name="farmer_matches")
    matched = models.BooleanField(default=False)
    reasons_json = models.JSONField(default=list)  # [{matched, reason, rule}]
    confidence = models.CharField(max_length=10, default="low")
    needs_official_verification = models.BooleanField(default=True)
    evaluated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-evaluated_at"]
        constraints = [
            models.UniqueConstraint(fields=["farm", "scheme"], name="uniq_farm_scheme_match")
        ]

    def __str__(self):
        return f"{self.farm_id} vs {self.scheme.name}: {self.matched}"


class SchemeApplicationChecklist(BaseModel):
    """Farmer-specific checklist for applying to a matched scheme."""

    match = models.ForeignKey(FarmerSchemeMatch, on_delete=models.CASCADE, related_name="checklists")
    items_json = models.JSONField(default=list)  # [{document, required, gathered}]
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Checklist for {self.match_id}"


class SubsidySourceReference(BaseModel):
    """Official source URL associated with a scheme."""

    scheme = models.ForeignKey(SubsidyScheme, on_delete=models.CASCADE, related_name="sources")
    title = models.CharField(max_length=150)
    url = models.URLField()
    last_accessed = models.DateField(null=True, blank=True)

    class Meta:
        ordering = ["scheme", "title"]

    def __str__(self):
        return self.title