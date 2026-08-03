"""SSRF-safe HTTP URL validation and request execution."""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from collections.abc import Iterable
from urllib.parse import urljoin, urlsplit

import httpx


DEFAULT_MAX_RESPONSE_BYTES = 1_048_576


class UnsafeURLError(ValueError):
    """Raised when a URL may target a non-public network resource."""


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
        hostname.rstrip("."), parsed.port or (443 if parsed.scheme.lower() == "https" else 80)
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
    except ValueError as exc:
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
    request = client.build_request(method, url, **kwargs)
    response = await client.send(request, stream=True, follow_redirects=False)
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
            if int(value) > max_response_bytes:
                raise UnsafeURLError(
                    f"Response exceeds the maximum allowed size of {max_response_bytes} bytes"
                )
        except (TypeError, ValueError) as exc:
            raise UnsafeURLError("Response Content-Length is invalid") from exc

    content = getattr(response, "content", b"")
    if isinstance(content, (bytes, bytearray)) and len(content) > max_response_bytes:
        raise UnsafeURLError(
            f"Response exceeds the maximum allowed size of {max_response_bytes} bytes"
        )


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

        if isinstance(client, httpx.AsyncClient):
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
                current_url, follow_redirects=False, **current_kwargs
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
