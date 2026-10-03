"""Admin configuration for the finance app."""
from django.contrib import admin

from apps.finance.models import (
    AffordabilityAssessment,
    BuyRentAnalysis,
    FinancingOption,
    IncomeProfile,
    LoanCalculation,
    MachineryPurchaseScenario,
    RepairReplaceAnalysis,
)


@admin.register(IncomeProfile)
class IncomeProfileAdmin(admin.ModelAdmin):
    list_display = ["farm", "year", "crop_income", "off_farm_income", "existing_emi_total", "created_at"]
    list_filter = ["year"]


@admin.register(FinancingOption)
class FinancingOptionAdmin(admin.ModelAdmin):
    list_display = ["name", "kind", "provider", "interest_rate_pct", "tenure_months", "is_illustrative"]


@admin.register(LoanCalculation)
class LoanCalculationAdmin(admin.ModelAdmin):
    list_display = ["principal_inr", "annual_interest_rate_pct", "tenure_months", "emi_inr", "interest_total_inr"]


@admin.register(MachineryPurchaseScenario)
class MachineryPurchaseScenarioAdmin(admin.ModelAdmin):
    list_display = ["farm", "equipment", "option", "purchase_price_inr", "estimated_subsidy_inr", "created_at"]
    list_filter = ["option"]
    readonly_fields = ["result_json"]


@admin.register(BuyRentAnalysis)
class BuyRentAnalysisAdmin(admin.ModelAdmin):
    list_display = ["farm", "equipment", "purchase_price_inr", "usage_hours_per_year", "rental_rate_per_hour_inr", "created_at"]
    readonly_fields = ["result_json"]


@admin.register(RepairReplaceAnalysis)
class RepairReplaceAnalysisAdmin(admin.ModelAdmin):
    list_display = ["farm", "equipment", "estimated_repair_cost_inr", "replacement_price_inr", "residual_value_inr"]
    readonly_fields = ["result_json"]


@admin.register(AffordabilityAssessment)
class AffordabilityAssessmentAdmin(admin.ModelAdmin):
    list_display = ["farm", "equipment", "annual_income_inr", "proposed_emi_inr", "income_burden_pct", "created_at"]
    readonly_fields = ["result_json"]