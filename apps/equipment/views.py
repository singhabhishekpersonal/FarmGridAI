"""API views for the equipment app."""
import hashlib
import io
from datetime import date

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from rest_framework import status
from rest_framework.permissions import IsAuthenticated

from apps.api.mixins import ApiResponseMixin, FarmAccessMixin
from apps.core.validators import (
    reencode_image,
    sniff_mime,
    validate_image_extension,
    validate_upload_file_size,
)
from apps.equipment.models import (
    CONDITION_BANDS,
    EquipmentCatalog,
    EquipmentCategory,
    EquipmentConditionAssessment,
    EquipmentImage,
    EquipmentImagePrediction,
    EquipmentOCRResult,
    FarmerEquipment,
)
from apps.equipment.serializers import (
    EquipmentCategorySerializer,
    EquipmentCatalogSerializer,
    EquipmentConditionAssessmentSerializer,
    EquipmentImagePredictionSerializer,
    EquipmentImageSerializer,
    FarmerEquipmentSerializer,
)
from apps.equipment.services import EquipmentOperatingCostEstimator
from apps.ml_engine.services.equipment_analysis import EquipmentAnalysisService
from drf_spectacular.utils import extend_schema


class EquipmentCategoryListView(ApiResponseMixin, FarmAccessMixin):
    """List every equipment category, unfiltered.

    The category set is small and shared reference data, so no farm scoping or
    query parameters apply despite the ``farm_id`` URL segment.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        qs = EquipmentCategory.objects.all()
        return self.respond(data=EquipmentCategorySerializer(qs, many=True).data, message="Categories retrieved.")


class EquipmentCatalogListView(ApiResponseMixin, FarmAccessMixin):
    """Browse verified catalog models, optionally filtered by brand or category.

    Unverified entries are never exposed. ``brand`` matches case-insensitively
    anywhere in the name, ``category`` matches the category code exactly, and
    the result is hard-capped at 200 rows since there is no pagination.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        qs = EquipmentCatalog.objects.filter(is_verified=True)
        brand = request.query_params.get("brand")
        category = request.query_params.get("category")
        if brand:
            qs = qs.filter(brand__icontains=brand)
        if category:
            qs = qs.filter(category__code=category)
        qs = qs[:200]
        return self.respond(data=EquipmentCatalogSerializer(qs, many=True).data, message="Catalog retrieved.")


class FarmerEquipmentListView(ApiResponseMixin, FarmAccessMixin):
    """List or add the equipment owned by one of the caller's farms.

    Every query is scoped through ``FarmAccessMixin``, so a farm the caller does
    not own yields a 404 rather than an empty list. On create, the farm and the
    caller are set by the view and cannot be spoofed in the payload.
    """

    permission_classes = [IsAuthenticated]

    @extend_schema(operation_id="v1_farms_equipment_list")
    def get(self, request, farm_id):
        farm = self.get_farm()
        items = FarmerEquipment.objects.filter(farm=farm).select_related("catalog", "category")
        return self.respond(data=FarmerEquipmentSerializer(items, many=True).data, message="Equipment retrieved.")

    def post(self, request, farm_id):
        farm = self.get_farm()
        serializer = FarmerEquipmentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save(farm=farm, created_by=request.user)
        return self.respond(data=serializer.data, message="Equipment saved.", status_code=status.HTTP_201_CREATED)


