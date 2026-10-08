"""Shared HTTPS settings for outgoing requests (job boards, search, webhooks)."""

import ssl
from functools import lru_cache

import certifi

from ai_service.app.core.config import settings


@lru_cache(maxsize=1)
def tls_verify() -> ssl.SSLContext | bool:
    """The `verify` value for httpx clients.

    Trusts the operating system's certificate store (on Windows that includes root certificates a company
    proxy installs) plus Mozilla's bundle that httpx uses by default, so certificate checks stay on even
    behind such proxies. TLS_VERIFY=false disables checking; CA_BUNDLE adds a PEM file.
    """
    if not settings.tls_verify:
        return False
    context = ssl.create_default_context()
    context.load_verify_locations(cafile=certifi.where())
    if settings.ca_bundle:
        context.load_verify_locations(cafile=settings.ca_bundle)
    return context
