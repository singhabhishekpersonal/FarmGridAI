"""Terms-of-service retrieval and review flags.

Terms cannot be legally evaluated by code — we can only fetch and preserve
them, then require manual review before collection is permitted (except for
sources that are manual-import-only, where no automated collection occurs).
"""
import re
from dataclasses import dataclass

from apps.data_ingestion.services.urlutils import validate_scheme


@dataclass
class TermsDecision:
    retrieved: bool
    manual_review_required: bool
    url: str = ""
    note: str = ""


_SENSITIVE_HINTS = (
    "crawl",
    "scrape",
    "scraping",
    "automated",
    "robot",
    "bot",
    "do not copy",
    "no commercial",
    "all rights reserved",
    "prohibited",
)


def detect_restrictive_hints(text):
    """Very conservative hint flags; never an authorization to collect."""
    lowered = text.lower()
    return [h for h in _SENSITIVE_HINTS if h in lowered]


def evaluate_terms(content, terms_url):
    """Evaluate fetched terms content.

    Returns :class:`TermsDecision`. The default remains *manual review*:
    presence of restrictive language or of no terms at all both force review.
    """
    validate_scheme(terms_url)
    if not content:
        return TermsDecision(retrieved=False, manual_review_required=True, url=terms_url, note="No terms content retrieved.")
    hints = detect_restrictive_hints(content)
    if hints:
        return TermsDecision(
            retrieved=True,
            manual_review_required=True,
            url=terms_url,
            note=f"Restrictive language hints present: {hints}",
        )
    return TermsDecision(retrieved=True, manual_review_required=False, url=terms_url, note="No restrictive hints detected (manual review still recommended).")