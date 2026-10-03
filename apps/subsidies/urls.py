"""URL configuration for the subsidies app."""
from django.urls import path

from apps.subsidies.views import (
    SubsidyChecklistView,
    SubsidyMatchView,
    SubsidyRecommendationsView,
    SubsidySchemeDetailView,
    SubsidySchemeListView,
)

urlpatterns = [
    path("subsidies", SubsidySchemeListView.as_view(), name="subsidy-scheme-list"),
    path("subsidies/<uuid:scheme_id>", SubsidySchemeDetailView.as_view(), name="subsidy-scheme-detail"),
    path("farms/<uuid:farm_id>/subsidies/match", SubsidyMatchView.as_view(), name="subsidy-match"),
    path("farms/<uuid:farm_id>/subsidies/recommendations", SubsidyRecommendationsView.as_view(), name="subsidy-recommendations"),
    path("farms/<uuid:farm_id>/subsidies/checklists", SubsidyChecklistView.as_view(), name="subsidy-checklists"),
]