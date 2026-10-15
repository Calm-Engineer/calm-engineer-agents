# Development assurance (stub)

This repo is a pilot for a task-based, CI-checked workflow. This page lists what is enforced
today and nothing else.

## Status

**Nothing here is merge-blocking yet.** CI reports red or green on every pull request and push
to `main`, but no branch ruleset exists, so a failing check does not prevent a merge. This page
will be updated when the ruleset is enabled.

## Checks CI runs today (`.github/workflows/ci.yml`)

| Job | What it does |
|---|---|
| `lint` | `ruff check .` (rules E, F, I, B; line length 100). Two pre-existing import-order findings are ignored per file, with a comment in `pyproject.toml`. |
| `test` | `pytest`. Tests must run offline with no API keys. |
| `secret-scan` | gitleaks (pinned version, checksum-verified) over the full git history. |

CI uses read-only permissions and no secrets.

## Not enforced yet

- `ruff format --check` (deferred until the existing source is formatted).
- Any review automation, spec locking, or branch protection.
