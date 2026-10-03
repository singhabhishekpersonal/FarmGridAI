"""URL configuration for the crops app."""
from django.urls import path

from apps.crops.views import (
    CropCatalogView,
    FarmCropEstimateDetailView,
    FarmCropEstimateView,
    FarmCropListView,
)

urlpatterns = [
    path("crops", CropCatalogView.as_view(), name="crop-catalog"),
    path("farms/<uuid:farm_id>/crops", FarmCropListView.as_view(), name="farm-crop-list"),
    path("farms/<uuid:farm_id>/crops/estimates", FarmCropEstimateView.as_view(), name="farm-crop-estimates"),
    path("farms/<uuid:farm_id>/crops/<uuid:crop_id>/estimate", FarmCropEstimateDetailView.as_view(), name="farm-crop-estimate-detail"),
]