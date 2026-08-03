# Horizon Public Release Audit

## Scope

Evidence-driven audit of `iibaranov-IG/Horizon` under the canonical `AUDIT-FIRST` and `MINIMAL REMEDIATION ONLY` contract.

## Contract

- Canonical file: `docs/audits/public-release-audit-contract.md`
- Contract commit: `0e43b906e8d624469163cf6321b58052c36d9d6f`

## Baseline

- Audit baseline branch SHA: `35fd468`
- Main baseline SHA: `f37ec60a14b3cc5f0f73535b66ed822acef82056`
- Contract baseline SHA: `0e43b906e8d624469163cf6321b58052c36d9d6f`
- Branch was two commits ahead of `main` and zero commits behind when the audit began.

## Current audited SHA

- Production head evaluated after remediation: `b25e7f7191345aeca8cfb6d46fab1fcf77dad8a4`
- Exact-head blocking CI: GitHub Actions run `30644200114` (push event)
- Draft PR: `#1`, `audit/public-release-blockers -> main`

The blocking workflow was observed on the exact audited branch-head SHA through its `push` trigger. The earlier pull-request merge run remains supplementary evidence only.

## Evidence

### Repository state

Command-equivalent GitHub compare:

```text
base: f37ec60
head: audit/public-release-blockers
status: ahead
behind_by: 0
```

The branch contained the expected canonical contract. No force push, merge to `main`, history rewrite, data migration, or public schema change was performed.

### GitHub Actions

Workflow:

```text
.github/workflows/public-release-audit.yml
```

Observed run:

```text
run_id: 30644200114
workflow: Public release audit
trigger context: push
head SHA: b25e7f7191345aeca8cfb6d46fab1fcf77dad8a4
workflow URL: https://github.com/iibaranov-IG/Horizon/actions/runs/30644200114
```

Jobs:

```text
Full test suite: SUCCESS
Build and clean wheel install: SUCCESS
Publication hygiene scan: SUCCESS
```

Artifacts were uploaded by all three jobs. Heavy logs and build outputs were not committed to Git.

## Critical blockers

None confirmed during this bounded run.

## High-priority findings

### H-01 — SSRF response-size and DNS-to-connection guarantees are incomplete

**State:** `src/url_security.py` validates URL schemes, rejects embedded credentials, resolves all addresses, rejects non-global targets, and revalidates redirects.

**Cause:** The reviewed implementation does not itself cap response-body size. It also validates DNS results separately from `httpx` connection establishment, so the audit did not establish that the connection is pinned to the exact validated address set rather than performing a second resolution.

**Action:** No autonomous production change was made because multiple safe implementation approaches affect networking behavior differently.

**Result:** Documented as a release blocker requiring an explicit design decision and regression tests.

### H-02 — Public governance files contain an unconfirmed personal contact

**State:** `SECURITY.md` and `CODE_OF_CONDUCT.md` direct reports to `thysrael@gmail.com`.

**Cause:** The audit cannot prove that this address is controlled by the current repository owner or is authorized as the public security and conduct contact.

**Action:** The address was not replaced automatically because the canonical replacement contact was not defined.

**Result:** Publication blocker pending human confirmation or replacement with an approved project contact.

## Medium-priority findings

### M-01 — CI security scan is intentionally narrow

The current workflow rejects tracked runtime/private filenames and records repository inventory, but it does not claim full secret-scanner, dependency-vulnerability, lint, formatting, or type-check coverage. Those tools are not configured in `pyproject.toml`; unsupported checks were not falsely reported as passed.

### M-02 — Live integrations are not verified

SMTP, live webhooks, and paid AI-provider calls were not exercised because no live secrets were provided. Their absence is recorded as `NOT VERIFIED`, not `PASS`.

## Resolved findings

### R-01 — Exact-head CI evidence was not previously recorded

**State:** The earlier report only recorded a successful pull-request merge workflow for the production fix SHA.

**Cause:** GitHub pull-request workflows test a synthetic merge ref, which is not exact-head evidence under the contract.

**Action:** Retrieved and verified the later `push` workflow run `30644200114` bound directly to `b25e7f7191345aeca8cfb6d46fab1fcf77dad8a4`.

