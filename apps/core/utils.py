"""Shared utilities: money, dates, privacy, hashing, ids."""
import hashlib
import re
import uuid
from datetime import date, datetime

from django.utils import timezone

NUM_WORDS = ["", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine"]
LAKH = 100000
CRORE = 10000000


def format_inr(amount):
    """Format a number as Indian-style currency text (e.g. '2.4 Lakh').

    Returns an empty string for None.
    """
    if amount is None:
        return ""
    if abs(amount) >= CRORE:
        return f"{amount / CRORE:.2f} Crore"
    if abs(amount) >= LAKH:
        return f"{amount / LAKH:.2f} Lakh"
    return f"{amount:,.0f}"


def inr_text(amount):
    """Safe rounded INR label."""
    return format_inr(amount)


def current_year():
    return date.today().year


def iso_now():
    return timezone.now().isoformat()


def age_from_year(purchase_year, reference_year=None):
    reference_year = reference_year or current_year()
    if not purchase_year:
        return None
    return max(0, reference_year - int(purchase_year))


def short_uuid():
    return uuid.uuid4().hex[:12]


def content_hash(content: bytes) -> str:
    """SHA-256 hash of binary content - used for image input auditing."""
    return hashlib.sha256(content).hexdigest()


def stable_hash_string(value: str) -> str:
    return hashlib.sha256((value or "").encode("utf-8")).hexdigest()


def redact_phone(value):
    if not value:
        return ""
    value = re.sub(r"\D", "", value)
    if len(value) < 6:
        return "*" * len(value)
    return value[:2] + "*" * (len(value) - 4) + value[-2:]


def redact_email(value):
    if not value:
        return ""
    if "@" not in value:
        return "*"
    local, domain = value.split("@", 1)
    if len(local) <= 2:
        visible = local[0]
    else:
        visible = local[:2]
    return f"{visible}{'*' * max(0, len(local) - 2)}@{domain}"


def parse_iso(value):
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(value)
    except (ValueError, TypeError):
        return None


def weighted_average(pairs):
    """Weighted average of (value, weight) pairs, returning None if empty."""
    total_weight = sum(w for _v, w in pairs)
    if total_weight <= 0:
        return None
    return sum(v * w for v, w in pairs) / total_weight