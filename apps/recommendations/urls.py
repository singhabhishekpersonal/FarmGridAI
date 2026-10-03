"""URL configuration for the recommendations app."""
from django.urls import path

from apps.recommendations.views import (
    CostSavingOpportunitiesView,
    RecommendationExplainView,
    RecommendationFeedbackView,
    RecommendationRunView,
    RecommendationsGenerateView,
    RecommendationsListView,
)

urlpatterns = [
    path("farms/<uuid:farm_id>/recommendations", RecommendationsListView.as_view(), name="recommendation-list"),
    path("farms/<uuid:farm_id>/recommendations/run", RecommendationsGenerateView.as_view(), name="recommendation-run"),
    path("farms/<uuid:farm_id>/recommendations/<uuid:recommendation_id>/explain", RecommendationExplainView.as_view(), name="recommendation-explain"),
    path("farms/<uuid:farm_id>/recommendations/<uuid:recommendation_id>/feedback", RecommendationFeedbackView.as_view(), name="recommendation-feedback"),
    path("farms/<uuid:farm_id>/opportunities", CostSavingOpportunitiesView.as_view(), name="cost-saving-opportunities"),
    path("farms/<uuid:farm_id>/recommendation-runs", RecommendationRunView.as_view(), name="recommendation-runs"),
]