# Horizon Public Release Audit Contract

## Status

```text
CONTRACT: ACCEPTED
MODE: AUDIT-FIRST
REMEDIATION: MINIMAL AND BACKWARD-COMPATIBLE ONLY
AUTONOMOUS NIGHT RUN: APPROVED
FINAL HUMAN VERDICT: REQUIRED
```

## 1. Purpose

Determine, with commit-bound evidence, whether the current Horizon revision can be safely published and which release blockers remain.

The audit is not required to produce a `READY` result. It is required to establish the real state of the product without hiding failures or simulating success.

## 2. Repository Boundary

```text
Repository: iibaranov-IG/Horizon
Audit branch: audit/public-release-blockers
Audit baseline branch SHA: 35fd468
Audit baseline main SHA: f37ec60
Current audited SHA: recorded separately for every CI run and final report
```

The audit must not:

- modify `main`;
- merge into `main`;
- force-push;
- rewrite history;
- delete user data;
- commit secrets, local databases, dumps, logs, caches, build outputs, or private configuration;
- hide failures through fallback behavior;
- treat HTTP 200, an artifact, a branch name, or a local run on another SHA as proof of correctness.

Working principle:

```text
State -> Cause -> One action -> Result
```

## 3. Autonomous Change Boundary

The purpose of the night run is an evidence-driven audit with minimal remediation of confirmed release blockers.

Autonomous changes are allowed only when they are:

- local;
- minimal;
- backward-compatible;
- directly linked to a confirmed release blocker;
- covered by a regression test where technically applicable;
- free of public contract changes.

Without separate human approval, the executor must not:

- change the public API;
- change public CLI commands or required arguments;
- change the configuration schema;
- migrate user data;
- change storage layout;
- remove backward compatibility;
- perform a large refactor;
- perform a major dependency upgrade;
- rename public packages or modules;
- change file formats;
- change provider-selection policy;
- change output contracts;
- change the supported Python version matrix;
- change default behavior except when closing a confirmed security vulnerability with a clearly minimal fix.

If a blocker requires any prohibited change, the executor must document it as `CRITICAL` or `HIGH`, stop remediation for that blocker, and set the preliminary verdict to `NOT READY`.

## 4. Audit vs. Remediation

### May be fixed autonomously

- missing regression tests;
- incorrect exit codes;
- obvious unsafe path resolution with a local fix;
- missing timeout;
- secret leakage in logs;
- missing `.gitignore` rules;
- incorrect public configuration examples;
- CI workflow defects;
- documentation that contradicts actual behavior;
- explicit SSRF protections that do not require a public API change;
- narrow backward-compatible fixes for confirmed path traversal or unsafe overwrite defects.

### Must only be documented as blockers

- configuration schema changes;
- public CLI changes;
- storage layout changes;
- incompatible data migrations;
- removal of functionality;
- provider-policy changes;
- output-format changes;
- broad package restructuring;
- supported Python version changes;
- ambiguous fixes where multiple safe approaches would change product behavior differently.

## 5. Stop Conditions

Work stops without hidden workarounds when:

- required access is unavailable;
- CI evidence cannot be linked to an exact commit SHA;
- required secrets have not been explicitly provided;
- a blocker requires an incompatible or architectural change;
- remediation would touch or migrate user data;
- there is no unambiguous minimal safe fix;
- the maximum night changeset is reached;
- a baseline build or installation failure makes later checks meaningless;
- infrastructure prevents reproducible evidence;
- two reasonable fixes would alter product behavior differently.

Every stop condition must be recorded in the audit report. A stop condition must never be converted into a false `PASS`.

## 6. Night Changeset Limit

Maximum autonomous changes:

```text
8 thematic commits
500 changed lines of production code
15 changed production-code files
1 new workflow
0 major dependency upgrades
```

Tests and documentation do not count toward the production-line limit, but must not be duplicated artificially.

When the limit is reached, the executor must stop, write the remaining-work plan, and issue `NOT READY` or a candidate verdict with explicitly unresolved risks.

## 7. Evidence Model

Every item of evidence is valid only for one exact commit SHA.

```text
Evidence is valid only for commit <SHA>.
```

After any production-code change, the previous final audit verdict becomes invalid until every blocking CI job has completed again on the new SHA.

The following are not sufficient evidence:

- a branch name;
- HTTP 200;
- the existence of an artifact;
- a green workflow from an older SHA;
- a local successful run against a different revision;
- the existence of a WAV, output file, or generated object without semantic validation.

## 8. Audit Priority

The audit proceeds in this order:

