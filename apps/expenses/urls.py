"""URL configuration for the expenses app."""
from django.urls import path

from apps.expenses.views import (
    ElectricityBillView,
    ExpenseAnalysisView,
    ExpenseCategoryListView,
    ExpenseDocumentView,
    ExpenseListView,
    ExpenseSummaryView,
    FuelExpenseView,
    InputExpenseView,
    LabourExpenseView,
    RentalExpenseView,
    TransportExpenseView,
)

urlpatterns = [
    path("farms/<uuid:farm_id>/expenses", ExpenseListView.as_view(), name="expense-list"),
    path("farms/<uuid:farm_id>/expenses/categories", ExpenseCategoryListView.as_view(), name="expense-categories"),
    path("farms/<uuid:farm_id>/expenses/electricity", ElectricityBillView.as_view(), name="electricity-bill"),
    path("farms/<uuid:farm_id>/expenses/fuel", FuelExpenseView.as_view(), name="fuel-expense"),
    path("farms/<uuid:farm_id>/expenses/inputs", InputExpenseView.as_view(), name="input-expense"),
    path("farms/<uuid:farm_id>/expenses/labour", LabourExpenseView.as_view(), name="labour-expense"),
    path("farms/<uuid:farm_id>/expenses/transport", TransportExpenseView.as_view(), name="transport-expense"),
    path("farms/<uuid:farm_id>/expenses/rental", RentalExpenseView.as_view(), name="rental-expense"),
    path("farms/<uuid:farm_id>/expenses/analysis", ExpenseAnalysisView.as_view(), name="expense-analysis"),
    path("farms/<uuid:farm_id>/expenses/summary", ExpenseSummaryView.as_view(), name="expense-summary"),
    path("farms/<uuid:farm_id>/expenses/documents", ExpenseDocumentView.as_view(), name="expense-document"),
]