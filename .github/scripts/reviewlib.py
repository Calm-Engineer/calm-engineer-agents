"""Shared helpers for the git-bus checks.

Standard library only. GitHub access is read-only (GET). Every function that can fail
returns a Result; no path reports success unless every check passed.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import http.client
import json
import os
import re
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable, NamedTuple

API_HOST = "api.github.com"
HTTP_TIMEOUT_S = 20
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_FILE_BYTES = 256 * 1024
MAX_FRONT_MATTER_LINES = 40
MAX_LINE_CHARS = 300
MAX_PR_FILE_PAGES = 30  # 100 per page; GitHub lists at most 3000 files
MAX_CONTEXT_FILES = 50

TASK_ID_RE = re.compile(r"[A-Z]{2,6}-[0-9]{3,6}")
BRANCH_RE = re.compile(r"task/([A-Z]{2,6}-[0-9]{3,6})-([a-z0-9]+(?:-[a-z0-9]+)*)")
SHA256_RE = re.compile(r"[0-9a-f]{64}")
GIT_SHA_RE = re.compile(r"[0-9a-f]{40}")
OWNER_RE = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?")
REPO_RE = re.compile(r"[A-Za-z0-9._-]{1,100}")
BRANCH_NAME_RE = re.compile(r"[A-Za-z0-9._-]{1,100}")
TOKEN_RE = re.compile(r"[\x21-\x7e]{1,512}")  # printable ASCII, no whitespace
REPO_PATH_RE = re.compile(r"[A-Za-z0-9._-]+(?:/[A-Za-z0-9._-]+)*")
# "key: value", optionally followed by "  # comment" (two or more spaces before the #),
# which is how the templates write comments.
_KEY_LINE_RE = re.compile(r"([a-z][a-z0-9_]*):[ ]+(\S.*?)(?:[ ]{2,}#.*)?")


@dataclass(frozen=True)
class Result:
    ok: bool
    reason: str = ""
    value: Any = None
    code: int = 0  # HTTP status when the failure came from the API, else 0


def ok(value: Any = None) -> Result:
    return Result(True, "", value)


def fail(reason: str, code: int = 0) -> Result:
    return Result(False, sanitize(reason, 200) or "failed", None, code)


def is_absent(result: Result) -> bool:
    """True only for an API 404, so callers can tell 'no such file' from other failures."""
    return not result.ok and result.code == 404


# ---------------------------------------------------------------- sanitizer

_DROP_CATEGORIES = {"Cc", "Cf", "Cs", "Co", "Zl", "Zp"}


def _has_unsafe_chars(text: str) -> bool:
    return any(unicodedata.category(c) in _DROP_CATEGORIES for c in text)


def sanitize(text: object, limit: int = 2000) -> str:
    """Make untrusted text safe for logs and the step summary.

    Drops control and format characters and prefixes any line that could be read as a
    workflow command (`::...` or `##[...`) so it is printed, not executed.
    """
    lines = []
    raw = str(text).replace("\r\n", "\n").replace("\r", "\n").replace("\t", " ")
    for line in raw.split("\n"):
        line = "".join(c for c in line if unicodedata.category(c) not in _DROP_CATEGORIES)
        if line.lstrip().startswith(("::", "##[")):
            line = "| " + line
        lines.append(line)
    out = "\n".join(lines)
    return out if len(out) <= limit else out[:limit] + "...[truncated]"


# ------------------------------------------------------------- front matter


def is_safe_repo_path(path: str) -> bool:
    return (
        isinstance(path, str)
        and 0 < len(path) <= 200
        and REPO_PATH_RE.fullmatch(path) is not None
        and all(seg not in (".", "..") for seg in path.split("/"))
    )


def _enum(*allowed: str) -> Callable[[str], str]:
    def check(value: str) -> str:
        if value not in allowed:
            raise ValueError
        return value

    return check


def _pattern(rx: re.Pattern[str], allow_empty: bool = False) -> Callable[[str], str]:
    def check(value: str) -> str:
        if (allow_empty and value == "") or rx.fullmatch(value):
            return value
        raise ValueError

    return check


def _path_list(value: str) -> list[str]:
    """Flat inline list only: `[]` or `[a/b.py, c.py]`. No quotes, no nesting."""
    if value == "[]":
        return []
    m = re.fullmatch(r"\[([^\[\]]+)\]", value)
    if not m:
        raise ValueError
    items = [i.strip(" ") for i in m.group(1).split(",")]
    if len(items) > MAX_CONTEXT_FILES or len(set(items)) != len(items):
        raise ValueError
    if not all(is_safe_repo_path(i) for i in items):
        raise ValueError
    return items


# Empty ("") is accepted for sha and owner fields because the templates ship that way.
# Callers must treat an empty value as a failure wherever a real value is required.
TASK_SCHEMA: dict[str, Callable[[str], Any]] = {
    "id": _pattern(TASK_ID_RE),
    "branch": _pattern(BRANCH_RE),
    "spec_sha256": _pattern(SHA256_RE, allow_empty=True),
    "base_sha": _pattern(GIT_SHA_RE, allow_empty=True),
    "head_sha": _pattern(GIT_SHA_RE, allow_empty=True),
    "status": _enum("in-progress", "in-review", "done", "abandoned"),
}
SPEC_SCHEMA: dict[str, Callable[[str], Any]] = {
    "id": _pattern(TASK_ID_RE),
    "risk_tier": _enum("low", "med", "high"),
    "status": _enum("draft", "approved"),
    "owner": _pattern(OWNER_RE, allow_empty=True),
    "context_files": _path_list,
}


def parse_front_matter(data: bytes, schema: dict[str, Callable[[str], Any]]) -> Result:
    """Parse the `key: value` block at the very top of a TASK.md or SPEC.md.

    Every key in the schema must appear exactly once; anything else fails closed.
    On success `value` is a dict of validated values.
    """
    if not isinstance(data, bytes) or len(data) > MAX_FILE_BYTES:
        return fail("file missing or over the size cap")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return fail("file is not valid UTF-8")
    lines = text.split("\n")
    if lines[0] != "---":
        return fail("front matter must start on line 1 with ---")
    try:
        end = lines.index("---", 1)
    except ValueError:
        return fail("front matter has no closing ---")
    block = lines[1:end]
    if not block or len(block) > MAX_FRONT_MATTER_LINES:
        return fail("front matter is empty or too long")
    parsed: dict[str, Any] = {}
    for line in block:
        if len(line) > MAX_LINE_CHARS or "\t" in line or _has_unsafe_chars(line):
            return fail("front matter has a tab, control character or over-long line")
        m = _KEY_LINE_RE.fullmatch(line)
        if not m:
            return fail("front matter line is not a plain 'key: value'")
        key, raw = m.group(1), m.group(2)
        if key not in schema:
            return fail(f"front matter key not allowed: {key}")
        if key in parsed:
            return fail(f"duplicate key: {key}")
        try:
            parsed[key] = schema[key]("" if raw == '""' else raw)
        except ValueError:
            return fail(f"invalid value for {key}")
    missing = sorted(set(schema) - set(parsed))
    if missing:
        return fail("missing keys: " + ", ".join(missing))
    return ok(parsed)


# ------------------------------------------------------------- GitHub client


class _SameHostRedirects(urllib.request.HTTPRedirectHandler):
    """Follow redirects only to https://api.github.com so credentials never leave it."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        parts = urllib.parse.urlsplit(newurl)
        if parts.scheme != "https" or parts.hostname != API_HOST or parts.port not in (None, 443):
            raise urllib.error.HTTPError(req.full_url, code, "redirect refused", headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


# No proxies picked up from the environment; GET-only requests are built below.
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}), _SameHostRedirects)


