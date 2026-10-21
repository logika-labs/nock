"""Decisions: recorded and committed on the main checkout, reviewed by the owner
on the page or in a session, told to the session that recorded them, shown
when a governed file is edited, elaborated by a dispatched agent, and held
to the map. And where it all stands: `nock status`, and the session start."""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from nock.decisions import Decisions
from nock.hooks import HookRunner
from nock.project import Project
from nock.web import Server

from .conftest import git, nock

DRAFT: dict[str, Any] = {
    "title": "Orders live in SQLite",
    "status": "done",
    "summary": "One file is enough for **orders** at today's load.",
    "evidence": ["40 writes a second at the busiest hour"],
    "alternatives": [{"option": "Postgres", "why_not": "a server to run, for load we do not have"}],
    "tags": ["technical", "Storage"],
    "touches": ["README.md"],
}


def decide(directory: Path, draft: dict[str, Any] = DRAFT) -> dict[str, Any]:
    result = nock(directory, "decide", json.dumps(draft), "--json")
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def edit(directory: Path, change: dict[str, Any]) -> dict[str, Any]:
    result = nock(directory, "decisions", "edit", json.dumps(change), "--json")
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def start(project: Project, session: str) -> dict[str, Any]:
    output = HookRunner(project, {"session_id": session}).handle("SessionStart")
    assert output is not None
    return output


