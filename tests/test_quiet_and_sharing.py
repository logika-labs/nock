"""nock on someone else's machine: `reminders = false` keeps it silent unless
asked while it still records; usage statistics are shared only once the
owner was told, with the project's anonymous id, and never when `share` is false."""

from __future__ import annotations

import json
import threading
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from nock.hooks import HookRunner
from nock.project import Project
from nock.usage import DISCLOSURE, IDENTITY, UNMADE, Moment, Usage

from .conftest import git, nock, write_tool
from .test_decisions import decide, edit
from .test_telemetry_and_reflection import transcript


def configure(project: Project, old: str, new: str) -> Project:
    """A committed setting changed, the project read afresh."""
    config = project.root / ".nock" / "config.toml"
    assert old in config.read_text()
    config.write_text(config.read_text().replace(old, new, 1))
    return Project.discover(project.root)


def shared(project: Project, value: str) -> Project:
    return configure(project, "share = true", f"share = {value}")


def test_with_reminders_off_nock_says_nothing_unasked_and_still_records(
    project: Project,
) -> None:
    write_tool(project, "work", "import nock\n\n@nock.command\ndef deploy():\n    '''Ship it.'''\n")
    number = decide(project.root)["number"]
    edit(project.root, {"number": number, "review": "rejected", "note": "Postgres"})
    quiet = configure(project, "reminders = true", "reminders = false")
    assert HookRunner(quiet, {"session_id": "s1"}).handle("SessionStart") is None
    assert HookRunner(quiet, {"session_id": "s1"}).handle("UserPromptSubmit") is None
    payload = {"session_id": "s1", "tool_name": "Edit", "tool_input": {"file_path": "README.md"}}
    assert HookRunner(quiet, payload).handle("PostToolUse") is None
    primer = (project.root / ".nock" / "context.md").read_text()
    assert "It stays quiet here" in primer
    assert "Record decisions" not in primer
    path = transcript(quiet, "s1", ["Deploy it"], [("make deploy", 10, False)])
    HookRunner(quiet, {"session_id": "s1", "transcript_path": str(path)}).handle("SessionEnd")
    assert quiet.store.rows("SELECT id FROM sessions") == [{"id": "s1"}]
    assert "deploy" in nock(project.root).stdout
    assert json.loads(nock(project.root, "status", "--json").stdout)["to_rework"]


class Receiver(BaseHTTPRequestHandler):
    received: list[dict[str, object]] = []

    def do_POST(self) -> None:
        self.received.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
        self.send_response(204)
        self.end_headers()

    def log_message(self, format: str, *arguments: object) -> None:
        pass


@pytest.fixture
def receiver(project: Project) -> Iterator[list[dict[str, object]]]:
    """A real endpoint the usage statistics go to, set on this machine."""
    received: list[dict[str, object]] = []
    handler = type("Handler", (Receiver,), {"received": received})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    local = project.root / ".nock" / "local" / "config.toml"
    local.write_text(
        local.read_text() + f'[endpoints]\nusage = "http://127.0.0.1:{server.server_address[1]}/"\n'
    )
    yield received
    server.shutdown()
    server.server_close()


def a_week_ago(project: Project) -> None:
    """The disclosure moved a week back, as if the owner was told then."""
    path = project.root / ".nock" / "local" / "usage.json"
    state = json.loads(path.read_text())
    moment = datetime.now(UTC).replace(microsecond=0) - timedelta(days=8)
    state["disclosed"]["at"] = moment.isoformat().replace("+00:00", "Z")
    path.write_text(json.dumps(state))


def end_session(project: Project, session: str) -> None:
    path = transcript(project, session, ["Fix the login bug"], [("pytest -q", 10, True)])
    HookRunner(project, {"session_id": session, "transcript_path": str(path)}).handle("SessionEnd")


