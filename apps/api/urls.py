"""Central API v1 router: everything is namespaced under ``/api/v1/``."""
from django.urls import include, path

from apps.farms.views import BighaRuleListView, LandUnitConvertView

from .views import (
    CapabilitiesView,
    DataSourceStatusView,
    ModelStatusView,
    health_check,
    readiness_check,
)

urlpatterns = [
    path("auth/", include("apps.accounts.urls")),
    path("farms/", include("apps.farms.urls")),
    path("land-units/convert", LandUnitConvertView.as_view(), name="land-unit-convert"),
    path("bigha-rules", BighaRuleListView.as_view(), name="bigha-rules"),
    path("", include("apps.crops.urls")),
    path("", include("apps.equipment.urls")),
    path("", include("apps.expenses.urls")),
    path("", include("apps.energy.urls")),
    path("", include("apps.finance.urls")),
    path("", include("apps.subsidies.urls")),
    path("", include("apps.recommendations.urls")),
    path("data-ingestion/", include("apps.data_ingestion.urls")),
    path("chat/", include("apps.chatbot.urls")),
    path("health", health_check, name="health"),
    path("readiness", readiness_check, name="readiness"),
    path("system/capabilities", CapabilitiesView.as_view(), name="system-capabilities"),
    path("system/model-status", ModelStatusView.as_view(), name="system-model-status"),
    path("system/data-source-status", DataSourceStatusView.as_view(), name="system-data-source-status"),
]