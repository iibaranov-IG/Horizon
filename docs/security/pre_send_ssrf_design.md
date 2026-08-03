# Pre-send SSRF connection pinning

## Threat model

An attacker controls a webhook hostname and changes its DNS answer after URL
validation. A secure request must not send headers or a body to an address that
was not in the validated answer set.

## Architecture

For every hop Horizon parses the URL, resolves it once, validates every answer,
selects one public address deterministically, and creates a one-use HTTPX
transport. Its `httpcore.AsyncNetworkBackend` receives the hostname as the HTTP
origin but opens the socket only to the selected address. Thus httpcore retains
the hostname for HTTP Host, TLS SNI, and certificate hostname validation while
the backend cannot invoke DNS. The transport has no retry and no fallback to
the caller's normal HTTPX transport. HTTPS uses `ssl.create_default_context()`;
verification is never disabled.

Redirects re-enter this cycle before a subsequent request. Response-size and
peer checks remain defence in depth.

## Alternatives

Direct TCP/TLS would require reimplementing HTTP parsing, streaming, redirects,
and timeout behavior. Ordinary HTTPX cannot pin the peer. The chosen transport
uses the exported httpcore backend/pool interfaces, locked explicitly at
`httpcore==1.0.9`; this is a maintenance risk and upgrades require rerunning
the transport-boundary tests.

## Security proof obligations

Tests must show the backend receives the validated IP as its socket destination,
the request origin remains the hostname, a private redirect is rejected before
connection, and a backend failure cannot fall back to ordinary HTTPX.