0. Record baseline SHAs and clean repository state.
1. Secret and publication scan.
2. Clean package build and installation.
3. Existing full test suite without code changes.
4. Create or harden the audit workflow.
5. Obtain the first commit-bound CI run.
6. Verify configuration, path, and storage contracts.
7. Verify SSRF and network trust boundaries.
8. Verify CLI exit codes and error semantics.
9. Verify provider-chain behavior.
10. Verify email behavior.
11. Verify localization behavior.
12. Verify publication hygiene.
13. Apply only permitted minimal remediation.
14. Run full blocking CI on the final SHA.
15. Write the audit report.
16. Open a draft pull request.
17. Issue the preliminary automated verdict.

If a secret is exposed or the package cannot build/install, lower-priority cosmetic checks must not take precedence.

## 9. Required Audit Scope

### 9.1 Git integrity and publication hygiene

Verify:

- exact branch and commit state;
- diff against `main`;
- changed files and commits;
- accidental generated files, archives, databases, logs, credentials, private URLs, internal IPs, local paths, and large binaries;
- package metadata, license, README, security policy, contribution guidance, `.gitignore`, dependency declarations, lock files, badges, versions, and supported Python versions.

### 9.2 Configuration and path contracts

Verify behavior:

- from repository root;
- from an arbitrary working directory;
- through CLI;
- through MCP adapter;
- through webhook CLI;
- from an installed wheel;
- in Docker only when Docker is an advertised release path.

Relative paths must follow one explicit and consistent contract. Prefer paths relative to the configuration file location when that is the intended product contract.

Verify at least:

- config path;
- `profiles_dir`;
- locale paths;
- nested relative paths;
- repository-relative vs. config-relative vs. current-working-directory-relative behavior.

### 9.3 CLI contracts

Verify:

- module entry points;
- console scripts;
- `--help`;
- unknown arguments;
- required options;
- exit codes;
- stdout/stderr separation;
- missing and malformed configuration;
- missing files;
- invalid JSON;
- readable user-facing errors for expected failures.

### 9.4 Localization

Verify:

- language and locale loading;
- locale mode;
- missing locale files;
- malformed locale files;
- duplicate and missing keys;
- unsupported languages;
- development vs. production behavior;
- explicit fallback rules;
- consistency between code, tests, README, `docs/configuration.md`, `data/config.example.json`, and `data/config.github.json`.

Required locales must not silently degrade to another language in production unless that fallback is explicitly part of the public contract.

### 9.5 Profiles

Verify:

- `profiles_dir`;
- default profile;
- profile schema;
- missing and malformed profiles;
- unknown fields;
- inheritance if implemented;
- `tech-news` and `tech-blog` examples;
- installed-package access to required profile data.

### 9.6 Provider chain

Verify:

- provider order;
- retry limits;
- timeouts;
- throttling;
- first-provider failure;
- all-provider failure;
- malformed, partial, and empty responses;
- preservation of the real root cause;
- prevention of unbounded or unexpectedly repeated paid requests;
- absence of API keys in logs.

### 9.7 Storage and filesystem security

Verify:

- directory traversal;
- absolute paths;
- Windows and POSIX traversal forms;
- symbolic-link escape;
- overwrite policy;
- atomic writes;
- temporary-file handling;
- filename sanitization;
- duplicate names;
- encoding;
- permissions;
- confinement to the configured storage root.

### 9.8 Webhook and SSRF

Required behavior:

- allow only `http` and `https`;
- reject credentials in URLs;
- resolve hostnames before connection;
- validate every resolved address;
- reject private, loopback, link-local, and metadata-service targets;
- revalidate every redirect target;
- enforce a redirect limit;
- enforce connect and read timeouts;
- cap response size;
- reject unsupported protocols.

A string-only URL check is not sufficient SSRF protection.

### 9.9 Email

Verify:

- SMTP and STARTTLS behavior;
- connection cleanup;
- authentication failure;
- TLS failure;
- timeout behavior;
- recipient validation;
- header injection defenses;
- absence of credentials in logs.

### 9.10 Docker

Docker is blocking only when advertised as a supported release path.

When blocking, verify:

- `docker build`;
- startup without a bind mount;
- required locales and profiles inside the image;
- no secrets in image layers;
- non-root execution where practical;
- a minimal CLI smoke test;
- documented entry point and health behavior where applicable.

## 10. Network-Dependent Test Policy

### Required unit/security tests

- blocking;
- deterministic;
- no external network;
- mocks, fakes, or local test servers only.

### Live integration tests

- run only when secrets are explicitly provided;
- are never simulated with fake production credentials;
- absence of required live secrets is reported as `NOT VERIFIED`, never `PASS`;
- do not block the branch solely because external infrastructure is unavailable, unless the release contract explicitly requires that integration to be verified before publication.

