"""PDF text extraction.

Optional dependency guard: extraction works when ``pypdf`` is installed and
degrades to metadata-only otherwise. PDFs that cannot be parsed are routed to
manual review — we never guess their content.
"""


def _try_import_pypdf():
    try:
        import pypdf  # noqa: F401

        return pypdf
    except ImportError:
        return None


def extract_pdf(content):
    """Return ``{"text": str, "pages": int, "explicit_metadata": dict}``.

    Raises ``PdfExtractionUnavailable`` when no PDF library is installed.
    """
    pypdf = _try_import_pypdf()
    if pypdf is None:
        return {"text": "", "pages": 0, "explicit_metadata": {}, "engine": "none", "note": "pypdf not installed; manual review required"}
    reader = pypdf.PdfReader(io_bytes := _as_bytes(content))
    pages = len(reader.pages)
    text_parts = []
    for page in reader.pages:
        text_parts.append(page.extract_text() or "")
    text = "\n".join(text_parts)
    return {
        "text": text,
        "pages": pages,
        "explicit_metadata": {str(k): str(v) for k, v in (getattr(reader.metadata, "items", lambda: [])() or [])},
        "engine": "pypdf",
    }


def _as_bytes(content):
    import io

    if isinstance(content, bytes):
        return io.BytesIO(content)
    return io.BytesIO(content.read())