**Result:** All three blocking jobs succeeded and uploaded their evidence artifacts. This resolves the exact-head-CI finding for the audited SHA.

### R-02 — `horizon-wizard --help` entered interactive mode and failed

**Initial evidence:** Workflow run `30643891828`, job `Build and clean wheel install`, step `Verify installed package outside checkout`.

Observed failure:

```text
horizon-wizard --help
EOFError: EOF when reading a line
exit code: 1
```

**Cause:** The `horizon-wizard` console entry point called the interactive wizard directly and did not parse standard CLI help arguments.

**Regression test:** `tests/test_wizard_cli.py`

**Test commit:** `0ab081228134712ad422b59734ac7f52c00b4d72`

**Minimal fix:** Added `src/setup/wizard_cli.py` as a non-interactive argparse boundary and routed only the existing console entry point through it.

**Fix commits:**

```text
83b6973ca6560236abfebd05e0d3c8a56438e252
fcd84797fcbd78feb011190aa9b2e7632319e172
```

**Result:** Final observed PR workflow completed package build, clean wheel installation, and console-script smoke tests successfully.

## CI results

### Full test suite

Exact command from the job:

```bash
python -m pytest --durations=20
```

Observed result on exact push SHA `b25e7f7191345aeca8cfb6d46fab1fcf77dad8a4`:

```text
472 passed in 6.45s
exit code: 0
Python: 3.11.15
Ubuntu: 24.04.4
```

### Package build and clean installation

Observed sequence:

```text
python -m build
created horizon-0.1.0.tar.gz
created horizon-0.1.0-py3-none-any.whl
installed wheel in /tmp/horizon-audit-venv
import src from site-packages
horizon --help
horizon-mcp --help
horizon-wizard --help
horizon-webhook --help
horizon-locales --help
python -m pip check
```

Result: success on exact push SHA `b25e7f7191345aeca8cfb6d46fab1fcf77dad8a4`.

### Publication hygiene job

The job recorded changed files, tracked files, largest tracked files, and rejected tracked runtime/private filename patterns. Result: success on the same PR merge SHA.

## Security review

Verified statically:

- only HTTP/HTTPS accepted by URL validator;
- URL credentials rejected;
- localhost explicitly rejected;
- all resolved IP addresses checked;
- private, loopback, link-local, multicast, reserved, and unspecified addresses rejected;
- redirect targets revalidated;
- redirect limit present;
- sensitive webhook headers redacted from preview/log output.

Not established:

- response-body size cap;
- connection pinning to previously validated DNS results;
- full dependency vulnerability scan;
- live SMTP/webhook/provider behavior.

## Packaging review

Verified by CI on the observed PR merge SHA:

- wheel and sdist build;
- wheel installation in a new virtual environment;
- import outside source checkout;
- all declared console-script help commands;
- dependency consistency through `pip check`;
- built-in profiles included through Hatch `force-include`.

No claim is made that external locale files are package data; the current localization design loads configured locale paths and requires separate contract review.

## Not verified integrations

```text
Live SMTP: NOT VERIFIED
Live webhook delivery: NOT VERIFIED
Paid AI providers: NOT VERIFIED
Docker release path: NOT VERIFIED / not established as blocking during this run
Exact-head push CI evidence for b25e7f7...: VERIFIED by run 30644200114
```

## Remaining risks

1. Confirm or replace the public governance contact in `SECURITY.md` and `CODE_OF_CONDUCT.md`.
2. Decide and implement the SSRF connection-pinning and response-size contract with tests.
3. Decide whether dependency vulnerability scanning is required before public publication.
4. Complete the remaining static contract review for storage, email, provider-chain, and localization edge cases before changing the verdict.

## Remaining work plan

1. Human owner confirms the canonical security/conduct contact.
2. Design review selects one SSRF-safe connection strategy and maximum response-size policy.
3. Add deterministic security tests before the minimal SSRF remediation.
4. Re-run every blocking job on the resulting exact SHA.
5. Update this report and PR body with the new commit-bound evidence.

## Automated release verdict

```text
NOT READY
```

Reasons:

- public governance contact is unconfirmed;
- the SSRF acceptance contract is not fully demonstrated;
- several release-critical integration/security areas remain `NOT VERIFIED`.

`READY` is reserved for human approval and has not been assigned.
