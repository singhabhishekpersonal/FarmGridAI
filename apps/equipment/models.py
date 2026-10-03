"""Equipment domain models: catalog, farmer equipment, images, predictions,
condition, usage, maintenance and OCR records."""
from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models

from apps.core.constants import EQUIPMENT_CLASS_CHOICES, DataSource
from apps.core.models import BaseModel
from apps.core.validators import validate_non_negative
from apps.farms.models import Farm

CONDITION_BANDS = [("good", "Good"), ("moderate", "Moderate"), ("poor", "Poor"), ("unknown", "Unknown")]


class EquipmentCategory(BaseModel):
    """Broad equipment class with benchmark characteristics."""

    code = models.CharField(max_length=30, choices=EQUIPMENT_CLASS_CHOICES, unique=True)
    name = models.CharField(max_length=80)
    description = models.TextField(blank=True)
    typical_hp_min = models.DecimalField(max_digits=6, decimal_places=1, null=True, blank=True, validators=[validate_non_negative])
    typical_hp_max = models.DecimalField(max_digits=6, decimal_places=1, null=True, blank=True, validators=[validate_non_negative])
    fuel_consumption_l_per_hr = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True, validators=[validate_non_negative])
    price_range_min = models.PositiveIntegerField(null=True, blank=True)
    price_range_max = models.PositiveIntegerField(null=True, blank=True)
    typical_lifespan_years = models.PositiveIntegerField(null=True, blank=True)
    is_synthetic_benchmark = models.BooleanField(default=False)

    class Meta:
        ordering = ["code"]

    def __str__(self):
        return self.name


class EquipmentCatalog(BaseModel):
    """A specific brand/model entry with benchmark price and specifications."""

    category = models.ForeignKey(EquipmentCategory, on_delete=models.CASCADE, related_name="catalog_items")
    brand = models.CharField(max_length=80)
    model = models.CharField(max_length=120)
    slug = models.SlugField(max_length=200, blank=True)
    hp = models.DecimalField(max_digits=6, decimal_places=1, null=True, blank=True, validators=[validate_non_negative])
    price_min = models.PositiveIntegerField(null=True, blank=True)
    price_max = models.PositiveIntegerField(null=True, blank=True)
    price_expected = models.PositiveIntegerField(null=True, blank=True)
    fuel_type = models.CharField(max_length=20, blank=True)
    drive_type = models.CharField(max_length=30, blank=True)
    image_url = models.URLField(blank=True)
    source_url = models.URLField(blank=True)
    source = models.CharField(max_length=20, choices=DataSource.choices, default=DataSource.SCRAPED)
    is_verified = models.BooleanField(default=False)
    is_synthetic_benchmark = models.BooleanField(default=False)

    class Meta:
        ordering = ["brand", "model"]
        indexes = [models.Index(fields=["brand", "model"])]
        constraints = [
            models.UniqueConstraint(
                fields=["category", "brand", "model"],
                condition=models.Q(deleted_at__isnull=True),
                name="uniq_catalog_category_brand_model",
            )
        ]

    def __str__(self):
        return f"{self.brand} {self.model}"

    def save(self, *args, **kwargs):
        if not self.slug:
            import re
            import uuid

            base = re.sub(r"[^a-z0-9]+", "-", f"{self.brand} {self.model}".lower()).strip("-")
            self.slug = f"{base[:150]}-{uuid.uuid4().hex[:6]}"
        super().save(*args, **kwargs)

    @property
    def price_midpoint(self):
        if self.price_expected:
            return self.price_expected
        if self.price_min and self.price_max:
            return (self.price_min + self.price_max) // 2
        return None


