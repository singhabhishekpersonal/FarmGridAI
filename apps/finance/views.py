"""API views for the finance app."""
from rest_framework import status
from rest_framework.permissions import IsAuthenticated

from apps.api.mixins import ApiResponseMixin, FarmAccessMixin
from apps.finance.models import (
    AffordabilityAssessment,
    BuyRentAnalysis,
    IncomeProfile,
    MachineryPurchaseScenario,
    RepairReplaceAnalysis,
)
from apps.finance.serializers import (
    AffordabilityAssessmentSerializer,
    AffordabilityInputSerializer,
    BuyRentAnalysisSerializer,
    BuyRentInputSerializer,
    IncomeProfileSerializer,
    MachineryPurchaseScenarioSerializer,
    RepairReplaceAnalysisSerializer,
    RepairReplaceInputSerializer,
)
from apps.finance.services import (
    calculate_buy_vs_rent,
    calculate_machine_affordability,
    calculate_repair_vs_replace,
    generate_machinery_recommendation,
)


class IncomeProfileView(ApiResponseMixin, FarmAccessMixin):
    """Reads or records the farm's income profile used for affordability checks.

    GET returns only the most recent year's profile (null data when none saved);
    POST always inserts a new row, so repeated posts build a per-year history."""

    permission_classes = [IsAuthenticated]

    def get(self, request, farm_id):
        farm = self.get_farm()
        # Most recent year's profile, matching the model's default ordering.
        profile = farm.income_profiles.order_by("-year", "-created_at").first()
        if profile is None:
            return self.respond(data=None, message="No income profile saved yet.")
        return self.respond(data=IncomeProfileSerializer(profile).data, message="Income profile retrieved.")

    def post(self, request, farm_id):
        farm = self.get_farm()
        serializer = IncomeProfileSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save(farm=farm, created_by=request.user)
        return self.respond(data=serializer.data, message="Income profile saved.", status_code=status.HTTP_201_CREATED)


class BuyVsRentView(ApiResponseMixin, FarmAccessMixin):
    """Compares annual ownership cost against rental cost for a machine.

    Write-only POST. The result, including the loan EMI worked out from the
    supplied subsidy, tenure and interest rate, is persisted as a
    BuyRentAnalysis row and returned with its new analysis_id."""

    permission_classes = [IsAuthenticated]

    def post(self, request, farm_id):
        farm = self.get_farm()
        serializer = BuyRentInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        result = calculate_buy_vs_rent(
            purchase_price=data["purchase_price_inr"],
            annual_hours=data["usage_hours_per_year"],
            rental_rate_per_hour=data["rental_rate_per_hour_inr"],
            subsidy=data.get("subsidy_inr", 0),
            loan_years=data.get("loan_years", 5),
            interest_rate_pct=data.get("interest_rate_pct", 12.0),
        )
        analysis = BuyRentAnalysis.objects.create(
            farm=farm,
            purchase_price_inr=data["purchase_price_inr"],
            usage_hours_per_year=data["usage_hours_per_year"],
            rental_rate_per_hour_inr=data["rental_rate_per_hour_inr"],
            result_json=result,
            created_by=request.user,
        )
        return self.respond(
            data={"analysis_id": str(analysis.id), **result},
            message="Buy vs rent analysis computed.",
        )


