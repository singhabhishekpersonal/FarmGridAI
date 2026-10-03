"""Serializers for the subsidies app."""
from rest_framework import serializers

from apps.subsidies.models import (
    FarmerSchemeMatch,
    SchemeApplicationChecklist,
    SchemeDocumentRequirement,
    SubsidyEligibilityRule,
    SubsidyScheme,
    SubsidySchemeVersion,
    SubsidySourceReference,
)


class SchemeDocumentRequirementSerializer(serializers.ModelSerializer):
    class Meta:
        model = SchemeDocumentRequirement
        fields = ["id", "document_name", "required", "notes"]
        read_only_fields = ["id"]


class SubsidyEligibilityRuleSerializer(serializers.ModelSerializer):
    class Meta:
        model = SubsidyEligibilityRule
        fields = ["id", "field", "operator", "value", "reason", "sequence"]
        read_only_fields = ["id"]


class SubsidySchemeSerializer(serializers.ModelSerializer):
    documents = SchemeDocumentRequirementSerializer(many=True, read_only=True)
    rules = SubsidyEligibilityRuleSerializer(many=True, read_only=True)

    class Meta:
        model = SubsidyScheme
        fields = [
            "id", "name", "slug", "category", "administrative_level", "state", "district",
            "is_active", "effective_from", "effective_to", "benefit_type", "benefit_min_inr",
            "benefit_max_inr", "official_url", "application_steps", "last_verified_at",
            "scheme_version", "is_illustrative", "documents", "rules", "notes",
        ]
        read_only_fields = ["id"]


class FarmerSchemeMatchSerializer(serializers.ModelSerializer):
    scheme = SubsidySchemeSerializer(read_only=True)

    class Meta:
        model = FarmerSchemeMatch
        fields = ["id", "farm", "scheme", "matched", "reasons_json", "confidence", "needs_official_verification", "evaluated_at"]
        read_only_fields = ["id", "evaluated_at"]


class SchemeApplicationChecklistSerializer(serializers.ModelSerializer):
    class Meta:
        model = SchemeApplicationChecklist
        fields = ["id", "match", "items_json", "notes"]


class SubsidySchemeVersionSerializer(serializers.ModelSerializer):
    class Meta:
        model = SubsidySchemeVersion
        fields = ["id", "version", "changes_json", "verified_at", "supersedes_on"]


class SubsidySourceReferenceSerializer(serializers.ModelSerializer):
    class Meta:
        model = SubsidySourceReference
        fields = ["id", "title", "url", "last_accessed"]