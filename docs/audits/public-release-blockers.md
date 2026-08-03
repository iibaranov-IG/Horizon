# Horizon Public Release Audit

## Scope

Evidence-driven audit of `iibaranov-IG/Horizon` under the canonical `AUDIT-FIRST` and `MINIMAL REMEDIATION ONLY` contract.

## Contract

- Canonical file: `docs/audits/public-release-audit-contract.md`
- Contract commit: `0e43b906e8d624469163cf6321b58052c36d9d6f`

## Baseline

- Audit baseline branch SHA: `35fd468`
- Main baseline SHA: `f37ec60a14b3cc5f0f73535b66ed822acef82056`
- Pull request: `#1`, `audit/public-release-blockers -> main`

## Current security result

### B-01 — SSRF DNS-to-connection gap

**Status: REMEDIATED.**

The request path now resolves and validates every DNS answer before connection establishment, selects one validated public address, and creates a one-use pinned HTTPX/httpcore transport. The HTTP origin remains the original hostname for the `Host` authority, TLS SNI, and certificate hostname validation, while the network backend opens the TCP socket only to the selected validated IP address.

The implementation has no fallback to the caller's ordinary hostname transport. Every redirect re-enters URL parsing, DNS resolution, address validation, address selection, and connection pinning before the next request. Response-size and connected-peer checks remain defence in depth.

Security implementation commits:

```text
7161d1379bd86780e35ecf1665d319b9b5d8950b  fix(security): pin validated webhook connections
1a63b49eda4621fee1b7c17c23c657fb6cc173a6  test(security): cover pinned connection backend
5a9c71ccb5fdb000bfa04ae93b9848e3434863b2  fix(security): close pinned transport on connection failure
f963ce8f506194d39175c75599520556acb6af04  test(security): prove pinned HTTPS request boundary
679e3aac9b80efbe5aca25b44801b53d3388145b  test(security): normalize HTTP header assertion
```

The transport dependency is explicitly fixed at `httpcore==1.0.9`. This is a maintenance constraint: any HTTPX/httpcore upgrade must rerun the transport-boundary tests before release.

## Security proof

Deterministic transport-boundary tests establish that:

- the socket backend receives the validated IP rather than the hostname;
- the request origin remains the original hostname;
- HTTPS starts TLS with the original hostname as SNI;
- the default SSL context keeps hostname checking enabled and requires a valid certificate;
- the HTTP `Host` authority remains the original hostname;
- request headers and body are written only after TLS has started;
- a private redirect is rejected before a second transport connection;
- a public redirect is resolved, validated, and pinned independently;
- a pinned-backend connection failure does not fall back to an unvalidated client;
- the pinned client and connection pool close on both success and failure.

Regression coverage is in `tests/test_url_security.py`.

## CI evidence

### Accepted security implementation SHA

```text
679e3aac9b80efbe5aca25b44801b53d3388145b
```

Blocking pull-request workflow:

```text
workflow: Public release audit
run_id: 30803212957
run number: 34
result: SUCCESS
```

All blocking jobs succeeded:

```text
Full test suite: SUCCESS
Build and clean wheel install: SUCCESS
Publication hygiene scan: SUCCESS
```

The immediately preceding workflow run `30802927938` failed only because a new test compared the case of an HTTP header name. HTTP header names are case-insensitive; the assertion was normalized in commit `679e3aa...`. No production behavior was changed by that correction. The successful run reported the complete suite passing.

This documentation update creates a newer branch SHA. Under the audit contract, the new exact branch head must also complete the blocking workflow successfully before merge.

## Package acceptance

The workflow verifies:

- wheel and sdist build;
- installation into an isolated environment;
- import outside the source checkout;
- all declared console-script `--help` commands;
- `pip check`;
- publication hygiene inventory.

## Other resolved findings

### R-01 — Unconfirmed public governance address

The unconfirmed personal address was removed from `SECURITY.md` and `CODE_OF_CONDUCT.md`. Security reports are directed to GitHub's private security advisory interface; conduct reports are directed to private repository moderation/reporting mechanisms.

### R-03 — `horizon-wizard --help` entered interactive mode

A non-interactive argparse boundary and regression coverage were added. Clean-install console-script checks pass.

## Remaining non-blocking risks

The following integrations remain intentionally `NOT VERIFIED` because no live credentials or approved external test systems were supplied:

```text
Live SMTP delivery: NOT VERIFIED
Live webhook delivery against an external endpoint: NOT VERIFIED
Paid AI-provider calls: NOT VERIFIED
Docker release path: NOT VERIFIED / not established as the official Python-package release path
```

These items are not represented as passed and are not part of the closed pre-send SSRF finding.

## Automated release verdict

```text
READY CANDIDATE WITH NON-BLOCKING RISKS
```

This is not the final human `READY` decision. Before merge, a human must review:

- the final branch SHA;
- the complete diff;
- the successful blocking workflow for that exact final branch SHA;
- this report;
- the remaining `NOT VERIFIED` integrations.
