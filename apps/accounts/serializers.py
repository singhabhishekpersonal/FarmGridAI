"""API serializers for the accounts app."""
from django.contrib.auth.password_validation import validate_password
from django.core.validators import RegexValidator
from rest_framework import serializers
from drf_spectacular.utils import extend_schema_field

from apps.accounts.models import ConsentRecord, FarmerProfile, User, UserLanguagePreference

PHONE_VALIDATOR = RegexValidator(
    regex=r"^[0-9]{10}$",
    message="Enter a valid 10-digit Indian mobile number.",
)


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "username", "email", "phone", "first_name", "last_name", "preferred_language", "is_farmer"]
        read_only_fields = ["id", "is_farmer"]

    # Declared explicitly: ``is_farmer`` is a model @property, so spectacular
    # would otherwise fall back to a string and the frontend would lose the
    # boolean contract.
    is_farmer = serializers.BooleanField(read_only=True)


class RegisterSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=150)
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, min_length=8, validators=[validate_password])
    phone = serializers.CharField(required=False, allow_blank=True, max_length=15)
    full_name = serializers.CharField(required=False, allow_blank=True, max_length=120)
    state = serializers.CharField(required=False, allow_blank=True, max_length=60)
    district = serializers.CharField(required=False, allow_blank=True, max_length=60)
    village = serializers.CharField(required=False, allow_blank=True, max_length=80)
    pincode = serializers.CharField(required=False, allow_blank=True, max_length=6)
    land_size = serializers.DecimalField(required=False, allow_null=True, max_digits=10, decimal_places=3)
    land_unit = serializers.ChoiceField(required=False, choices=FarmerProfile._meta.get_field("land_unit").choices, default="acre")

    def validate_pincode(self, value):
        if value and (not value.isdigit() or len(value) != 6):
            raise serializers.ValidationError("Enter a valid 6-digit pincode.")
        return value

    def validate_phone(self, value):
        if value:
            PHONE_VALIDATOR(value)
        return value

    def validate_land_size(self, value):
        if value is not None and value <= 0:
            raise serializers.ValidationError("Land size must be positive.")
        return value


class FarmerProfileSerializer(serializers.ModelSerializer):
    user = UserSerializer(read_only=True)
    area_in_hectares = serializers.SerializerMethodField()

    class Meta:
        model = FarmerProfile
        fields = [
            "id",
            "user",
            "full_name",
            "phone",
            "gender",
            "state",
            "district",
            "village",
            "pincode",
            "land_size",
            "land_unit",
            "normalized_land_hectares",
            "area_in_hectares",
            "land_ownership",
            "irrigated",
            "irrigation_source",
            "yearly_farm_income_min",
            "yearly_farm_income_max",
            "household_income_min",
            "household_income_max",
            "consent_accepted",
            "onboard_complete",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "user", "normalized_land_hectares", "area_in_hectares", "consent_accepted", "created_at", "updated_at"]

    @extend_schema_field(serializers.FloatField())
    def get_area_in_hectares(self, obj):
        return obj.area_in_hectares

    def validate(self, attrs):
        land_size = attrs.get("land_size", getattr(self.instance, "land_size", None))
        land_unit = attrs.get("land_unit", getattr(self.instance, "land_unit", "acre"))
        if land_size is not None and land_size <= 0:
            raise serializers.ValidationError({"land_size": "Land size must be positive."})
        return attrs


class ConsentRecordSerializer(serializers.ModelSerializer):
    purpose_label = serializers.CharField(source="get_purpose_display", read_only=True)

    class Meta:
        model = ConsentRecord
        fields = ["id", "purpose", "purpose_label", "granted", "granted_at", "revoked_at", "consent_version", "created_at"]
        read_only_fields = ["id", "granted", "granted_at", "revoked_at", "created_at"]


class UserLanguagePreferenceSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserLanguagePreference
        fields = ["id", "language_code", "is_primary", "created_at"]