"""Serializers for the crops app."""
from rest_framework import serializers

from apps.crops.models import Crop, CropCostBenchmark, CropInputEstimate, FarmCrop


class CropSerializer(serializers.ModelSerializer):
    class Meta:
        model = Crop
        fields = ["id", "name", "local_name", "slug", "category", "primary_season", "typical_days_to_harvest", "typical_yield_qtl_per_acre", "is_synthetic_benchmark"]
        read_only_fields = ["id"]


class CropCostBenchmarkSerializer(serializers.ModelSerializer):
    class Meta:
        model = CropCostBenchmark
        fields = ["id", "crop", "input_type", "unit", "state", "min_cost", "max_cost", "expected_cost", "source", "is_verified", "notes"]
        read_only_fields = ["id"]


class FarmCropSerializer(serializers.ModelSerializer):
    crop_name = serializers.CharField(source="crop.name", read_only=True)
    area_acres = serializers.SerializerMethodField()

    class Meta:
        model = FarmCrop
        fields = ["id", "crop", "crop_name", "season", "year", "area", "area_unit", "area_hectares", "area_acres", "expected_yield_qtl_per_acre", "is_planned"]
        read_only_fields = ["id", "area_hectares", "area_acres"]

    def get_area_acres(self, obj):
        return obj.area_acres


class CropInputEstimateSerializer(serializers.ModelSerializer):
    class Meta:
        model = CropInputEstimate
        fields = ["id", "input_type", "min_cost", "max_cost", "expected_cost", "per_acre", "confidence", "assumptions_json"]


class FarmCropEstimateSerializer(serializers.Serializer):
    farm_crop = FarmCropSerializer()
    estimate = serializers.DictField()