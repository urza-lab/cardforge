"""Shared exceptions for public-URL source adapters (Moxfield, Archidekt).
`AuthRequiredError` lives in app.security.ssrf_guard instead of here, since
it's about a security-relevant condition (don't bypass a login wall) rather
than an adapter implementation detail.
"""
from __future__ import annotations


class InvalidUrlError(ValueError):
    """The given URL doesn't look like a deck URL this adapter handles."""


class SourceFetchError(RuntimeError):
    """Network error, unexpected response shape, or any other failure to
    fetch/parse a deck that isn't specifically "blocked" (SsrfBlockedError)
    or "needs login" (AuthRequiredError).
    """
