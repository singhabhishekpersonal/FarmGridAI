"""URL configuration for the finance app."""
from django.urls import path

from apps.finance.views import (
    AffordabilityView,
    BuyVsRentView,
    IncomeProfileView,
    MachineryDecisionView,
    RepairVsReplaceView,
    ScenariosView,
)

urlpatterns = [
    path("farms/<uuid:farm_id>/income-profile", IncomeProfileView.as_view(), name="income-profile"),
    path("farms/<uuid:farm_id>/finance/buy-vs-rent", BuyVsRentView.as_view(), name="buy-vs-rent"),
    path("farms/<uuid:farm_id>/finance/repair-vs-replace", RepairVsReplaceView.as_view(), name="repair-vs-replace"),
    path("farms/<uuid:farm_id>/finance/affordability", AffordabilityView.as_view(), name="affordability"),
    path("farms/<uuid:farm_id>/finance/machinery-decision", MachineryDecisionView.as_view(), name="machinery-decision"),
    path("farms/<uuid:farm_id>/finance/scenarios", ScenariosView.as_view(), name="finance-scenarios"),
]