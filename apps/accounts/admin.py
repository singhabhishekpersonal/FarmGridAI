"""Admin configuration for the accounts app."""
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from apps.accounts.models import ConsentRecord, FarmerProfile, User, UserLanguagePreference


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ["username", "email", "phone", "is_farmer", "is_staff", "date_joined"]
    search_fields = ["username", "email", "phone"]
    readonly_fields = ["last_login", "date_joined"]
    fieldsets = BaseUserAdmin.fieldsets + (("Profile", {"fields": ("phone", "preferred_language")}),)


@admin.register(FarmerProfile)
class FarmerProfileAdmin(admin.ModelAdmin):
    list_display = ["full_name", "user", "state", "district", "land_size", "land_unit", "normalized_land_hectares", "consent_accepted"]
    list_filter = ["state", "irrigated", "land_ownership", "consent_accepted"]
    search_fields = ["full_name", "user__email", "user__username", "phone", "village"]
    readonly_fields = ["id", "normalized_land_hectares", "created_at", "updated_at", "created_by", "updated_by"]


class ConsentInline(admin.TabularInline):
    model = ConsentRecord
    extra = 0
    readonly_fields = ["purpose", "granted", "granted_at", "revoked_at", "consent_version"]


@admin.register(ConsentRecord)
class ConsentRecordAdmin(admin.ModelAdmin):
    list_display = ["user", "purpose", "granted", "granted_at", "revoked_at", "consent_version"]
    list_filter = ["purpose", "granted"]
    search_fields = ["user__email", "user__username"]
    readonly_fields = ["id", "created_at", "updated_at"]


@admin.register(UserLanguagePreference)
class UserLanguagePreferenceAdmin(admin.ModelAdmin):
    list_display = ["user", "language_code", "is_primary"]
    list_filter = ["language_code", "is_primary"]