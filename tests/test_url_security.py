from __future__ import annotations

import asyncio
import ssl
from unittest.mock import AsyncMock, MagicMock, patch

import httpcore
import httpx
import pytest

from src.url_security import (
    UnsafeURLError,
    _PinnedNetworkBackend,
    _verify_response_peer,
    safe_request,
    validate_public_http_url,
)


def _run(coro):
    return asyncio.run(coro)


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/",
        "http://10.0.0.1/",
        "http://169.254.169.254/",
        "http://0.0.0.0/",
        "http://224.0.0.1/",
        "http://192.0.2.1/",
        "http://[::1]/",
        "http://[fc00::1]/",
        "http://[fe80::1]/",
        "http://[::]/",
        "http://[ff02::1]/",
        "http://[2001:db8::1]/",
    ],
)
def test_rejects_non_public_ip_destinations(url):
    with pytest.raises(UnsafeURLError, match="non-public"):
        _run(validate_public_http_url(url))


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost/",
        "https://service.localhost./hook",
        "ftp://example.com/file",
        "https://user:secret@example.com/hook",
    ],
)
def test_rejects_unsafe_url_forms(url):
    with pytest.raises(UnsafeURLError):
        _run(validate_public_http_url(url))


def test_rejects_hostname_when_any_resolved_ip_is_private():
    with patch(
        "src.url_security._resolve_hostname",
        new=AsyncMock(return_value={"93.184.216.34", "10.0.0.2"}),
    ):
        with pytest.raises(UnsafeURLError, match="10.0.0.2"):
            _run(validate_public_http_url("https://example.com/hook"))


def test_accepts_public_ipv4_and_ipv6_dns_answers():
    with patch(
        "src.url_security._resolve_hostname",
        new=AsyncMock(
            return_value={"93.184.216.34", "2606:2800:220:1:248:1893:25c8:1946"}
        ),
    ):
        assert _run(validate_public_http_url("https://example.com/hook"))


def test_redirect_is_validated_before_second_request():
    redirect = MagicMock(
        status_code=302,
        headers={"location": "http://127.0.0.1/admin"},
        content=b"",
    )
    client = MagicMock()
    client.get = AsyncMock(return_value=redirect)

    with patch(
        "src.url_security._resolve_hostname",
        new=AsyncMock(side_effect=[{"93.184.216.34"}, {"127.0.0.1"}]),
    ):
        with pytest.raises(UnsafeURLError, match="non-public"):
            _run(safe_request(client, "GET", "https://example.com/start"))

    client.get.assert_awaited_once_with(
        "https://example.com/start", follow_redirects=False
    )


def test_public_relative_redirect_is_followed():
    redirect = MagicMock(status_code=301, headers={"location": "/next"}, content=b"")
    success = MagicMock(status_code=200, headers={}, content=b"ok")
    client = MagicMock()
    client.get = AsyncMock(side_effect=[redirect, success])

    with patch(
        "src.url_security._resolve_hostname",
        new=AsyncMock(return_value={"93.184.216.34"}),
    ):
        result = _run(safe_request(client, "GET", "https://example.com/start"))

    assert result is success
    assert client.get.await_args_list[1].args == ("https://example.com/next",)
    assert client.get.await_args_list[1].kwargs == {"follow_redirects": False}


def test_rejects_declared_response_larger_than_limit():
    response = MagicMock(
        status_code=200,
        headers={"content-length": "11"},
        content=b"small",
    )
    client = MagicMock()
    client.get = AsyncMock(return_value=response)

    with patch(
        "src.url_security._resolve_hostname",
        new=AsyncMock(return_value={"93.184.216.34"}),
    ):
        with pytest.raises(UnsafeURLError, match="maximum allowed size"):
            _run(
                safe_request(
                    client,
                    "GET",
                    "https://example.com/start",
                    max_response_bytes=10,
                )
            )


def test_rejects_buffered_response_larger_than_limit_without_content_length():
    response = MagicMock(status_code=200, headers={}, content=b"01234567890")
    client = MagicMock()
    client.get = AsyncMock(return_value=response)

    with patch(
        "src.url_security._resolve_hostname",
        new=AsyncMock(return_value={"93.184.216.34"}),
    ):
        with pytest.raises(UnsafeURLError, match="maximum allowed size"):
            _run(
                safe_request(
                    client,
                    "GET",
                    "https://example.com/start",
                    max_response_bytes=10,
                )
            )