def test_nothing_is_sent_before_the_owner_is_told_and_then_weekly_counts_only(
    project: Project, receiver: list[dict[str, object]]
) -> None:
    write_tool(
        project, "secret", "import nock\n\n@nock.command\ndef acme_payroll():\n    '''Pay.'''\n"
    )
    nock(project.root, "acme-payroll")
    end_session(project, "s1")
    assert receiver == [] and not Usage(project).due()
    before = json.loads(nock(project.root, "usage", "--json").stdout)
    assert before["disclosed"] is None and before["would_send"]["project"] == UNMADE
    assert not (project.root / ".nock" / IDENTITY).exists()

    started = json.loads(nock(project.root, "reflect", "--json").stdout)
    assert started["tell_the_owner"] == DISCLOSURE
    again = json.loads(nock(project.root, "reflect", "--json").stdout)
    assert "tell_the_owner" not in again
    number = decide(project.root)["number"]
    assert "tell_the_owner" not in edit(project.root, {"number": number, "review": "accepted"})
    end_session(project, "s2")
    assert receiver == []

    a_week_ago(project)
    nock(project.root, "acme-payroll")
    shown = json.loads(nock(project.root, "usage", "--json").stdout)
    assert shown["would_send"]["project"] == UNMADE
    assert not (project.root / ".nock" / IDENTITY).exists()
    end_session(project, "s3")
    (report,) = receiver
    assert report == {
        **shown["would_send"],
        "metrics": report["metrics"],
        "project": report["project"],
    }
    assert report["toolbox"]["tools"] == 1 and "tools" not in report
    identity = json.loads((project.root / ".nock" / IDENTITY).read_text())["id"]
    assert report["project"] == identity and uuid.UUID(identity).version == 4
    assert git(project.root, "log", "-1", "--format=%s", "--", f".nock/{IDENTITY}").startswith(
        "nock: the project's anonymous id"
    )
    assert report["commands"]["decide"] == {"calls": 1, "failures": 0}
    assert report["metrics"]["sessions"] >= 1
    sent = json.dumps(report)
    for private in ("acme", "payroll", "login", "pytest", "Orders", project.root.name, "README"):
        assert private not in sent
    shown = json.loads(nock(project.root, "usage", "--json").stdout)
    assert shown["would_send"]["project"] == identity
    end_session(project, "s4")
    assert len(receiver) == 1
    assert git(project.root, "status", "--porcelain") == ""


def test_with_share_false_nothing_is_told_made_or_sent(
    project: Project, receiver: list[dict[str, object]]
) -> None:
    silent = shared(project, "false")
    assert "tell_the_owner" not in json.loads(nock(silent.root, "reflect", "--json").stdout)
    shown = json.loads(nock(silent.root, "usage", "--json").stdout)
    assert shown["share"] is False and shown["would_send"] is None and shown["to"] is None
    end_session(silent, "s1")
    assert receiver == []
    assert not (silent.root / ".nock" / IDENTITY).exists()
    refused = nock(silent.root, "share", '{"send": true}')
    assert refused.returncode != 0 and "`share` is false" in refused.stderr


def test_every_clone_reports_the_same_id(project: Project, tmp_path: Path) -> None:
    made = Usage(project).identity()
    clone = tmp_path / "clone"
    git(tmp_path, "clone", "--quiet", str(project.root), str(clone))
    (clone / ".nock" / "local").mkdir(exist_ok=True)
    assert Usage(Project.discover(clone)).report()["project"] == made
    assert Usage(project).report(sending=True)["project"] == made


@pytest.mark.parametrize(
    ("setting", "shares"),
    [('level = "none"', False), ('level = "anonymous"', True), ('level = "public"', True)],
)
def test_an_earlier_share_level_still_reads_sensibly_with_a_note(
    project: Project, setting: str, shares: bool
) -> None:
    old = configure(project, "share = true", f"[share]\n{setting}")
    shown = json.loads(nock(old.root, "usage", "--json").stdout)
    assert shown["share"] is shares and "earlier nock" in shown["note"]
    assert (shown["would_send"] is None) is not shares
    if shares:
        assert set(shown["would_send"]) >= {"project", "commands"}
        assert "tools" not in shown["would_send"] and "level" not in shown["would_send"]


def test_opening_the_page_tells_the_owner_once(project: Project) -> None:
    usage = Usage(project)
    assert usage.disclose(Moment.STUDIO) == DISCLOSURE
    assert usage.disclose(Moment.STUDIO) is None
    assert (
        json.loads((project.root / ".nock" / "local" / "usage.json").read_text())["disclosed"][
            "moment"
        ]
        == "studio"
    )


def test_a_share_that_is_not_true_or_false_is_refused_plainly(project: Project) -> None:
    shared(project, '"everything"')
    result = nock(project.root, "usage")
    assert result.returncode == 42 and "it is true or false" in result.stderr


def test_the_primer_follows_the_committed_settings_not_the_machine_s(project: Project) -> None:
    local = project.root / ".nock" / "local" / "config.toml"
    local.write_text("reminders = false\n" + local.read_text())
    quiet = Project.discover(project.root)
    assert HookRunner(quiet, {"session_id": "s1"}).handle("SessionStart") is None
    assert "Record decisions" in (project.root / ".nock" / "context.md").read_text()
    assert git(project.root, "status", "--porcelain") == ""
