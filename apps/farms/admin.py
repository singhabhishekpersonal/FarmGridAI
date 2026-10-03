"""Admin configuration for the farms app."""
from django.contrib import admin

from apps.farms.models import (
    BighaConversionRule,
    Farm,
    FarmCropSeason,
    FarmLocation,
    IrrigationProfile,
    LandParcel,
    LandUnitConversion,
)


class LandParcelInline(admin.TabularInline):
    model = LandParcel
    extra = 0
    readonly_fields = ["id", "area_hectares"]


@admin.register(Farm)
class FarmAdmin(admin.ModelAdmin):
    list_display = ["name", "user", "is_default", "active_season_year", "created_at"]
    list_filter = ["is_default"]
    search_fields = ["name", "user__email", "user__username"]
    inlines = [LandParcelInline]
    readonly_fields = ["id", "created_at", "updated_at", "created_by", "updated_by"]


@admin.register(FarmLocation)
class FarmLocationAdmin(admin.ModelAdmin):
    list_display = ["farm", "state", "district", "village", "pincode"]
    list_filter = ["state"]
    search_fields = ["farm__name", "village", "district"]


@admin.register(LandParcel)
class LandParcelAdmin(admin.ModelAdmin):
    list_display = ["name", "farm", "area", "unit", "area_hectares", "area_requires_confirmation", "is_primary"]
    list_filter = ["unit", "irrigated", "ownership"]
    search_fields = ["name", "farm__name"]
    readonly_fields = ["id", "area_hectares", "conversion_note"]


@admin.register(LandUnitConversion)
class LandUnitConversionAdmin(admin.ModelAdmin):
    list_display = ["original_value", "original_unit", "result_hectares", "method", "requires_confirmation"]
    list_filter = ["original_unit", "requires_confirmation"]


@admin.register(BighaConversionRule)
class BighaConversionRuleAdmin(admin.ModelAdmin):
    list_display = ["state", "district", "sq_meters_per_bigha", "is_verified", "last_verified_at", "source"]
    list_filter = ["state", "is_verified"]
    search_fields = ["state", "district", "label"]


@admin.register(IrrigationProfile)
class IrrigationProfileAdmin(admin.ModelAdmin):
    list_display = ["farm", "source", "typical_hours_per_day", "monthly_electricity_kwh"]
    list_filter = ["source"]


@admin.register(FarmCropSeason)
class FarmCropSeasonAdmin(admin.ModelAdmin):
    list_display = ["farm", "season", "year", "is_active"]
    list_filter = ["season", "year"]