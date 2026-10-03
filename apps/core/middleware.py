"""Request metadata middleware; attaches a request_id and stamps the header."""
import re
import uuid

# A client-supplied X-Request-ID is echoed back only when it is safe to
# embed in logs/headers. Anything else is replaced by a server-generated id.
_SAFE_CLIENT_ID = re.compile(r"^[A-Za-z0-9._:-]{1,64}$")


class RequestIdMiddleware:
    """Attach ``request.request_id`` and set the ``X-Request-ID`` response header."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        client_id = request.headers.get("X-Request-ID")
        if client_id and isinstance(client_id, str) and _SAFE_CLIENT_ID.match(client_id):
            request.request_id = client_id
            request.client_request_id = client_id
        else:
            request.request_id = str(uuid.uuid4())
            request.client_request_id = None
        response = self.get_response(request)
        response["X-Request-ID"] = request.request_id
        return response