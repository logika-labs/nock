"""api.nock.dev over HTTP, under real uvicorn on real Postgres: what it keeps, every body it refuses, the
edge every request passes, and the rate limit on a virtual clock."""

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import psycopg
import pytest
from nock.prices import Prices
from nock.project import Project
from nock.setup import Installer
from nock.usage import Usage

from nock_api import rules
from tests.conftest import Api, Clock
from tests.test_migrate import nock_api

REPORT: dict[str, Any] = {
    "schema": 2,
    "project": "6f1c2b9e-3d4a-4e5f-8a7b-1c2d3e4f5a6b",
    "nock": "0.3.0",
    "python": "3.12",
    "platform": "darwin",
    "settings": {"reminders": True, "consult": True, "logika": False},
    "metrics": {"days": 7.0, "sessions": 3, "cost": 1.25},
    "commands": {
        "decide": {"calls": 1, "failures": 0},
        "decisions edit": {"calls": 2, "failures": 1},
    },
    "toolbox": {"tools": 1, "checks": 2, "hooks": 0, "generators": 0, "load_failures": 0},
    "rounds": {"nock": 1, "logika": 0},
}
# A copy of a few entries of LiteLLM's price table (nock's own tests'), so no test reaches the network.
PRICES = Path(__file__).resolve().parents[2] / "tests" / "prices.json"


def git(directory: Path, *arguments: str) -> None:
    subprocess.run(["git", *arguments], cwd=directory, check=True, capture_output=True)


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Project:
    """A repository with nock installed, as a project that shares its usage has it."""
    for name in list(os.environ):
        if name.startswith(("CLAUDE", "NOCK_", "GIT_")):
            monkeypatch.delenv(name)
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude"))
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(tmp_path / "gitconfig"))
    for role in ("AUTHOR", "COMMITTER"):
        monkeypatch.setenv(f"GIT_{role}_NAME", "Test")
        monkeypatch.setenv(f"GIT_{role}_EMAIL", "test@example.com")
    root = tmp_path / "repository"
    root.mkdir()
    git(root, "init", "-q", "-b", "main")
    (root / "README.md").write_text("# demo\n")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "init")
    Installer(root).install()
    local = root / ".nock" / "local"
    local.mkdir(exist_ok=True)
    (local / "config.toml").write_text("[upgrade]\ncheck = false\n")
    monkeypatch.chdir(root)
    project = Project.discover(root)
    Prices(project, PRICES.as_uri()).table()
    return project


def test_the_report_nock_builds_is_kept_as_it_arrived(
    project: Project, api: Api, clock: Clock
) -> None:
    built = Usage(project).report(sending=True)
    assert built["schema"] == 3
    status, answer = api.post("/usage", built)
    assert (status, answer) == (201, {"id": 1})
    (row,) = api.rows("usage")
    assert str(row["project"]) == built["project"] and row["schema"] == 3
    assert row["report"] == built and row["received"] == clock.moment


@pytest.mark.parametrize(
    ("change", "said"),
    [
        ({"tools": [{"tool": "deploy", "calls": 1, "failures": 0}]}, "unexpected fields: tools"),
        ({"level": "anonymous"}, "unexpected fields: level"),
        ({"settings": {**REPORT["settings"], "branch": "main"}}, "unexpected fields: branch"),
        ({"commands": {"decide": {"calls": 1, "failures": 0, "arguments": "x"}}}, "unexpected"),
        ({"commands": {"acme_payroll": {"calls": 1, "failures": 0}}}, "commands"),
        ({"metrics": {"Fix the login bug": 1}}, "metrics"),
        ({"metrics": {"sessions": "three"}}, "metrics.sessions"),
        ({"metrics": {"sessions": True}}, "metrics.sessions"),
        ({"metrics": {"sessions": float("inf")}}, "metrics.sessions"),
        ({"toolbox": {**REPORT["toolbox"], "tools": -1}}, "toolbox.tools"),
        ({"toolbox": {**REPORT["toolbox"], "tools": 1.5}}, "toolbox.tools"),
        ({"rounds": {"nock": 10**12}}, "rounds.nock"),
        ({"settings": {**REPORT["settings"], "consult": 1}}, "settings.consult"),
        ({"project": "/Users/someone/acme"}, "`project` is a random UUID"),
        ({"project": "6F1C2B9E-3D4A-4E5F-8A7B-1C2D3E4F5A6B"}, "`project` is a random UUID"),
        ({"project": "6f1c2b9e-3d4a-1e5f-8a7b-1c2d3e4f5a6b"}, "`project` is a random UUID"),
        ({"schema": 1}, "`schema` is one of 2, 3"),
        ({"schema": True}, "`schema` is one of 2, 3"),
        ({"schema": 2, "metrics": {"api_cost": None}}, "metrics.api_cost"),
        ({"platform": "a laptop at acme"}, "platform"),
        ({"nock": "latest"}, "nock"),
        ({"python": "3"}, "python"),
    ],
)
def test_a_report_with_anything_unexpected_is_refused_whole(
    api: Api, change: dict[str, Any], said: str
) -> None:
    status, answer = api.post("/usage", {**REPORT, **change})
    assert status == 400 and said in answer["error"]
    assert api.rows("usage") == []


