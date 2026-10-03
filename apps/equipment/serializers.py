"""Serializers for the equipment app."""
from django.conf import settings
from rest_framework import serializers

from apps.core.validators import reencode_image, sniff_mime, validate_image_extension, validate_upload_file_size
from apps.equipment.models import (
    EquipmentCatalog,
    EquipmentCategory,
    EquipmentConditionAssessment,
    EquipmentImage,
    EquipmentImagePrediction,
    EquipmentMaintenanceRecord,
    EquipmentOCRResult,
    EquipmentUsageRecord,
    FarmerEquipment,
)


class EquipmentCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = EquipmentCategory
        fields = ["id", "code", "name", "description", "typical_hp_min", "typical_hp_max", "fuel_consumption_l_per_hr", "price_range_min", "price_range_max", "typical_lifespan_years"]
        read_only_fields = ["id"]


class EquipmentCatalogSerializer(serializers.ModelSerializer):
    category_code = serializers.CharField(source="category.code", read_only=True)
    category_name = serializers.CharField(source="category.name", read_only=True)

    class Meta:
        model = EquipmentCatalog
        fields = ["id", "category", "category_code", "category_name", "brand", "model", "slug", "hp", "price_min", "price_max", "price_expected", "fuel_type", "drive_type", "image_url", "source_url", "source", "is_verified"]
        read_only_fields = ["id"]


class FarmerEquipmentSerializer(serializers.ModelSerializer):
    display_name = serializers.CharField(read_only=True)
    age_years = serializers.SerializerMethodField()

    class Meta:
        model = FarmerEquipment
        fields = [
            "id", "catalog", "category", "custom_brand", "custom_model", "display_name",
            "horsepower", "purchase_year", "purchase_price", "condition", "fuel_type",
            "usage_hours_per_year", "area_served_acres", "is_owned", "is_operational",
            "confirmation_required", "age_years", "notes", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "display_name", "age_years", "created_at", "updated_at"]

    def get_age_years(self, obj):
        return obj.age_years

    def validate(self, attrs):
        hp = attrs.get("horsepower")
        if hp is not None and hp <= 0:
            raise serializers.ValidationError({"horsepower": "Must be positive."})
        year = attrs.get("purchase_year")
        if year and year > self.context.get("current_year", 2099):
            raise serializers.ValidationError({"purchase_year": "Not a valid year."})
        return attrs


class EquipmentImageSerializer(serializers.ModelSerializer):
    class Meta:
        model = EquipmentImage
        fields = ["id", "image", "original_name", "content_hash", "file_size", "width", "height", "status", "is_primary", "rejection_reason", "created_at"]
        read_only_fields = ["id", "content_hash", "file_size", "width", "height", "status"]


class EquipmentImageUploadSerializer(serializers.Serializer):
    image = serializers.ImageField()
    is_primary = serializers.BooleanField(default=False)

    def validate_image(self, value):
        validate_upload_file_size(value)
        validate_image_extension(value.name)
        content = value.read()
        value.seek(0)
        mime = sniff_mime(content)
        if mime and mime not in settings.ALLOWED_IMAGE_MIME_TYPES:
            raise serializers.ValidationError("Unsupported image type.")
        return value


class EquipmentImagePredictionSerializer(serializers.ModelSerializer):
    class Meta:
        model = EquipmentImagePrediction
        fields = ["id", "predicted_class", "predicted_brand", "confidence", "class_probabilities", "top_predictions", "confidence_label", "used_ml", "artifact_available", "unknown_threshold", "model_name", "model_version", "input_hash", "source", "needs_user_confirmation", "created_at"]
        read_only_fields = ["id", "created_at"]


class EquipmentConditionAssessmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = EquipmentConditionAssessment
        fields = ["id", "visible_condition_score", "condition_band", "issue_tags", "method", "confidence", "needs_user_confirmation", "created_at"]
        read_only_fields = ["id"]


class EquipmentUsageRecordSerializer(serializers.ModelSerializer):
    class Meta:
        model = EquipmentUsageRecord
        fields = ["id", "year", "hours_used", "fuel_used_litres", "area_covered_acres", "notes"]
        read_only_fields = ["id"]


class EquipmentMaintenanceRecordSerializer(serializers.ModelSerializer):
    class Meta:
        model = EquipmentMaintenanceRecord
        fields = ["id", "occurred_on", "kind", "cost", "description"]
        read_only_fields = ["id"]


class EquipmentOCRResultSerializer(serializers.ModelSerializer):
    class Meta:
        model = EquipmentOCRResult
        fields = ["id", "provider", "raw_text", "brand_candidates", "model_candidates", "confidence", "needs_user_confirmation", "error"]
        read_only_fields = ["id"]


class EquipmentConfirmClassificationSerializer(serializers.Serializer):
    predicted_class = serializers.ChoiceField(choices=EquipmentCategory._meta.get_field("code").choices)
    brand = serializers.CharField(required=False, allow_blank=True)
    model = serializers.CharField(required=False, allow_blank=True)


class EquipmentAnalyzeViewSerializer(serializers.Serializer):
    """Body accepted by the analyze endpoint (all optional)."""
    run_ocr = serializers.BooleanField(default=True)