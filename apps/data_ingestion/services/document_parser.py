"""Parsers for flat files: JSON, CSV, and text.

All parsers are pure (no network, no filesystem) — they accept ``bytes`` or
``str`` and return structured data. They never attempt JavaScript-heavy or
labelled-page extraction; sources requiring that are marked manual-review.
"""
import csv
import io
import json


class ParseError(Exception):
    pass


def parse_json(content):
    if isinstance(content, bytes):
        content = content.decode("utf-8", errors="replace")
    try:
        return json.loads(content)
    except (json.JSONDecodeError, TypeError) as exc:
        raise ParseError(f"invalid JSON: {exc}") from exc


def parse_csv(content):
    if isinstance(content, bytes):
        content = content.decode("utf-8", errors="replace")
    reader = csv.DictReader(io.StringIO(content))
    rows = list(reader)
    if not rows:
        raise ParseError("empty CSV")
    return rows


def parse_lines(content):
    if isinstance(content, bytes):
        content = content.decode("utf-8", errors="replace")
    return [line.strip() for line in content.splitlines() if line.strip()]


def detect_type_from_content(content):
    """Best-effort content-type detection for text payloads."""
    head = content[:512].lstrip()
    if head.startswith(b"{") or head.startswith(b"["):
        return "json"
    if b"," in head and any(b"\r\n" in content[:2048], b"\n" in content[:2048]):
        return "csv"
    return "text"