def test_a_schema_3_report_may_have_null_metrics(api: Api) -> None:
    sent = {**REPORT, "schema": 3, "metrics": {"api_cost": None, "sessions": 2}}
    assert api.post("/usage", sent) == (201, {"id": 1})
    assert api.rows("usage")[0]["report"] == sent


def test_a_report_missing_a_field_too_large_or_not_json_is_refused(api: Api, clock: Clock) -> None:
    # More posts than one burst: each a minute after the last.
    def post(path: str, sent: Any) -> tuple[int, dict[str, Any]]:
        clock.advance(60)
        return api.post(path, sent)

    missing = {key: value for key, value in REPORT.items() if key != "rounds"}
    assert post("/usage", missing) == (400, {"error": "`report` lacks rounds"})
    status, answer = post("/usage", b"not json")
    assert status == 400 and answer["error"].startswith("Expecting value")
    assert post("/usage", [REPORT]) == (400, {"error": "`report` is an object"})
    assert post("/usage", b"\xff")[0] == 400
    many = {f"metric_{index}": index for index in range(65)}
    assert post("/usage", {**REPORT, "metrics": many})[0] == 400
    assert post("/usage", b"{" + b" " * rules.LARGEST["/usage"] + b"}") == (
        413,
        {"error": "at most 32000 bytes"},
    )
    assert post("/usage", b"[" * 20_000 + b"]" * 20_000)[0] == 413
    assert post("/usage", b"[" * 15_000 + b"]" * 15_000)[0] == 400
    assert post("/elsewhere", REPORT) == (404, {"error": "nothing here"})
    assert api.rows("usage") == []


def test_a_summary_is_kept_without_anything_about_its_sender(api: Api, clock: Clock) -> None:
    status, answer = api.post(
        "/reflections", {"summary": " Early days. ", "round": "2026-10-31"}, "203.0.113.7"
    )
    assert (status, answer) == (201, {"id": 1})
    assert api.rows("reflections") == [
        {"id": 1, "received": clock.moment, "round": "2026-10-31", "summary": "Early days."}
    ]
    clock.advance(60)
    assert api.post("/reflections", {"summary": "Undated."}) == (201, {"id": 2})
    refused, said = api.post("/reflections", {"summary": "Hi.", "visibility": "public"})
    assert refused == 400 and "unexpected fields: visibility" in said["error"]
    assert api.post("/reflections", {"summary": "  "})[0] == 400
    assert api.post("/reflections", {"summary": 3})[0] == 400
    assert api.post("/reflections", {"summary": "x" * (rules.LONGEST + 1)})[0] == 400
    clock.advance(60)
    assert api.post("/reflections", {"summary": "Hi.", "round": 2026})[0] == 400
    assert api.post("/reflections", {"round": "2026-10-31"})[0] == 400
    assert [row["round"] for row in api.rows("reflections")] == ["2026-10-31", None]


def test_text_postgres_cannot_hold_is_refused_not_failed(api: Api) -> None:
    error = f"`summary` is text of at most {rules.LONGEST} characters"
    assert api.post("/reflections", {"summary": "a\x00b"}) == (400, {"error": error})
    assert api.post("/reflections", b'{"summary": "\\ud800"}') == (400, {"error": error})
    said = {"error": "`round` is the round's date"}
    assert api.post("/reflections", {"summary": "Hi.", "round": "\x00"}) == (400, said)
    assert api.rows("reflections") == []


