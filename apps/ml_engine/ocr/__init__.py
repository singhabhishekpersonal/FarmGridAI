"""Optical character recognition for equipment nameplates / plates.

OCR is heuristic evidence only. Providers are pluggable; ``pytesseract`` is
used when installed (it is not by default), otherwise an empty extraction is
returned with a low-confidence flag.
"""
try:
    import pytesseract  # type: ignore

    _HAVE_TESSERACT = True
except Exception:  # pragma: no cover
    _HAVE_TESSERACT = False


def extract_text(image_file, provider="auto"):
    """Return dict with raw_text, brand/model candidates, confidence, error."""
    if provider == "auto":
        provider = "pytesseract" if _HAVE_TESSERACT else "heuristic"
    try:
        image_file.seek(0)
        if not _HAVE_TESSERACT:
            return {
                "provider": "heuristic",
                "raw_text": "",
                "brand_candidates": [],
                "model_candidates": [],
                "confidence": 0.0,
                "needs_user_confirmation": True,
                "error": "No OCR engine installed; enter brand/model manually.",
            }
        from PIL import Image

        raw = pytesseract.image_to_string(Image.open(image_file))
        lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
        return {
            "provider": "pytesseract",
            "raw_text": raw.strip(),
            "brand_candidates": lines[:4],
            "model_candidates": lines[4:16],
            "confidence": 0.5,
            "needs_user_confirmation": True,
            "error": "",
        }
    except Exception as exc:  # pragma: no cover
        return {
            "provider": "heuristic",
            "raw_text": "",
            "brand_candidates": [],
            "model_candidates": [],
            "confidence": 0.0,
            "needs_user_confirmation": True,
            "error": f"OCR failed: {exc}",
        }


def matches_catalog(candidates, catalog):
    """Best-effort string match of OCR tokens against a catalog record."""
    if not candidates or not catalog:
        return False, 0.0, ""
    tokens = catalog.brand.lower().split() + catalog.model.lower().split()
    for candidate in candidates:
        hay = " ".join(candidate.lower().split())
        if not hay:
            continue
        for token in tokens:
            if token and token in hay:
                return True, 0.7, candidate
    return False, 0.0, ""