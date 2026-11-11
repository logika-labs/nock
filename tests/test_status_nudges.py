"""`nock status` nudges the session asking: files it changed without
consulting, commits with nothing recorded in the topics, generated files
edited by hand — each only when it applies, and never at a session's start."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from nock.hooks import HookRunner
from nock.project import Project
from nock.status import consult_nudge, gen_nudge, record_nudge

from .conftest import git, nock, write_tool
from .store import submit

HOUR_AGO = (datetime.now(UTC) - timedelta(hours=1)).replace(microsecond=0)


def moment(when: datetime) -> str:
    return when.isoformat().replace("+00:00", "Z")


def session_started(project: Project, session: str, when: datetime) -> None:
    project.store.insert(
        "sessions", {"id": session, "role": "interactive", "started": moment(when)}
    )


def test_a_session_that_changed_files_and_consulted_on_none_is_nudged(project: Project) -> None:
    session_started(project, "s1", HOUR_AGO)
    assert consult_nudge(project, "s1") == ""
    for path in ("src/app.py", "src/app.py", "src/db.py"):
        project.store.insert(
            "events", {"session": "s1", "moment": moment(HOUR_AGO), "tool": "Edit", "input": path}
        )
    said = consult_nudge(project, "s1")
    assert "changed 2 file(s) and consulted on none" in said and "nock consult" in said
    project.store.insert(
        "calls",
        {"tool": "consult", "arguments": "[]", "session": "s1", "started": moment(HOUR_AGO)},
    )
    assert consult_nudge(project, "s1") == ""
    assert consult_nudge(project, None) == ""


def test_commits_with_nothing_recorded_since_nudge_until_the_session_records(
    project: Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "s1")
    assert record_nudge(project, "s1") == ""
    submit(project.root)
    for number in range(3):
        assert record_nudge(project, "s1") == ""
        git(project.root, "commit", "-q", "--allow-empty", "-m", f"Change {number}")
    assert "3 commit(s) since this session last recorded anything" in record_nudge(project, "s1")
    assert record_nudge(project, "s2") == ""
    submit(project.root, {"title": "Orders are kept a year", "decision": {"answer": "Yes."}})
    # nock's own commit for it is the session's latest: nothing since.
    assert record_nudge(project, "s1") == ""


def test_a_generated_file_edited_by_hand_is_nudged(project: Project) -> None:
    write_tool(
        project,
        "versions",
        "import nock\n\n@nock.generator('src/version.py')\ndef version(root):\n"
        "    return 'VERSION = 1'\n",
    )
    assert nock(project.root, "gen").returncode == 0
    assert gen_nudge(project) == ""
    (project.root / "src" / "version.py").write_text("VERSION = 2\n")
    said = gen_nudge(project)
    assert "src/version.py is generated and out of step" in said and "nock gen" in said


def test_status_shows_the_nudges_and_a_session_start_does_not(
    project: Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_tool(
        project,
        "versions",
        "import nock\n\n@nock.generator('src/version.py')\ndef version(root):\n"
        "    return 'VERSION = 1'\n",
    )
    nock(project.root, "gen")
    (project.root / "src" / "version.py").write_text("VERSION = 2\n")
    standing = json.loads(nock(project.root, "status", "--json").stdout)
    assert any("out of step" in line for line in standing["nudges"])
    started = HookRunner(project, {"session_id": "s9"}).handle("SessionStart") or {}
    assert "out of step" not in json.dumps(started)