def test_bodies_past_the_cap_or_without_a_length_are_refused_unread(api: Api) -> None:
    for path in (b"/usage", b"/reflections"):
        head = b"POST " + path + b" HTTP/1.1\r\nHost: x\r\nContent-Length: 131072\r\n"
        assert api.answer_to(head) == b"413"
    negative = b"POST /usage HTTP/1.1\r\nHost: x\r\nContent-Length: -1\r\n"
    assert api.answer_to(negative) == b"400"
    assert api.answer_to(b"POST /usage HTTP/1.1\r\nHost: x\r\n") == b"411"
    chunked = b"POST /usage HTTP/1.1\r\nHost: x\r\nTransfer-Encoding: chunked\r\n"
    assert api.answer_to(chunked) == b"411"
    assert api.rows("usage") == [] and api.rows("reflections") == []


def test_health_and_the_edge(api: Api) -> None:
    assert api.get("/health") == (200, {"ok": True})
    for path in ("/health/", "/health?probe=1", "/usage", "/"):
        assert api.get(path) == (404, {"error": "nothing here"})
    assert api.post("/usage/", REPORT) == (201, {"id": 1})
    assert api.post("/usage?from=nock", REPORT) == (404, {"error": "nothing here"})
    assert api.post("/health", {}) == (404, {"error": "nothing here"})
    status, answer, _ = api.exchange("/usage", REPORT, method="PUT")
    assert (status, answer) == (501, {"error": "Unsupported method ('PUT')"})
    assert api.exchange("/health", None, method="HEAD")[0] == 501


def test_an_address_gets_a_burst_of_five_then_six_a_minute_across_both_endpoints(
    api: Api, clock: Clock
) -> None:
    sender = "203.0.113.7"
    for path in ("/usage", "/reflections", "/usage", "/reflections", "/usage"):
        assert api.post(path, REPORT if path == "/usage" else {"summary": "Hi."}, sender)[0] == 201
    status, answer, headers = api.exchange("/reflections", {"summary": "Hi."}, sender)
    assert (status, answer) == (429, {"error": "at most 5 at once and 6 a minute; try again later"})
    assert headers["retry-after"] == "10"
    assert api.post("/usage", REPORT, sender)[0] == 429
    assert api.post("/elsewhere", REPORT, sender)[0] == 429
    assert api.post("/usage", REPORT, "198.51.100.4")[0] == 201
    clock.advance(9)
    assert api.post("/usage", REPORT, sender)[0] == 429
    clock.advance(1)
    assert api.post("/usage", REPORT, sender)[0] == 201
    assert api.post("/usage", REPORT, sender)[0] == 429
    assert api.get("/health")[0] == 200
    clock.advance(60)
    assert [api.post("/usage", REPORT, sender)[0] for _ in range(6)] == [201] * 5 + [429]
    assert len(api.rows("usage")) == 3 + 1 + 1 + 5


def test_the_first_forwarded_address_is_the_sender(api: Api) -> None:
    for index in range(5):
        assert api.post("/usage", REPORT, f"203.0.113.9, 10.0.0.{index}")[0] == 201
    assert api.post("/usage", REPORT, "203.0.113.9")[0] == 429
    assert api.post("/usage", REPORT, "10.0.0.1")[0] == 201
    # Without the header, the peer (here 127.0.0.1) is the sender.
    assert [api.post("/usage", REPORT)[0] for _ in range(6)] == [201] * 5 + [429]


def test_addresses_are_held_in_memory_only_and_forgotten_once_idle(
    api: Api, clock: Clock, database_url: str
) -> None:
    api.limit.most = 50
    for index in range(4):
        assert api.post("/usage", REPORT, f"203.0.113.{index}")[0] == 201
    assert list(api.limit.buckets) == [f"203.0.113.{index}" for index in range(4)]
    clock.advance(9)
    api.post("/usage", REPORT, "203.0.113.0")
    clock.advance(1)
    api.post("/usage", REPORT, "198.51.100.1")
    assert list(api.limit.buckets) == ["203.0.113.0", "198.51.100.1"]
    clock.advance(15)
    api.post("/usage", REPORT, "198.51.100.2")
    assert list(api.limit.buckets) == ["198.51.100.2"]
    api.limit.most = 3
    for index in range(6):
        api.post("/usage", REPORT, f"192.0.2.{index}")
    assert list(api.limit.buckets) == ["192.0.2.3", "192.0.2.4", "192.0.2.5"]
    with psycopg.connect(database_url) as connection:
        kept = connection.execute(
            "SELECT string_agg(t::text, ' ') FROM (SELECT * FROM usage) t"
        ).fetchone()
    assert kept is not None and "203.0.113" not in kept[0] and "192.0.2" not in kept[0]


