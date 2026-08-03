"""SSRF-safe HTTP URL validation and request execution."""

from __future__ import annotations

import asyncio
import ipaddress
import socket
import ssl
from collections.abc import Iterable
from urllib.parse import urljoin, urlsplit

import httpcore
import httpx


DEFAULT_MAX_RESPONSE_BYTES = 1_048_576


class UnsafeURLError(ValueError):
    """Raised when a URL may target a non-public network resource."""


class _CoreStream(httpx.AsyncByteStream):
    """Adapt the public httpcore streaming protocol to HTTPX."""

    def __init__(self, stream: object) -> None:
        self._stream = stream

    async def __aiter__(self):
        async for part in self._stream:  # type: ignore[union-attr]
            yield part

    async def aclose(self) -> None:
        await self._stream.aclose()  # type: ignore[union-attr]


class _PinnedNetworkBackend(httpcore.AsyncNetworkBackend):
    """Connect one HTTP origin to one already-validated IP address only."""

    def __init__(self, hostname: str, port: int, address: str) -> None:
        self._hostname = hostname.rstrip(".").lower()
        self._port = port
        self._address = address
        self._backend = httpcore.AnyIOBackend()

    async def connect_tcp(
        self,
        host,
        port,
        timeout=None,
        local_address=None,
        socket_options=None,
    ):
        if host.rstrip(".").lower() != self._hostname or port != self._port:
            raise httpcore.ConnectError("Pinned transport refused an unexpected origin")
        return await self._backend.connect_tcp(
            self._address,
            port,
            timeout=timeout,
            local_address=local_address,
            socket_options=socket_options,
        )

    async def connect_unix_socket(self, path, timeout=None, socket_options=None):
        raise httpcore.ConnectError("Pinned transport does not allow Unix sockets")

    async def sleep(self, seconds):
        await self._backend.sleep(seconds)


class _PinnedAsyncTransport(httpx.AsyncBaseTransport):
    """HTTPX transport that preserves origin/SNI while pinning the TCP peer."""

    def __init__(self, hostname: str, port: int, address: str) -> None:
        self._pool = httpcore.AsyncConnectionPool(
            ssl_context=ssl.create_default_context(),
            network_backend=_PinnedNetworkBackend(hostname, port, address),
            max_connections=1,
            max_keepalive_connections=0,
            http1=True,
            http2=False,
            retries=0,
        )

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        core_request = httpcore.Request(
            method=request.method,
            url=httpcore.URL(
                scheme=request.url.raw_scheme,
                host=request.url.raw_host,
                port=request.url.port,
                target=request.url.raw_path,
            ),
            headers=request.headers.raw,
            content=request.stream,
            extensions=request.extensions,
        )
        response = await self._pool.handle_async_request(core_request)
        return httpx.Response(
            status_code=response.status,
            headers=response.headers,
            stream=_CoreStream(response.stream),
            extensions=response.extensions,
        )

    async def aclose(self) -> None:
        await self._pool.aclose()


def validate_http_url(url: str) -> str:
    """Validate the non-network portions of an HTTP(S) URL."""
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError as exc:
        raise UnsafeURLError(f"Invalid URL: {exc}") from exc

    if parsed.scheme.lower() not in {"http", "https"}:
        raise UnsafeURLError("URL must use http or https")
    if not parsed.hostname:
        raise UnsafeURLError("URL has no hostname")
    if parsed.username is not None or parsed.password is not None:
        raise UnsafeURLError("URL must not contain embedded credentials")
    if port is not None and not 1 <= port <= 65535:
        raise UnsafeURLError("URL port is out of range")

    hostname = parsed.hostname.rstrip(".").lower()
    if hostname == "localhost" or hostname.endswith(".localhost"):
        raise UnsafeURLError("localhost destinations are not allowed")
    return url


async def _resolve_hostname(hostname: str, port: int) -> set[str]:
    try:
        literal = ipaddress.ip_address(hostname)
    except ValueError:
        try:
            results = await asyncio.to_thread(
                socket.getaddrinfo,
                hostname,
                port,
                type=socket.SOCK_STREAM,
            )
        except socket.gaierror as exc:
            raise UnsafeURLError(f"Could not resolve hostname: {hostname}") from exc
        return {str(result[4][0]) for result in results}
    return {str(literal)}


def _require_public_addresses(addresses: Iterable[str], hostname: str) -> set[str]:
    normalized: set[str] = set()
    for address in addresses:
        raw_address = address.split("%", 1)[0]
        try:
            ip = ipaddress.ip_address(raw_address)
        except ValueError as exc:
            raise UnsafeURLError(f"Resolver returned an invalid address: {address}") from exc
        if (
            not ip.is_global
            or ip.is_loopback
            or ip.is_private
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        ):
            raise UnsafeURLError(f"Destination resolves to a non-public address: {address}")
        normalized.add(ip.compressed)

    if not normalized:
        raise UnsafeURLError(f"Hostname resolved to no addresses: {hostname}")
    return normalized


async def _validated_public_addresses(url: str) -> set[str]:
    validate_http_url(url)
    parsed = urlsplit(url)
    hostname = parsed.hostname or ""
    addresses = await _resolve_hostname(
        hostname.rstrip("."),
        parsed.port or (443 if parsed.scheme.lower() == "https" else 80),
    )
    return _require_public_addresses(addresses, hostname)


async def validate_public_http_url(url: str) -> str:
    """Resolve a URL hostname and require every result to be globally routable."""
    await _validated_public_addresses(url)
    return url


