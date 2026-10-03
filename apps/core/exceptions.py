"""Domain-level exceptions used across the platform.

These map to stable HTTP responses in ``apps.api.exceptions``.
"""


class FarmGridError(Exception):
    """Base exception for the application."""


class ConflictError(FarmGridError):
    """Request conflicts with existing state (e.g. duplicate consent)."""


class NotFoundError(FarmGridError):
    """Resource not found (already provided by DRF; kept for services)."""


class PermissionViolationError(FarmGridError):
    """User does not own / is not allowed to access the resource."""


class InsufficientDataError(FarmGridError):
    """Not enough information to produce a confident recommendation.

    Callers should return ``gather_more_information`` style outputs instead
    of fabricating data.
    """


class ValidationFailedError(FarmGridError):
    """Input validation failed in a service layer."""


class ModelUnavailableError(FarmGridError):
    """Requested ML model is unavailable; callers must use fallbacks."""