def test_the_report_kept_is_what_was_sent(api: Api) -> None:
    raw = json.dumps(REPORT, indent=2).encode()
    assert api.post("/usage", raw)[0] == 201
    assert api.rows("usage")[0]["report"] == REPORT


WRITTEN = {
    "text": "I need nock to list the decisions a commit touched.",
    "nock": "0.3.0",
    "platform": "darwin",
}


def test_a_report_is_kept_stripped_without_anything_about_its_sender(
    api: Api, clock: Clock
) -> None:
    sent = {**WRITTEN, "text": f"  {WRITTEN['text']}\n"}
    assert api.post("/reports", sent, "203.0.113.7") == (201, {"id": 1})
    assert api.rows("reports") == [{"id": 1, "received": clock.moment, **WRITTEN}]


@pytest.mark.parametrize(
    ("change", "said"),
    [
        ({"text": "   "}, "`text` is text of at most 10000 characters"),
        ({"text": 3}, "`text` is text of at most 10000 characters"),
        ({"text": "x" * (rules.LONGEST_WRITTEN + 1)}, "`text` is text of at most 10000"),
        ({"text": "a\x00b"}, "`text` is text of at most 10000 characters"),
        ({"email": "someone@example.com"}, "unexpected fields: email"),
        ({"nock": "latest"}, "`nock` is not what it should be"),
        ({"platform": "a laptop at acme"}, "`platform` is not what it should be"),
    ],
)
def test_a_report_with_anything_unexpected_is_refused(
    api: Api, clock: Clock, change: dict[str, Any], said: str
) -> None:
    status, answer = api.post("/reports", {**WRITTEN, **change})
    assert status == 400 and said in answer["error"]
    missing = {key: value for key, value in WRITTEN.items() if key != "platform"}
    clock.advance(60)
    assert api.post("/reports", missing) == (400, {"error": "`body` lacks platform"})
    assert api.rows("reports") == []


def test_a_report_past_its_cap_is_refused_unread(api: Api) -> None:
    head = b"POST /reports HTTP/1.1\r\nHost: x\r\nContent-Length: 40001\r\n"
    assert api.answer_to(head) == b"413"
    assert api.post("/reports", b"{" + b" " * rules.LARGEST["/reports"] + b"}") == (
        413,
        {"error": "at most 40000 bytes"},
    )
    assert api.rows("reports") == []


def test_reports_share_the_rate_limit_with_every_other_post(api: Api) -> None:
    sender = "203.0.113.7"
    for _ in range(4):
        assert api.post("/usage", REPORT, sender)[0] == 201
    assert api.post("/reports", WRITTEN, sender)[0] == 201
    assert api.post("/reports", WRITTEN, sender)[0] == 429
    assert len(api.rows("reports")) == 1


def test_nock_report_sends_to_the_api_and_says_the_id(project: Project, api: Api) -> None:
    local = project.root / ".nock" / "local" / "config.toml"
    local.write_text(local.read_text() + f'[endpoints]\nreports = "{api.address}/reports"\n')
    run = subprocess.run(
        [str(project.root / ".nock" / "nock"), "report", WRITTEN["text"], "--yes", "--json"],
        cwd=project.root,
        capture_output=True,
        text=True,
        env={**os.environ, "NOCK_PYTHON": sys.executable},
    )
    assert run.returncode == 0, run.stderr
    assert json.loads(run.stdout)["id"] == 1
    (row,) = api.rows("reports")
    assert row["text"] == WRITTEN["text"] and row["platform"] == sys.platform


def test_the_makers_read_the_latest_reports_newest_first(
    api: Api, clock: Clock, database_url: str
) -> None:
    assert nock_api("reports", url=database_url).stdout == "no reports yet\n"
    api.post("/reports", {**WRITTEN, "text": "First.\nTwo lines."})
    clock.advance(60)
    api.post("/reports", {**WRITTEN, "text": "Second.", "platform": "linux"})
    listed = nock_api("reports", url=database_url)
    assert listed.returncode == 0, listed.stderr
    assert listed.stdout == (
        "#2  2026-11-03 12:01 UTC  nock 0.3.0 on linux\n    Second.\n\n"
        "#1  2026-11-03 12:00 UTC  nock 0.3.0 on darwin\n    First.\n    Two lines.\n"
    )
    assert nock_api("reports", "--limit", "1", url=database_url).stdout.count("#") == 1
