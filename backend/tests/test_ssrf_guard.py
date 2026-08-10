from __future__ import annotations

import socket

import httpx
import pytest
from app.security import ssrf_guard


def _fake_addrinfo(*ips: str) -> list[tuple]:
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 0)) for ip in ips]


def test_rejects_non_http_scheme():
    with pytest.raises(ssrf_guard.SsrfBlockedError, match="scheme"):
        ssrf_guard.check_url("ftp://example.com/file")


def test_rejects_file_scheme():
    with pytest.raises(ssrf_guard.SsrfBlockedError, match="scheme"):
        ssrf_guard.check_url("file:///etc/passwd")


def test_rejects_url_with_no_hostname():
    with pytest.raises(ssrf_guard.SsrfBlockedError, match="hostname"):
        ssrf_guard.check_url("http:///path")


def test_rejects_blocked_hostname_literal(monkeypatch: pytest.MonkeyPatch):
    # Should be rejected before any DNS lookup even happens.
    def _boom(*args: object, **kwargs: object) -> None:
        raise AssertionError("should not resolve a blocklisted hostname")

    monkeypatch.setattr(ssrf_guard.socket, "getaddrinfo", _boom)
    with pytest.raises(ssrf_guard.SsrfBlockedError, match="blocked"):
        ssrf_guard.check_url("http://localhost:8000/api")
    with pytest.raises(ssrf_guard.SsrfBlockedError, match="blocked"):
        ssrf_guard.check_url("http://backend/api")


@pytest.mark.parametrize(
    "ip",
    [
        "127.0.0.1",  # loopback
        "10.0.0.5",  # RFC 1918
        "172.16.0.5",  # RFC 1918
        "192.168.1.1",  # RFC 1918
        "169.254.169.254",  # link-local / cloud metadata endpoint
        "0.0.0.0",  # unspecified
        "224.0.0.1",  # multicast
        "::1",  # IPv6 loopback
        "fe80::1",  # IPv6 link-local
        "fc00::1",  # IPv6 unique local (private)
    ],
)
def test_blocks_internal_ip_ranges(monkeypatch: pytest.MonkeyPatch, ip: str):
    monkeypatch.setattr(ssrf_guard.socket, "getaddrinfo", lambda *a, **k: _fake_addrinfo(ip))
    with pytest.raises(ssrf_guard.SsrfBlockedError, match="blocked address"):
        ssrf_guard.check_url("http://evil.example.com/")


def test_allows_public_ip(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(ssrf_guard.socket, "getaddrinfo", lambda *a, **k: _fake_addrinfo("93.184.216.34"))
    ssrf_guard.check_url("https://example.com/")  # must not raise


def test_blocks_if_any_resolved_address_is_internal(monkeypatch: pytest.MonkeyPatch):
    # A hostname resolving to multiple A/AAAA records where even one is
    # internal must be blocked - the attacker only needs one to win a race.
    monkeypatch.setattr(
        ssrf_guard.socket, "getaddrinfo", lambda *a, **k: _fake_addrinfo("93.184.216.34", "127.0.0.1")
    )
    with pytest.raises(ssrf_guard.SsrfBlockedError, match="blocked address"):
        ssrf_guard.check_url("https://example.com/")


def test_unresolvable_host_is_blocked(monkeypatch: pytest.MonkeyPatch):
    def _raise_gaierror(*args: object, **kwargs: object) -> None:
        raise OSError("Name or service not known")

    monkeypatch.setattr(ssrf_guard.socket, "getaddrinfo", _raise_gaierror)
    with pytest.raises(ssrf_guard.SsrfBlockedError, match="could not resolve"):
        ssrf_guard.check_url("https://this-domain-does-not-exist.invalid/")


def test_guarded_get_returns_final_response(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(ssrf_guard.socket, "getaddrinfo", lambda *a, **k: _fake_addrinfo("93.184.216.34"))
    monkeypatch.setattr(
        httpx, "get", lambda url, **kwargs: httpx.Response(200, text="ok", request=httpx.Request("GET", url))
    )
    resp = ssrf_guard.guarded_get("https://example.com/")
    assert resp.status_code == 200


def test_guarded_get_follows_and_revalidates_redirects(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(ssrf_guard.socket, "getaddrinfo", lambda *a, **k: _fake_addrinfo("93.184.216.34"))

    calls: list[str] = []

    def _fake_get(url: str, **kwargs: object) -> httpx.Response:
        calls.append(url)
        if url == "https://example.com/start":
            return httpx.Response(
                302, headers={"location": "https://example.com/end"}, request=httpx.Request("GET", url)
            )
        return httpx.Response(200, text="ok", request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx, "get", _fake_get)
    resp = ssrf_guard.guarded_get("https://example.com/start")
    assert resp.status_code == 200
    assert calls == ["https://example.com/start", "https://example.com/end"]


def test_guarded_get_blocks_redirect_to_internal_address(monkeypatch: pytest.MonkeyPatch):
    def _fake_getaddrinfo(hostname: str, *a: object, **k: object) -> list[tuple]:
        if hostname == "internal.example.com":
            return _fake_addrinfo("127.0.0.1")
        return _fake_addrinfo("93.184.216.34")

    monkeypatch.setattr(ssrf_guard.socket, "getaddrinfo", _fake_getaddrinfo)

    def _fake_get(url: str, **kwargs: object) -> httpx.Response:
        if url == "https://example.com/start":
            return httpx.Response(
                302,
                headers={"location": "https://internal.example.com/steal"},
                request=httpx.Request("GET", url),
            )
        raise AssertionError("must never actually request the redirect target")

    monkeypatch.setattr(httpx, "get", _fake_get)
    with pytest.raises(ssrf_guard.SsrfBlockedError, match="blocked address"):
        ssrf_guard.guarded_get("https://example.com/start")


def test_guarded_get_bounds_redirect_chain_length(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(ssrf_guard.socket, "getaddrinfo", lambda *a, **k: _fake_addrinfo("93.184.216.34"))

    def _fake_get(url: str, **kwargs: object) -> httpx.Response:
        return httpx.Response(
            302, headers={"location": "https://example.com/next"}, request=httpx.Request("GET", url)
        )

    monkeypatch.setattr(httpx, "get", _fake_get)
    with pytest.raises(ssrf_guard.SsrfBlockedError, match="too many redirects"):
        ssrf_guard.guarded_get("https://example.com/start")
