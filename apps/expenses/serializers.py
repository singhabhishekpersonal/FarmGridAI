"""Serializers for the expenses app."""
from django.conf import settings
from rest_framework import serializers

from apps.core.validators import reencode_image, sniff_mime, validate_document_extension, validate_upload_file_size
from apps.expenses.models import (
    ElectricityBill,
    ExpenseCategory,
    ExpenseDocument,
    FarmExpense,
    FarmExpenseSummary,
    FuelExpense,
    InputExpense,
    LabourExpense,
    RentalExpense,
    TransportExpense,
)


class ExpenseCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = ExpenseCategory
        fields = ["id", "code", "name", "is_custom"]


class FarmExpenseSerializer(serializers.ModelSerializer):
    year = serializers.IntegerField(read_only=True)

    class Meta:
        model = FarmExpense
        fields = ["id", "occurred_on", "amount", "category", "expense_type", "note", "year", "created_at"]
        read_only_fields = ["id", "year"]


class ElectricityBillSerializer(serializers.ModelSerializer):
    class Meta:
        model = ElectricityBill
        fields = ["id", "occurred_on", "amount", "provider", "units_kwh", "bill_month", "tariff_effective_per_kwh", "note"]
        read_only_fields = ["id", "tariff_effective_per_kwh"]


class FuelExpenseSerializer(serializers.ModelSerializer):
    class Meta:
        model = FuelExpense
        fields = ["id", "occurred_on", "amount", "litre_volume", "price_per_litre", "fuel_type", "purpose", "note"]
        read_only_fields = ["id"]


class InputExpenseSerializer(serializers.ModelSerializer):
    class Meta:
        model = InputExpense
        fields = ["id", "occurred_on", "amount", "input_type", "product_name", "quantity", "quantity_unit", "note"]
        read_only_fields = ["id"]


class LabourExpenseSerializer(serializers.ModelSerializer):
    class Meta:
        model = LabourExpense
        fields = ["id", "occurred_on", "amount", "labour_type", "person_days", "wage_per_day", "note"]
        read_only_fields = ["id"]


class TransportExpenseSerializer(serializers.ModelSerializer):
    class Meta:
        model = TransportExpense
        fields = ["id", "occurred_on", "amount", "vehicle_type", "distance_km", "note"]
        read_only_fields = ["id"]


class RentalExpenseSerializer(serializers.ModelSerializer):
    class Meta:
        model = RentalExpense
        fields = ["id", "occurred_on", "amount", "equipment_class", "rental_hours", "rental_days", "note"]
        read_only_fields = ["id"]


class ExpenseDocumentSerializer(serializers.ModelSerializer):
    class Meta:
        model = ExpenseDocument
        fields = ["id", "document", "original_name", "content_hash", "file_size", "category", "created_at"]
        read_only_fields = ["id", "content_hash", "file_size"]


class ExpenseDocumentUploadSerializer(serializers.Serializer):
    document = serializers.FileField()
    category = serializers.PrimaryKeyRelatedField(queryset=ExpenseCategory.objects.all(), required=False, allow_null=True)

    def validate_document(self, value):
        validate_upload_file_size(value)
        validate_document_extension(value.name)
        return value


class FarmExpenseSummarySerializer(serializers.ModelSerializer):
    per_hectare = serializers.SerializerMethodField()

    class Meta:
        model = FarmExpenseSummary
        fields = ["id", "year", "total_min", "total_max", "total_expected", "by_category", "per_hectare", "data_completeness", "confidence", "assumptions_json", "limitations_json"]
        read_only_fields = ["id"]

    def get_per_hectare(self, obj):
        return obj.per_hectare