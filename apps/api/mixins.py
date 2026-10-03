"""Shared API view mixins for consistent response wrapping."""
from django.http import Http404
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.response import error_response, success_response


class ApiResponseMixin(APIView):
    """Mixin that renders standard envelopes from view result dictionaries.

    Subclasses ``APIView`` so every consumer gets ``as_view()``, ``dispatch``
    and ``permission_classes`` for free.

    Views/methods returning a regular DRF Response bypass the envelope.
    """

    def respond(self, data=None, message="", status_code=status.HTTP_200_OK, meta=None, request=None):
        return Response(
            success_response(data=data, message=message, request=request or getattr(self, "request", None), meta=meta),
            status=status_code,
        )

    def respond_error(self, errors, message="Request failed.", status_code=status.HTTP_400_BAD_REQUEST):
        return Response(error_response(errors, message, request=getattr(self, "request", None)), status=status_code)


class FarmAccessMixin:
    """Resolve and validate ownership of a farm referenced in the URL.

    Any view using this mixin must either set ``farm_lookup`` or accept a
    ``farm_id`` kwarg from the router.
    """

    farm_lookup = "farm_id"

    def get_farm(self):
        from apps.farms.models import Farm

        pk = self.kwargs.get(self.farm_lookup)
        if not pk:
            raise Http404("Farm identifier missing.")
        farm = Farm.objects.filter(pk=pk, user=self.request.user).first()
        if farm is None:
            raise Http404("Farm not found.")
        return farm