def _read_token() -> Result:
    token = os.environ.get("GITHUB_TOKEN", "")
    if not TOKEN_RE.fullmatch(token):
        return fail("GITHUB_TOKEN is missing or malformed")  # never echo the value
    return ok(token)


def api_get(path: str, query: dict[str, Any] | None = None, *, opener: Any = None) -> Result:
    """GET https://api.github.com<path>. `value` is the decoded JSON body.

    On an HTTP error the Result's `code` is the status (404 means "not found").
    """
    token = _read_token()
    if not token.ok:
        return token
    if not path.startswith("/repos/"):
        return fail("refusing a non-repository API path")
    url = f"https://{API_HOST}{path}"
    if query:
        url += "?" + urllib.parse.urlencode(query)
    req = urllib.request.Request(
        url,
        method="GET",
        headers={
            "Authorization": "Bearer " + token.value,
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "git-bus-checks",
        },
    )
    try:
        with (opener or _OPENER).open(req, timeout=HTTP_TIMEOUT_S) as resp:
            if resp.status != 200:
                return fail(f"HTTP {resp.status}", resp.status)
            body = resp.read(MAX_RESPONSE_BYTES + 1)
    except urllib.error.HTTPError as exc:
        return fail(f"HTTP {exc.code}", exc.code)
    except (urllib.error.URLError, http.client.HTTPException, OSError, ValueError):
        return fail("network error")  # exception text can contain URLs; not reported
    if len(body) > MAX_RESPONSE_BYTES:
        return fail("response over the size cap")
    try:
        return ok(json.loads(body.decode("utf-8")))
    except (UnicodeDecodeError, ValueError):
        return fail("response is not valid JSON")


