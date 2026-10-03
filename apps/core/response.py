"""Consistent API response envelope used by every endpoint.

Shape:
{
  "success": true,
  "message": "Human-readable message",
  "data": {},
  "meta": {"request_id": ..., "timestamp": ..., "version": "v1"},
  "errors": []
}
"""
import uuid
from datetime import datetime, timezone


def _request_id(request):
    if request is None:
        return str(uuid.uuid4())
    return getattr(request, "request_id", None) or str(uuid.uuid4())


def success_response(data=None, message="", request=None, meta=None):
    payload_meta = {
        "request_id": _request_id(request),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "version": "v1",
    }
    if meta:
        payload_meta.update(meta)
    return {
        "success": True,
        "message": message or "Request succeeded.",
        "data": data if data is not None else {},
        "meta": payload_meta,
        "errors": [],
    }


def error_response(errors, message="Request failed.", status_meta=None, request=None):
    return {
        "success": False,
        "message": message,
        "data": {},
        "meta": {
            "request_id": _request_id(request),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "version": "v1",
        },
        "errors": errors or [],
    }