"""URL configuration for the energy app."""
from django.urls import path

from apps.energy.views import (
    DieselPriceBenchmarkView,
    EnergyAnalyzeView,
    EnergyProjectionView,
    PumpProfileView,
    SolarComparisonView,
    SolarConfigurationView,
    TariffBenchmarkView,
)

urlpatterns = [
    path("farms/<uuid:farm_id>/pump-profile", PumpProfileView.as_view(), name="pump-profile"),
    path("farms/<uuid:farm_id>/solar-configuration", SolarConfigurationView.as_view(), name="solar-configuration"),
    path("farms/<uuid:farm_id>/energy/analyze", EnergyAnalyzeView.as_view(), name="energy-analyze"),
    path("farms/<uuid:farm_id>/energy/solar-comparison", SolarComparisonView.as_view(), name="solar-comparison"),
    path("farms/<uuid:farm_id>/energy/projection", EnergyProjectionView.as_view(), name="energy-projection"),
    path("energy/tariff-benchmarks", TariffBenchmarkView.as_view(), name="tariff-benchmarks"),
    path("energy/diesel-price-benchmarks", DieselPriceBenchmarkView.as_view(), name="diesel-price-benchmarks"),
]