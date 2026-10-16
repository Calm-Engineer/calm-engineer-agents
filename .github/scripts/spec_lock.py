"""spec-lock: keep an approved SPEC.md immutable once work starts.

Read-only. Classifies a pull request from API data, then checks the SPEC hash recorded in
TASK.md against the SPEC on the default branch. Every error path is a failing result.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Callable, NamedTuple

import reviewlib as lib

KINDS = (lib.SPEC_ONLY, lib.IMPLEMENTATION, lib.NO_TASK, lib.INVALID)
APPROVAL_VALUES = ("success", "failure", "cancelled", "skipped")
FIXTURES = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "spec_lock_cases.json"
MAX_FIXTURE_BYTES = 1024 * 1024

# task_id -> Result(value=(sha256 hex, bytes)) read from the default branch tip
BaseSpec = Callable[[str], lib.Result]
# repo path -> Result(value=bytes) read at the PR head commit
HeadFile = Callable[[str], lib.Result]
# () -> Result(value=approver login): does this run have a real "approved" review record?
VerifyApproval = Callable[[], lib.Result]


class Verdict(NamedTuple):
    ok: bool
    message: str


def _pass(message: str) -> Verdict:
    return Verdict(True, lib.sanitize(message, 300))


def _fail(message: str) -> Verdict:
    return Verdict(False, lib.sanitize(message, 300))


def _parse_spec(raw: bytes, task_id: str) -> lib.Result:
    parsed = lib.parse_front_matter(raw, lib.SPEC_SCHEMA)
    if parsed.ok and parsed.value["id"] != task_id:
        return lib.fail("SPEC id does not match the task folder")
    return parsed


def _decide_spec_only(
    cls: lib.Classification,
    approval: str,
    base_spec: BaseSpec,
    head_file: HeadFile,
    verify_approval: VerifyApproval | None,
) -> Verdict:
    if approval != "success":
        return _fail("spec-only pull request: waiting for spec-approval")
    if verify_approval is None:
        return _fail("spec-approval was not verified against the run's review record")
    record = verify_approval()
    if not record.ok:
        return _fail(f"no verified spec-approval record: {record.reason}")
    base = base_spec(cls.task_id)
    # A SPEC absent at base is allowed here (a brand-new task); any other error is not.
    if not base.ok and not lib.is_absent(base):
        return _fail(f"cannot read the base SPEC: {base.reason}")
    head = head_file(f"tasks/{cls.task_id}/SPEC.md")
    if not head.ok:
        return _fail(f"cannot read the SPEC at head: {head.reason}")
    parsed = _parse_spec(head.value, cls.task_id)
    if not parsed.ok:
        return _fail(f"SPEC at head is invalid: {parsed.reason}")
    who = record.value or "unknown"
    return _pass(f"spec-only pull request approved via spec-approval by {who}")


def _decide_implementation(
    cls: lib.Classification, base_spec: BaseSpec, head_file: HeadFile
) -> Verdict:
    if cls.spec_modified:
        return _fail("implementation pull request modifies a SPEC.md")
    base = base_spec(cls.task_id)
    if not base.ok:
        if lib.is_absent(base):
            return _fail("no SPEC on the default branch (absence is only allowed for spec-only)")
        return _fail(f"cannot read the base SPEC: {base.reason}")
    spec_hash, spec_bytes = base.value
    spec = _parse_spec(spec_bytes, cls.task_id)
    if not spec.ok:
        return _fail(f"base SPEC is invalid: {spec.reason}")
    if spec.value["status"] != "approved":
        return _fail("base SPEC is not status: approved")
    task = head_file(f"tasks/{cls.task_id}/TASK.md")
    if not task.ok:
        return _fail(f"cannot read TASK.md at head: {task.reason}")
    front = lib.parse_front_matter(task.value, lib.TASK_SCHEMA)
    if not front.ok:
        return _fail(f"TASK.md is invalid: {front.reason}")
    if front.value["id"] != cls.task_id:
        return _fail("TASK.md id does not match the task folder")
    recorded = front.value["spec_sha256"]
    if recorded == "":
        return _fail("TASK.md spec_sha256 is empty (unfilled template?)")
    if recorded != spec_hash:
        return _fail("TASK.md spec_sha256 does not match the approved SPEC on the default branch")
    return _pass(f"SPEC hash matches the approved SPEC ({spec_hash[:12]})")


def decide(
    cls: lib.Classification,
    approval: str,
    base_spec: BaseSpec,
    head_file: HeadFile,
    verify_approval: VerifyApproval | None = None,
) -> Verdict:
    """The spec-lock verdict for one classified pull request."""
    if cls.kind == lib.INVALID:
        return _fail(f"invalid pull request: {cls.reason}")
    if cls.kind == lib.NO_TASK:
        if cls.spec_modified:
            return _fail("a SPEC was modified but no task was resolved")
        return _pass("not required: no task involved")
    if cls.kind == lib.SPEC_ONLY:
        return _decide_spec_only(cls, approval, base_spec, head_file, verify_approval)
    if cls.kind == lib.IMPLEMENTATION:
        return _decide_implementation(cls, base_spec, head_file)
    return _fail("unknown classification")


# ------------------------------------------------------------------ reporting


def _env(name: str) -> str:
    return os.environ.get(name, "")


def _report(lines: list[str]) -> None:
    text = lib.sanitize("\n".join(lines), 4000)
    print(text)
    path = _env("GITHUB_STEP_SUMMARY")
    if path:
        try:
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(text + "\n")
        except OSError:
            pass  # the exit code, not the summary, carries the verdict


def _stop(message: str) -> int:
    _report([f"FAIL: {message}"])
    return 1


# --------------------------------------------------------------- live commands


def _inputs() -> lib.Result:
    sha = lib.read_event_head_sha()
    if not sha.ok:
        return sha
    number = _env("PR_NUMBER")
    if not re.fullmatch(r"[0-9]{1,9}", number) or int(number) == 0:
        return lib.fail("PR_NUMBER is missing or malformed")
    owner, _, repo = _env("GITHUB_REPOSITORY").partition("/")  # reviewlib validates both
    return lib.ok({"owner": owner, "repo": repo, "number": int(number), "sha": sha.value})


def _classify(inp: dict[str, Any]) -> lib.Result:
    """Fetch the PR and classify it. `value` is a Classification."""
    pr = lib.get_pull(inp["owner"], inp["repo"], inp["number"])
    if not pr.ok:
        return pr
    count = pr.value.get("changed_files")
    if not isinstance(count, int):
        return lib.fail("pull request has no changed_files count")
    files = lib.list_pull_files(inp["owner"], inp["repo"], inp["number"], count)
    if not files.ok:
        return files
    return lib.ok(lib.classify_pr(pr.value, files.value, inp["sha"]))


def cmd_classify() -> int:
    inp = _inputs()
    if not inp.ok:
        return _stop(inp.reason)
    res = _classify(inp.value)
    if not res.ok:
        return _stop(res.reason)
    cls = res.value
    out = _env("GITHUB_OUTPUT")
    if cls.kind not in KINDS or not out:
        return _stop("cannot publish the classification")
    try:
        with open(out, "a", encoding="utf-8") as fh:
            fh.write(f"kind={cls.kind}\n")  # fixed enum only; nothing PR-controlled
    except OSError:
        return _stop("cannot write the job output")
    _report([f"classification: {cls.kind}" + (f" ({cls.reason})" if cls.reason else "")])
    return 0  # `invalid` is enforced by the spec-lock job, not here


def cmd_check() -> int:
    inp = _inputs()
    if not inp.ok:
        return _stop(inp.reason)
    i = inp.value
    if _env("CLASSIFY_RESULT") != "success":
        return _stop("the classify job did not succeed")
    expected = _env("CLASSIFY_KIND")
    if expected not in KINDS:
        return _stop("CLASSIFY_KIND is missing or not a known kind")
    approval = _env("APPROVAL_RESULT") or "skipped"
    if approval not in APPROVAL_VALUES:
        return _stop("APPROVAL_RESULT is not a known value")
    run_id = lib.read_run_id()
    if not run_id.ok:
        return _stop(run_id.reason)

    tip = lib.resolve_default_tip(i["owner"], i["repo"])  # once per run
    if not tip.ok:
        return _stop(f"cannot resolve the default branch: {tip.reason}")
    res = _classify(i)
    if not res.ok:
        return _stop(res.reason)
    cls = res.value
    if cls.kind != expected:
        return _stop("classification changed between jobs")

    verdict = decide(
        cls,
        approval,
        lambda task_id: lib.base_spec(i["owner"], i["repo"], task_id, tip.value),
        lambda path: lib.get_file_bytes(i["owner"], i["repo"], path, i["sha"]),
        lambda: lib.require_approval(i["owner"], i["repo"], run_id.value),
    )
    end = lib.recheck_head(i["owner"], i["repo"], i["number"], i["sha"])
    if not end.ok:
        return _stop(end.reason)
    _report([f"{'PASS' if verdict.ok else 'FAIL'} [{cls.kind}]: {verdict.message}"])
    return 0 if verdict.ok else 1


# --------------------------------------------------------------------- dry run


def build_case(case: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]], str]:
    """Expand a compact fixture case into (pull request payload, files, event head SHA)."""
    head_sha = case.get("head_sha", "1" * 40)
    pr = {
        "head": {"ref": case["ref"], "sha": head_sha, "repo": {"id": 2 if case.get("fork") else 1}},
        "base": {"repo": {"id": 1}},
    }
    files = [
        {"filename": f} if isinstance(f, str) else {"filename": f[0], "previous_filename": f[1]}
        for f in case["files"]
    ]
    return pr, files, case.get("event_head_sha", head_sha)


def run_case(case: dict[str, Any]) -> Verdict:
    """Run one fixture case offline. `{SPEC_SHA256}` in head files is the base SPEC's hash."""
    pr, files, event_sha = build_case(case)
    cls = lib.classify_pr(pr, files, event_sha)
    base_text = case.get("base_spec")
    spec_hash = lib.sha256_hex(base_text.encode("utf-8")) if isinstance(base_text, str) else ""

    def base_spec(task_id: str) -> lib.Result:
        if case.get("base_spec_error"):
            return lib.fail("HTTP 500", 500)
        if not isinstance(base_text, str):
            return lib.fail("HTTP 404", 404)
        return lib.ok((spec_hash, base_text.encode("utf-8")))

    def head_file(path: str) -> lib.Result:
        text = case.get("head", {}).get(path)
        if not isinstance(text, str):
            return lib.fail("HTTP 404", 404)
        return lib.ok(text.replace("{SPEC_SHA256}", spec_hash).encode("utf-8"))

    def verify_approval() -> lib.Result:
        if case.get("approval_record", True) is not True:
            return lib.fail("no approved review record for the spec-approval environment")
        return lib.ok("fixture-approver")

    return decide(cls, case.get("approval", "skipped"), base_spec, head_file, verify_approval)


