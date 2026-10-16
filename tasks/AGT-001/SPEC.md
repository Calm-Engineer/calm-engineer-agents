---
id: AGT-001
risk_tier: med  # chosen to exercise the pipeline
status: draft
owner: ""       # the owner sets this when approving
context_files: [pyproject.toml, .github/workflows/ci.yml, docs/policy-stub.md, src/agentic_business_research/__init__.py, src/agentic_business_research/cli.py, src/agentic_business_research/config.py, src/agentic_business_research/prompts.py, src/agentic_business_research/workflow.py]
---

> This spec is human-owned. Claude Code must not edit it after `status` is `approved`.
> To change an approved spec, the owner makes the change in a separate spec-only pull request.

# Goal

Bring `src/` to the lint and format baseline the CI already describes: formatted with ruff, no
per-file lint ignores, and `ruff format --check` enforced in CI. The risk tier is "med" only to
exercise the review pipeline; the change itself is formatting and import order.

# Requirements

- **REQ-1:** Run `ruff format` over the repository, honouring the existing `extend-exclude`
  (`archive`, `notebooks`), so that `ruff format --check .` passes. Only files that command
  reports today are changed.
- **REQ-2:** Fix the two `I001` (unsorted imports) findings in
  `src/agentic_business_research/config.py` and `src/agentic_business_research/workflow.py`.
- **REQ-3:** Remove the `[tool.ruff.lint.per-file-ignores]` section and its comment from
  `pyproject.toml`, so `ruff check .` passes with no per-file ignores.
- **REQ-4:** Add `ruff format --check .` to the `lint` job in `.github/workflows/ci.yml` and
  remove the comment saying it is deferred.
- **REQ-5:** Update `docs/policy-stub.md` so lines 16 and 24 describe what is now enforced (no
  per-file ignores; `ruff format --check` is part of `lint`).

# Acceptance criteria

Each criterion is checkable by a test or by inspection.

- **AC-1:** All CI jobs (`lint`, `test`, `secret-scan`) are green on the pull request, including
  the new `ruff format --check .` step.
- **AC-2:** The existing tests pass with no change to any test's logic or assertions.
- **AC-3 (negative):** No behaviour change. The diff under `src/` consists only of formatting
  (whitespace, line wrapping, quote style, trailing commas) and import order within existing
  import blocks. Verified by inspecting the diff and by comparing each changed file's parsed
  syntax tree before and after, ignoring import order.
- **AC-4 (negative):** `archive/` and `notebooks/` are untouched: `git diff --name-only` against
  the base lists no path under either folder.
- **AC-5 (negative):** No new dependencies: no change to dependency declarations or requirements
  files, and no new install step in `ci.yml`.
- **AC-6 (negative):** No lint rule is loosened. The selected rules (`E`, `F`, `I`, `B`) and the
  line length (100) in `pyproject.toml` are unchanged, and no `noqa` comment is added.
- **AC-7 (tenant isolation):** Not applicable. This repository is single-tenant and the change
  touches formatting and CI configuration only; it reads or writes no tenant or user data.

# Architecture refs

- `pyproject.toml`: ruff configuration and the per-file-ignores comment to be removed.
- `.github/workflows/ci.yml`: the `lint` job and the deferral comment on line 24.
- `docs/policy-stub.md`: lines 16 and 24 describe the current, pre-change behaviour.
- `tasks/README.md`: task conventions.

# Out of scope

- Reformatting `archive/` or `notebooks/`.
- Changing the set of lint rules, the line length, or adding type checking.
- Any dependency change, or any behaviour change in `src/`.
- The spec-lock and reviewer work (PR2a, PR2b).
