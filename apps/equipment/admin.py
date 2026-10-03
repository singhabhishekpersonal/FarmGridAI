"""Admin configuration for the equipment app."""
from django.contrib import admin

from apps.equipment.models import (
    EquipmentCatalog,
    EquipmentCategory,
    EquipmentConditionAssessment,
    EquipmentImage,
    EquipmentImagePrediction,
    EquipmentMaintenanceRecord,
    EquipmentOCRResult,
    EquipmentUsageRecord,
    FarmerEquipment,
)


@admin.register(EquipmentCategory)
class EquipmentCategoryAdmin(admin.ModelAdmin):
    list_display = ["code", "name", "typical_hp_min", "typical_hp_max", "price_range_min", "price_range_max", "is_synthetic_benchmark"]
    search_fields = ["code", "name"]


@admin.register(EquipmentCatalog)
class EquipmentCatalogAdmin(admin.ModelAdmin):
    list_display = ["brand", "model", "category", "hp", "price_min", "price_max", "is_verified", "source"]
    list_filter = ["category", "brand", "source", "is_verified"]
    search_fields = ["brand", "model"]
    readonly_fields = ["id", "created_at", "updated_at"]


@admin.register(FarmerEquipment)
class FarmerEquipmentAdmin(admin.ModelAdmin):
    list_display = ["display_name", "farm", "category", "horsepower", "purchase_year", "condition", "is_operational"]
    list_filter = ["category", "fuel_type", "condition", "is_owned"]
    search_fields = ["custom_brand", "custom_model", "farm__name", "catalog__model"]
    readonly_fields = ["id", "created_at", "updated_at"]


class EquipmentImagePredictionInline(admin.TabularInline):
    model = EquipmentImagePrediction
    extra = 0
    readonly_fields = ["predicted_class", "confidence", "class_probabilities", "model_name", "model_version", "input_hash", "source", "needs_user_confirmation"]


@admin.register(EquipmentImage)
class EquipmentImageAdmin(admin.ModelAdmin):
    list_display = ["equipment", "original_name", "status", "is_primary", "file_size", "created_at"]
    list_filter = ["status", "is_primary"]
    search_fields = ["original_name", "equipment__custom_model"]
    inlines = [EquipmentImagePredictionInline]
    readonly_fields = ["id", "content_hash", "width", "height", "mime_type", "file_size", "created_at", "updated_at"]


@admin.register(EquipmentImagePrediction)
class EquipmentImagePredictionAdmin(admin.ModelAdmin):
    list_display = ["image", "predicted_class", "confidence", "model_name", "model_version", "needs_user_confirmation", "created_at"]
    list_filter = ["predicted_class", "model_name", "needs_user_confirmation"]
    readonly_fields = ["class_probabilities", "input_hash", "created_at", "updated_at"]


@admin.register(EquipmentConditionAssessment)
class EquipmentConditionAssessmentAdmin(admin.ModelAdmin):
    list_display = ["equipment", "condition_band", "visible_condition_score", "confidence", "needs_user_confirmation"]
    list_filter = ["condition_band", "confidence"]
    readonly_fields = ["issue_tags", "created_at", "updated_at"]


@admin.register(EquipmentUsageRecord)
class EquipmentUsageRecordAdmin(admin.ModelAdmin):
    list_display = ["equipment", "year", "hours_used", "fuel_used_litres", "area_covered_acres"]
    list_filter = ["year"]


@admin.register(EquipmentMaintenanceRecord)
class EquipmentMaintenanceRecordAdmin(admin.ModelAdmin):
    list_display = ["equipment", "occurred_on", "kind", "cost"]
    list_filter = ["kind"]
    search_fields = ["equipment__custom_model", "description"]


@admin.register(EquipmentOCRResult)
class EquipmentOCRResultAdmin(admin.ModelAdmin):
    list_display = ["image", "provider", "confidence", "needs_user_confirmation"]
    list_filter = ["provider"]
    readonly_fields = ["raw_text", "brand_candidates", "model_candidates", "created_at", "updated_at"]