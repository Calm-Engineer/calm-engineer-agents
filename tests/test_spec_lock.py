"""Offline tests for the spec-lock checks (reviewlib.py and spec_lock.py).

No test may reach the network: an autouse fixture makes every socket and urllib entry
point raise, and API-facing tests install a fake opener instead.
"""

import base64
import hashlib
import io
import json
import socket
import urllib.error
import urllib.request
from pathlib import Path
from types import SimpleNamespace

import pytest
import reviewlib as lib
import spec_lock

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_FILE = REPO_ROOT / "tests" / "fixtures" / "spec_lock_cases.json"
CASES = json.loads(FIXTURE_FILE.read_text(encoding="utf-8"))
SHA = "1" * 40
OTHER_SHA = "2" * 40
RUN_ID = 12345678901
OTHER_RUN_ID = 98765432109
FAKE_TOKEN = "fake-token-for-unit-tests-only"


# ------------------------------------------------------------------- helpers


def spec_bytes(task_id="AGT-001", status="approved", extra=""):
    return (
        "---\n"
        f"id: {task_id}\n"
        "risk_tier: med  # chosen to exercise the pipeline\n"
        f"status: {status}\n"
        'owner: ""\n'
        "context_files: []\n"
        f"{extra}---\n\n# Goal\n\nTest spec.\n"
    ).encode()


def task_bytes(spec_sha, task_id="AGT-001"):
    """`spec_sha` is written verbatim; pass '""' for the unfilled-template value."""
    return (
        "---\n"
        f"id: {task_id}\n"
        f"branch: task/{task_id}-baseline\n"
        f"spec_sha256: {spec_sha}\n"
        'base_sha: ""\n'
        'head_sha: ""\n'
        "status: in-progress\n"
        "---\n\n# Status log\n"
    ).encode()


def contents_json(file_path, raw, **override):
    blob = hashlib.sha1(b"blob %d\x00" % len(raw) + raw).hexdigest()
    body = {
        "type": "file",
        "encoding": "base64",
        "path": file_path,
        "content": base64.encodebytes(raw).decode(),
        "size": len(raw),
        "sha": blob,
    }
    body.update(override)
    return json.dumps(body).encode()


def page(count):
    return json.dumps([{"filename": f"f{i}.md"} for i in range(count)]).encode()


def approval_record(state="approved", env="spec-approval"):
    return {
        "state": state,
        "user": {"login": "Calm-Engineer"},
        "environments": [{"name": env}],
        "comment": "",
    }


def approvals(*records):
    return json.dumps(list(records)).encode()


def http_error(code):
    return urllib.error.HTTPError("https://api.github.com/x", code, "err", {}, io.BytesIO(b""))


class FakeResponse:
    def __init__(self, body, status=200):
        self.body, self.status = body, status

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self, n=-1):
        return self.body if n < 0 else self.body[:n]


class FakeOpener:
    """Queue of canned results: bytes (a 200 body), (status, bytes), or an exception."""

    def __init__(self, *queue):
        self.queue, self.requests = list(queue), []

    def open(self, req, timeout=None):
        self.requests.append(req)
        item = self.queue.pop(0)
        if isinstance(item, BaseException):
            raise item
        if isinstance(item, tuple):
            return FakeResponse(item[1], item[0])
        return FakeResponse(item)


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError("network access attempted in a test")

    monkeypatch.setattr(socket, "getaddrinfo", blocked)
    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(urllib.request, "urlopen", blocked)
    monkeypatch.setattr(lib._OPENER, "open", blocked)