class _NetworkStream:
    def __init__(self, peer):
        self.peer = peer

    def get_extra_info(self, name):
        if name in {"server_addr", "peername"}:
            return self.peer
        return None


def test_connected_peer_must_match_validated_dns_result():
    response = httpx.Response(
        200,
        request=httpx.Request("GET", "https://example.com"),
        extensions={"network_stream": _NetworkStream(("93.184.216.35", 443))},
    )

    with pytest.raises(UnsafeURLError, match="not in the validated DNS result set"):
        _verify_response_peer(response, {"93.184.216.34"})


def test_connected_peer_matching_validated_dns_result_is_accepted():
    response = httpx.Response(
        200,
        request=httpx.Request("GET", "https://example.com"),
        extensions={"network_stream": _NetworkStream(("93.184.216.34", 443))},
    )

    _verify_response_peer(response, {"93.184.216.34"})


def test_missing_peer_metadata_fails_closed():
    response = httpx.Response(
        200,
        request=httpx.Request("GET", "https://example.com"),
    )

    with pytest.raises(UnsafeURLError, match="Could not verify"):
        _verify_response_peer(response, {"93.184.216.34"})


def test_pinned_backend_connects_only_to_validated_ip(monkeypatch):
    calls = []

    class Backend:
        async def connect_tcp(self, host, port, **kwargs):
            calls.append((host, port))
            return object()

    backend = _PinnedNetworkBackend("example.com", 443, "93.184.216.34")
    monkeypatch.setattr(backend, "_backend", Backend())

    _run(backend.connect_tcp("example.com", 443))

    assert calls == [("93.184.216.34", 443)]


def test_pinned_backend_rejects_unexpected_origin_without_dns(monkeypatch):
    backend = _PinnedNetworkBackend("example.com", 443, "93.184.216.34")
    connect = AsyncMock()
    monkeypatch.setattr(backend, "_backend", MagicMock(connect_tcp=connect))

    with pytest.raises(Exception, match="unexpected origin"):
        _run(backend.connect_tcp("rebound.example", 443))

    connect.assert_not_awaited()


class _TLSObject:
    def selected_alpn_protocol(self):
        return None


class _ScriptedStream:
    def __init__(self, peer: str, response: bytes) -> None:
        self.peer = peer
        self._reads = [response, b""]
        self.writes: list[tuple[bool, bytes]] = []
        self.tls_started = False
        self.server_hostname = None
        self.ssl_context = None
        self.closed = False

    async def read(self, max_bytes: int, timeout=None) -> bytes:
        return self._reads.pop(0) if self._reads else b""

    async def write(self, buffer: bytes, timeout=None) -> None:
        self.writes.append((self.tls_started, bytes(buffer)))

    async def aclose(self) -> None:
        self.closed = True

    async def start_tls(self, ssl_context, server_hostname=None, timeout=None):
        self.tls_started = True
        self.server_hostname = server_hostname
        self.ssl_context = ssl_context
        return self

    def get_extra_info(self, name):
        if name == "ssl_object" and self.tls_started:
            return _TLSObject()
        if name in {"server_addr", "peername"}:
            return (self.peer, 443)
        return None


class _ScriptedBackend:
    def __init__(self, stream: _ScriptedStream, *, error: Exception | None = None) -> None:
        self.stream = stream
        self.error = error
        self.connect_calls: list[tuple[str, int]] = []

    async def connect_tcp(self, host, port, **kwargs):
        self.connect_calls.append((host, port))
        if self.error is not None:
            raise self.error
        return self.stream

    async def sleep(self, seconds):
        return None


def _http_response(status: str = "200 OK", headers: dict[str, str] | None = None, body: bytes = b"OK") -> bytes:
    response_headers = {"Content-Length": str(len(body)), **(headers or {})}
    lines = [f"HTTP/1.1 {status}", *[f"{key}: {value}" for key, value in response_headers.items()], "", ""]
    return "\r\n".join(lines).encode("ascii") + body


