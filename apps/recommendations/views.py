"""API views for the recommendations app."""
from rest_framework.permissions import IsAuthenticated

from apps.api.mixins import ApiResponseMixin, FarmAccessMixin
from apps.recommendations.models import CostSavingOpportunity, Recommendation, RecommendationFeedback, RecommendationRun
from apps.recommendations.serializers import (
    CostSavingOpportunitySerializer,
    RecommendationFeedbackSerializer,
    RecommendationSerializer,
)
from apps.recommendations.services import ExplainabilityGenerator, RecommendationEngine


class RecommendationsListView(ApiResponseMixin, FarmAccessMixin):
    """Read-only list of every stored recommendation for the farm.

    Returns every row regardless of run, priority or category, so successive
    generate calls accumulate history rather than replacing it."""

    permission_classes = [IsAuthenticated]

    def get(self, request, farm_id):
        farm = self.get_farm()
        recs = Recommendation.objects.filter(farm=farm).select_related("run")
        return self.respond(data=RecommendationSerializer(recs, many=True).data, message="Recommendations retrieved.")


class RecommendationsGenerateView(ApiResponseMixin, FarmAccessMixin):
    """Runs the recommendation engine synchronously and persists the results.

    POST only. Each call writes a RecommendationRun plus one Recommendation
    with its evidence and assumption rows; prior runs are left intact.
    Set use_ml_ranker false to skip ML ranking and use the deterministic
    priority score. Evidence gathering is best-effort, so missing source
    data yields fewer recommendations rather than an error."""

    permission_classes = [IsAuthenticated]

    def post(self, request, farm_id):
        farm = self.get_farm()
        use_ml = request.data.get("use_ml_ranker", True)
        engine = RecommendationEngine(farm, use_ml_ranker=bool(use_ml))
        result = engine.run(persist=True, user=request.user)
        return self.respond(data=result, message="Recommendations generated.")


class RecommendationExplainView(ApiResponseMixin, FarmAccessMixin):
    """Builds the explanation object for one recommendation (evidence, assumptions, uncertainty).

    Read-only and scoped to the farm, so another farm's id returns a 404 error
    envelope rather than an exception. Nothing is persisted."""

    permission_classes = [IsAuthenticated]

    def get(self, request, farm_id, recommendation_id):
        farm = self.get_farm()
        rec = Recommendation.objects.filter(farm=farm, pk=recommendation_id).first()
        if rec is None:
            return self.respond_error([{"field": "recommendation", "message": "Recommendation not found."}], status_code=404)
        explanation = ExplainabilityGenerator().explain(rec)
        return self.respond(data=explanation, message="Explanation generated.")


class CostSavingOpportunitiesView(ApiResponseMixin, FarmAccessMixin):
    """Read-only list of cost-saving opportunities recorded for the farm.

    Unpaginated and unordered beyond the model's default newest-first
    ordering; rows are written elsewhere, not here."""

    permission_classes = [IsAuthenticated]

    def get(self, request, farm_id):
        farm = self.get_farm()
        opportunities = CostSavingOpportunity.objects.filter(farm=farm)
        return self.respond(data=CostSavingOpportunitySerializer(opportunities, many=True).data, message="Opportunities retrieved.")


class RecommendationFeedbackView(ApiResponseMixin, FarmAccessMixin):
    """Records a farmer's helpful/accurate flags, rating and comment on a recommendation.

    POST only, and appends rather than updating: each call creates a new
    feedback row. Request data is read without a serializer, so missing fields
    fall back to defaults and rating is stored unchecked. An unknown or
    foreign recommendation returns a 404 error envelope."""

    permission_classes = [IsAuthenticated]

    def post(self, request, farm_id, recommendation_id):
        farm = self.get_farm()
        rec = Recommendation.objects.filter(farm=farm, pk=recommendation_id).first()
        if rec is None:
            return self.respond_error([{"field": "recommendation", "message": "Recommendation not found."}], status_code=404)
        feedback = RecommendationFeedback.objects.create(
            recommendation=rec,
            user=request.user,
            helpful=request.data.get("helpful", True),
            accurate=request.data.get("accurate", True),
            rating=request.data.get("rating"),
            comment=request.data.get("comment", ""),
            created_by=request.user,
        )
        return self.respond(data=RecommendationFeedbackSerializer(feedback).data, message="Feedback saved.")


class RecommendationRunView(ApiResponseMixin, FarmAccessMixin):
    """Read-only list of recommendation runs for the farm.

    Serialized with .values() rather than a model serializer, so it returns raw
    model columns including audit fields; no cap or pagination is applied."""

    permission_classes = [IsAuthenticated]

    def get(self, request, farm_id):
        farm = self.get_farm()
        runs = RecommendationRun.objects.filter(farm=farm)
        return self.respond(data=list(runs.values()), message="Recommendation runs retrieved.")