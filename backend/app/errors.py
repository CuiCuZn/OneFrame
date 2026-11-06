"""Domain errors shared by adapters, router and API layer."""

from __future__ import annotations


class AppError(Exception):
    status_code = 400
    code = "app_error"

    def __init__(self, message: str, *, detail: dict | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.detail = detail or {}


class NotFound(AppError):
    status_code = 404
    code = "not_found"


class Conflict(AppError):
    status_code = 409
    code = "conflict"


class Unsupported(AppError):
    """Capability or parameter mismatch; never worth failing over."""

    status_code = 422
    code = "unsupported"


class ProviderError(AppError):
    """Upstream failure.

    ``kind`` drives routing decisions:
      auth / quota / params  -> retry another key or route
      network                -> ambiguous, never replay automatically
      upstream               -> route-level failure, may fail over before submit
      content                -> request rejected, do not retry
    """

    status_code = 502
    code = "provider_error"

    def __init__(
        self,
        message: str,
        *,
        kind: str = "upstream",
        status: int | None = None,
        retryable: bool = True,
        ambiguous: bool = False,
        detail: dict | None = None,
    ) -> None:
        super().__init__(message, detail=detail)
        self.kind = kind
        self.status = status
        self.retryable = retryable
        self.ambiguous = ambiguous
