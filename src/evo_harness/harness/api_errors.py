from __future__ import annotations


class HarnessApiError(RuntimeError):
    """Base class for upstream API failures."""


class AuthenticationFailure(HarnessApiError):
    """Raised when the upstream service rejects the provided credentials."""


class RateLimitFailure(HarnessApiError):
    """Raised when the upstream service rejects the request due to rate limits."""


class RequestFailure(HarnessApiError):
    """Raised for generic request or transport failures."""


class ClientRequestFailure(RequestFailure):
    """Raised for non-retryable client-side request errors such as invalid payloads."""
