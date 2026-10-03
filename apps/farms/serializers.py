"""Serializers for the farms app."""
from rest_framework import serializers

from apps.farms.models import (
    BighaConversionRule,
    Farm,
    FarmCropSeason,
    FarmLocation,
    IrrigationProfile,
    LandParcel,
    LandUnitConversion,
)


class FarmLocationSerializer(serializers.ModelSerializer):
    class Meta:
        model = FarmLocation
        fields = ["id", "state", "district", "tehsil", "village", "pincode", "latitude", "longitude"]
        read_only_fields = ["id"]


class LandParcelSerializer(serializers.ModelSerializer):
    area_acre = serializers.SerializerMethodField()

    class Meta:
        model = LandParcel
        fields = [
            "id",
            "name",
            "area",
            "unit",
            "area_hectares",
            "area_acre",
            "area_requires_confirmation",
            "conversion_note",
            "ownership",
            "irrigated",
            "irrigation_source",
            "soil_type",
            "is_primary",
        ]
        read_only_fields = ["id", "area_hectares", "area_acre", "area_requires_confirmation", "conversion_note"]

    def get_area_acre(self, obj):
        return obj.area_acre


class IrrigationProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = IrrigationProfile
        fields = ["id", "source", "availability", "typical_hours_per_day", "monthly_electricity_kwh", "notes"]
        read_only_fields = ["id"]


class FarmCropSeasonSerializer(serializers.ModelSerializer):
    class Meta:
        model = FarmCropSeason
        fields = ["id", "season", "year", "is_active"]
        read_only_fields = ["id"]


class FarmSerializer(serializers.ModelSerializer):
    location = FarmLocationSerializer(read_only=True)
    parcels = LandParcelSerializer(many=True, read_only=True)
    total_hectares = serializers.SerializerMethodField()

    class Meta:
        model = Farm
        fields = [
            "id",
            "name",
            "description",
            "is_default",
            "active_season_year",
            "location",
            "parcels",
            "total_hectares",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "location", "parcels", "total_hectares", "created_at", "updated_at"]

    def get_total_hectares(self, obj):
        return obj.total_hectares


class FarmCreateSerializer(serializers.ModelSerializer):
    state = serializers.CharField(write_only=True, required=False, default="")
    district = serializers.CharField(write_only=True, required=False, default="")
    village = serializers.CharField(write_only=True, required=False, default="")
    pincode = serializers.CharField(write_only=True, required=False, allow_blank=True, default="")
    parcel_area = serializers.DecimalField(write_only=True, required=False, max_digits=12, decimal_places=3)
    parcel_unit = serializers.ChoiceField(write_only=True, required=False, choices=LandParcel._meta.get_field("unit").choices, default="acre")

    class Meta:
        model = Farm
        fields = [
            "name",
            "description",
            "is_default",
            "state",
            "district",
            "village",
            "pincode",
            "parcel_area",
            "parcel_unit",
        ]

    def create(self, validated_data):
        from apps.farms.models import FarmService

        farm = FarmService.create_farm(
            user=self.context["request"].user,
            name=validated_data["name"],
            description=validated_data.get("description", ""),
            state=validated_data.get("state", ""),
            district=validated_data.get("district", ""),
            village=validated_data.get("village", ""),
            pincode=validated_data.get("pincode", ""),
            is_default=validated_data.get("is_default"),
            area=validated_data.get("parcel_area"),
            unit=validated_data.get("parcel_unit", "acre"),
        )
        return farm


class BighaConversionRuleSerializer(serializers.ModelSerializer):
    class Meta:
        model = BighaConversionRule
        fields = ["id", "state", "district", "label", "sq_meters_per_bigha", "is_verified", "last_verified_at", "source"]
        read_only_fields = ["id", "is_verified", "last_verified_at"]


class LandUnitConversionSerializer(serializers.ModelSerializer):
    class Meta:
        model = LandUnitConversion
        fields = ["id", "original_value", "original_unit", "result_hectares", "method", "requires_confirmation"]
        read_only_fields = ["id"]