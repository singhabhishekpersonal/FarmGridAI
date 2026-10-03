"""Safe, rate-limited HTTP client.

The client refuses to talk to any host that has not been explicitly approved
(as a :class:`DataSource` base URL) and refuses private/loopback targets. The
whole module is inert unless ``DATA_INGESTION_NETWORK_ALLOWED`` is enabled.
"""
import time
from dataclasses import dataclass, field
from urllib.parse import urlparse

import requests
from django.conf import settings

from apps.data_ingestion.services.urlutils import (
    UnsafeURL,
    hostname_allowed,
    validate_no_private_target,
    validate_scheme,
)


class NetworkDisabledError(Exception):
    """Raised when a network request is attempted while networking is off."""


class ResponseTooLarge(Exception):
    """Raised when a response exceeds the configured cap."""


def default_user_agent():
    contact = getattr(settings, "DATA_INGESTION_CONTACT_EMAIL", "") or "research-contact@example.invalid"
    return getattr(settings, "DATA_INGESTION_USER_AGENT", "").format(contact=contact)


@dataclass
class DomainRateLimiter:
    """Per-domain token bucket so we never outrun an approved source."""

    default_per_minute: int = 10

    def __post_init__(self):
        self._last_request = {}
        self._intervals = {}

    def wait(self, host):
        now = time.monotonic()
        interval = self._intervals.get(host)
        if interval is None:
            per_minute = self.default_per_minute or 10
            interval = 60.0 / max(1, per_minute)
            self._intervals[host] = interval
        last = self._last_request.get(host, 0.0)
        wait_for = max(0.0, last + interval - now)
        if wait_for:
            time.sleep(wait_for)
        self._last_request[host] = time.monotonic()


@dataclass
class SafeHTTPClient:
    timeout: int = 15
    max_bytes: int = 25 * 1024 * 1024
    max_redirects: int = 3
    resolve_hosts: bool = False
    rate_limiter: DomainRateLimiter = field(default_factory=DomainRateLimiter)
    network_allowed: bool | None = None

    def __post_init__(self):
        if self.network_allowed is None:
            self.network_allowed = bool(getattr(settings, "DATA_INGESTION_NETWORK_ALLOWED", False))
        if self.timeout is None:
            self.timeout = getattr(settings, "DATA_INGESTION_DEFAULT_HTTP_TIMEOUT_SECONDS", 15)

    def _assert_network(self):
        if not self.network_allowed:
            raise NetworkDisabledError(
                "Network access is disabled (DATA_INGESTION_NETWORK_ALLOWED is false). "
                "Connectivity is only ever enabled for an approved source during a single run."
            )

    def _validate_target(self, url, allowed_hosts=None):
        validate_scheme(url)
        validate_no_private_target(url, resolve=self.resolve_hosts)
        if allowed_hosts:
            # Entries may be full URLs or bare hostnames; normalize before
            # comparing so an approved `source.base_url` matches its host.
            hostname_allowed(url, allowed_hosts)

    def get(self, url, *, allowed_hosts=None, headers=None, timeout=None):
        """GET ``url`` returning ``(final_url, status_code, content_bytes, response_headers)``."""
        self._assert_network()
        self._validate_target(url, allowed_hosts=allowed_hosts)
        if urlparse(url).hostname:
            self.rate_limiter.wait(urlparse(url).hostname)

        session = requests.Session()
        req_headers = {"User-Agent": default_user_agent()}
        req_headers.update(headers or {})
        final_url = url

        for _ in range(self.max_redirects + 1):
            with session.get(
                final_url,
                headers=req_headers,
                timeout=timeout or self.timeout,
                stream=True,
                allow_redirects=False,
            ) as resp:
                if resp.status_code in (301, 302, 303, 307, 308) and resp.headers.get("Location"):
                    final_url = resp.headers["Location"]
                    if not final_url.startswith(("http://", "https://")):
                        raise UnsafeURL("Redirect Location is not an absolute http(s) URL")
                    # Validate the redirect destination BEFORE following it, so a
                    # redirect can never carry us to a disallowed/private host.
                    self._validate_target(final_url, allowed_hosts=allowed_hosts)
                    continue
                self._validate_target(final_url, allowed_hosts=allowed_hosts)
                content_length = resp.headers.get("Content-Length")
                try:
                    length_int = int(content_length) if content_length else None
                except ValueError as exc:
                    raise ResponseTooLarge(f"Invalid Content-Length header: {content_length!r}") from exc
                if length_int is not None and length_int > self.max_bytes:
                    raise ResponseTooLarge(f"Content-Length {content_length} exceeds cap")
                chunks = []
                size = 0
                for chunk in resp.iter_content(chunk_size=1 << 20):
                    size += len(chunk)
                    if size > self.max_bytes:
                        raise ResponseTooLarge(f"Response exceeded cap of {self.max_bytes} bytes")
                    chunks.append(chunk)
                return final_url, resp.status_code, b"".join(chunks), dict(resp.headers)

        raise UnsafeURL("Too many redirects")