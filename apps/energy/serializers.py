"""Serializers for the energy app."""
from rest_framework import serializers

from apps.energy.models import (
    DieselPriceBenchmark,
    EnergyTariffBenchmark,
    PumpProfile,
    SolarAnalysis,
    SolarCostBenchmark,
    SolarProjectionYear,
    SolarSystemConfiguration,
)


class PumpProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = PumpProfile
        fields = ["id", "pump_type", "horsepower", "power_kw", "water_source", "operating_hours_per_day", "irrigation_days_per_year", "existing_annual_maintenance"]
        read_only_fields = ["id"]


class SolarSystemConfigurationSerializer(serializers.ModelSerializer):
    total_upfront = serializers.SerializerMethodField()

    class Meta:
        model = SolarSystemConfiguration
        fields = [
            "id", "system_kw", "pump_hp", "pump_cost_inr", "installation_cost_inr", "total_upfront",
            "panel_types", "storage_kwh", "estimated_subsidy_inr", "loan_amount_inr", "loan_years",
            "loan_interest_rate_pct", "annual_maintenance_inr",
        ]
        read_only_fields = ["id", "total_upfront"]

    def get_total_upfront(self, obj):
        return obj.total_upfront


class EnergyTariffBenchmarkSerializer(serializers.ModelSerializer):
    class Meta:
        model = EnergyTariffBenchmark
        fields = ["id", "state", "provider", "slab_name", "per_kwh_inr", "effective_from", "is_verified", "notes"]
        read_only_fields = ["id"]


class DieselPriceBenchmarkSerializer(serializers.ModelSerializer):
    class Meta:
        model = DieselPriceBenchmark
        fields = ["id", "state", "district", "price_per_litre", "observed_on", "is_verified"]
        read_only_fields = ["id"]


class SolarProjectionYearSerializer(serializers.ModelSerializer):
    class Meta:
        model = SolarProjectionYear
        fields = ["year_index", "year_label", "grid_cost", "diesel_cost", "solar_cumulative", "solar_maintenance", "cumulative_savings", "is_break_even"]


class SolarAnalysisSerializer(serializers.ModelSerializer):
    projection = SolarProjectionYearSerializer(many=True, read_only=True)

    class Meta:
        model = SolarAnalysis
        fields = ["id", "scenario", "break_even_year", "payback_years", "npv_inr", "calculations_json", "projection", "confidence", "assumptions_json", "limitations_json", "created_at"]
        read_only_fields = ["id"]


class SolarCostBenchmarkSerializer(serializers.ModelSerializer):
    class Meta:
        model = SolarCostBenchmark
        fields = ["id", "state", "min_inr_per_kw", "max_inr_per_kw", "is_verified"]