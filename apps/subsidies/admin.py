"""Admin configuration for the subsidies app."""
from django.contrib import admin

from apps.subsidies.models import (
    FarmerSchemeMatch,
    SchemeApplicationChecklist,
    SchemeDocumentRequirement,
    SubsidyEligibilityRule,
    SubsidyScheme,
    SubsidySchemeVersion,
    SubsidySourceReference,
)


class SchemeDocumentInline(admin.TabularInline):
    model = SchemeDocumentRequirement
    extra = 0


class SchemeRuleInline(admin.TabularInline):
    model = SubsidyEligibilityRule
    extra = 0
    fields = ["field", "operator", "value", "reason", "sequence"]


class SchemeSourceInline(admin.TabularInline):
    model = SubsidySourceReference
    extra = 0


@admin.register(SubsidyScheme)
class SubsidySchemeAdmin(admin.ModelAdmin):
    list_display = ["name", "category", "administrative_level", "state", "is_active", "last_verified_at", "is_illustrative"]
    list_filter = ["category", "administrative_level", "state", "is_active", "is_illustrative"]
    search_fields = ["name", "slug", "state"]
    inlines = [SchemeDocumentInline, SchemeRuleInline, SchemeSourceInline]
    readonly_fields = ["id", "created_at", "updated_at"]


@admin.register(SubsidySchemeVersion)
class SubsidySchemeVersionAdmin(admin.ModelAdmin):
    list_display = ["scheme", "version", "verified_at", "supersedes_on"]


@admin.register(FarmerSchemeMatch)
class FarmerSchemeMatchAdmin(admin.ModelAdmin):
    list_display = ["farm", "scheme", "matched", "confidence", "needs_official_verification", "evaluated_at"]
    list_filter = ["matched", "confidence"]
    readonly_fields = ["reasons_json", "evaluated_at"]


@admin.register(SchemeApplicationChecklist)
class SchemeApplicationChecklistAdmin(admin.ModelAdmin):
    list_display = ["match", "created_at"]
    readonly_fields = ["items_json"]