"""API views for the subsidies app."""
from rest_framework.permissions import IsAuthenticated

from apps.api.mixins import ApiResponseMixin, FarmAccessMixin
from apps.subsidies.models import FarmerSchemeMatch, SubsidyScheme
from apps.subsidies.serializers import (
    FarmerSchemeMatchSerializer,
    SchemeApplicationChecklistSerializer,
    SubsidySchemeSerializer,
)
from apps.subsidies.services import SchemeEligibilityEngine
from drf_spectacular.utils import extend_schema


class SubsidySchemeListView(ApiResponseMixin, FarmAccessMixin):
    """Browse active subsidy schemes, filterable by category and state.

    Only ``is_active`` schemes are listed; eligibility is not evaluated here."""

    permission_classes = [IsAuthenticated]

    @extend_schema(operation_id="v1_subsidies_list")
    def get(self, request):
        qs = SubsidyScheme.objects.filter(is_active=True)
        category = request.query_params.get("category")
        state = request.query_params.get("state")
        if category:
            qs = qs.filter(category=category)
        if state:
            qs = qs.filter(state__iexact=state)
        return self.respond(data=SubsidySchemeSerializer(qs, many=True).data, message="Scheme list (preliminary, verify officially).")


class SubsidySchemeDetailView(ApiResponseMixin, FarmAccessMixin):
    """Full record for a single scheme, including inactive ones.

    A missing id is reported as a 404 error envelope rather than raised."""

    permission_classes = [IsAuthenticated]

    def get(self, request, scheme_id):
        scheme = SubsidyScheme.objects.filter(pk=scheme_id).first()
        if scheme is None:
            return self.respond_error([{"field": None, "message": "Scheme not found."}], status_code=404)
        return self.respond(data=SubsidySchemeSerializer(scheme).data, message="Scheme detail.")


class SubsidyMatchView(ApiResponseMixin, FarmAccessMixin):
    """Run the eligibility engine against one farm and persist the matches.

    This is a write: ``run_match`` upserts ``FarmerSchemeMatch`` rows, which
    the recommendations and checklist views then read back."""

    permission_classes = [IsAuthenticated]

    def post(self, request, farm_id):
        farm = self.get_farm()
        interest = request.data.get("category")
        engine = SchemeEligibilityEngine(farm)
        result = engine.run_match(interest_category=interest, persist=True)
        return self.respond(data=result, message="Preliminary scheme matching completed.")


class SubsidyRecommendationsView(ApiResponseMixin, FarmAccessMixin):
    """Schemes previously matched to this farm, with match reasons.

    Reads the stored matches instead of re-running the engine, so it is empty
    until ``SubsidyMatchView`` has been called for the farm."""

    permission_classes = [IsAuthenticated]

    def get(self, request, farm_id):
        farm = self.get_farm()
        matches = FarmerSchemeMatch.objects.filter(farm=farm, matched=True).select_related("scheme")
        return self.respond(data=FarmerSchemeMatchSerializer(matches, many=True).data, message="Matched schemes (verify officially).")


class SubsidyChecklistView(ApiResponseMixin, FarmAccessMixin):
    """Flattened document checklists for every matched scheme on a farm.

    Each row is prefixed with its ``match_id`` and scheme name so the client
    can group documents without a second request."""

    permission_classes = [IsAuthenticated]

    def get(self, request, farm_id):
        farm = self.get_farm()
        lists = []
        for match in FarmerSchemeMatch.objects.filter(farm=farm, matched=True).prefetch_related("checklists"):
            for checklist in match.checklists.all():
                lists.append(
                    {
                        "match_id": str(match.pk),
                        "scheme": match.scheme.name,
                        **SchemeApplicationChecklistSerializer(checklist).data,
                    }
                )
        return self.respond(data=lists, message="Application checklists.")