@pytest.fixture
def token(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", FAKE_TOKEN)
    return FAKE_TOKEN


@pytest.fixture
def api(monkeypatch, token):
    """Install a FakeOpener with the given queue in place of the real opener."""

    def install(*queue):
        opener = FakeOpener(*queue)
        monkeypatch.setattr(lib, "_OPENER", opener)
        return opener

    return install


def test_network_guard_blocks_every_entry_point(token):
    with pytest.raises(AssertionError):
        socket.getaddrinfo("example.invalid", 443)
    with socket.socket() as sock, pytest.raises(AssertionError):
        sock.connect(("127.0.0.1", 9))
    with pytest.raises(AssertionError):
        urllib.request.urlopen("https://example.invalid/")
    with pytest.raises(AssertionError):  # the real opener, reached through api_get
        lib.api_get("/repos/o/r")


# ------------------------------------------------------------- front matter


def test_valid_spec_and_task_parse():
    spec = lib.parse_front_matter(spec_bytes(), lib.SPEC_SCHEMA)
    assert spec.ok
    assert spec.value["risk_tier"] == "med"
    assert spec.value["owner"] == ""
    assert spec.value["context_files"] == []
    task = lib.parse_front_matter(task_bytes("a" * 64), lib.TASK_SCHEMA)
    assert task.ok
    assert task.value["spec_sha256"] == "a" * 64


@pytest.mark.parametrize(
    ("name", "schema"),
    [("SPEC.md", lib.SPEC_SCHEMA), ("TASK.md", lib.TASK_SCHEMA)],
)
def test_repo_templates_parse(name, schema):
    data = (REPO_ROOT / "tasks" / "_template" / name).read_bytes()
    data = data.replace(b"\r\n", b"\n")  # a Windows checkout may predate .gitattributes
    assert lib.parse_front_matter(data, schema).ok


REJECTED_FRONT_MATTER = {
    "duplicate key": spec_bytes(extra="status: draft\n"),
    "unknown key": spec_bytes(extra="extra: 1\n"),
    "missing key": spec_bytes().replace(b'owner: ""\n', b""),
    "missing closing fence": b"---\nid: AGT-001\nrisk_tier: med\n",
    "no opening fence": b"id: AGT-001\n---\n",
    "byte order mark": b"\xef\xbb\xbf" + spec_bytes(),
    "tab": spec_bytes().replace(b"risk_tier: med", b"risk_tier:\tmed"),
    "carriage return": spec_bytes().replace(b"\n", b"\r\n"),
    "not utf-8": b"---\nid: \xff\n---\n",
    "oversize": spec_bytes() + b"x" * lib.MAX_FILE_BYTES,
    "single-space comment": spec_bytes().replace(b"med  #", b"med #"),
    "bad enum": spec_bytes().replace(b"risk_tier: med", b"risk_tier: huge"),
    "bad id": spec_bytes(task_id="agt-1"),
    "nested value": spec_bytes().replace(b"context_files: []\n", b"context_files:\n  - a.py\n"),
    "empty value": spec_bytes().replace(b'owner: ""', b"owner:"),
    "blank line inside": spec_bytes().replace(b"status: approved\n", b"\nstatus: approved\n"),
    "control character": spec_bytes().replace(b'owner: ""', b'owner: ""  # a\x07b'),
    "empty front matter": b"---\n---\n",
}


@pytest.mark.parametrize(
    "data",
    REJECTED_FRONT_MATTER.values(),
    ids=REJECTED_FRONT_MATTER.keys(),
)
def test_front_matter_rejections(data):
    result = lib.parse_front_matter(data, lib.SPEC_SCHEMA)
    assert not result.ok
    assert result.reason


def test_front_matter_must_be_bytes():
    assert not lib.parse_front_matter("---\n---\n", lib.SPEC_SCHEMA).ok


@pytest.mark.parametrize(
    "sha",
    ["A" * 64, "a" * 63, "a" * 65, "g" * 64, "'" + "a" * 64 + "'"],
)
def test_bad_spec_sha256_rejected(sha):
    assert not lib.parse_front_matter(task_bytes(sha), lib.TASK_SCHEMA).ok


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("status", "done-ish"),
        ("branch", "feature/x"),
        ("base_sha", "abc"),
        ("head_sha", "Z" * 40),
    ],
)
def test_bad_task_values_rejected(field, value):
    lines = task_bytes("a" * 64).decode().splitlines(keepends=True)
    text = "".join(f"{field}: {value}\n" if ln.startswith(field + ":") else ln for ln in lines)
    assert not lib.parse_front_matter(text.encode(), lib.TASK_SCHEMA).ok


def _with_context_files(value):
    return spec_bytes().replace(b"context_files: []", f"context_files: {value}".encode())


@pytest.mark.parametrize(
    "value",
    [
        "[]",
        "[a.py]",
        "[a.py, b/c.py]",
        "[ a.py ,b.py ]",
        "[" + ", ".join(map(str, range(50))) + "]",
    ],
)
def test_context_files_accepted(value):
    assert lib.parse_front_matter(_with_context_files(value), lib.SPEC_SCHEMA).ok


@pytest.mark.parametrize(
    "value",
    [
        "[../x.py]",
        "[/abs.py]",
        "[a.py, a.py]",
        '["a.py"]',
        "[a.py,]",
        "[[a]]",
        "a.py",
        '""',
        "[a b.py]",
        "[.]",
        "[a//b.py]",
        "[" + ", ".join(map(str, range(51))) + "]",
    ],
)
def test_context_files_rejected(value):
    assert not lib.parse_front_matter(_with_context_files(value), lib.SPEC_SCHEMA).ok


# ---------------------------------------------------------------- sanitizer


@pytest.mark.parametrize(
    "text",
    [
        "::error::x",
        "  ::set-output name=a::b",
        "##[group]x",
        "ok\n::warning::y",
        ":\u200b:error::z",
        "a\r::b",
        "\t::c",
    ],
)
def test_sanitizer_neutralizes_workflow_commands(text):
    for line in lib.sanitize(text).split("\n"):
        assert not line.lstrip().startswith(("::", "##["))


def test_sanitizer_keeps_the_text_visible():
    assert lib.sanitize("::error::x") == "| ::error::x"
    assert lib.sanitize("plain") == "plain"


def test_sanitizer_strips_control_and_format_characters():
    assert lib.sanitize("a\x1b[31mb\x00c\u202ed") == "a[31mbcd"
    assert lib.sanitize("a\tb") == "a b"


def test_sanitizer_truncates():
    assert lib.sanitize("a" * 500, 100) == "a" * 100 + "...[truncated]"


def test_fail_reason_is_sanitized():
    assert lib.fail("::bad").reason == "| ::bad"
    assert lib.fail("").reason == "failed"
    assert not lib.fail("x").ok


# ------------------------------------------------------------- GitHub client


