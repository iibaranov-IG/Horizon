# Horizon Public Release Audit

## Scope

Evidence-driven audit of `iibaranov-IG/Horizon` under the canonical `AUDIT-FIRST` and `MINIMAL REMEDIATION ONLY` contract.

## Contract

- Canonical file: `docs/audits/public-release-audit-contract.md`
- Contract commit: `0e43b906e8d624469163cf6321b58052c36d9d6f`

## Baseline

- Audit baseline branch SHA: `35fd468`
- Main baseline SHA: `f37ec60a14b3cc5f0f73535b66ed822acef82056`
- Draft PR: `#1`, `audit/public-release-blockers -> main`

## Final correction — pre-send DNS rebinding blocker

**Status: BLOCKING / NOT REMEDIATED.**

The previous wording that described R-02 as resolved was incorrect. The
implementation performs `_validated_public_addresses(url)`, then calls
`client.send(request, stream=True)`, and only afterwards calls
`_verify_response_peer(response, allowed_addresses)`. HTTPX receives the
original hostname, so its normal transport performs its own DNS lookup when
opening the TCP connection. A DNS rebind between those lookups can therefore
cause request headers and a body to reach a prohibited address before the peer
metadata is inspected. The peer check is defence in depth after transmission;
it is not pre-send DNS-rebinding protection.

The deterministic tests currently cover DNS validation, response size, and
post-connect peer metadata. They do not establish a pinned connection before
headers/body transmission, and must not be cited as proof of that property.

### Architecture assessment

| Option | Pre-send rebinding protection | TLS SNI / certificate hostname validation | Redirects | Risk |
| --- | --- | --- | --- | --- |
| Custom HTTPX/httpcore transport with a pinned backend | Yes in principle | Yes, because the HTTP origin remains the hostname | Per-hop transport required | Depends on HTTPX/httpcore transport internals not exposed by the project contract |
| Explicit TCP/TLS connection to the selected IP | Yes | Possible, but would require reimplementing HTTP parsing, redirects, response streaming, and timeout semantics | Must be reimplemented | Larger networking-stack replacement |
| Standard `httpx.AsyncClient` after validation | No | Yes | Yes | Current unsafe behavior |

HTTPX 0.28.1 exposes no supported public request option that pins a TCP peer
to a validated IP while retaining the original hostname for both HTTP Host
authority and HTTPS SNI/certificate validation. The first option would require
constructing a custom `httpcore.AsyncConnectionPool` and injecting a network
backend; that is an internal integration boundary. The second option exceeds
the minimal-remediation limit. Therefore no unambiguous, supported minimal
remediation is available under the audit contract.

The final exact-head SHA, exact-head push CI, and PR merge-ref CI for a future
real remediation are **PENDING**. Existing runs are evidence only for their
respective historical commits and do not close this blocker.

## Current audited state

The two remaining publication blockers identified by the first audit have been remediated:

1. The unconfirmed personal address was removed from `SECURITY.md` and `CODE_OF_CONDUCT.md`.
2. The SSRF request path now enforces a bounded response body and verifies that the connected peer address belongs to the DNS address set validated immediately before the request. Redirect targets are resolved and validated again.

Production remediation SHA:

```text
01a07c66a006f7e7ab33048f3f8d05eec45aa4e7
```

Exact-head blocking CI for that production SHA:

```text
workflow: Public release audit
run_id: 30796914087
run number: 22
trigger: push
result: SUCCESS
```

A later documentation-only commit records this evidence. Under the contract, the final documentation SHA must also receive a successful blocking workflow before human release approval.

## Evidence

### GitHub Actions on production remediation SHA

Run `30796914087` completed successfully for exact branch-head SHA `01a07c66a006f7e7ab33048f3f8d05eec45aa4e7`.

Jobs:

```text
Full test suite: SUCCESS
Build and clean wheel install: SUCCESS
Publication hygiene scan: SUCCESS
```

The preceding run `30796778704` failed and was not treated as evidence. Its failures exposed two test-double compatibility defects in the first SSRF implementation. Those defects were corrected in `01a07c66...`, after which the complete blocking workflow passed.

### Package acceptance

The workflow verifies:

- wheel and sdist build;
- installation into an isolated environment;
- import outside the source checkout;
- all declared console-script `--help` commands;
- `pip check`;
- publication hygiene inventory.

### Security acceptance

The URL security path now verifies:

- only HTTP and HTTPS schemes;
- no embedded URL credentials;
- rejection of localhost, loopback, private, link-local, multicast, reserved, unspecified, and otherwise non-global addresses;
- validation of every resolved address;
- validation of every redirect target;
- redirect limit;
- maximum response-body size, including streamed responses without `Content-Length`;
- connected peer address matches the immediately validated DNS result set;
- failure closed when the connected peer cannot be verified.

Regression coverage is in `tests/test_url_security.py`.

## Resolved findings

### R-01 — Unconfirmed public governance address

**State:** `SECURITY.md` and `CODE_OF_CONDUCT.md` previously published an address whose ownership was not confirmed.

**Action:** Removed the address. Security reports are directed to GitHub's private security advisory interface; conduct reports are directed to private repository moderation/reporting mechanisms.

**Commits:**

```text
897813a992e214782666aea16770a8ac4d8e1ea1
bd4f2cef327a29a70d612d9ae723703c5d60361a
```

**Result:** No unconfirmed personal address remains in the public governance files.

### B-01 — SSRF DNS-to-connection gap (re-opened)

**State:** The implementation validates DNS before the request and verifies
peer metadata after the response starts, but it does not pin the TCP connection
to the validated IP before headers/body are sent.

**Action:** No production change was made during this correction. A
post-connect peer check and response-size limit remain useful defence in depth,
but do not remediate DNS rebinding before payload transmission.

**Commits:**

```text
ec63db73cd887775fc50d0f96aef009eb291217b
0f1450cc3a61dce5996ef28172ce27d359416637
01a07c66a006f7e7ab33048f3f8d05eec45aa4e7
```

**Result:** `NOT READY`. A supported pinned transport (or an explicitly
approved networking-contract change) and deterministic transport-boundary
tests are required before this finding can be resolved.

### R-03 — `horizon-wizard --help` entered interactive mode

The earlier audit added a non-interactive argparse boundary and regression coverage. The clean-install console-script checks remain successful.

## Remaining non-blocking risks

The following live integrations remain intentionally `NOT VERIFIED` because no live credentials or external test systems were supplied:

```text
Live SMTP delivery: NOT VERIFIED
Live webhook delivery: NOT VERIFIED
Paid AI-provider calls: NOT VERIFIED
Docker release path: NOT VERIFIED / not established as the official Python-package release path
```

The audit workflow does not claim a full dependency vulnerability scan, lint, formatting, or type-check gate because those tools are not established project contracts in `pyproject.toml`.

## Automated release verdict

```text
NOT READY
```

Publication is blocked until B-01 is remediated with a connection pinned to a
validated public IP before request headers/body are transmitted. Human approval
must review:

- the final branch SHA;
- the diff;
- the successful exact-head blocking workflow;
- this report;
- the remaining `NOT VERIFIED` integrations.

The Draft PR must not be merged automatically.
