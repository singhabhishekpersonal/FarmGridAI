"""URL configuration for the farms app (farm-scoped routes)."""
from django.urls import path

from apps.farms.views import FarmDetailView, FarmLandParcelView, FarmListCreateView, FarmSummaryView

urlpatterns = [
    path("", FarmListCreateView.as_view(), name="farm-list"),
    path("<uuid:farm_id>", FarmDetailView.as_view(), name="farm-detail"),
    path("<uuid:farm_id>/land-parcels", FarmLandParcelView.as_view(), name="farm-land-parcels"),
    path("<uuid:farm_id>/summary", FarmSummaryView.as_view(), name="farm-summary"),
]