class FarmerEquipmentDetailView(ApiResponseMixin, FarmAccessMixin):
    """Retrieve, partially update or hard-delete one equipment record.

    Rows are looked up by farm plus id, so an id from another farm reads as 404.
    Delete is a real row deletion, not a soft delete, and is therefore not
    reversible.
    """

    permission_classes = [IsAuthenticated]

    def _get(self, request, farm_id, equipment_id):
        farm = self.get_farm()
        return FarmerEquipment.objects.filter(farm=farm, pk=equipment_id).select_related("catalog", "category").first()

    def get(self, request, farm_id, equipment_id):
        item = self._get(request, farm_id, equipment_id)
        if item is None:
            return self.respond_error([{"field": "equipment", "message": "Equipment not found."}], status_code=404)
        return self.respond(data=FarmerEquipmentSerializer(item).data, message="Equipment detail.")

    def patch(self, request, farm_id, equipment_id):
        item = self._get(request, farm_id, equipment_id)
        if item is None:
            return self.respond_error([{"field": "equipment", "message": "Equipment not found."}], status_code=404)
        serializer = FarmerEquipmentSerializer(item, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return self.respond(data=serializer.data, message="Equipment updated.")

    def delete(self, request, farm_id, equipment_id):
        item = self._get(request, farm_id, equipment_id)
        if item is None:
            return self.respond_error([{"field": "equipment", "message": "Equipment not found."}], status_code=404)
        item.delete()
        return self.respond(message="Equipment removed.")


class EquipmentImageUploadView(ApiResponseMixin, FarmAccessMixin):
    """Upload a photo for one equipment item after re-encoding it as a safe image.

    The upload is validated by size and extension, sniffed by content rather
    than trusting the declared MIME type, then re-encoded to strip metadata and
    embedded payloads before storage. The row records a SHA-256 of the sanitized
    bytes plus probed dimensions and MIME; failures are reported as 400 field
    errors, and a missing equipment id as 404.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request, farm_id, equipment_id):
        farm = self.get_farm()
        item = FarmerEquipment.objects.filter(farm=farm, pk=equipment_id).first()
        if item is None:
            return self.respond_error([{"field": "equipment", "message": "Equipment not found."}], status_code=404)
        image_file = request.FILES.get("image")
        if not image_file:
            return self.respond_error([{"field": "image", "message": "image file is required."}])
        try:
            validate_upload_file_size(image_file)
            validate_image_extension(image_file.name)
            raw = image_file.read()
            input_mime = sniff_mime(raw)
            if input_mime not in settings.ALLOWED_IMAGE_MIME_TYPES:
                raise ValidationError("Unsupported image type. Allowed: jpeg, png, webp.")
            sanitized = reencode_image(raw)
        except ValidationError as exc:
            return self.respond_error([{"field": "image", "message": exc.messages[0]}])
        except Exception:
            return self.respond_error([{"field": "image", "message": "File is not a valid image."}])
        mime = sniff_mime(sanitized) or "image/jpeg"
        width, height = None, None
        try:
            from PIL import Image

            probe = Image.open(io.BytesIO(sanitized))
            width, height = probe.size
        except Exception:
            pass
        obj = EquipmentImage.objects.create(
            equipment=item,
            image=ContentFile(sanitized, name=image_file.name),
            original_name=image_file.name,
            content_hash=hashlib.sha256(sanitized).hexdigest(),
            file_size=len(sanitized),
            width=width,
            height=height,
            mime_type=mime,
            status="processed",
            is_primary=request.data.get("is_primary") in (True, "true", 1, "1"),
            created_by=request.user,
        )
        return self.respond(data={"image_id": str(obj.id), "status": "uploaded"}, message="Image uploaded.", status_code=status.HTTP_201_CREATED)


class EquipmentImageAnalyzeView(ApiResponseMixin, FarmAccessMixin):
    """Run classification + OCR + condition over an uploaded image."""

    permission_classes = [IsAuthenticated]

    def post(self, request, farm_id, equipment_id, image_id):
        farm = self.get_farm()
        image = EquipmentImage.objects.filter(equipment_id=equipment_id, equipment__farm=farm, pk=image_id).first()
        if image is None:
            return self.respond_error([{"field": "image", "message": "Image not found."}], status_code=404)
        service = EquipmentAnalysisService(image, user=request.user)
        result = service.run_analysis(persist=True)
        return self.respond(data=result, message="Analysis completed - estimates need confirmation.")


class EquipmentOperatingCostView(ApiResponseMixin, FarmAccessMixin):
    """Compute the running-cost pack for one equipment item.

    Read-only arithmetic over the stored purchase and usage fields; nothing is
    persisted. A missing equipment id returns 404.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request, farm_id, equipment_id):
        farm = self.get_farm()
        item = FarmerEquipment.objects.filter(farm=farm, pk=equipment_id).first()
        if item is None:
            return self.respond_error([{"field": "equipment", "message": "Equipment not found."}], status_code=404)
        estimator = EquipmentOperatingCostEstimator()
        result = estimator.operating_cost_estimate(item)
        return self.respond(data=result, message="Operating cost estimate computed.")
