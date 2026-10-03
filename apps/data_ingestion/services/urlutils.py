"""URL safety + network-reputation helpers for web collection.

Everything that performs a network request goes through this module first.
The rules here encode the project's hard compliance boundary:

* only ``http``/``https`` schemes,
* the request target must belong to an explicitly approved host,
* private / loopback / link-local / reserved addresses are never contacted
  (we refuse IP literals immediately, and refuse localhost hostnames; real
  DNS resolution for FQDNs is optional and off by default).
"""
import ipaddress
import re
import socket
from urllib.parse import urlparse

from django.conf import settings


class UnsafeURL(Exception):
    """Raised when a URL fails a safety gate."""


def _public_ip_addresses(host):
    if not host:
        return []
    return [addr for addr in host.split(",") if addr.strip()]


def _is_private_literal(host):
    """True if ``host`` is an IP literal on a private/reserved/loopback range."""
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        return False
    if addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved or addr.is_multicast:
        return True
    return False


_LOOPBACK_HOSTNAMES = {"localhost", "localhost.localdomain", "::1"}


def normalize_host(host):
    """Strip port + surrounding brackets for comparison."""
    host = (host or "").strip().lower().rstrip(".")
    if host.startswith("[") and host.endswith("]"):
        host = host[1:-1]
    return host.split(":")[0] if ":" in host else host


def is_loopback_hostname(host):
    return normalize_host(host) in _LOOPBACK_HOSTNAMES


def validate_scheme(url):
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise UnsafeURL(f"Unsupported URL scheme: {parsed.scheme!r}")
    return parsed


def _host_of(entry):
    """Extract a normalized hostname from a URL or a bare host string."""
    if "://" in (entry or ""):
        parsed = urlparse(entry)
        if parsed.hostname:
            return normalize_host(parsed.hostname)
        raise UnsafeURL(f"cannot interpret allowed host entry: {entry!r}")
    return normalize_host(entry)


def hostname_allowed(url, allowed_hosts):
    """True if the URL's host is in ``allowed_hosts`` (exact matches only).

    Entries may be full URLs (``https://approved.example/...``) or bare hosts
    (``approved.example``); either is normalized to a bare hostname.
    """
    parsed = validate_scheme(url)
    if not parsed.hostname:
        raise UnsafeURL("URL has no hostname")
    host = normalize_host(parsed.hostname)
    allowed = {_host_of(h) for h in allowed_hosts if h}
    if host not in allowed:
        raise UnsafeURL(f"Host {host!r} is not an approved source host")


def validate_no_private_target(url, resolve=False):
    """Raise :class:`UnsafeURL` if the target resolves to a private address.

    IP literals are checked directly (no network). For hostnames, DNS
    resolution is only performed when ``resolve=True`` so that offline code
    paths (and tests) never hit the network.
    """
    parsed = validate_scheme(url)
    host = parsed.hostname or ""
    if _is_private_literal(host) or is_loopback_hostname(host):
        raise UnsafeURL(f"Refusing to contact private/loopback host: {host!r}")
    if not resolve:
        return
    try:
        infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise UnsafeURL(f"Could not resolve host {host!r}: {exc}") from exc
    for info in infos:
        candidate = info[4][0]
        if _is_private_literal(candidate):
            raise UnsafeURL(f"Host {host!r} resolves to blocked address {candidate!r}")


def validate_target_url(url, allowed_hosts=None, resolve=False):
    """Full pre-request gate. Returns the normalized parsed URL on success."""
    parsed = validate_scheme(url)
    if not parsed.hostname:
        raise UnsafeURL("URL has no hostname")
    validate_no_private_target(url, resolve=resolve)
    if allowed_hosts:
        hostname_allowed(url, allowed_hosts)
    return parsed


def is_blob_or_data_url(url):
    return url.lower().startswith(("data:", "blob:"))


def safe_filename_component(value):
    """Single-line filename-safe token from an arbitrary string."""
    value = re.sub(r"[^A-Za-z0-9._-]+", "_", str(value))
    return value[:120] or "unnamed"


def default_network_allowed():
    return bool(getattr(settings, "DATA_INGESTION_NETWORK_ALLOWED", False))


def public_addresses(host):
    """Resolve a hostname to its public addresses (empty when refusal is certain)."""
    return _public_ip_addresses(host)