class RepairVsReplaceView(ApiResponseMixin, FarmAccessMixin):
    """Decides whether repairing an existing machine beats replacing it.

    Write-only POST. Remaining life is inferred from usage hours and repair
    frequency; the outcome is stored as a RepairReplaceAnalysis row and
    returned with its analysis_id."""

    permission_classes = [IsAuthenticated]

    def post(self, request, farm_id):
        farm = self.get_farm()
        serializer = RepairReplaceInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        result = calculate_repair_vs_replace(
            repair_cost=data["estimated_repair_cost_inr"],
            replacement_price=data["replacement_price_inr"],
            residual_value=data.get("residual_value_inr", 0),
            annual_usage_hours=data.get("annual_usage_hours", 700),
            repair_frequency_per_year=data.get("repair_frequency_per_year", 1.0),
        )
        analysis = RepairReplaceAnalysis.objects.create(
            farm=farm,
            estimated_repair_cost_inr=data["estimated_repair_cost_inr"],
            replacement_price_inr=data["replacement_price_inr"],
            residual_value_inr=data.get("residual_value_inr", 0),
            result_json=result,
            created_by=request.user,
        )
        return self.respond(data={"analysis_id": str(analysis.id), **result}, message="Repair vs replace computed.")


class AffordabilityView(ApiResponseMixin, FarmAccessMixin):
    """Scores proposed and existing EMIs as a percentage of annual farm income.

    Write-only POST. Burden above the safe percentage raises the risk level;
    the assessment is saved as an AffordabilityAssessment row. This is an
    estimate, not a lending decision."""

    permission_classes = [IsAuthenticated]

    def post(self, request, farm_id):
        farm = self.get_farm()
        serializer = AffordabilityInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        result = calculate_machine_affordability(
            annual_income=data["annual_income_inr"],
            proposed_emi=data["proposed_emi_inr"],
            existing_emi_total=data.get("existing_emi_total_inr", 0),
            safe_burden_pct=data.get("safe_burden_pct", 25.0),
        )
        assessment = AffordabilityAssessment.objects.create(
            farm=farm,
            annual_income_inr=data["annual_income_inr"],
            proposed_emi_inr=data["proposed_emi_inr"],
            income_burden_pct=result["income_burden_pct"],
            result_json=result,
            created_by=request.user,
        )
        return self.respond(data={"assessment_id": str(assessment.id), **result}, message="Affordability computed.")


class MachineryDecisionView(ApiResponseMixin, FarmAccessMixin):
    """Runs the rule-first machinery decision engine over farmer-supplied inputs.

    Write-only POST. Unlike the other calculators this view has no input
    serializer: every field is read loosely and falls back to a default, so
    missing usage hours or purchase price yield 'gather_more_information'.
    The scenario is saved as a MachineryPurchaseScenario row."""

    permission_classes = [IsAuthenticated]

    def post(self, request, farm_id):
        farm = self.get_farm()

        def num(key, default):
            value = request.data.get(key, default)
            try:
                return float(value)
            except (TypeError, ValueError):
                return default

        result = generate_machinery_recommendation(
            usage_hours=num("usage_hours_per_year", None),
            rental_available=bool(request.data.get("rental_available", True)),
            annual_repair_spend=num("annual_repair_spend", 10000),
            residual_value=num("residual_value", 100000),
            purchase_price=num("purchase_price", None),
            annual_income=num("annual_income", 300000),
            emi=num("proposed_emi", 0),
            existing_emi=num("existing_emi", 0),
            subsidy=num("subsidy", 0),
        )
        scenario = MachineryPurchaseScenario.objects.create(
            farm=farm,
            option=result["suggested_option"],
            purchase_price_inr=int(num("purchase_price", 0) or 0) or None,
            estimated_subsidy_inr=int(num("subsidy", 0) or 0),
            result_json=result,
            created_by=request.user,
        )
        return self.respond(data={"scenario_id": str(scenario.id), **result}, message="Machinery recommendation generated.")


class ScenariosView(ApiResponseMixin, FarmAccessMixin):
    """Read-only list of stored machinery scenarios, newest first.

    Capped at the 20 most recent scenarios for the farm; nothing is written
    and no filtering or pagination is exposed."""

    permission_classes = [IsAuthenticated]

    def get(self, request, farm_id):
        farm = self.get_farm()
        scenarios = farm.machinery_scenarios.order_by("-created_at")[:20]
        return self.respond(data=MachineryPurchaseScenarioSerializer(scenarios, many=True).data, message="Scenarios retrieved.")