def test_get_file_bytes_returns_exact_bytes(api, token):
    raw = b"line1\r\nline2\n" + bytes(range(256))
    opener = api(contents_json("tasks/AGT-001/SPEC.md", raw))
    result = lib.get_file_bytes("o", "r", "tasks/AGT-001/SPEC.md", SHA)
    assert result.ok
    assert result.value == raw
    req = opener.requests[0]
    expected_url = f"https://api.github.com/repos/o/r/contents/tasks/AGT-001/SPEC.md?ref={SHA}"
    assert req.get_method() == "GET"
    assert req.full_url == expected_url
    assert req.get_header("Authorization") == "Bearer " + token


@pytest.mark.parametrize(
    ("override", "reason"),
    [
        ({"content": "!!!not base64!!!"}, "not valid base64"),
        ({"size": 999}, "size"),
        ({"sha": "0" * 40}, "blob SHA"),
        ({"type": "dir"}, "unexpected contents response"),
        ({"encoding": "none"}, "unexpected contents response"),
        ({"path": "other/file"}, "unexpected contents response"),
    ],
)
def test_get_file_bytes_rejects_bad_responses(api, override, reason):
    api(contents_json("a/b.md", b"hello", **override))
    result = lib.get_file_bytes("o", "r", "a/b.md", SHA)
    assert not result.ok
    assert reason in result.reason


@pytest.mark.parametrize(
    ("path", "ref"),
    [("../x", SHA), ("/abs", SHA), ("a b", SHA), ("a/b.md", "main"), ("a/b.md", SHA[:-1])],
)
def test_get_file_bytes_rejects_bad_inputs_before_any_request(token, path, ref):
    assert not lib.get_file_bytes("o", "r", path, ref).ok  # the guard would raise on a request


def test_is_absent_only_for_404(api):
    api(http_error(404))
    missing = lib.get_file_bytes("o", "r", "a/b.md", SHA)
    assert missing.code == 404
    assert lib.is_absent(missing)
    api(contents_json("a/b.md", b"x"))
    assert not lib.is_absent(lib.get_file_bytes("o", "r", "a/b.md", SHA))


@pytest.mark.parametrize("code", [301, 302, 403, 422, 500])
def test_other_http_errors_are_not_absent(api, code):
    api(http_error(code))
    result = lib.get_file_bytes("o", "r", "a/b.md", SHA)
    assert not result.ok
    assert result.code == code
    assert not lib.is_absent(result)


def test_network_error_is_not_absent(api):
    api(OSError("boom"))
    result = lib.get_file_bytes("o", "r", "a/b.md", SHA)
    assert not result.ok
    assert not lib.is_absent(result)


def test_redirect_handler_refuses_cross_host_and_downgrades():
    handler = lib._SameHostRedirects()
    req = urllib.request.Request("https://api.github.com/repos/o/r", method="GET")
    for target in (
        "https://evil.example/x",
        "http://api.github.com/x",
        "https://api.github.com.evil.example/x",
        "https://api.github.com:8443/x",
        "file:///etc/passwd",
    ):
        with pytest.raises(urllib.error.HTTPError) as caught:
            handler.redirect_request(req, io.BytesIO(b""), 302, "Found", {}, target)
        assert caught.value.code == 302
    allowed = handler.redirect_request(
        req, io.BytesIO(b""), 302, "Found", {}, "https://api.github.com/repos/o/r2"
    )
    assert allowed.full_url == "https://api.github.com/repos/o/r2"


def test_refused_redirect_does_not_look_absent(api):
    api(http_error(301))
    result = lib.api_get("/repos/o/r")
    assert result.code == 301
    assert not lib.is_absent(result)


def test_token_never_appears_in_results(api):
    for failure in (
        http_error(500),
        OSError(f"boom {FAKE_TOKEN}"),
        urllib.error.URLError(f"x {FAKE_TOKEN}"),
        (200, b"not json"),
    ):
        api(failure)
        result = lib.api_get("/repos/o/r")
        assert not result.ok
        assert FAKE_TOKEN not in result.reason
        assert FAKE_TOKEN not in repr(result)


@pytest.mark.parametrize(
    "bad",
    ["", "has space in the token value", "x" * 513, "tab\tin", "new\nline", "tökén-with-unicode"],
)
def test_malformed_token_is_refused_and_not_echoed(monkeypatch, bad):
    monkeypatch.setenv("GITHUB_TOKEN", bad)
    result = lib.api_get("/repos/o/r")  # the guard would raise if a request were sent
    assert not result.ok
    assert result.reason == "GITHUB_TOKEN is missing or malformed"


