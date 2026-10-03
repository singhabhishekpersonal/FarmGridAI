"""Central DRF exception handler producing the standard response envelope."""
import logging

from django.core.exceptions import ObjectDoesNotExist, PermissionDenied, ValidationError as DjangoValidationError
from django.http import Http404
from rest_framework import exceptions as drf_exc
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_default_exception_handler

from apps.core.response import error_response

logger = logging.getLogger("FarmGrid")


def _flat_errors(detail):
    """Flatten DRF validation detail into a list of error dicts."""
    if detail is None:
        return []
    if isinstance(detail, dict):
        items = []
        for key, value in detail.items():
            if isinstance(value, (list, tuple)):
                for item in value:
                    items.append({"field": key, "message": str(item)})
            else:
                items.append({"field": key, "message": str(value)})
        return items
    if isinstance(detail, (list, tuple)):
        return [{"field": None, "message": str(item)} for item in detail]
    return [{"field": None, "message": str(detail)}]


def api_exception_handler(exc, context):
    """Wrap every exception in the standard {success,message,data,meta,errors} envelope."""
    response = drf_default_exception_handler(exc, context)

    if response is None:
        # Fall through: Django-level errors
        if isinstance(exc, Http404):
            return Response(error_response([{"field": None, "message": "Not found."}], "Resource not found.", request=context.get("request")), status=404)
        if isinstance(exc, PermissionDenied):
            return Response(error_response([{"field": None, "message": str(exc)}], "Permission denied.", request=context.get("request")), status=403)
        if isinstance(exc, DjangoValidationError):
            return Response(error_response(_flat_errors(exc.message_dict if hasattr(exc, "message_dict") else exc.messages), "Validation failed.", request=context.get("request")), status=400)
        logger.exception("Unhandled API exception", exc_info=exc)
        return Response(error_response([{"field": None, "message": "Internal server error."}], "Internal server error.", request=context.get("request")), status=500)

    status_code = response.status_code
    detail = response.data
    message = getattr(exc, "detail", "Request failed.")
    if isinstance(message, (dict, list)):
        message = "Request failed."
    return Response(error_response(_flat_errors(detail), str(message), request=context.get("request")), status=status_code)