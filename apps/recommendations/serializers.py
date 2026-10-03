"""Serializers for the recommendations app."""
from rest_framework import serializers

from apps.recommendations.models import (
    CostSavingOpportunity,
    Recommendation,
    RecommendationAssumption,
    RecommendationEvidence,
    RecommendationFeedback,
    RecommendationRun,
)


class RecommendationEvidenceSerializer(serializers.ModelSerializer):
    class Meta:
        model = RecommendationEvidence
        fields = ["id", "evidence_type", "description", "data_reference"]


class RecommendationAssumptionSerializer(serializers.ModelSerializer):
    class Meta:
        model = RecommendationAssumption
        fields = ["id", "assumption"]


class RecommendationSerializer(serializers.ModelSerializer):
    evidence = RecommendationEvidenceSerializer(many=True, read_only=True)
    assumptions = RecommendationAssumptionSerializer(many=True, read_only=True)

    class Meta:
        model = Recommendation
        fields = [
            "id", "farm", "category", "priority", "title", "text",
            "expected_benefit_min", "expected_benefit_max", "expected_cost",
            "financial_risk_level", "confidence", "model_versions_json",
            "disclaimer", "next_steps", "evidence", "assumptions", "created_at",
        ]
        read_only_fields = ["id", "created_at"]


class CostSavingOpportunitySerializer(serializers.ModelSerializer):
    class Meta:
        model = CostSavingOpportunity
        fields = ["id", "title", "category", "savings_min", "savings_max", "confidence", "basis", "created_at"]
        read_only_fields = ["id", "created_at"]


class RecommendationFeedbackSerializer(serializers.ModelSerializer):
    class Meta:
        model = RecommendationFeedback
        fields = ["id", "recommendation", "helpful", "accurate", "rating", "comment", "created_at"]
        read_only_fields = ["id", "created_at"]


class RecommendationRunSerializer(serializers.ModelSerializer):
    class Meta:
        model = RecommendationRun
        fields = ["id", "farm", "status", "summary_json", "models_used_json", "score", "created_at"]
        read_only_fields = ["id", "created_at"]