"""Recommendation domain models and their evidence/assumption records."""
from django.conf import settings
from django.db import models

from apps.core.models import BaseModel
from apps.farms.models import Farm


class RecommendationRun(BaseModel):
    """A batch execution of the recommendation engine."""

    farm = models.ForeignKey(Farm, on_delete=models.CASCADE, related_name="recommendation_runs")
    status = models.CharField(max_length=15, default="completed")
    summary_json = models.JSONField(default=dict)
    models_used_json = models.JSONField(default=list)
    score = models.FloatField(default=0.0)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Run {self.pk} for {self.farm_id}"


class Recommendation(BaseModel):
    """A single explainable recommendation for a farm."""

    CATEGORY_CHOICES = [
        ("reduce_fertilizer_cost", "Reduce fertilizer cost"),
        ("review_high_energy_cost", "Review high energy cost"),
        ("solar_feasibility", "Solar feasibility"),
        ("machine_buy_or_rent", "Machine buy or rent"),
        ("repair_or_replace", "Repair or replace"),
        ("use_custom_hiring_center", "Use custom hiring center"),
        ("consider_shared_ownership", "Consider shared ownership"),
        ("apply_for_subsidy", "Apply for subsidy"),
        ("review_unusual_expense", "Review unusual expense"),
        ("collect_more_data", "Collect more data"),
        ("preventive_maintenance", "Preventive maintenance"),
        ("optimize_crop_cost_plan", "Optimize crop cost plan"),
        ("general_financial_health", "General financial health"),
    ]
    PRIORITY_CHOICES = [("critical", "Critical"), ("high", "High"), ("medium", "Medium"), ("low", "Low")]

    farm = models.ForeignKey(Farm, on_delete=models.CASCADE, related_name="recommendations")
    run = models.ForeignKey("recommendations.RecommendationRun", on_delete=models.SET_NULL, null=True, blank=True, related_name="recommendations")
    category = models.CharField(max_length=40, choices=CATEGORY_CHOICES)
    priority = models.CharField(max_length=10, choices=PRIORITY_CHOICES, default="medium")
    title = models.CharField(max_length=160)
    text = models.TextField()
    expected_benefit_min = models.PositiveIntegerField(null=True, blank=True)
    expected_benefit_max = models.PositiveIntegerField(null=True, blank=True)
    expected_cost = models.PositiveIntegerField(null=True, blank=True)
    financial_risk_level = models.CharField(max_length=12, default="medium")
    confidence = models.CharField(max_length=10, default="low")
    model_versions_json = models.JSONField(default=list)
    disclaimer = models.TextField(blank=True)
    next_steps = models.JSONField(default=list)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["farm", "category"])]

    def __str__(self):
        return f"{self.farm_id}: {self.category} ({self.priority})"


class RecommendationEvidence(BaseModel):
    """Explainable evidence supporting a recommendation."""

    recommendation = models.ForeignKey(Recommendation, on_delete=models.CASCADE, related_name="evidence")
    evidence_type = models.CharField(max_length=30)
    description = models.TextField()
    data_reference = models.JSONField(default=dict)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.recommendation_id}: {self.evidence_type}"


class RecommendationAssumption(BaseModel):
    """Assumption the recommendation relies on."""

    recommendation = models.ForeignKey(Recommendation, on_delete=models.CASCADE, related_name="assumptions")
    assumption = models.TextField()

    def __str__(self):
        return f"{self.recommendation_id}: {self.assumption[:60]}"


class CostSavingOpportunity(BaseModel):
    """Identified cost-saving opportunity with an estimated savings range."""

    farm = models.ForeignKey(Farm, on_delete=models.CASCADE, related_name="cost_saving_opportunities")
    title = models.CharField(max_length=160)
    category = models.CharField(max_length=40, choices=Recommendation.CATEGORY_CHOICES, default="general_financial_health")
    savings_min = models.PositiveIntegerField(default=0)
    savings_max = models.PositiveIntegerField(default=0)
    confidence = models.CharField(max_length=10, default="low")
    basis = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.farm_id}: {self.title} (Rs {self.savings_min}-{self.savings_max})"


class RecommendationFeedback(BaseModel):
    """User feedback/correction on a recommendation."""

    recommendation = models.ForeignKey(Recommendation, on_delete=models.CASCADE, related_name="feedback_records")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="recommendation_feedback")
    helpful = models.BooleanField(default=True)
    accurate = models.BooleanField(default=True)
    rating = models.PositiveSmallIntegerField(null=True, blank=True)
    comment = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.recommendation_id} feedback by {self.user_id}"