def _repo_base(owner: str, repo: str) -> Result:
    if not (isinstance(owner, str) and isinstance(repo, str)):
        return fail("invalid repository name")
    if not (OWNER_RE.fullmatch(owner) and REPO_RE.fullmatch(repo)) or repo in (".", ".."):
        return fail("invalid repository name")
    return ok(f"/repos/{owner}/{repo}")


def _valid_number(number: Any) -> bool:
    return isinstance(number, int) and not isinstance(number, bool) and 0 < number < 10**9


def get_pull(owner: str, repo: str, number: int) -> Result:
    base = _repo_base(owner, repo)
    if not base.ok:
        return base
    if not _valid_number(number):
        return fail("invalid pull request number")
    r = api_get(f"{base.value}/pulls/{number}")
    if r.ok and not isinstance(r.value, dict):
        return fail("unexpected pull request response")
    return r


def list_pull_files(owner: str, repo: str, number: int, expected_count: int) -> Result:
    """All changed files of a PR. Fails if the listing may be truncated."""
    base = _repo_base(owner, repo)
    if not base.ok:
        return base
    if not _valid_number(number) or not isinstance(expected_count, int):
        return fail("invalid pull request number or file count")
    files: list[Any] = []
    for page in range(1, MAX_PR_FILE_PAGES + 1):
        r = api_get(f"{base.value}/pulls/{number}/files", {"per_page": 100, "page": page})
        if not r.ok:
            return r
        if not isinstance(r.value, list):
            return fail("unexpected file listing response")
        files.extend(r.value)
        if len(r.value) < 100:
            if len(files) != expected_count:
                return fail("file listing does not match the PR's changed_files count")
            return ok(files)
    return fail("file listing hit the page limit and may be truncated")


def resolve_default_tip(owner: str, repo: str) -> Result:
    """Current commit SHA of the default branch (resolve once per run)."""
    base = _repo_base(owner, repo)
    if not base.ok:
        return base
    r = api_get(base.value)
    if not r.ok:
        return r
    branch = r.value.get("default_branch") if isinstance(r.value, dict) else None
    if not isinstance(branch, str) or not BRANCH_NAME_RE.fullmatch(branch):
        return fail("unexpected default branch name")
    c = api_get(f"{base.value}/commits/{urllib.parse.quote(branch, safe='')}")
    if not c.ok:
        return c
    sha = c.value.get("sha") if isinstance(c.value, dict) else None
    if not isinstance(sha, str) or not GIT_SHA_RE.fullmatch(sha):
        return fail("unexpected default branch commit")
    return ok(sha)


