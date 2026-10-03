"""API views for the crops app."""
from rest_framework.permissions import IsAuthenticated

from apps.api.mixins import ApiResponseMixin, FarmAccessMixin
from apps.crops.models import Crop, FarmCrop
from apps.crops.serializers import CropSerializer, FarmCropSerializer
from apps.crops.services import CropCostEstimationService, estimate_farm_crops


class CropCatalogView(ApiResponseMixin, FarmAccessMixin):
    """The reference crop catalog, searchable by name.

    Only active crops are listed; ``search`` is a case-insensitive substring
    match on the crop name."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        crops = Crop.objects.filter(is_active=True)
        search = request.query_params.get("search")
        if search:
            crops = crops.filter(name__icontains=search)
        return self.respond(data=CropSerializer(crops, many=True).data, message="Crop catalog retrieved.")


class FarmCropListView(ApiResponseMixin, FarmAccessMixin):
    """Crops sown on one farm, and adding a crop to it.

    The farm comes from the URL, so a posted crop can never be attached to a
    farm the caller does not own."""

    permission_classes = [IsAuthenticated]

    def get(self, request, farm_id):
        farm = self.get_farm()
        return self.respond(data=FarmCropSerializer(farm.crops.all(), many=True).data, message="Farm crops retrieved.")

    def post(self, request, farm_id):
        farm = self.get_farm()
        serializer = FarmCropSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save(farm=farm, created_by=request.user)
        return self.respond(data=serializer.data, message="Farm crop created.", status_code=201)


class FarmCropEstimateView(ApiResponseMixin, FarmAccessMixin):
    """Cultivation cost estimates for every crop on a farm, optionally by year.

    Aggregates per-input benchmark ranges across the farm's crops and rewrites
    the stored ``CropInputEstimate`` rows as it goes; the optional ``year``
    query param narrows which crops are estimated."""

    permission_classes = [IsAuthenticated]

    def get(self, request, farm_id):
        farm = self.get_farm()
        year = request.query_params.get("year")
        if year:
            year = int(year)
        result = estimate_farm_crops(farm.id, year=year)
        return self.respond(data=result, message="Crop cost estimates computed.")


class FarmCropEstimateDetailView(ApiResponseMixin, FarmAccessMixin):
    """Cost estimate for a single farm crop, broken down by input type.

    Estimating replaces that crop's stored ``CropInputEstimate`` rows, so
    calling it is a write rather than a pure read. A crop id outside this farm
    returns a 404 error envelope."""

    permission_classes = [IsAuthenticated]

    def post(self, request, farm_id, crop_id):
        farm = self.get_farm()
        farm_crop = FarmCrop.objects.filter(farm=farm, pk=crop_id).first()
        if farm_crop is None:
            return self.respond_error([{"field": None, "message": "Farm crop not found."}], status_code=404)
        service = CropCostEstimationService()
        result = service.estimate_farm_crop(farm_crop)
        return self.respond(data=result, message="Farm crop estimate computed.")