def test_https_request_pins_ip_and_preserves_sni_host_and_certificate_validation(monkeypatch):
    stream = _ScriptedStream("93.184.216.34", _http_response())
    backend = _ScriptedBackend(stream)
    monkeypatch.setattr("src.url_security.httpcore.AnyIOBackend", lambda: backend)

    resolver = AsyncMock(return_value={"93.184.216.34"})
    with patch("src.url_security._resolve_hostname", new=resolver):
        async def exercise():
            async with httpx.AsyncClient() as client:
                return await safe_request(
                    client,
                    "POST",
                    "https://example.com/hook",
                    headers={"Authorization": "Bearer top-secret"},
                    content=b"private-payload",
                )

        response = _run(exercise())

    assert response.status_code == 200
    assert response.content == b"OK"
    resolver.assert_awaited_once_with("example.com", 443)
    assert backend.connect_calls == [("93.184.216.34", 443)]
    assert stream.server_hostname in {"example.com", b"example.com"}
    assert stream.ssl_context.check_hostname is True
    assert stream.ssl_context.verify_mode == ssl.CERT_REQUIRED
    assert stream.writes and all(tls_started for tls_started, _ in stream.writes)
    wire_bytes = b"".join(buffer for _, buffer in stream.writes)
    assert b"host: example.com" in wire_bytes.lower()
    assert b"authorization: Bearer top-secret" in wire_bytes
    assert b"private-payload" in wire_bytes


def test_private_redirect_is_rejected_before_a_second_transport_connect(monkeypatch):
    stream = _ScriptedStream(
        "93.184.216.34",
        _http_response(
            "302 Found",
            headers={"Location": "http://127.0.0.1/admin"},
            body=b"",
        ),
    )
    backend = _ScriptedBackend(stream)
    factories = [backend]
    monkeypatch.setattr(
        "src.url_security.httpcore.AnyIOBackend", lambda: factories.pop(0)
    )

    resolver = AsyncMock(side_effect=[{"93.184.216.34"}, {"127.0.0.1"}])
    with patch("src.url_security._resolve_hostname", new=resolver):
        async def exercise():
            async with httpx.AsyncClient() as client:
                await safe_request(client, "GET", "https://example.com/start")

        with pytest.raises(UnsafeURLError, match="non-public"):
            _run(exercise())

    assert backend.connect_calls == [("93.184.216.34", 443)]
    assert factories == []
    assert resolver.await_count == 2


def test_public_redirect_re_resolves_and_re_pins_each_hop(monkeypatch):
    first_stream = _ScriptedStream(
        "93.184.216.34",
        _http_response(
            "302 Found",
            headers={"Location": "https://second.example/next"},
            body=b"",
        ),
    )
    second_stream = _ScriptedStream("93.184.216.35", _http_response(body=b"done"))
    first_backend = _ScriptedBackend(first_stream)
    second_backend = _ScriptedBackend(second_stream)
    factories = [first_backend, second_backend]
    monkeypatch.setattr(
        "src.url_security.httpcore.AnyIOBackend", lambda: factories.pop(0)
    )

    resolver = AsyncMock(
        side_effect=[{"93.184.216.34"}, {"93.184.216.35"}]
    )
    with patch("src.url_security._resolve_hostname", new=resolver):
        async def exercise():
            async with httpx.AsyncClient() as client:
                return await safe_request(client, "GET", "https://example.com/start")

        response = _run(exercise())

    assert response.content == b"done"
    assert first_backend.connect_calls == [("93.184.216.34", 443)]
    assert second_backend.connect_calls == [("93.184.216.35", 443)]
    assert first_stream.server_hostname in {"example.com", b"example.com"}
    assert second_stream.server_hostname in {"second.example", b"second.example"}
    assert resolver.await_args_list[0].args == ("example.com", 443)
    assert resolver.await_args_list[1].args == ("second.example", 443)


def test_pinned_transport_failure_has_no_fallback_to_unvalidated_client(monkeypatch):
    stream = _ScriptedStream("93.184.216.34", _http_response())
    backend = _ScriptedBackend(stream, error=httpcore.ConnectError("blocked"))
    monkeypatch.setattr("src.url_security.httpcore.AnyIOBackend", lambda: backend)

    resolver = AsyncMock(return_value={"93.184.216.34"})
    with patch("src.url_security._resolve_hostname", new=resolver):
        async def exercise():
            async with httpx.AsyncClient() as client:
                await safe_request(
                    client,
                    "POST",
                    "https://example.com/hook",
                    headers={"Authorization": "Bearer top-secret"},
                    content=b"private-payload",
                )

        with pytest.raises(httpcore.ConnectError, match="blocked"):
            _run(exercise())

    assert backend.connect_calls == [("93.184.216.34", 443)]
    assert stream.writes == []
