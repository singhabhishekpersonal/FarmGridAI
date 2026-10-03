"""Admin configuration for the energy app."""
from django.contrib import admin

from apps.energy.models import (
    DieselPriceBenchmark,
    EnergyTariffBenchmark,
    PumpProfile,
    SolarAnalysis,
    SolarCostBenchmark,
    SolarProjectionYear,
    SolarSystemConfiguration,
)


@admin.register(PumpProfile)
class PumpProfileAdmin(admin.ModelAdmin):
    list_display = ["farm", "pump_type", "horsepower", "power_kw", "operating_hours_per_day", "irrigation_days_per_year"]
    list_filter = ["pump_type"]


@admin.register(EnergyTariffBenchmark)
class EnergyTariffBenchmarkAdmin(admin.ModelAdmin):
    list_display = ["state", "provider", "per_kwh_inr", "is_verified", "effective_from"]
    list_filter = ["state", "is_verified"]


@admin.register(DieselPriceBenchmark)
class DieselPriceBenchmarkAdmin(admin.ModelAdmin):
    list_display = ["state", "district", "price_per_litre", "observed_on", "is_verified"]
    list_filter = ["state", "is_verified"]


@admin.register(SolarSystemConfiguration)
class SolarSystemConfigurationAdmin(admin.ModelAdmin):
    list_display = ["farm", "system_kw", "pump_hp", "pump_cost_inr", "estimated_subsidy_inr", "created_at"]
    list_filter = ["farm"]


@admin.register(SolarCostBenchmark)
class SolarCostBenchmarkAdmin(admin.ModelAdmin):
    list_display = ["state", "min_inr_per_kw", "max_inr_per_kw", "is_verified"]


class SolarProjectionYearInline(admin.TabularInline):
    model = SolarProjectionYear
    extra = 0
    readonly_fields = ["year_index", "year_label", "grid_cost", "diesel_cost", "solar_cumulative", "cumulative_savings", "is_break_even"]


@admin.register(SolarAnalysis)
class SolarAnalysisAdmin(admin.ModelAdmin):
    list_display = ["farm", "break_even_year", "payback_years", "npv_inr", "scenario", "confidence", "created_at"]
    inlines = [SolarProjectionYearInline]
    readonly_fields = ["calculations_json", "assumptions_json", "limitations_json"]