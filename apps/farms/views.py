"""Farm API views."""
from rest_framework import status
from rest_framework.permissions import IsAuthenticated

from apps.api.mixins import ApiResponseMixin, FarmAccessMixin
from apps.core.units import UnitConversionService
from apps.farms.models import BighaConversionRule, FarmService
from apps.farms.serializers import (
    BighaConversionRuleSerializer,
    FarmCreateSerializer,
    FarmSerializer,
    LandParcelSerializer,
)
from drf_spectacular.utils import extend_schema


class FarmListCreateView(ApiResponseMixin, FarmAccessMixin):
    """List the farms owned by the caller, or register a new one.

    Reads are scoped by ``request.user.farms``, so no farm filter is accepted;
    creation delegates validation to ``FarmCreateSerializer``."""

    permission_classes = [IsAuthenticated]

    @extend_schema(operation_id="v1_farms_list")
    def get(self, request):
        farms = request.user.farms.all()
        return self.respond(data=FarmSerializer(farms, many=True).data, message="Farms retrieved.")

    def post(self, request):
        serializer = FarmCreateSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        farm = serializer.save(created_by=request.user)
        return self.respond(data=FarmSerializer(farm).data, message="Farm created.", status_code=status.HTTP_201_CREATED)


class FarmDetailView(ApiResponseMixin, FarmAccessMixin):
    """Read, patch or soft-delete a single farm the caller owns.

    ``delete`` is a soft delete: the row is removed from the default manager
    and only ``updated_by`` is stamped afterwards via ``all_objects``."""

    permission_classes = [IsAuthenticated]

    def get_object(self):
        return self.get_farm()

    def get(self, request, farm_id):
        return self.respond(data=FarmSerializer(self.get_object()).data, message="Farm retrieved.")

    def patch(self, request, farm_id):
        farm = self.get_object()
        serializer = FarmSerializer(farm, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save(updated_by=request.user)
        return self.respond(data=serializer.data, message="Farm updated.")

    def delete(self, request, farm_id):
        from apps.farms.models import Farm

        farm = self.get_object()
        farm.delete()
        Farm.all_objects.filter(pk=farm.pk).update(updated_by=request.user)
        return self.respond(data={}, message="Farm soft-deleted.", status_code=status.HTTP_200_OK)


class FarmLandParcelView(ApiResponseMixin, FarmAccessMixin):
    """The land parcels belonging to one farm, and parcel creation.

    Parcels are always created against the farm resolved from the URL rather
    than a farm id in the payload, so a farm cannot be written across."""

    permission_classes = [IsAuthenticated]

    def get(self, request, farm_id):
        farm = self.get_farm()
        return self.respond(data=LandParcelSerializer(farm.land_parcels.all(), many=True).data, message="Land parcels retrieved.")

    def post(self, request, farm_id):
        farm = self.get_farm()
        serializer = LandParcelSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save(farm=farm, created_by=request.user)
        return self.respond(data=serializer.data, message="Land parcel created.", status_code=status.HTTP_201_CREATED)


class FarmSummaryView(ApiResponseMixin, FarmAccessMixin):
    """Rolled-up view of one farm: parcel count, totals and location.

    Hectares are summed from the parcels and echoed in acres, and parcels still
    flagged ``area_requires_confirmation`` are listed by id."""

    permission_classes = [IsAuthenticated]

    def get(self, request, farm_id):
        farm = self.get_farm()
        return self.respond(data=FarmService.summary(farm), message="Farm summary.")


class LandUnitConvertView(ApiResponseMixin, FarmAccessMixin):
    """Convert land area: POST /api/v1/land-units/convert/"""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        value = request.data.get("value")
        unit = request.data.get("unit")
        state = request.data.get("state", "")
        district = request.data.get("district", "")
        if value is None or unit is None:
            return self.respond_error([{"field": None, "message": "value and unit are required."}])

        rule = None
        if unit == "bigha":
            rule = (
                BighaConversionRule.objects.filter(state__iexact=state if state else "unknown")
                .order_by("-is_verified", "-last_verified_at")
                .first()
            )
            if not rule and district:
                rule = BighaConversionRule.objects.filter(state__iexact=state, district__iexact=district).first()

        try:
            result = UnitConversionService().to_hectares(float(value), unit, rule=rule, state=state, district=district)
        except ValueError as exc:
            return self.respond_error([{"field": "unit", "message": str(exc)}])
        return self.respond(data={"result": result}, message="Conversion computed.")


class BighaRuleListView(ApiResponseMixin, FarmAccessMixin):
    """Verified bigha-to-hectare conversion rules, optionally by state.

    Only ``is_verified`` rows are exposed so unverified seed data never reaches
    the client; the optional ``state`` filter is case-insensitive."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        rules = BighaConversionRule.objects.filter(is_verified=True)
        state = request.query_params.get("state")
        if state:
            rules = rules.filter(state__iexact=state)
        return self.respond(data=BighaConversionRuleSerializer(rules, many=True).data, message="Bigha conversion rules.")