@pytest.fixture
def page(project: Project) -> Iterator[str]:
    server = Server(Decisions(project), 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server.address
    server.shutdown()
    server.server_close()


def post(address: str, number: int, word: dict[str, object]) -> tuple[int, dict[str, Any]]:
    request = urllib.request.Request(
        f"{address}decisions/{number}",
        data=json.dumps(word).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read())


def test_a_decision_recorded_in_a_worktree_is_committed_on_the_main_checkout(
    project: Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    worktree = project.root.with_name("feature")
    git(project.root, "worktree", "add", "-q", "-b", "feature", str(worktree))
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "s1")
    recorded = decide(worktree)
    assert recorded["number"] == 1 and recorded["new_tags"] == ["storage"]
    assert set(recorded["tags_in_use"][:2]) == {"storage", "technical"}
    assert not (worktree / ".nock" / "decisions").exists()
    assert git(project.root, "log", "-1", "--format=%s") == "Decision 1: Orders live in SQLite"
    assert git(project.root, "status", "--porcelain") == ""
    decision = Decisions(project).get(1)
    assert decision["review"] == "unreviewed" and decision["tags"] == ["storage", "technical"]
    assert decision["recorded"]["session"] == "s1"
    todo = decide(
        project.root, {"title": "Split orders out", "status": "todo", "summary": "Later."}
    )
    assert todo["number"] == 2 and todo["new_tags"] == []
    listed = json.loads(nock(project.root, "decisions", "list", "--json").stdout)
    assert (
        listed["counts"]["done"]["unreviewed"] == 1 and listed["counts"]["todo"]["unreviewed"] == 1
    )
    only = nock(project.root, "decisions", "list", '{"status": "todo"}', "--json")
    assert [row["number"] for row in json.loads(only.stdout)["decisions"]] == [2]


def test_a_decision_must_say_what_and_supersede_only_what_stands(project: Project) -> None:
    missing = nock(project.root, "decide", json.dumps({"title": "x", "summary": "y"}))
    assert missing.returncode == 40 and "status" in missing.stderr
    first = decide(project.root)["number"]
    itself = nock(
        project.root, "decisions", "edit", json.dumps({"number": first, "supersedes": [first]})
    )
    assert itself.returncode == 40 and "cannot supersede itself" in itself.stderr
    second = decide(
        project.root, {**DRAFT, "title": "Orders move to Postgres", "supersedes": [first]}
    )
    assert Decisions(project).get(first)["superseded_by"] == second["number"]
    third = nock(project.root, "decide", json.dumps({**DRAFT, "supersedes": [first]}))
    assert third.returncode == 40 and f"already superseded by {second['number']}" in third.stderr


def test_a_change_to_what_a_decision_says_asks_for_a_fresh_review(project: Project) -> None:
    number = decide(project.root)["number"]
    accepted = edit(project.root, {"number": number, "review": "accepted", "note": "fine"})
    assert accepted["review"] == "accepted" and accepted["note"] == "fine"
    assert (
        git(project.root, "log", "-1", "--format=%s")
        == f"Decision {number}, accepted: Orders live in SQLite"
    )
    assert edit(project.root, {"number": number, "tags": ["storage"]})["review"] == "accepted"
    reworked = edit(project.root, {"number": number, "status": "todo", "summary": "Not yet."})
    assert reworked["review"] == "unreviewed" and reworked["note"] == "fine"
    assert Decisions(project).get(number)["reviewed"] is None


def test_the_owner_reviews_on_the_page_and_the_recording_session_hears_once(
    project: Project, page: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "s1")
    number = decide(project.root)["number"]
    with urllib.request.urlopen(page) as response:
        assert b"<h1>Decisions</h1>" in response.read()
    with urllib.request.urlopen(f"{page}decisions") as response:
        listed = json.loads(response.read())
        assert listed["decisions"][0]["title"] == "Orders live in SQLite"
        assert "important" in listed["tags"]
    status, error = post(page, number, {"review": "maybe"})
    assert status == 400 and "not one of" in str(error["error"])
    status, error = post(page, number, {"title": "Something else"})
    assert status == 400
    status, decision = post(page, number, {"review": "rejected", "note": "Postgres, please"})
    assert status == 200 and decision["review"] == "rejected"
    assert git(project.root, "status", "--porcelain") == ""

    prompt = HookRunner(project, {"session_id": "s1"}).handle("UserPromptSubmit")
    assert prompt is not None
    told = prompt["hookSpecificOutput"]["additionalContext"]
    assert f"[D{number}] Orders live in SQLite — rejected: Postgres, please" in told
    assert HookRunner(project, {"session_id": "s1"}).handle("UserPromptSubmit") is None
    assert HookRunner(project, {"session_id": "s2"}).handle("UserPromptSubmit") is None

    begun = start(project, "s3")
    context = begun["hookSpecificOutput"]["additionalContext"]
    assert "1 rejected to rework" in context and "/nock-triage" in context
    assert f"- rework [D{number}] Orders live in SQLite — the owner: Postgres, please" in context
    assert "1 rejected to rework" in begun["systemMessage"]
    standing = json.loads(nock(project.root, "status", "--json").stdout)
    assert standing["to_rework"] == [
        {"number": number, "title": "Orders live in SQLite", "note": "Postgres, please"}
    ]
    assert standing["decisions"]["done"]["rejected"] == 1 and standing["reflection"]["due"] is None


def test_an_elaborating_agent_deepens_the_decision(project: Project) -> None:
    number = decide(project.root)["number"]
    asked = edit(project.root, {"number": number, "elaborate": True, "note": "what load?"})
    assert asked["note"] == "what load?"
    result = nock(project.root, "decisions", "elaborate", str(number))
    assert result.returncode == 0, result.stdout + result.stderr
    decision = Decisions(project).get(number)
    assert decision["summary"] == "SQLite holds the load: 40 writes a second."
    assert decision["elaborating"] is False and decision["note"] == "what load?"


def test_an_elaboration_that_edits_nothing_says_so(
    project: Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    number = decide(project.root)["number"]
    Decisions(project).edit({"number": number, "elaborate": True})
    monkeypatch.setenv("FAKE_ELABORATE", "silent")
    result = nock(project.root, "decisions", "elaborate", str(number))
    assert result.returncode == 1 and "was not elaborated" in result.stdout + result.stderr
    assert Decisions(project).get(number)["elaborating"] is False


def edited(project: Project, session: str, path: str) -> str | None:
    payload = {"session_id": session, "tool_name": "Edit", "tool_input": {"file_path": path}}
    output = HookRunner(project, payload).handle("PostToolUse")
    return output["hookSpecificOutput"]["additionalContext"] if output else None


def test_an_edit_to_a_governed_file_shows_its_standing_decisions_once(project: Project) -> None:
    first = decide(project.root)["number"]
    told = edited(project, "s1", str(project.root / "README.md"))
    assert told is not None and f"[D{first}] (done, unreviewed) Orders live in SQLite." in told
    assert edited(project, "s1", "README.md") is None
    assert edited(project, "s1", str(project.root / ".nock" / "config.toml")) is None

    second = decide(
        project.root, {**DRAFT, "title": "Orders move to Postgres", "supersedes": [first]}
    )
    other = decide(project.root, {**DRAFT, "title": "Keep the README short"})
    edit(project.root, {"number": other["number"], "review": "rejected", "note": "it can be long"})
    told = edited(project, "s2", "README.md")
    assert told is not None and f"[D{first}]" not in told
    assert told.index(f"[D{other['number']}]") < told.index(f"[D{second['number']}]")
    assert "The owner: it can be long" in told


def test_the_map_check_holds_citations_and_touches_to_what_exists(project: Project) -> None:
    number = decide(project.root)["number"]
    decisions = Decisions(project)
    decisions.map.write_text(f"- If you touch the database, SQLite [D{number}].\n")
    assert nock(project.root, "check", "nock-map").returncode == 0
    decisions.map.write_text(f"- [D{number}] and [D42]\n")
    (project.root / "README.md").unlink()
    result = nock(project.root, "check", "nock-map")
    assert result.returncode == 1
    assert ".nock/decisions/map.md:1: [D42] is no decision" in result.stdout
    assert "touches `README.md`, which matches no file" in result.stdout


def test_the_edit_hook_is_wired_for_edits_only(project: Project) -> None:
    settings = json.loads((project.root / ".claude" / "settings.json").read_text())
    (entry,) = settings["hooks"]["PostToolUse"]
    assert entry["matcher"] == "Edit|MultiEdit|Write|NotebookEdit"


def test_a_consultation_waits_for_the_reframed_task(project: Project) -> None:
    consultation = {"intent": "Move orders to Postgres.", "context": "SQLite is slow."}
    result = nock(project.root, "consult", json.dumps(consultation))
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.startswith("**The task, reframed**")
    roles = [row["role"] for row in project.store.rows("SELECT role FROM sessions")]
    assert roles == ["consultant"]
