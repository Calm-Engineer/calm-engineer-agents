---
id: GHG-001
risk_tier: high  # changes a merge-gating control
status: approved
owner: Calm-Engineer
context_files: [.github/workflows/spec-lock.yml, .github/scripts/spec_lock.py, .github/scripts/reviewlib.py, tests/test_spec_lock.py, tests/fixtures/spec_lock_cases.json]
---

> This spec is human-owned. Claude Code must not edit it after `status` is `approved`.
> To change an approved spec, the owner makes the change in a separate spec-only pull request.

# Goal

Make `spec-lock` require a human approval for any pull request that changes `.github/**`, using
the same approval-record mechanism that already protects SPEC changes. This lets `spec-lock`
become a required check without leaving workflow changes unmergeable.

# Requirements

- **REQ-1:** `classify` emits a second fixed output, `github`, that is `true` when any changed
  path (a rename's previous path included) is under `.github/` (case-insensitive, with the
  existing `..` guard), and `false` otherwise. The `kind` values are unchanged.
- **REQ-2:** A new job runs in the `human-merge` environment only when `github` is `true`.
- **REQ-3:** When `github` is `true`, `spec-lock` passes only if that job succeeded and
  `GET /repos/{owner}/{repo}/actions/runs/{run_id}/approvals` returns an `approved` record for
  `human-merge`. `require_approval` takes the environment name as a parameter; the
  `spec-approval` behaviour is unchanged.
- **REQ-4:** A pull request that touches `.github/**` and has a task folder needs both the
  existing task checks and the `human-merge` record. With no task folder it is still `invalid`.
- **REQ-5:** Tests and fixtures cover each rule above, offline.

# Acceptance criteria

- **AC-1:** A `.github/**` pull request passes `spec-lock` only after the owner approves
  `human-merge` for that run.
- **AC-2 (negative):** With no approval, a rejected deployment, a 403, an unexpected response
  shape or an approval for a different environment, `spec-lock` fails.
- **AC-3 (negative):** `.github/**` plus a path outside the no-task allowlist and no task folder
  fails.
- **AC-4 (negative):** Nothing PR-controlled is written to `GITHUB_OUTPUT` or `GITHUB_ENV`, no
  PR code is checked out, and no job gets a write permission.
- **AC-5 (negative):** `spec-approval` behaviour is unchanged and all existing tests still pass.
- **AC-5b:** A run passes human-merge only on an approved record for that run; a re-run does not
  pass without one.
- **AC-6 (tenant isolation):** not applicable; this is a single-owner repository.

# Architecture refs

`.github/workflows/spec-lock.yml`, `.github/scripts/spec_lock.py`, `.github/scripts/reviewlib.py`.

# Out of scope

- AGT-001's `ci.yml` change.
- The model reviewer (PR2b-2).
- Any ruleset change; the owner applies those separately.
