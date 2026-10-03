"""Record-level validation for extracted data.

The validation rules encode the project's data-safety boundary: reject slots
that carry personal data (Aadhaar / phone / name / address / credentials),
reject values the platform must never fabricate (unknown subsidy amounts),
and prefer every financial figure to carry an explicit ``is_estimate`` +
``source_url`` so downstream systems always know the provenance.
"""
from urllib.parse import urlparse

_HARD_PII_KEYS = {
    "aadhaar", "aadhar", "pan", "password", "token", "otp", "credential",
    "secret", "account", "bank_acct", "bank_account", "ifsc", "upi",
}

_SOFT_PII_KEYS = {
    "phone", "mobile", "contact", "email", "address", "pincode", "postal_code",
    "pin_code", "name", "full_name", "dob",
}

_BENCHMARK_REQUIRED = {"indicator", "value", "source_url"}
_SCHEME_REQUIRED = {"name", "status", "source_url"}

_APPROVED_PREFIXES = ("http://", "https://")


def _flag_pii(payload):
    keys = {str(k).lower() for k in (payload or {})}
    return (sorted(keys & _HARD_PII_KEYS), sorted(keys & _SOFT_PII_KEYS))


def _validate_url(value, key="source_url"):
    if not value:
        return f"missing {key}"
    if not isinstance(value, str) or not value.startswith(_APPROVED_PREFIXES):
        return f"{key} must be an http(s) absolute URL"
    parsed = urlparse(value)
    if not parsed.netloc:
        return f"{key} has no host"
    return ""


def _validate_numeric_keys(payload, keys):
    problems = []
    for key in keys:
        value = payload.get(key)
        if value is None:
            continue
        candidate = float(value)
        if candidate < 0:
            problems.append(f"{key} must be >= 0")
    return problems


def validate_extracted_record_payload(record_type, payload):
    """Return ``{"ok": bool, "errors": [...], "warnings": [...]}``."""
    payload = payload or {}
    errors, warnings = [], []

    hard_pii, soft_pii = _flag_pii(payload)
    if hard_pii:
        errors.append(f"payload contains hard personal/credential keys: {hard_pii}")
    if soft_pii:
        warnings.append(f"payload contains soft personal-contact keys: {soft_pii}")

    if record_type == "scheme":
        missing = _SCHEME_REQUIRED - set(payload)
        if missing:
            errors.append(f"missing required fields: {sorted(missing)}")
        if payload.get("status") not in {None, "preliminary", "active", "closed", "unknown"}:
            warnings.append(f"unexpected scheme status {payload.get('status')!r}")
        if "needs_official_verification" not in payload:
            warnings.append("government scheme record missing needs_official_verification flag")
        if payload.get("benefit_amount") is not None and payload.get("is_estimate") is not True:
            warnings.append("benefit_amount present without is_estimate=true")

    if record_type in {"crop_benchmark", "energy_benchmark", "diesel_benchmark", "machinery_benchmark", "subsidy_benchmark"}:
        missing = _BENCHMARK_REQUIRED - set(payload)
        if missing:
            errors.append(f"missing required fields: {sorted(missing)}")
        errors.extend(_validate_numeric_keys(payload, ["value", "low", "high"]))

    if record_type == "equipment_image":
        if not payload.get("image_url"):
            errors.append("equipment_image payload requires image_url")

    for key in ("source_url", "official_url"):
        if key in payload:
            problem = _validate_url(payload[key], key)
            if problem:
                errors.append(problem)

    forbidden = {"source_code", "exec", "eval"}
    if forbidden & set(payload):
        errors.append("payload must never contain executable content")

    return {"ok": not errors, "errors": errors, "warnings": warnings}


def validate_image_compare_data(metadata):
    """Safety net for image metadata: never carry PII or absolute user paths."""
    if not isinstance(metadata, dict):
        return "metadata must be a mapping"
    hard_pii, soft_pii = _flag_pii(metadata)
    if hard_pii or soft_pii:
        return f"metadata contains personal keys: {hard_pii + soft_pii}"
    if metadata.get("original_name") and "/" in str(metadata.get("original_name")):
        return "original_name must not contain path separators"
    return ""


def build_validation_result(result):
    result = result or {}
    return {
        "ok": bool(result.get("ok")),
        "errors": result.get("errors", []),
        "warnings": result.get("warnings", []),
    }