def test_missing_token_is_refused(monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    assert not lib.api_get("/repos/o/r").ok


def test_api_get_refuses_non_repository_paths(token):
    assert not lib.api_get("/user").ok


def test_api_get_size_cap_status_and_json(api):
    api(b"x" * (lib.MAX_RESPONSE_BYTES + 1))
    assert "size cap" in lib.api_get("/repos/o/r").reason
    api((204, b""))
    assert lib.api_get("/repos/o/r").code == 204
    api(b"{not json")
    assert "not valid JSON" in lib.api_get("/repos/o/r").reason


def test_list_pull_files_ok_and_paginates(api):
    opener = api(page(100), page(5))
    result = lib.list_pull_files("o", "r", 7, 105)
    assert result.ok
    assert len(result.value) == 105
    assert "per_page=100&page=2" in opener.requests[1].full_url


def test_list_pull_files_fails_on_count_mismatch(api):
    api(page(3))
    result = lib.list_pull_files("o", "r", 7, 4)
    assert not result.ok
    assert "does not match" in result.reason


def test_list_pull_files_fails_at_the_page_limit(api):
    api(*[page(100)] * lib.MAX_PR_FILE_PAGES)
    result = lib.list_pull_files("o", "r", 7, 3000)
    assert not result.ok
    assert "page limit" in result.reason


def test_list_pull_files_rejects_odd_inputs(api, token):
    api(b'{"not": "a list"}')
    assert not lib.list_pull_files("o", "r", 7, 0).ok
    assert not lib.list_pull_files("o", "r", 0, 0).ok
    assert not lib.list_pull_files("o/x", "r", 7, 0).ok


def test_resolve_default_tip(api):
    api(json.dumps({"default_branch": "main"}).encode(), json.dumps({"sha": SHA}).encode())
    assert lib.resolve_default_tip("o", "r").value == SHA
    api(json.dumps({"default_branch": "ma in"}).encode())
    assert not lib.resolve_default_tip("o", "r").ok
    api(json.dumps({"default_branch": "main"}).encode(), json.dumps({"sha": "short"}).encode())
    assert not lib.resolve_default_tip("o", "r").ok


def test_event_head_sha_must_be_valid(monkeypatch):
    monkeypatch.setenv("EVENT_HEAD_SHA", SHA)
    assert lib.read_event_head_sha().value == SHA
    for bad in ("", "abc", ("a" * 40).upper(), "g" * 40, SHA + "0"):
        monkeypatch.setenv("EVENT_HEAD_SHA", bad)
        assert not lib.read_event_head_sha().ok


def test_recheck_head(api):
    api(json.dumps({"head": {"sha": SHA}}).encode())
    assert lib.recheck_head("o", "r", 7, SHA).ok
    api(json.dumps({"head": {"sha": OTHER_SHA}}).encode())
    moved = lib.recheck_head("o", "r", 7, SHA)
    assert not moved.ok
    assert "changed" in moved.reason
    api(json.dumps({"unexpected": 1}).encode())
    assert not lib.recheck_head("o", "r", 7, SHA).ok


# ---------------------------------------------------------- approval record


def test_read_run_id(monkeypatch):
    monkeypatch.setenv("RUN_ID", str(RUN_ID))
    assert lib.read_run_id().value == RUN_ID
    for bad in ("", "0", "abc", "12 3", "-1", "1" * 21, "\uff11\uff12\uff13", "1.5", " 1", "1\n"):
        monkeypatch.setenv("RUN_ID", bad)
        assert not lib.read_run_id().ok
    monkeypatch.delenv("RUN_ID")
    assert not lib.read_run_id().ok


def test_require_approval_accepts_a_matching_record(api):
    opener = api(approvals(approval_record()))
    result = lib.require_approval("o", "r", RUN_ID)
    assert result.ok
    assert result.value == "Calm-Engineer"
    req = opener.requests[0]
    assert req.get_method() == "GET"
    assert req.full_url == f"https://api.github.com/repos/o/r/actions/runs/{RUN_ID}/approvals"


@pytest.mark.parametrize("run_id", [1, RUN_ID, 10**19])
def test_require_approval_asks_about_this_runs_id(api, run_id):
    opener = api(approvals(approval_record()))
    assert lib.require_approval("o", "r", run_id).ok
    url = opener.requests[0].full_url
    assert url.endswith(f"/actions/runs/{run_id}/approvals")
    assert str(OTHER_RUN_ID) not in url


def test_a_matching_record_is_only_ever_requested_for_the_given_run(api):
    # The API answers for the run named in the URL, so the URL must never carry another id.
    opener = api(approvals(approval_record()), approvals(approval_record()))
    assert lib.require_approval("o", "r", RUN_ID).ok
    assert lib.require_approval("o", "r", OTHER_RUN_ID).ok
    first, second = (req.full_url for req in opener.requests)
    assert f"/runs/{RUN_ID}/" in first
    assert str(OTHER_RUN_ID) not in first
    assert f"/runs/{OTHER_RUN_ID}/" in second
    assert str(RUN_ID) not in second


def test_require_approval_finds_a_later_matching_record(api):
    api(
        approvals(
            approval_record("pending"),
            approval_record("approved", env="production"),
            approval_record("rejected"),
            approval_record(),
        )
    )
    result = lib.require_approval("o", "r", RUN_ID)
    assert result.ok
    assert result.value == "Calm-Engineer"


@pytest.mark.parametrize("state", ["pending", "rejected", "", "APPROVED", "approved ", None])
def test_require_approval_needs_the_state_approved(api, state):
    api(approvals(approval_record(state)))
    assert not lib.require_approval("o", "r", RUN_ID).ok


BAD_APPROVAL_BODIES = {
    "no records": [],
    "different environment": [approval_record(env="production")],
    "environment name differs in case": [approval_record(env="Spec-Approval")],
    "environments is a dict": [{"state": "approved", "environments": {"name": "spec-approval"}}],
    "environments is None": [{"state": "approved", "environments": None}],
    "environments is empty": [{"state": "approved", "environments": []}],
    "environments missing": [{"state": "approved"}],
    "environment entry is not an object": [
        {"state": "approved", "environments": ["spec-approval"]}
    ],
    "record is not an object": ["approved"],
    "junk record before a match": ["junk", approval_record()],
    "body is an object": {"state": "approved", "environments": [{"name": "spec-approval"}]},
    "body is null": None,
    "body is a string": "approved",
}


@pytest.mark.parametrize("body", BAD_APPROVAL_BODIES.values(), ids=BAD_APPROVAL_BODIES.keys())
def test_require_approval_fails_closed_on_bad_records(api, body):
    api(json.dumps(body).encode())
    result = lib.require_approval("o", "r", RUN_ID)
    assert not result.ok
    assert result.reason


@pytest.mark.parametrize(
    ("user", "expected"),
    [
        (None, ""),
        ("not-an-object", ""),
        ({}, ""),
        ({"login": 123}, ""),
        ({"login": "github-actions[bot]"}, ""),
        ({"login": "Calm-Engineer"}, "Calm-Engineer"),
    ],
)
def test_require_approval_user_shapes(api, user, expected):
    record = approval_record()
    record["user"] = user
    api(approvals(record))
    result = lib.require_approval("o", "r", RUN_ID)
    assert result.ok
    assert result.value == expected


@pytest.mark.parametrize("code", [401, 403, 404, 422, 500])
def test_require_approval_fails_closed_on_http_errors(api, code):
    api(http_error(code))
    result = lib.require_approval("o", "r", RUN_ID)
    assert not result.ok
    assert result.code == code


def test_require_approval_fails_closed_on_network_errors_and_bad_bodies(api):
    api(OSError("boom"))
    assert not lib.require_approval("o", "r", RUN_ID).ok
    api(b"<html>200 but not json</html>")
    result = lib.require_approval("o", "r", RUN_ID)
    assert not result.ok
    assert "not valid JSON" in result.reason
    api(b"")
    assert not lib.require_approval("o", "r", RUN_ID).ok


@pytest.mark.parametrize("run_id", [0, -1, True, "123", None, 1.5, 10**20])
def test_require_approval_rejects_bad_run_ids_before_any_request(token, run_id):
    assert not lib.require_approval("o", "r", run_id).ok  # the guard would raise on a request


def test_require_approval_rejects_bad_repository_names(token):
    assert not lib.require_approval("o/x", "r", RUN_ID).ok


# ----------------------------------------------------------- classification


def classify(ref, files, **extra):
    pr, changed, event_sha = spec_lock.build_case({"ref": ref, "files": files, **extra})
    return lib.classify_pr(pr, changed, event_sha)


@pytest.mark.parametrize(
    "files",
    [
        ["docs/a.md"],
        ["docs/sub/dir/x.png"],
        ["README.md"],
        ["CHANGELOG.md", "docs/a.md"],
        [".gitignore"],
        [".gitattributes"],
        ["tasks/_template/SPEC.md"],
        ["tasks/_template/TASK.md", "README.md"],
    ],
)
def test_no_task_allowlist_accepts(files):
    result = classify("chore/x", files)
    assert result.kind == lib.NO_TASK
    assert not result.spec_modified


@pytest.mark.parametrize(
    "files",
    [
        ["src/a.py"],
        ["tests/test_x.py"],
        ["requirements.txt"],
        ["requirements-dev.txt"],
        ["pyproject.toml"],
        ["setup.py"],
        ["Docs/a.md"],
        ["docs/ok.md", "src/a.py"],
        [["docs/moved.py", "src/old.py"]],
        [".github/workflows/ci.yml"],
        [".github/CODEOWNERS"],
        ["tasks/README.md"],
        ["docs/../src/x.py"],
        ["notes.txt"],
    ],
)
def test_no_task_allowlist_rejects(files):
    result = classify("chore/x", files)
    assert result.kind == lib.INVALID
    assert "tasks/<ID>/" in result.reason


def test_template_folder_is_exempt_from_the_spec_rule():
    result = classify("chore/x", ["tasks/_template/SPEC.md"])
    assert result.kind == lib.NO_TASK
    assert not result.spec_modified


def test_spec_only_and_implementation_kinds():
    only = classify("spec/AGT-001", ["tasks/AGT-001/SPEC.md", "tasks/AGT-001/TASK.md"])
    assert (only.kind, only.task_id) == (lib.SPEC_ONLY, "AGT-001")
    mixed = classify("spec/AGT-001", ["tasks/AGT-001/SPEC.md", "src/a.py"])
    assert (mixed.kind, mixed.spec_modified) == (lib.IMPLEMENTATION, True)
    task_only = classify("task/AGT-001-x", ["tasks/AGT-001/TASK.md"])
    assert (task_only.kind, task_only.spec_modified) == (lib.IMPLEMENTATION, False)


def test_branch_name_is_only_a_lookup_key():
    found = classify("task/AGT-001-baseline", ["src/a.py"])
    assert (found.kind, found.task_id) == (lib.IMPLEMENTATION, "AGT-001")
    assert classify("task/AGT-001-x", ["tasks/AGT-002/TASK.md"]).kind == lib.INVALID
    assert classify("task/bad", ["docs/a.md"]).kind == lib.INVALID
    assert classify("task/AGT-001-x\nevil=1", ["src/a.py"]).kind == lib.INVALID
    assert classify("task/AGT-001-" + "a" * 100, ["src/a.py"]).kind == lib.INVALID


def test_odd_task_folders_are_invalid():
    assert classify("x", ["tasks/AGT-001/a.md", "tasks/AGT-002/b.md"]).kind == lib.INVALID
    assert classify("x", ["tasks/foo/a.md"]).kind == lib.INVALID


def test_malformed_payloads_are_invalid():
    pr, files, sha = spec_lock.build_case({"ref": "x", "files": ["docs/a.md"]})
    assert lib.classify_pr(None, files, sha).kind == lib.INVALID
    assert lib.classify_pr(pr, [], sha).kind == lib.INVALID
    assert lib.classify_pr(pr, ["not a dict"], sha).kind == lib.INVALID
    assert lib.classify_pr(pr, [{"filename": ""}], sha).kind == lib.INVALID
    assert lib.classify_pr(pr, [{"filename": "a\x00b"}], sha).kind == lib.INVALID
    pr["head"]["repo"] = None
    assert lib.classify_pr(pr, files, sha).kind == lib.INVALID


def test_head_sha_must_match_the_event():
    assert classify("x", ["docs/a.md"]).kind == lib.NO_TASK
    moved = classify("x", ["docs/a.md"], event_head_sha=OTHER_SHA)
    assert moved.kind == lib.INVALID
    assert "event head" in moved.reason
    assert classify("x", ["docs/a.md"], fork=True).kind == lib.INVALID


# ------------------------------------------------------------------- decide


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_fixture_cases(case):
    verdict = spec_lock.run_case(case)
    assert verdict.ok == (case["expect"] == "pass")
    assert case.get("expect_text", "") in verdict.message


def test_unfilled_template_task_md_is_rejected():
    template = (REPO_ROOT / "tasks" / "_template" / "TASK.md").read_bytes()
    template = template.replace(b"\r\n", b"\n")
    # The parser accepts the template's shape (empty shas are allowed)...
    assert lib.parse_front_matter(template, lib.TASK_SCHEMA).ok
    # ...so the rejection is decide()'s job.
    spec = spec_bytes("AGT-000")
    cls = lib.Classification(lib.IMPLEMENTATION, "AGT-000", "", False)
    verdict = spec_lock.decide(
        cls,
        "skipped",
        lambda task_id: lib.ok((lib.sha256_hex(spec), spec)),
        lambda path: lib.ok(template),
    )
    assert not verdict.ok
    assert "spec_sha256 is empty" in verdict.message


def test_decide_defensive_branches():
    def nothing(*args):
        return lib.fail("unused")

    weird = lib.Classification("weird", "AGT-001", "", False)
    verdict = spec_lock.decide(weird, "skipped", nothing, nothing)
    assert "unknown classification" in verdict.message
    stray = lib.Classification(lib.NO_TASK, "", "", True)
    assert not spec_lock.decide(stray, "skipped", nothing, nothing).ok


def test_decide_messages_are_sanitized():
    cls = lib.Classification(lib.INVALID, "", "::error::injected", False)
    verdict = spec_lock.decide(cls, "skipped", None, None)
    assert not verdict.message.lstrip().startswith("::")


def spec_only_cls():
    return lib.Classification(lib.SPEC_ONLY, "AGT-001", "", True)


def spec_only_readers():
    calls = []

    def base_spec(task_id):
        calls.append("base")
        return lib.fail("HTTP 404", 404)

    def head_file(path):
        calls.append("head")
        return lib.ok(spec_bytes())

    return calls, base_spec, head_file


def test_spec_only_passes_with_a_verified_record():
    _, base_spec, head_file = spec_only_readers()
    cls = spec_only_cls()
    verdict = spec_lock.decide(
        cls, "success", base_spec, head_file, lambda: lib.ok("Calm-Engineer")
    )
    assert verdict.ok
    assert "approved via spec-approval by Calm-Engineer" in verdict.message
    verdict = spec_lock.decide(cls, "success", base_spec, head_file, lambda: lib.ok(""))
    assert verdict.ok
    assert "by unknown" in verdict.message


def test_spec_only_without_a_verifier_fails():
    _, base_spec, head_file = spec_only_readers()
    verdict = spec_lock.decide(spec_only_cls(), "success", base_spec, head_file)
    assert not verdict.ok
    assert "not verified" in verdict.message


def test_spec_only_fails_without_a_record_and_reads_nothing_else():
    calls, base_spec, head_file = spec_only_readers()
    verdict = spec_lock.decide(
        spec_only_cls(), "success", base_spec, head_file, lambda: lib.fail("HTTP 403", 403)
    )
    assert not verdict.ok
    assert "no verified spec-approval record: HTTP 403" in verdict.message
    assert calls == []


@pytest.mark.parametrize("approval", ["skipped", "failure", "cancelled", "", "banana"])
def test_the_verifier_is_not_called_unless_approval_succeeded(approval):
    _, base_spec, head_file = spec_only_readers()
    called = []

    def verifier():
        called.append(1)
        return lib.ok("x")

    verdict = spec_lock.decide(spec_only_cls(), approval, base_spec, head_file, verifier)
    assert not verdict.ok
    assert called == []


def test_other_kinds_never_call_the_verifier():
    def verifier():
        raise AssertionError("the verifier must not be called")

    def nothing(*args):
        return lib.fail("unused")

    for cls in (
        lib.Classification(lib.NO_TASK, "", "", False),
        lib.Classification(lib.INVALID, "", "x", False),
        lib.Classification(lib.IMPLEMENTATION, "AGT-001", "", False),
    ):
        spec_lock.decide(cls, "success", nothing, nothing, verifier)


# ------------------------------------------------------------ live commands


@pytest.fixture
def live(monkeypatch, tmp_path):
    """A passing implementation PR, with every reviewlib call faked."""
    pr, files, _ = spec_lock.build_case(
        {"ref": "task/AGT-001-baseline", "files": ["src/a.py", "tasks/AGT-001/TASK.md"]}
    )
    pr["changed_files"] = len(files)
    spec = spec_bytes()
    task = task_bytes(lib.sha256_hex(spec))
    state = SimpleNamespace(
        pr=pr,
        files=files,
        pull_error=False,
        tip_error=False,
        recheck=lib.ok(SHA),
        approval=lib.ok("Calm-Engineer"),
        approval_calls=[],
        out=tmp_path / "output",
        summary=tmp_path / "summary",
    )

    def get_pull(owner, repo, number):
        return lib.fail("HTTP 500", 500) if state.pull_error else lib.ok(state.pr)

    def resolve_tip(owner, repo):
        return lib.fail("HTTP 500", 500) if state.tip_error else lib.ok(OTHER_SHA)

    monkeypatch.setattr(lib, "get_pull", get_pull)
    monkeypatch.setattr(lib, "list_pull_files", lambda o, r, n, c: lib.ok(state.files))
    monkeypatch.setattr(lib, "resolve_default_tip", resolve_tip)
    monkeypatch.setattr(lib, "base_spec", lambda o, r, t, s: lib.ok((lib.sha256_hex(spec), spec)))

    def get_file_bytes(owner, repo, path, ref):
        return lib.ok(spec if path.endswith("SPEC.md") else task)

    def require_approval(owner, repo, run_id, *rest):
        state.approval_calls.append(run_id)
        return state.approval

    monkeypatch.setattr(lib, "get_file_bytes", get_file_bytes)
    monkeypatch.setattr(lib, "require_approval", require_approval)
    monkeypatch.setattr(lib, "recheck_head", lambda o, r, n, s: state.recheck)
    for key, value in {
        "GITHUB_REPOSITORY": "o/r",
        "PR_NUMBER": "7",
        "EVENT_HEAD_SHA": SHA,
        "CLASSIFY_RESULT": "success",
        "CLASSIFY_KIND": "implementation",
        "APPROVAL_RESULT": "skipped",
        "RUN_ID": str(RUN_ID),
        "GITHUB_OUTPUT": str(state.out),
        "GITHUB_STEP_SUMMARY": str(state.summary),
    }.items():
        monkeypatch.setenv(key, value)
    return state


def test_check_passes_the_baseline(live, capsys):
    assert spec_lock.cmd_check() == 0
    assert "PASS [implementation]" in capsys.readouterr().out
    assert "PASS" in live.summary.read_text()
    assert live.approval_calls == []  # only spec-only pull requests need a review record


def test_check_fails_when_classification_changed_between_jobs(live, monkeypatch, capsys):
    monkeypatch.setenv("CLASSIFY_KIND", "spec-only")
    assert spec_lock.cmd_check() == 1
    assert "classification changed" in capsys.readouterr().out


def test_check_fails_when_classify_did_not_succeed(live, monkeypatch, capsys):
    for value in ("failure", "skipped", "cancelled", ""):
        monkeypatch.setenv("CLASSIFY_RESULT", value)
        assert spec_lock.cmd_check() == 1
    assert "classify job did not succeed" in capsys.readouterr().out


@pytest.mark.parametrize("kind", ["", "weird", "Implementation"])
def test_check_fails_on_unknown_classify_kind(live, monkeypatch, kind):
    monkeypatch.setenv("CLASSIFY_KIND", kind)
    assert spec_lock.cmd_check() == 1


def test_check_fails_on_unknown_approval_result(live, monkeypatch, capsys):
    monkeypatch.setenv("APPROVAL_RESULT", "banana")
    assert spec_lock.cmd_check() == 1
    assert "not a known value" in capsys.readouterr().out


def test_check_fails_when_the_head_moved_at_the_end(live, capsys):
    live.recheck = lib.fail("pull request head changed during the run")
    assert spec_lock.cmd_check() == 1
    out = capsys.readouterr().out
    assert "head changed" in out
    assert "PASS" not in out


def test_check_fails_when_api_calls_fail(live):
    live.pull_error = True
    assert spec_lock.cmd_check() == 1
    live.pull_error = False
    live.tip_error = True
    assert spec_lock.cmd_check() == 1


def make_spec_only(live, monkeypatch, approval="success"):
    live.pr["head"]["ref"] = "spec/AGT-001"
    live.pr["changed_files"] = 1
    live.files = [{"filename": "tasks/AGT-001/SPEC.md"}]
    monkeypatch.setenv("CLASSIFY_KIND", "spec-only")
    monkeypatch.setenv("APPROVAL_RESULT", approval)


def test_check_spec_only_passes_with_a_review_record(live, monkeypatch, capsys):
    make_spec_only(live, monkeypatch)
    assert spec_lock.cmd_check() == 0
    assert "approved via spec-approval by Calm-Engineer" in capsys.readouterr().out
    assert live.approval_calls == [RUN_ID]


def test_check_spec_only_fails_without_a_review_record(live, monkeypatch, capsys):
    make_spec_only(live, monkeypatch)
    live.approval = lib.fail("no approved review record for the spec-approval environment")
    assert spec_lock.cmd_check() == 1
    out = capsys.readouterr().out
    assert "no verified spec-approval record" in out
    assert "PASS" not in out


def test_check_spec_only_fails_when_the_approvals_api_is_forbidden(live, monkeypatch, capsys):
    make_spec_only(live, monkeypatch)
    live.approval = lib.fail("HTTP 403", 403)
    assert spec_lock.cmd_check() == 1
    assert "HTTP 403" in capsys.readouterr().out


def test_check_does_not_look_for_a_record_before_approval_succeeds(live, monkeypatch):
    make_spec_only(live, monkeypatch, approval="skipped")
    assert spec_lock.cmd_check() == 1
    assert live.approval_calls == []


@pytest.mark.parametrize("value", ["", "0", "abc", "12 3", "-1"])
def test_check_fails_closed_on_a_bad_run_id(live, monkeypatch, value):
    monkeypatch.setenv("RUN_ID", value)
    assert spec_lock.cmd_check() == 1
    assert live.approval_calls == []


def test_check_fails_closed_without_a_run_id(live, monkeypatch):
    monkeypatch.delenv("RUN_ID")
    assert spec_lock.cmd_check() == 1


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("EVENT_HEAD_SHA", ""),
        ("EVENT_HEAD_SHA", "abc"),
        ("PR_NUMBER", "0"),
        ("PR_NUMBER", "abc"),
        ("PR_NUMBER", "12345678901"),
        ("PR_NUMBER", ""),
    ],
)
def test_bad_inputs_fail_closed(live, monkeypatch, name, value):
    monkeypatch.setenv(name, value)
    assert spec_lock.cmd_check() == 1
    assert spec_lock.cmd_classify() == 1


