"""OpenAPI schema helpers.

Every endpoint in this project answers with the same envelope produced by
``apps.core.response.success_response``::

    {"success": bool, "message": str, "data": ..., "meta": {...}, "errors": [...]}

drf-spectacular cannot infer that from an ``APIView`` that builds its own
``Response``, so it reports "unable to guess serializer" for every route.

These helpers describe the envelope around a payload. They are built with
``inline_serializer`` because drf-spectacular only resolves serializers it meets
through the documented override slots -- an arbitrary nested serializer class
inside a hand-written dict is emitted verbatim and then fails YAML
serialisation.

``inline_serializer`` mints a *new* class on every call, and spectacular
complains when two same-named components have different identities. Every
serializer used here is therefore built exactly once, at import time, and reused.
"""
import re

from rest_framework import serializers
from drf_spectacular.utils import OpenApiResponse, extend_schema, inline_serializer

__all__ = [
    "envelope",
    "envelope_list",
    "error_envelope",
    "token_envelope",
    "token_pair",
    "extend_schema",
]


def _camel_to_snake(name):
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()


def _derive_name(data_field):
    """Stable component name for an envelope wrapping ``data_field``."""
    inner = getattr(data_field, "child", None) or data_field
    cls_name = getattr(inner, "__name__", None)
    if not cls_name:
        return None
    base = cls_name[: -len("Serializer")] if cls_name.endswith("Serializer") else cls_name
    kind = "list" if getattr(data_field, "many", False) else "item"
    return f"{_camel_to_snake(base or 'payload')}_{kind}_envelope"


def _build_envelope(component, data_field):
    return inline_serializer(
        name=component,
        fields={
            "success": serializers.BooleanField(help_text="Always true on a successful call."),
            "message": serializers.CharField(help_text="Human readable summary of the outcome."),
            "data": data_field,
            "meta": serializers.DictField(required=False, allow_null=True, help_text="Pagination and request metadata."),
            "errors": serializers.ListField(child=serializers.DictField(), required=False),
        },
    )


_TOKEN_PAIR = inline_serializer(
    name="TokenPair",
    fields={
        "access": serializers.CharField(),
        # Omitted by simplejwt when the token is not rotated.
        "refresh": serializers.CharField(required=False),
    },
)
_TOKEN_ENVELOPE = _build_envelope("token_pair_envelope", _TOKEN_PAIR)

_ERROR_ENVELOPE = inline_serializer(
    name="ApiErrorEnvelope",
    fields={
        "success": serializers.BooleanField(help_text="Always false."),
        "message": serializers.CharField(help_text="Human readable summary of the failure."),
        "data": serializers.DictField(required=False, allow_null=True),
        "errors": serializers.ListField(child=serializers.DictField(), required=False),
    },
)

_ENVELOPE_CACHE = {}


def envelope(data_field, name=None):
    """Describe the standard success envelope around ``data_field``.

    ``data_field`` is a serializer instance (optionally ``many=True``) or a field
    instance -- never a bare class. Pass ``name`` when the payload has no
    intrinsic component name to derive one from.
    """
    component = name or _derive_name(data_field) or "api_envelope"
    if component not in _ENVELOPE_CACHE:
        _ENVELOPE_CACHE[component] = _build_envelope(component, data_field)
    return OpenApiResponse(response=_ENVELOPE_CACHE[component], description="Standard API envelope.")


def envelope_list(serializer_class, name=None):
    """Describe the standard success envelope around a collection."""
    return envelope(serializer_class(many=True), name=name)


def token_envelope():
    """Describe the envelope used by the JWT issuing and refresh endpoints."""
    return OpenApiResponse(response=_TOKEN_ENVELOPE, description="Standard API envelope.")


def token_pair():
    """The shared ``{access, refresh}`` serializer, for nesting inside other payloads."""
    return _TOKEN_PAIR


def error_envelope(description="Request failed."):
    """Describe the standard error envelope."""
    return OpenApiResponse(response=_ERROR_ENVELOPE, description=description)