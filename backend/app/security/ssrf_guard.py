"""SSRF guard for public-URL source adapters (Moxfield, Archidekt, and any
future generic configurable source) — see SECURITY.md "SSRF protections".
Every outbound request a URL adapter makes for a user-supplied URL goes
through `guarded_get` first.

Known limitation (accepted trade-off, not an oversight): this validates the
hostname's resolved IPs immediately before each request/redirect hop, but
does not pin the connection to the exact IP checked (true pinning needs
low-level transport control disproportionate to what a self-hosted hobby
tool's threat model calls for). A DNS response that changes between the
check and the actual TCP connect (classic "DNS rebinding") could in theory
slip through. What this *does* reliably stop: the much more common case of
a URL that's simply, statically, an internal address — localhost, the
Docker compose network, cloud metadata endpoints (169.254.169.254), RFC 1918
ranges, etc.
"""
from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

import httpx

ALLOWED_SCHEMES = {"http", "https"}
MAX_REDIRECTS = 5

# Compose-network service names. DNS wouldn't resolve these from outside the
# stack anyway, but blocking by name is cheap defense in depth (e.g. against
# a future deploy that adds a matching public DNS record, or a container
# alias added later without anyone revisiting this list).
BLOCKED_HOSTNAMES = {"localhost", "backend", "postgres", "redis", "worker", "frontend", "secrets-init"}


class SsrfBlockedError(ValueError):
    """A URL failed the guard. Callers should treat this as a permanent
    rejection (report FAILED/blocked to the user), never retry it as if it
    were a transient network error.
    """


class AuthRequiredError(RuntimeError):
    """Raised by an adapter (not this module) when a fetch landed on a login
    wall / auth-required page instead of the expected content. Shared here
    so every adapter reports the same condition the same way — see
    SOURCE_ADAPTERS.md status vocabulary, AUTH_REQUIRED.
    """


def _is_blocked_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved or ip.is_unspecified:
        return True
    if isinstance(ip, ipaddress.IPv6Address):
        mapped = ip.ipv4_mapped
        if mapped is not None and _is_blocked_ip(mapped):
            return True
    return False


def check_url(url: str) -> None:
    """Raises SsrfBlockedError if `url` isn't safe to fetch. Does not return
    anything on success - callers re-check on every redirect hop too (see
    guarded_get), since the destination can change mid-flight.
    """
    parsed = urlparse(url)
    if parsed.scheme not in ALLOWED_SCHEMES:
        raise SsrfBlockedError(f"scheme '{parsed.scheme}' is not allowed (only http/https)")
    if not parsed.hostname:
        raise SsrfBlockedError("URL has no hostname")

    hostname = parsed.hostname.lower()
    if hostname in BLOCKED_HOSTNAMES:
        raise SsrfBlockedError(f"host '{hostname}' is blocked")

    try:
        addrinfo = socket.getaddrinfo(hostname, None)
    except OSError as exc:
        raise SsrfBlockedError(f"could not resolve host '{hostname}': {exc}") from exc

    for family_info in addrinfo:
        sockaddr = family_info[4]
        ip = ipaddress.ip_address(sockaddr[0])
        if _is_blocked_ip(ip):
            raise SsrfBlockedError(f"host '{hostname}' resolves to a blocked address ({ip})")


def guarded_get(url: str, *, headers: dict[str, str] | None = None, timeout: float = 30) -> httpx.Response:
    """GET `url` with the SSRF guard applied to the URL and to every redirect
    hop — httpx's own `follow_redirects` is deliberately never used here
    (see SECURITY.md: "Redirects are followed manually ... so each hop is
    re-validated").
    """
    current_url = url
    for _ in range(MAX_REDIRECTS + 1):
        check_url(current_url)
        resp = httpx.get(current_url, headers=headers, timeout=timeout, follow_redirects=False)
        if resp.is_redirect:
            location = resp.headers.get("location")
            if not location:
                raise SsrfBlockedError(f"redirect response from '{current_url}' had no Location header")
            current_url = str(httpx.URL(current_url).join(location))
            continue
        return resp
    raise SsrfBlockedError(f"too many redirects (>{MAX_REDIRECTS}) starting from '{url}'")
