"""Serializers for the finance app."""
from rest_framework import serializers

from apps.finance.models import (
    AffordabilityAssessment,
    BuyRentAnalysis,
    FinancingOption,
    IncomeProfile,
    LoanCalculation,
    MachineryPurchaseScenario,
    RepairReplaceAnalysis,
)


class IncomeProfileSerializer(serializers.ModelSerializer):
    total_income = serializers.SerializerMethodField()

    class Meta:
        model = IncomeProfile
        fields = ["id", "year", "crop_income", "livestock_income", "off_farm_income", "other_income", "existing_emi_total", "total_income"]
        read_only_fields = ["id", "total_income"]

    def get_total_income(self, obj):
        return obj.total_income


class FinancingOptionSerializer(serializers.ModelSerializer):
    class Meta:
        model = FinancingOption
        fields = ["id", "name", "kind", "provider", "interest_rate_pct", "tenure_months", "is_illustrative", "notes"]


class LoanCalculationSerializer(serializers.ModelSerializer):
    class Meta:
        model = LoanCalculation
        fields = ["id", "principal_inr", "annual_interest_rate_pct", "tenure_months", "emi_inr", "interest_total_inr", "total_payable_inr"]
        read_only_fields = ["id"]


class BuyRentInputSerializer(serializers.Serializer):
    purchase_price_inr = serializers.IntegerField(min_value=1)
    usage_hours_per_year = serializers.IntegerField(min_value=1)
    rental_rate_per_hour_inr = serializers.IntegerField(min_value=1)
    subsidy_inr = serializers.IntegerField(required=False, default=0)
    loan_years = serializers.IntegerField(required=False, default=5)
    interest_rate_pct = serializers.FloatField(required=False, default=12.0)


class RepairReplaceInputSerializer(serializers.Serializer):
    estimated_repair_cost_inr = serializers.IntegerField(min_value=0)
    replacement_price_inr = serializers.IntegerField(min_value=1)
    residual_value_inr = serializers.IntegerField(required=False, default=0)
    annual_usage_hours = serializers.IntegerField(required=False, default=700)
    repair_frequency_per_year = serializers.FloatField(required=False, default=1.0)


class AffordabilityInputSerializer(serializers.Serializer):
    annual_income_inr = serializers.IntegerField(min_value=1)
    proposed_emi_inr = serializers.IntegerField(min_value=0)
    existing_emi_total_inr = serializers.IntegerField(required=False, default=0)
    safe_burden_pct = serializers.FloatField(required=False, default=25.0)


class BuyRentAnalysisSerializer(serializers.ModelSerializer):
    class Meta:
        model = BuyRentAnalysis
        fields = ["id", "farm", "equipment", "purchase_price_inr", "usage_hours_per_year", "rental_rate_per_hour_inr", "result_json", "created_at"]


class RepairReplaceAnalysisSerializer(serializers.ModelSerializer):
    class Meta:
        model = RepairReplaceAnalysis
        fields = ["id", "farm", "equipment", "estimated_repair_cost_inr", "replacement_price_inr", "residual_value_inr", "result_json", "created_at"]


class AffordabilityAssessmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = AffordabilityAssessment
        fields = ["id", "farm", "equipment", "annual_income_inr", "proposed_emi_inr", "income_burden_pct", "result_json", "created_at"]


class MachineryPurchaseScenarioSerializer(serializers.ModelSerializer):
    class Meta:
        model = MachineryPurchaseScenario
        fields = ["id", "farm", "equipment", "option", "purchase_price_inr", "estimated_subsidy_inr", "result_json", "created_at"]