def test_classify_writes_only_the_kind_line(live):
    assert spec_lock.cmd_classify() == 0
    assert live.out.read_text() == "kind=implementation\n"


def test_classify_output_cannot_be_injected_through_the_branch_name(live):
    live.pr["head"]["ref"] = "task/AGT-001-x\nevil=1"
    assert spec_lock.cmd_classify() == 0
    assert live.out.read_text() == "kind=invalid\n"
    assert "evil" not in live.out.read_text()


def test_classify_reports_invalid_without_failing(live, capsys):
    live.pr["head"]["ref"] = "feature/x"
    live.files = [{"filename": "src/a.py"}]
    assert spec_lock.cmd_classify() == 0
    assert live.out.read_text() == "kind=invalid\n"
    assert "tasks/<ID>/" in capsys.readouterr().out


def test_classify_fails_closed_without_an_output_file(live, monkeypatch):
    monkeypatch.delenv("GITHUB_OUTPUT")
    assert spec_lock.cmd_classify() == 1


def test_classify_fails_closed_when_the_output_cannot_be_written(live, monkeypatch, tmp_path):
    monkeypatch.setenv("GITHUB_OUTPUT", str(tmp_path))  # a directory, not a file
    assert spec_lock.cmd_classify() == 1


def test_classify_writes_nothing_when_the_api_fails(live):
    live.pull_error = True
    assert spec_lock.cmd_classify() == 1
    assert not live.out.exists()


