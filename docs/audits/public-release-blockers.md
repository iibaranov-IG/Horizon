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

### R-02 — SSRF response size and DNS-to-connection gap

**State:** The original implementation validated DNS before the request but did not cap a streamed response and did not prove that the connected peer matched the validated address set.

**Action:** Added bounded streaming, `Content-Length` validation, connected-peer verification through HTTPX network-stream metadata, fail-closed behavior, and deterministic regression tests.

**Commits:**

```text
ec63db73cd887775fc50d0f96aef009eb291217b
0f1450cc3a61dce5996ef28172ce27d359416637
01a07c66a006f7e7ab33048f3f8d05eec45aa4e7
```

**Result:** Blocking CI passed on the exact production remediation SHA.

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
READY CANDIDATE WITH NON-BLOCKING RISKS
```

This is not the final `READY` decision. Human approval must review:

- the final branch SHA;
- the diff;
- the successful exact-head blocking workflow;
- this report;
- the remaining `NOT VERIFIED` integrations.

The Draft PR must not be merged automatically.
