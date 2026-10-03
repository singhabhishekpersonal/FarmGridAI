"""Admin configuration for the expenses app."""
from django.contrib import admin

from apps.expenses.models import (
    ElectricityBill,
    ExpenseCategory,
    ExpenseDocument,
    FarmExpense,
    FarmExpenseSummary,
    FuelExpense,
    InputExpense,
    LabourExpense,
    RentalExpense,
    TransportExpense,
)


@admin.register(ExpenseCategory)
class ExpenseCategoryAdmin(admin.ModelAdmin):
    list_display = ["code", "name", "is_custom"]
    search_fields = ["code", "name"]


@admin.register(FarmExpense)
class FarmExpenseAdmin(admin.ModelAdmin):
    list_display = ["farm", "occurred_on", "amount", "category", "expense_type"]
    list_filter = ["expense_type", "category"]
    search_fields = ["farm__name", "note"]


@admin.register(ElectricityBill)
class ElectricityBillAdmin(admin.ModelAdmin):
    list_display = ["farm", "occurred_on", "units_kwh", "amount", "tariff_effective_per_kwh", "provider"]
    list_filter = ["provider"]


@admin.register(FuelExpense)
class FuelExpenseAdmin(admin.ModelAdmin):
    list_display = ["farm", "occurred_on", "fuel_type", "litre_volume", "price_per_litre", "amount"]
    list_filter = ["fuel_type"]


@admin.register(InputExpense)
class InputExpenseAdmin(admin.ModelAdmin):
    list_display = ["farm", "occurred_on", "input_type", "product_name", "amount"]
    list_filter = ["input_type"]
    search_fields = ["product_name"]


@admin.register(LabourExpense)
class LabourExpenseAdmin(admin.ModelAdmin):
    list_display = ["farm", "occurred_on", "labour_type", "person_days", "wage_per_day", "amount"]
    list_filter = ["labour_type"]


@admin.register(TransportExpense)
class TransportExpenseAdmin(admin.ModelAdmin):
    list_display = ["farm", "occurred_on", "vehicle_type", "distance_km", "amount"]


@admin.register(RentalExpense)
class RentalExpenseAdmin(admin.ModelAdmin):
    list_display = ["farm", "occurred_on", "equipment_class", "rental_hours", "amount"]


@admin.register(ExpenseDocument)
class ExpenseDocumentAdmin(admin.ModelAdmin):
    list_display = ["farm", "original_name", "file_size", "status", "created_at"]
    search_fields = ["original_name"]
    readonly_fields = ["content_hash"]


@admin.register(FarmExpenseSummary)
class FarmExpenseSummaryAdmin(admin.ModelAdmin):
    list_display = ["farm", "year", "total_expected", "confidence", "data_completeness"]
    list_filter = ["year", "confidence"]
    readonly_fields = ["by_category", "assumptions_json", "limitations_json"]