class FarmerEquipment(BaseModel):
    """Equipment a farmer actually owns/uses."""

    FUEL_CHOICES = [("diesel", "Diesel"), ("petrol", "Petrol"), ("electric", "Electric"), ("solar", "Solar"), ("manual", "Manual"), ("unknown", "Unknown")]

    farm = models.ForeignKey(Farm, on_delete=models.CASCADE, related_name="equipment")
    catalog = models.ForeignKey(EquipmentCatalog, on_delete=models.SET_NULL, null=True, blank=True, related_name="farmer_instances")
    category = models.ForeignKey(EquipmentCategory, on_delete=models.PROTECT, related_name="farmer_equipment")
    custom_brand = models.CharField(max_length=80, blank=True)
    custom_model = models.CharField(max_length=120, blank=True)
    horsepower = models.DecimalField(max_digits=6, decimal_places=1, null=True, blank=True, validators=[validate_non_negative])
    purchase_year = models.PositiveIntegerField(null=True, blank=True)
    purchase_price = models.PositiveIntegerField(null=True, blank=True, validators=[validate_non_negative])
    condition = models.CharField(max_length=10, choices=CONDITION_BANDS, default="unknown")
    fuel_type = models.CharField(max_length=10, choices=FUEL_CHOICES, default="diesel")
    usage_hours_per_year = models.PositiveIntegerField(null=True, blank=True, validators=[validate_non_negative])
    area_served_acres = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True, validators=[validate_non_negative])
    is_owned = models.BooleanField(default=True)
    is_operational = models.BooleanField(default=True)
    confirmation_required = models.BooleanField(default=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        name = self.custom_model or (self.catalog.model if self.catalog else self.category.code)
        return f"{self.category.code}: {name}"

    @property
    def display_name(self):
        return self.custom_model or (f"{self.catalog.brand} {self.catalog.model}" if self.catalog else self.category.name)

    @property
    def age_years(self):
        from datetime import date

        if not self.purchase_year:
            return None
        return max(0, date.today().year - self.purchase_year)


class EquipmentImage(BaseModel):
    """Uploaded equipment photo with validation metadata."""

    PROCESSING_CHOICES = [("pending", "Pending"), ("processed", "Processed"), ("failed", "Failed"), ("rejected", "Rejected")]

    equipment = models.ForeignKey(FarmerEquipment, on_delete=models.CASCADE, related_name="images")
    image = models.ImageField(upload_to="equipment/%Y/%m/")
    thumb = models.ImageField(upload_to="equipment/thumbs/", blank=True)
    original_name = models.CharField(max_length=255)
    content_hash = models.CharField(max_length=64, db_index=True)
    file_size = models.PositiveIntegerField(default=0)
    width = models.PositiveIntegerField(null=True, blank=True)
    height = models.PositiveIntegerField(null=True, blank=True)
    mime_type = models.CharField(max_length=50, blank=True)
    status = models.CharField(max_length=12, choices=PROCESSING_CHOICES, default="pending")
    is_primary = models.BooleanField(default=False)
    rejection_reason = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ["-is_primary", "-created_at"]

    def __str__(self):
        return self.original_name


class EquipmentImagePrediction(BaseModel):
    """Stored output of the computer-vision classifier for one image."""

    image = models.ForeignKey(EquipmentImage, on_delete=models.CASCADE, related_name="predictions")
    predicted_class = models.CharField(max_length=30, choices=EQUIPMENT_CLASS_CHOICES, default="unknown")
    predicted_brand = models.CharField(max_length=60, blank=True, default="")
    confidence = models.FloatField(default=0.0)
    class_probabilities = models.JSONField(default=dict)
    top_predictions = models.JSONField(default=list)
    confidence_label = models.CharField(max_length=10, default="low")
    used_ml = models.BooleanField(default=False)
    artifact_available = models.BooleanField(default=False)
    unknown_threshold = models.FloatField(null=True, blank=True)
    model_name = models.CharField(max_length=120)
    model_version = models.CharField(max_length=40)
    input_hash = models.CharField(max_length=64)
    source = models.CharField(max_length=20, choices=DataSource.choices, default=DataSource.MODEL)
    needs_user_confirmation = models.BooleanField(default=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.predicted_class} ({self.confidence:.2f})"


class EquipmentConditionAssessment(BaseModel):
    """Broad visible-condition risk assessment - never exact mechanical health.

    Outputs are estimates with explicit confidence and confirmation flags.
    """

    equipment = models.ForeignKey(FarmerEquipment, on_delete=models.CASCADE, related_name="condition_assessments")
    visible_condition_score = models.PositiveSmallIntegerField(null=True, blank=True, validators=[MinValueValidator(0)])  # 0..100
    condition_band = models.CharField(max_length=12, choices=CONDITION_BANDS, default="unknown")
    issue_tags = models.JSONField(default=list)  # e.g. ["rust", "tyre_wear", ...]
    method = models.CharField(max_length=60, default="farmer-declared rule-based")
    confidence = models.CharField(max_length=10, default="low")
    needs_user_confirmation = models.BooleanField(default=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.equipment_id}: {self.condition_band}"


class EquipmentUsageRecord(BaseModel):
    """Yearly usage record for an equipment item."""

    equipment = models.ForeignKey(FarmerEquipment, on_delete=models.CASCADE, related_name="usage_records")
    year = models.PositiveIntegerField()
    hours_used = models.DecimalField(max_digits=8, decimal_places=1, null=True, blank=True, validators=[validate_non_negative])
    fuel_used_litres = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, validators=[validate_non_negative])
    area_covered_acres = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True, validators=[validate_non_negative])
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-year"]
        constraints = [
            models.UniqueConstraint(
                fields=["equipment", "year"],
                condition=models.Q(deleted_at__isnull=True),
                name="uniq_equipment_year",
            )
        ]

    def __str__(self):
        return f"{self.equipment_id} {self.year}: {self.hours_used} hrs"


class EquipmentMaintenanceRecord(BaseModel):
    """Service/repair events and historical repair costs."""

    MAINTENANCE_CHOICES = [("routine_service", "Routine service"), ("repair", "Repair"), ("overhaul", "Overhaul"), ("emergency", "Emergency")]

    equipment = models.ForeignKey(FarmerEquipment, on_delete=models.CASCADE, related_name="maintenance_records")
    occurred_on = models.DateField()
    kind = models.CharField(max_length=20, choices=MAINTENANCE_CHOICES, default="routine_service")
    cost = models.DecimalField(max_digits=12, decimal_places=2, default=0, validators=[validate_non_negative])
    description = models.TextField(blank=True)

    class Meta:
        ordering = ["-occurred_on"]

    def __str__(self):
        return f"{self.equipment_id} {self.kind} {self.cost} on {self.occurred_on}"


class EquipmentOCRResult(BaseModel):
    """OCR extraction output for an equipment image.

    OCR is heuristic evidence, never guaranteed truth.
    """

    image = models.ForeignKey(EquipmentImage, on_delete=models.CASCADE, related_name="ocr_results")
    provider = models.CharField(max_length=30, default="none")
    raw_text = models.TextField(blank=True)
    brand_candidates = models.JSONField(default=list)
    model_candidates = models.JSONField(default=list)
    confidence = models.FloatField(default=0.0)
    needs_user_confirmation = models.BooleanField(default=True)
    error = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"OCR {self.image_id} via {self.provider}"