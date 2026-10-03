"""Admin configuration for the crops app."""
from django.contrib import admin

from apps.crops.models import Crop, CropCostBenchmark, CropInputEstimate, FarmCrop


@admin.register(Crop)
class CropAdmin(admin.ModelAdmin):
    list_display = ["name", "local_name", "category", "primary_season", "typical_yield_qtl_per_acre", "is_synthetic_benchmark"]
    list_filter = ["category", "primary_season", "is_synthetic_benchmark"]
    search_fields = ["name", "local_name"]


class CropCostBenchmarkInline(admin.TabularInline):
    model = CropCostBenchmark
    extra = 0
    fields = ["input_type", "unit", "state", "min_cost", "max_cost", "expected_cost", "is_verified"]


@admin.register(CropCostBenchmark)
class CropCostBenchmarkAdmin(admin.ModelAdmin):
    list_display = ["crop", "input_type", "unit", "state", "expected_cost", "is_verified", "source"]
    list_filter = ["input_type", "state", "is_verified", "source"]
    search_fields = ["crop__name"]
    readonly_fields = ["id", "created_at", "updated_at"]


@admin.register(FarmCrop)
class FarmCropAdmin(admin.ModelAdmin):
    list_display = ["farm", "crop", "season", "year", "area", "area_unit", "area_hectares"]
    list_filter = ["season", "year"]
    search_fields = ["farm__name", "crop__name"]
    readonly_fields = ["id", "area_hectares"]


@admin.register(CropInputEstimate)
class CropInputEstimateAdmin(admin.ModelAdmin):
    list_display = ["farm_crop", "input_type", "min_cost", "max_cost", "expected_cost", "confidence"]
    list_filter = ["input_type", "confidence"]
    search_fields = ["farm_crop__farm__name"]