def get_file_bytes(owner: str, repo: str, path: str, ref: str) -> Result:
    """Bytes of `path` at the commit `ref`, exactly as the contents API returns them.

    A missing file gives a failing Result with code 404 (see is_absent).
    """
    base = _repo_base(owner, repo)
    if not base.ok:
        return base
    if not is_safe_repo_path(path) or not isinstance(ref, str) or not GIT_SHA_RE.fullmatch(ref):
        return fail("invalid path or ref (ref must be a full commit SHA)")
    r = api_get(f"{base.value}/contents/{urllib.parse.quote(path, safe='/')}", {"ref": ref})
    if not r.ok:
        return r
    v = r.value
    if not (
        isinstance(v, dict)
        and v.get("type") == "file"
        and v.get("encoding") == "base64"
        and v.get("path") == path
        and isinstance(v.get("content"), str)
        and isinstance(v.get("size"), int)
        and isinstance(v.get("sha"), str)
    ):
        return fail("unexpected contents response")
    try:
        raw = base64.b64decode(v["content"].replace("\n", ""), validate=True)
    except (binascii.Error, ValueError):
        return fail("file content is not valid base64")
    if len(raw) != v["size"]:
        return fail("file size does not match the API size")
    blob_sha = hashlib.sha1(b"blob %d\x00" % len(raw) + raw, usedforsecurity=False).hexdigest()
    if blob_sha != v["sha"]:
        return fail("file bytes do not match the git blob SHA")
    return ok(raw)


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def base_spec(owner: str, repo: str, task_id: str, base_sha: str) -> Result:
    """SPEC.md of a task at the base commit. `value` is (sha256 hex, raw bytes).

    A missing SPEC gives a failing Result with code 404; spec_lock.py decides whether
    that is acceptable (only for a brand-new SPEC in a spec-only PR).
    """
    if not isinstance(task_id, str) or not TASK_ID_RE.fullmatch(task_id):
        return fail("invalid task ID")
    r = get_file_bytes(owner, repo, f"tasks/{task_id}/SPEC.md", base_sha)
    if not r.ok:
        return r
    return ok((sha256_hex(r.value), r.value))


# ---------------------------------------------------------------- head guard


def read_event_head_sha() -> Result:
    """The head SHA the workflow event reported, passed in via the environment."""
    sha = os.environ.get("EVENT_HEAD_SHA", "")
    if not GIT_SHA_RE.fullmatch(sha):
        return fail("EVENT_HEAD_SHA is missing or malformed")
    return ok(sha)


def recheck_head(owner: str, repo: str, number: int, expected_sha: str) -> Result:
    """Fail if the PR head moved since the event fired. Call at the start and the end."""
    r = get_pull(owner, repo, number)
    if not r.ok:
        return r
    try:
        current = r.value["head"]["sha"]
    except (KeyError, TypeError):
        return fail("malformed pull request payload")
    if current != expected_sha:
        return fail("pull request head changed during the run")
    return ok(expected_sha)


# ------------------------------------------------------------ approval record

APPROVAL_ENVIRONMENT = "spec-approval"
_RUN_ID_RE = re.compile(r"[0-9]{1,20}")


def read_run_id() -> Result:
    """The current workflow run ID from the environment (ASCII digits only)."""
    raw = os.environ.get("RUN_ID", "")
    if not _RUN_ID_RE.fullmatch(raw) or int(raw) == 0:
        return fail("RUN_ID is missing or malformed")
    return ok(int(raw))


def require_approval(
    owner: str, repo: str, run_id: int, environment: str = APPROVAL_ENVIRONMENT
) -> Result:
    """Fail unless this run has an `approved` review record for `environment`.

    GitHub creates an unprotected environment if the named one does not exist, and a job
    in it then runs with no human click. That leaves no review record, so a missing
    record must fail closed. `value` is the approver's login, or "" if it is not a valid
    login.
    """
    base = _repo_base(owner, repo)
    if not base.ok:
        return base
    if not isinstance(run_id, int) or isinstance(run_id, bool) or not 0 < run_id < 10**20:
        return fail("invalid run ID")
    r = api_get(f"{base.value}/actions/runs/{run_id}/approvals")
    if not r.ok:
        return r
    if not isinstance(r.value, list):
        return fail("unexpected approvals response")
    for record in r.value:
        if not isinstance(record, dict):
            return fail("unexpected approvals response")
        envs = record.get("environments")
        if record.get("state") != "approved" or not isinstance(envs, list):
            continue
        if any(isinstance(e, dict) and e.get("name") == environment for e in envs):
            user = record.get("user")
            login = user.get("login") if isinstance(user, dict) else None
            return ok(login if isinstance(login, str) and OWNER_RE.fullmatch(login) else "")
    return fail(f"no approved review record for the {environment} environment on this run")


