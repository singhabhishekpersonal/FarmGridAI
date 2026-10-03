"""Per-image validation checks used before any collected image is accepted.

Applies the project's image-quality gates: MIME/extension allow-list, size
cap, PIL decode, minimum dimension, orientation normalization, EXIF strip,
blur/dark/bright detection, perceptual-hash generation, and best-effort
UI/icon/text-heavy detection. Returns a flat dict plus a validation status.
"""
import io
import re

from PIL import Image, ImageStat, UnidentifiedImageError

from apps.data_ingestion.models import CollectedArtifact
from apps.data_ingestion.services.deduplication import dhash
from apps.data_ingestion.services.hashing import sha256_of_bytes

_MIME_BY_FORMAT = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp"}
_ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP"}


class ImageValidationError(Exception):
    pass


def validate_image(data, *, filename="", max_bytes=None, min_dimension=None, allowed_mimes=None, allowed_extensions=None):
    """Validate raw image bytes. Returns a status dict (never raises).

    Result keys: sha256, format, mime_type, file_size, width, height,
    min_dimension_ok, blur_score, dark_bright, phash, orientation_note,
    ui_or_icon_like, text_heavy_like, status (from CollectedArtifact choices),
    errors (list).
    """
    result = {
        "sha256": "",
        "format": "",
        "mime_type": "",
        "file_size": len(data),
        "width": 0,
        "height": 0,
        "min_dimension_ok": False,
        "blur_score": 0.0,
        "dark_bright": "ok",
        "phash": 0,
        "orientation_note": "",
        "ui_or_icon_like": False,
        "text_heavy_like": False,
        "status": CollectedArtifact.ValidationStatus.VALID,
        "errors": [],
    }
    if len(data) == 0:
        result["status"] = CollectedArtifact.ValidationStatus.INVALID
        result["errors"].append("empty image payload")
        return result

    result["sha256"] = sha256_of_bytes(data)

    if max_bytes and len(data) > max_bytes:
        result["status"] = CollectedArtifact.ValidationStatus.INVALID
        result["errors"].append("file size exceeds cap")
        return result

    ext = _extension(filename)
    if allowed_extensions and ext and ext not in allowed_extensions:
        result["status"] = CollectedArtifact.ValidationStatus.INVALID
        result["errors"].append(f"extension {ext!r} not allowed")

    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except UnidentifiedImageError as exc:
        result["status"] = CollectedArtifact.ValidationStatus.INVALID
        result["errors"].append(f"undecodable image: {exc}")
        return result

    result["format"] = (img.format or "").upper()
    result["mime_type"] = _MIME_BY_FORMAT.get(result["format"], result["format"].lower())
    if result["format"] not in _ALLOWED_FORMATS:
        result["status"] = CollectedArtifact.ValidationStatus.INVALID
        result["errors"].append(f"unsupported format {result['format']!r}")
        return result
    if allowed_mimes and result["mime_type"] not in allowed_mimes:
        result["status"] = CollectedArtifact.ValidationStatus.INVALID
        result["errors"].append(f"mime type {result['mime_type']!r} not allowed")

    orientation = _exif_orientation(img)
    if orientation and orientation != 1:
        img = _apply_exif_orientation(img, orientation)
        result["orientation_note"] = f"normalized EXIF orientation {orientation} -> 1"

    width, height = img.size
    result["width"], result["height"] = width, height
    min_dimension = min_dimension or 1
    result["min_dimension_ok"] = min(width, height) >= min_dimension
    if not result["min_dimension_ok"]:
        result["status"] = CollectedArtifact.ValidationStatus.INVALID
        result["errors"].append(f"image smaller than {min_dimension}px minimum dimension")

    gray = img.convert("L").resize((64, 64))
    result["blur_score"] = _variance_of_laplacian(gray)
    result["dark_bright"] = _dark_bright(gray)
    result["phash"] = dhash(img)
    result["ui_or_icon_like"] = _ui_or_icon_like(img, width, height)
    result["text_heavy_like"] = _text_heavy_like(img)

    if result["blur_score"] < 10:
        if result["status"] == CollectedArtifact.ValidationStatus.VALID:
            result["status"] = CollectedArtifact.ValidationStatus.REVIEW
        result["errors"].append(f"blurry image (variance {result['blur_score']:.1f})")
    if result["dark_bright"] != "ok":
        if result["status"] == CollectedArtifact.ValidationStatus.VALID:
            result["status"] = CollectedArtifact.ValidationStatus.REVIEW
        result["errors"].append(f"bad exposure ({result['dark_bright']})")

    return result


def _extension(filename):
    match = re.search(r"\.([A-Za-z0-9]+)$", filename or "")
    return "." + match.group(1).lower() if match else ""


def _exif_orientation(img):
    try:
        exif = img.getexif()
        return int(exif.get(0x0112, 1))
    except Exception:  # noqa: BLE001
        return 1


def _apply_exif_orientation(img, orientation):
    transforms = {
        2: getattr(Image.Transpose, "FLIP_LEFT_RIGHT", None) or 1,
        3: getattr(Image.Transpose, "ROTATE_180", None) or 4,
        4: getattr(Image.Transpose, "FLIP_TOP_BOTTOM", None) or 2,
        5: getattr(Image.Transpose, "TRANSPOSE", None) or 3,
        6: getattr(Image.Transpose, "ROTATE_270", None) or 5,
        7: getattr(Image.Transpose, "TRANSVERSE", None) or 6,
        8: getattr(Image.Transpose, "ROTATE_90", None) or 7,
    }
    op = transforms.get(orientation)
    return img.transpose(op) if op is not None else img


def _variance_of_laplacian(gray):
    import numpy as np

    arr = np.asarray(gray, dtype=np.float32)
    laplacian = (
        -4 * arr[1:-1, 1:-1]
        + arr[:-2, 1:-1]
        + arr[2:, 1:-1]
        + arr[1:-1, :-2]
        + arr[1:-1, 2:]
    )
    return float(np.var(laplacian))


def _dark_bright(gray):
    mean = float(ImageStat.Stat(gray).mean[0])
    if mean < 24:
        return "too_dark"
    if mean > 235:
        return "too_bright"
    return "ok"


def _ui_or_icon_like(img, width, height):
    """Best-effort heuristic for UI screenshots / icons (flat majority color)."""
    if min(width, height) < 8:
        return True
    small = img.convert("RGB").resize((32, 32))
    colors = small.getcolors(32 * 32)
    if not colors:
        return False
    colors = sorted(colors, reverse=True)
    max_color_fraction = colors[0][0] / (32 * 32)
    return max_color_fraction > 0.85


def _text_heavy_like(img):
    """Very crude edge-layout heuristic; flagged as text-heavy-like."""
    small = img.convert("L").resize((48, 48))
    import numpy as np

    arr = np.asarray(small, dtype=np.float32)
    edges = np.abs(np.diff(arr, axis=0)) > 30
    return bool(float(edges.mean()) > 0.35)