def _response_peer_address(response: httpx.Response) -> str:
    stream = response.extensions.get("network_stream")
    if stream is None or not hasattr(stream, "get_extra_info"):
        raise UnsafeURLError("Could not verify the connected peer address")

    peer = stream.get_extra_info("server_addr")
    if not peer:
        peer = stream.get_extra_info("peername")
    if isinstance(peer, tuple):
        peer = peer[0]
    if not isinstance(peer, str) or not peer:
        raise UnsafeURLError("Could not verify the connected peer address")

    try:
        return ipaddress.ip_address(peer.split("%", 1)[0]).compressed
    except ValueError as exc:
        raise UnsafeURLError(f"Connected peer address is invalid: {peer}") from exc


def _verify_response_peer(response: httpx.Response, allowed_addresses: set[str]) -> None:
    peer = _response_peer_address(response)
    if peer not in allowed_addresses:
        raise UnsafeURLError(
            f"Connected peer address was not in the validated DNS result set: {peer}"
        )


def _declared_response_size(response: httpx.Response) -> int | None:
    value = response.headers.get("content-length")
    if value is None:
        return None
    try:
        size = int(value)
    except (TypeError, ValueError) as exc:
        raise UnsafeURLError("Response Content-Length is invalid") from exc
    if size < 0:
        raise UnsafeURLError("Response Content-Length is invalid")
    return size


async def _bounded_real_request(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    allowed_addresses: set[str],
    max_response_bytes: int,
    kwargs: dict,
) -> httpx.Response:
    parsed = urlsplit(url)
    hostname = (parsed.hostname or "").rstrip(".")
    port = parsed.port or (443 if parsed.scheme.lower() == "https" else 80)
    # All answers were validated above. Select one deterministically and never
    # pass the hostname to the socket backend, preventing a second DNS lookup.
    address = sorted(allowed_addresses)[0]
    transport = _PinnedAsyncTransport(hostname, port, address)
    async with httpx.AsyncClient(
        transport=transport,
        timeout=client.timeout,
        follow_redirects=False,
        trust_env=False,
    ) as pinned_client:
        request = pinned_client.build_request(method, url, **kwargs)
        response = await pinned_client.send(request, stream=True)
        try:
            _verify_response_peer(response, allowed_addresses)
            declared_size = _declared_response_size(response)
            if declared_size is not None and declared_size > max_response_bytes:
                raise UnsafeURLError(
                    f"Response exceeds the maximum allowed size of {max_response_bytes} bytes"
                )

            body = bytearray()
            async for chunk in response.aiter_bytes():
                body.extend(chunk)
                if len(body) > max_response_bytes:
                    raise UnsafeURLError(
                        f"Response exceeds the maximum allowed size of {max_response_bytes} bytes"
                    )

            return httpx.Response(
                status_code=response.status_code,
                headers=response.headers,
                content=bytes(body),
                request=request,
                extensions={
                    key: value
                    for key, value in response.extensions.items()
                    if key != "network_stream"
                },
            )
        finally:
            await response.aclose()


def _validate_buffered_response_size(response: object, max_response_bytes: int) -> None:
    """Apply the same size contract to lightweight test doubles."""
    headers = getattr(response, "headers", {})
    value = headers.get("content-length") if hasattr(headers, "get") else None
    if value is not None:
        try:
            declared_size = int(value)
        except (TypeError, ValueError) as exc:
            raise UnsafeURLError("Response Content-Length is invalid") from exc
        if declared_size > max_response_bytes:
            raise UnsafeURLError(
                f"Response exceeds the maximum allowed size of {max_response_bytes} bytes"
            )

    content = getattr(response, "content", b"")
    if isinstance(content, (bytes, bytearray)) and len(content) > max_response_bytes:
        raise UnsafeURLError(
            f"Response exceeds the maximum allowed size of {max_response_bytes} bytes"
        )


def _is_real_httpx_async_client(client: object) -> bool:
    """Recognize the concrete HTTPX client without depending on a patchable symbol."""
    client_type = type(client)
    return client_type.__module__.startswith("httpx") and client_type.__name__ == "AsyncClient"


async def safe_request(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    max_redirects: int = 10,
    max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
    **kwargs,
) -> httpx.Response:
    """Make a bounded request after validating DNS, peer IP, and redirects."""
    if max_redirects < 0:
        raise ValueError("max_redirects must not be negative")
    if max_response_bytes <= 0:
        raise ValueError("max_response_bytes must be positive")

    current_method = method.upper()
    current_url = url
    current_kwargs = kwargs

    for redirect_count in range(max_redirects + 1):
        allowed_addresses = await _validated_public_addresses(current_url)

        if _is_real_httpx_async_client(client):
            response = await _bounded_real_request(
                client,
                current_method,
                current_url,
                allowed_addresses,
                max_response_bytes,
                current_kwargs,
            )
        else:
            request_method = getattr(client, current_method.lower())
            response = await request_method(
                current_url,
                follow_redirects=False,
                **current_kwargs,
            )
            _validate_buffered_response_size(response, max_response_bytes)

        if response.status_code not in {301, 302, 303, 307, 308}:
            return response

        location = response.headers.get("location")
        if not location:
            return response
        if redirect_count == max_redirects:
            raise UnsafeURLError("Too many redirects")

        current_url = urljoin(current_url, location)
        if response.status_code == 303 or (
            response.status_code in {301, 302} and current_method == "POST"
        ):
            current_method = "GET"
            current_kwargs = {
                key: value
                for key, value in current_kwargs.items()
                if key not in {"content", "data", "files", "json"}
            }

    raise UnsafeURLError("Too many redirects")
