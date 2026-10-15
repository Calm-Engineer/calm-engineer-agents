---
id: AGT-000
risk_tier: low        # low | med | high
status: draft         # draft | approved
owner: ""             # the human who approves this spec
context_files: []     # repo paths the reviewer should read, for example src/pkg/module.py
---

> This spec is human-owned. Claude Code must not edit it after `status` is `approved`.
> To change an approved spec, the owner makes the change in a separate spec-only pull request.

# Goal

One or two sentences: what changes, and why.

# Requirements

- **REQ-1:** <what the system must do>
- **REQ-2:** <...>

# Acceptance criteria

Each criterion is checkable by a test or by inspection.

- **AC-1:** <given / when / then>
- **AC-2 (negative):** <input or state that must be rejected or must not change anything>
- **AC-3 (negative):** <failure or missing-input case and the expected behaviour>
- **AC-4 (tenant isolation):** <placeholder: if the system serves more than one tenant or user,
  state that one tenant cannot read or modify another's data. Write "not applicable" and the
  reason if there is a single tenant.>

# Architecture refs

Links or repo paths to the design notes and code this task depends on.

# Out of scope

What this task deliberately does not do.
