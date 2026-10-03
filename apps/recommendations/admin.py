"""Admin configuration for the recommendations app."""
from django.contrib import admin

from apps.recommendations.models import (
    CostSavingOpportunity,
    Recommendation,
    RecommendationAssumption,
    RecommendationEvidence,
    RecommendationFeedback,
    RecommendationRun,
)


class RecommendationEvidenceInline(admin.TabularInline):
    model = RecommendationEvidence
    extra = 0


class RecommendationAssumptionInline(admin.TabularInline):
    model = RecommendationAssumption
    extra = 0


@admin.register(Recommendation)
class RecommendationAdmin(admin.ModelAdmin):
    list_display = ["title", "farm", "category", "priority", "confidence", "created_at"]
    list_filter = ["category", "priority", "confidence"]
    search_fields = ["title", "text"]
    inlines = [RecommendationEvidenceInline, RecommendationAssumptionInline]


@admin.register(RecommendationRun)
class RecommendationRunAdmin(admin.ModelAdmin):
    list_display = ["farm", "status", "score", "created_at"]
    readonly_fields = ["summary_json", "models_used_json"]


@admin.register(RecommendationFeedback)
class RecommendationFeedbackAdmin(admin.ModelAdmin):
    list_display = ["recommendation", "user", "helpful", "accurate", "rating", "created_at"]


@admin.register(CostSavingOpportunity)
class CostSavingOpportunityAdmin(admin.ModelAdmin):
    list_display = ["title", "farm", "savings_min", "savings_max", "confidence"]