# ----------------------------------------------------------------------- CLI


@pytest.mark.parametrize("argv", [["x"], ["x", "bogus"], ["x", "check", "extra"], ["x", ""]])
def test_bad_cli_arguments_return_2(argv, capsys):
    assert spec_lock.main(argv) == 2
    assert "usage" in capsys.readouterr().err


def test_broad_except_prints_only_the_exception_type(monkeypatch, capsys):
    def boom():
        raise RuntimeError("::error::SECRET-TEXT-FROM-THE-PR")

    monkeypatch.setitem(spec_lock.COMMANDS, "check", boom)
    assert spec_lock.main(["x", "check"]) == 1
    captured = capsys.readouterr()
    assert "unexpected RuntimeError" in captured.out
    assert "SECRET-TEXT" not in captured.out + captured.err
    assert not any(line.startswith("::") for line in captured.out.splitlines())


def test_dry_run_reports_no_mismatches(capsys):
    assert spec_lock.cmd_dry_run() == 0
    out = capsys.readouterr().out
    assert f"{len(CASES)} cases, 0 mismatches" in out


def test_dry_run_detects_a_mismatch(monkeypatch, tmp_path, capsys):
    wrong = [{"name": "wrong", "ref": "x", "files": ["docs/a.md"], "expect": "fail"}]
    path = tmp_path / "cases.json"
    path.write_text(json.dumps(wrong), encoding="utf-8")
    monkeypatch.setattr(spec_lock, "FIXTURES", path)
    assert spec_lock.cmd_dry_run() == 1
    assert "MISMATCH" in capsys.readouterr().out


def test_dry_run_fails_closed_on_a_missing_or_empty_fixture_file(monkeypatch, tmp_path):
    monkeypatch.setattr(spec_lock, "FIXTURES", tmp_path / "missing.json")
    assert spec_lock.cmd_dry_run() == 1
    empty = tmp_path / "empty.json"
    empty.write_text("[]", encoding="utf-8")
    monkeypatch.setattr(spec_lock, "FIXTURES", empty)
    assert spec_lock.cmd_dry_run() == 1