## 11. CI Contract

Canonical workflow path:

```text
.github/workflows/public-release-audit.yml
```

Required triggers:

```yaml
on:
  push:
    branches:
      - audit/public-release-blockers
  pull_request:
    branches:
      - main
  workflow_dispatch:
```

Blocking jobs must not contain:

- `continue-on-error: true`;
- `|| true`;
- ignored exit codes;
- hidden fallbacks;
- `echo` substitutes for missing commands;
- a changed-files-only test subset in place of the required full suite.

Every job must have a timeout. CI must run in a clean checkout and must not depend on local user files, private configuration, or caches as the only source of correctness.

Expected blocking areas, when supported by the project configuration:

- unit tests;
- lint;
- formatting check;
- type checking;
- package build and clean installation;
- dependency consistency;
- security scan;
- path-contract tests.

A tool not configured by the project must not be added merely to create noise. Unsupported checks must be documented, not falsely reported as passed.

## 12. Package Acceptance

A successful source-tree test run is insufficient.

Required sequence:

1. Build wheel and sdist.
2. Create a clean environment.
3. Install the wheel.
4. Ensure imports do not resolve from the source checkout.
5. Import the package.
6. Run every required console script with `--help`.
7. Perform minimal configuration validation.
8. Run from an arbitrary working directory.
9. Verify required package data, including locales and profiles.
10. Run dependency consistency checks such as `pip check`.

## 13. Dependency Policy

- No major dependency upgrades during the night run.
- Patch or minor upgrades are allowed only when they are the smallest safe response to a confirmed blocker and the full test suite passes.
- Lock files must not be regenerated without necessity.
- A vulnerability without a minimal safe upgrade path is documented as a blocker.

## 14. Canonical Locations

```text
Production code: src/
Tests: tests/
Workflow: .github/workflows/public-release-audit.yml
Permanent contract: docs/audits/public-release-audit-contract.md
Permanent audit report: docs/audits/public-release-blockers.md
Public configuration examples: data/config.example.json, data/config.github.json
Profiles: profiles/
Locales: locales/
Heavy logs and generated evidence: GitHub Actions artifacts
Discussion and human acceptance: Draft Pull Request
```

Do not create parallel temporary source trees such as `src_new`, `src_fixed`, or `src_backup`.

Do not commit full CI logs, caches, virtual environments, local databases, private config, secrets, `build/`, or `dist/` outputs. Build outputs belong in workflow artifacts.

## 15. Commit Policy

Commits must be small and thematic, for example:

```text
test(config): cover config-relative path resolution
fix(config): resolve relative paths from config location
test(i18n): cover missing and malformed locales
fix(i18n): validate production locale completeness
test(security): cover webhook private-network redirects
fix(webhook): block private redirect targets
ci(audit): add public release verification workflow
docs(audit): document release blockers and evidence
```

Avoid commits such as `fix everything`, `final changes`, or `audit`.

Prefer:

```text
regression test -> minimal fix -> commit-bound CI evidence
```

## 16. Audit Report

Canonical report:

```text
docs/audits/public-release-blockers.md
```

Required sections:

- Scope;
- Baseline;
- Current audited SHA;
- Evidence;
- Critical blockers;
- High-priority findings;
- Medium-priority findings;
- Resolved findings;
- CI results;
- Security review;
- Packaging review;
- Not verified integrations;
- Remaining risks;
- Preliminary release verdict.

The report must name the exact commit SHA, exact commands or CI jobs, actual results, and fixing commits. It must not claim `PASS` without evidence.

## 17. Pull Request

Open a draft pull request:

```text
audit/public-release-blockers -> main
```

The PR must not be merged automatically.

The PR description must state:

- what was checked;
- what was found;
- what was fixed;
- which checks passed;
- which checks failed;
- what remains unverified;
- the current audited SHA;
- the preliminary release verdict.

## 18. Verdict Model

The automated executor may issue only:

```text
READY CANDIDATE
READY CANDIDATE WITH NON-BLOCKING RISKS
NOT READY
```

Final public release approval is human-owned.

Only a human reviewer may assign:

```text
READY
```

Human approval must review the final SHA, full blocking CI, audit report, diff, and remaining risks.

## 19. Final Locked State

```text
SCOPE: LOCKED
SAFETY BOUNDARY: DEFINED
STOP CONDITIONS: DEFINED
EVIDENCE MODEL: DEFINED
CI CONTRACT: DEFINED
REMEDIATION BOUNDARY: DEFINED
HUMAN APPROVAL GATE: DEFINED
NIGHT RUN: APPROVED
```
