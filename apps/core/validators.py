"""Validation helpers for uploads, area inputs and general data safety."""
import io
import re

from django.conf import settings
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

INR_PATTERN = re.compile(r"^[0-9]+(\.[0-9]{1,2})?$")
PINCODE_PATTERN = re.compile(r"^[1-9][0-9]{5}$")
NAME_PATTERN = re.compile(r"^[A-Za-z][A-Za-z .'-]{1,80}$")
MODEL_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 .\\/_-]{1,80}$")


def validate_non_negative(value):
    if value is not None and value < 0:
        raise ValidationError(_("Value must be non-negative."))


def validate_positive(value):
    if value is not None and value <= 0:
        raise ValidationError(_("Value must be greater than zero."))


def validate_pincode(value):
    if value and not PINCODE_PATTERN.match(str(value)):
        raise ValidationError(_("Enter a valid 6-digit Indian pincode."))


def validate_money(value):
    if value is not None and not INR_PATTERN.match(str(value)):
        raise ValidationError(_("Invalid monetary amount."))


def validate_image_extension(name):
    ext = ""
    if "." in name:
        ext = name.rsplit(".", 1)[1].lower()
    if ext and f".{ext}" not in settings.ALLOWED_IMAGE_EXTENSIONS:
        raise ValidationError(_("Unsupported image format. Allowed: %s") % ", ".join(sorted(settings.ALLOWED_IMAGE_EXTENSIONS)))


def validate_document_extension(name):
    ext = ""
    if "." in name:
        ext = name.rsplit(".", 1)[1].lower()
    if ext and f".{ext}" not in settings.ALLOWED_BILL_EXTENSIONS:
        raise ValidationError(_("Unsupported document format. Allowed: %s") % ", ".join(sorted(settings.ALLOWED_BILL_EXTENSIONS)))


def validate_upload_file_size(upload):
    """Validate file size against settings.MAX_UPLOAD_FILE_SIZE_MB."""
    limit = settings.MAX_UPLOAD_FILE_SIZE_MB * 1024 * 1024
    if upload.size > limit:
        raise ValidationError(
            _("File too large. Maximum allowed size is %(size)s MB.") % {"size": settings.MAX_UPLOAD_FILE_SIZE_MB}
        )


def sniff_mime(content: bytes):
    """Best-effort MIME detection for image bytes using PIL (imghdr is gone in 3.13)."""
    try:
        from PIL import Image

        image = Image.open(io.BytesIO(content))
        fmt = (image.format or "").lower()
        aliases = {"jpg": "jpeg"}
        kind = aliases.get(fmt, fmt)
        mapping = {"jpeg": "image/jpeg", "png": "image/png", "gif": "image/gif", "webp": "image/webp"}
        return mapping.get(kind, "")
    except Exception:
        return ""


def validate_image_content(content: bytes):
    """Validate that bytes are a decodable, supported image."""
    if not content:
        raise ValidationError(_("Empty file upload."))
    try:
        from PIL import Image

        image = Image.open(io.BytesIO(content))
        image.load()
        if image.format and f"image/{image.format.lower()}" not in settings.ALLOWED_IMAGE_MIME_TYPES:
            raise ValidationError(_("Unsupported image MIME type."))
    except ValidationError:
        raise
    except Exception as exc:
        raise ValidationError(_("File is not a valid image.")) from exc


def reencode_image(content: bytes, max_size=(1024, 1024)) -> bytes:
    """Re-encode an image to strip metadata (privacy-safe sanitization)."""
    from PIL import Image, ImageOps

    image = Image.open(io.BytesIO(content))
    image = ImageOps.exif_transpose(image)
    image = image.convert("RGB")
    image.thumbnail(max_size, Image.Resampling.LANCZOS)
    out = io.BytesIO()
    image.save(out, format="JPEG", quality=85)
    return out.getvalue()