def cmd_dry_run() -> int:
    try:
        data = FIXTURES.read_bytes()
        if len(data) > MAX_FIXTURE_BYTES:
            return _stop("fixture file over the size cap")
        cases = json.loads(data.decode("utf-8"))
    except (OSError, ValueError):
        return _stop("cannot read the fixture file")
    if not isinstance(cases, list) or not cases:
        return _stop("fixture file has no cases")
    lines = ["| case | verdict | expected | message | match |", "|---|---|---|---|---|"]
    mismatches = 0
    for case in cases:
        try:
            name = lib.sanitize(case["name"], 60)
            expect = case["expect"]
            verdict = run_case(case)
            got = "pass" if verdict.ok else "fail"
            matched = got == expect and case.get("expect_text", "") in verdict.message
            message = verdict.message.replace("|", "/")
        except (KeyError, TypeError, AttributeError):
            name, got, expect, message, matched = "malformed case", "-", "-", "-", False
        mismatches += 0 if matched else 1
        lines.append(
            f"| {name} | {got} | {expect} | {message} | {'ok' if matched else 'MISMATCH'} |"
        )
    lines.append(f"\n{len(cases)} cases, {mismatches} mismatches")
    _report(lines)
    return 0 if mismatches == 0 else 1


COMMANDS = {"classify": cmd_classify, "check": cmd_check, "dry-run": cmd_dry_run}


def main(argv: list[str]) -> int:
    if len(argv) != 2 or argv[1] not in COMMANDS:
        print("usage: spec_lock.py classify|check|dry-run", file=sys.stderr)
        return 2
    try:
        return COMMANDS[argv[1]]()
    except Exception as exc:  # fail closed; the type name only, never the message
        return _stop(f"unexpected {type(exc).__name__}")


if __name__ == "__main__":
    sys.exit(main(sys.argv))