# ----------------------------------------------------------- classification

SPEC_ONLY = "spec-only"
IMPLEMENTATION = "implementation"
NO_TASK = "no-task"
INVALID = "invalid"

_TASK_DIR_RE = re.compile(r"tasks/([^/]+)/", re.IGNORECASE)
# Any task SPEC; the template folder is exempt (tasks/_template/SPEC.md).
_SPEC_FILE_RE = re.compile(r"tasks/(?!_template/)[^/]+/spec\.md", re.IGNORECASE)
# Paths a PR may touch with no task folder. Case-sensitive on purpose.
# .github/** is deliberately absent; how it is handled is decided in PR2b.
_NO_TASK_OK_RE = re.compile(r"docs/.+|[^/]+\.md|\.gitignore|\.gitattributes|tasks/_template/.+")


class Classification(NamedTuple):
    kind: str
    task_id: str
    reason: str
    spec_modified: bool


def _invalid(reason: str) -> Classification:
    return Classification(INVALID, "", sanitize(reason, 200), False)


def _no_task_allowed(path: str) -> bool:
    return ".." not in path.split("/") and _NO_TASK_OK_RE.fullmatch(path) is not None


def classify_pr(pr: Any, files: Any, event_head_sha: str) -> Classification:
    """Classify a PR from API data only. Anything unexpected is `invalid`."""
    try:
        head, base = pr["head"], pr["base"]
        head_repo, base_repo = head["repo"], base["repo"]
        ref, head_sha = head["ref"], head["sha"]
        head_id, base_id = head_repo["id"], base_repo["id"]
    except (KeyError, TypeError):
        return _invalid("malformed pull request payload")
    if not (isinstance(head_id, int) and isinstance(base_id, int)) or head_id != base_id:
        return _invalid("fork pull request or missing head repository")
    if not isinstance(ref, str) or not isinstance(head_sha, str):
        return _invalid("malformed head reference")
    if not GIT_SHA_RE.fullmatch(head_sha) or head_sha != event_head_sha:
        return _invalid("pull request head differs from the event head")
    if not isinstance(files, list) or not files:
        return _invalid("no changed files listed")

    paths: list[str] = []
    for f in files:
        if not isinstance(f, dict):
            return _invalid("malformed file entry")
        for key in ("filename", "previous_filename"):  # a rename away counts as a change
            p = f.get(key)
            if p is None and key == "previous_filename":
                continue
            if not isinstance(p, str) or not p or len(p) > 1024 or _has_unsafe_chars(p):
                return _invalid("malformed changed path")
            paths.append(p)

    folder_ids: set[str] = set()
    for p in paths:
        m = _TASK_DIR_RE.match(p)
        if m and m.group(1).lower() != "_template":
            if not TASK_ID_RE.fullmatch(m.group(1)):
                return _invalid("a tasks/ folder name is not a valid task ID")
            folder_ids.add(m.group(1))
    if len(folder_ids) > 1:
        return _invalid("pull request touches more than one task")

    branch_id = ""
    if ref.startswith("task/"):  # the branch name is only a lookup key
        m = BRANCH_RE.fullmatch(ref)
        if not m or len(ref) > 100:
            return _invalid("branch name does not match task/<ID>-<slug>")
        branch_id = m.group(1)
    if folder_ids and branch_id and folder_ids != {branch_id}:
        return _invalid("branch task ID differs from the tasks/ folder")

    task_id = next(iter(folder_ids), branch_id)
    spec_modified = any(_SPEC_FILE_RE.fullmatch(p) for p in paths)
    if not task_id:
        if all(_no_task_allowed(p) for p in paths):
            return Classification(NO_TASK, "", "task not required", spec_modified)
        return _invalid("changes outside docs/ and root files need a tasks/<ID>/ folder")

    prefix = f"tasks/{task_id}/".lower()
    spec_path = f"tasks/{task_id}/SPEC.md".lower()
    in_task = all(p.lower().startswith(prefix) for p in paths)
    spec_changed = any(p.lower() == spec_path for p in paths)
    kind = SPEC_ONLY if in_task and spec_changed else IMPLEMENTATION
    return Classification(kind, task_id, "", spec_modified)
