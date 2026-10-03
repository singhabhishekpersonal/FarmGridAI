"""URL configuration for the equipment app."""
from django.urls import path

from apps.equipment.views import (
    EquipmentCatalogListView,
    EquipmentCategoryListView,
    EquipmentImageAnalyzeView,
    EquipmentImageUploadView,
    EquipmentOperatingCostView,
    FarmerEquipmentDetailView,
    FarmerEquipmentListView,
)

urlpatterns = [
    path("equipment/categories", EquipmentCategoryListView.as_view(), name="equipment-categories"),
    path("equipment/catalog", EquipmentCatalogListView.as_view(), name="equipment-catalog"),
    path("farms/<uuid:farm_id>/equipment", FarmerEquipmentListView.as_view(), name="farmer-equipment-list"),
    path("farms/<uuid:farm_id>/equipment/<uuid:equipment_id>", FarmerEquipmentDetailView.as_view(), name="farmer-equipment-detail"),
    path("farms/<uuid:farm_id>/equipment/<uuid:equipment_id>/images", EquipmentImageUploadView.as_view(), name="equipment-image-upload"),
    path("farms/<uuid:farm_id>/equipment/<uuid:equipment_id>/images/<uuid:image_id>/analyze", EquipmentImageAnalyzeView.as_view(), name="equipment-image-analyze"),
    path("farms/<uuid:farm_id>/equipment/<uuid:equipment_id>/operating-cost", EquipmentOperatingCostView.as_view(), name="equipment-operating-cost"),
]