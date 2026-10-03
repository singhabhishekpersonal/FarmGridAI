"""API views for the energy app."""
from rest_framework import status
from rest_framework.permissions import IsAuthenticated

from apps.api.mixins import ApiResponseMixin, FarmAccessMixin
from apps.energy.models import PumpProfile, SolarSystemConfiguration
from apps.energy.serializers import (
    DieselPriceBenchmarkSerializer,
    EnergyTariffBenchmarkSerializer,
    PumpProfileSerializer,
    SolarAnalysisSerializer,
    SolarSystemConfigurationSerializer,
)
from apps.energy.services import EnergyAnalysisService


class PumpProfileView(ApiResponseMixin, FarmAccessMixin):
    """Read and save the farm's pump profile.

    GET returns the most recently created profile, the same row
    EnergyAnalysisService resolves as current, or a null data payload when
    none is saved yet. POST appends a new profile rather than updating in
    place, so history is kept.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, farm_id):
        farm = self.get_farm()
        # Same row EnergyAnalysisService.resolve_inputs reads, so the form and
        # the analytics cannot disagree about which profile is current.
        profile = farm.pump_profiles.order_by("-created_at").first()
        if profile is None:
            return self.respond(data=None, message="No pump profile saved yet.")
        return self.respond(data=PumpProfileSerializer(profile).data, message="Pump profile retrieved.")

    def post(self, request, farm_id):
        farm = self.get_farm()
        serializer = PumpProfileSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save(farm=farm, created_by=request.user)
        return self.respond(data=serializer.data, message="Pump profile saved.", status_code=status.HTTP_201_CREATED)


class SolarConfigurationView(ApiResponseMixin, FarmAccessMixin):
    """Read and save the farm's solar system configuration.

    GET returns the newest configuration, matching the row the analysis
    service uses, and returns a null payload when none exists. POST inserts a
    new row each time, so the latest save is the effective one.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, farm_id):
        farm = self.get_farm()
        # Mirror resolve_inputs' selection so the form edits the row in use.
        config = farm.solar_configurations.order_by("-created_at").first()
        if config is None:
            return self.respond(data=None, message="No solar configuration saved yet.")
        return self.respond(data=SolarSystemConfigurationSerializer(config).data, message="Solar configuration retrieved.")

    def post(self, request, farm_id):
        farm = self.get_farm()
        serializer = SolarSystemConfigurationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save(farm=farm, created_by=request.user)
        return self.respond(data=serializer.data, message="Solar configuration saved.", status_code=status.HTTP_201_CREATED)


class EnergyAnalyzeView(ApiResponseMixin, FarmAccessMixin):
    """Compute the grid, diesel and solar comparison for a farm.

    Derives its inputs from the saved pump and solar configuration rows and
    recomputes the 10-year projections on every call. persist=True stores the
    result as a new SolarAnalysis plus its per-year projection rows, so each
    invocation adds a record and returns its analysis_id.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request, farm_id):
        farm = self.get_farm()
        service = EnergyAnalysisService(farm)
        result = service.run_analysis(persist=True)
        return self.respond(data=result, message="Energy analysis computed and stored.")


class SolarComparisonView(ApiResponseMixin, FarmAccessMixin):
    """Preview the solar comparison without storing it.

    Identical inputs and calculations to the analyze view but persist=False,
    so a client can show the result before committing a SolarAnalysis row.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, farm_id):
        farm = self.get_farm()
        service = EnergyAnalysisService(farm)
        result = service.run_analysis(persist=False)
        return self.respond(data=result, message="Solar comparison computed.")


class EnergyProjectionView(ApiResponseMixin, FarmAccessMixin):
    """Return the year-by-year projection from the farm's last saved analysis.

    Read-only: it serves the newest SolarAnalysis and its projection rows
    rather than recomputing, and returns an empty projection instead of a 404
    when no analysis has been stored yet.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, farm_id):
        farm = self.get_farm()
        analysis = farm.solar_analyses.order_by("-created_at").first()
        if analysis is None:
            return self.respond(data={"projection": [], "message": "Run an analysis first."})
        return self.respond(data=SolarAnalysisSerializer(analysis).data, message="Solar projection.")


class TariffBenchmarkView(ApiResponseMixin, FarmAccessMixin):
    """Published electricity tariff benchmarks, optionally filtered by state.

    Only rows flagged is_verified are returned. The state filter is
    case-insensitive and omitted entirely when absent, so the whole verified
    table is returned uncapped.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        from apps.energy.models import EnergyTariffBenchmark

        qs = EnergyTariffBenchmark.objects.filter(is_verified=True)
        state = request.query_params.get("state")
        if state:
            qs = qs.filter(state__iexact=state)
        return self.respond(data=EnergyTariffBenchmarkSerializer(qs, many=True).data, message="Tariff benchmarks.")


class DieselPriceBenchmarkView(ApiResponseMixin, FarmAccessMixin):
    """Verified diesel price benchmarks.

    Filtered to is_verified rows and capped at 50, so this is a sample rather
    than the full table; it takes no farm_id and reads no farm data.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        from apps.energy.models import DieselPriceBenchmark

        qs = DieselPriceBenchmark.objects.filter(is_verified=True)
        return self.respond(data=DieselPriceBenchmarkSerializer(qs[:50], many=True).data, message="Diesel price benchmarks.")