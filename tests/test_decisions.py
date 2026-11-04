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
from nock.studio import PAGES, TABS, Studio

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
    server = Studio(project, 0)
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
    assert not (worktree / ".nock" / "decisions" / "0001.json").exists()
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
        shown = response.read().decode()
    assert '<a href="#decisions" data-tab-link="decisions">Decisions</a>' in shown
    assert '<section data-tab-panel="decisions" hidden>' in shown
    assert "<!-- nock:" not in shown
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


def test_the_map_check_holds_citations_and_gone_files_go_to_the_round(project: Project) -> None:
    decisions = Decisions(project)
    assert "Empty until the first reflection round" in decisions.map.read_text()
    number = decide(project.root)["number"]
    decisions.map.write_text(f"- If you touch the database, SQLite [D{number}].\n")
    assert nock(project.root, "check", "nock-map").returncode == 0
    (project.root / "README.md").unlink()
    assert nock(project.root, "check", "nock-map").returncode == 0
    assert decisions.stale()[0][1] == ["README.md"]
    decisions.map.write_text(f"- [D{number}] and [D42]\n")
    result = nock(project.root, "check", "nock-map")
    assert result.returncode == 1
    assert ".nock/decisions/map.md:1: [D42] is no decision" in result.stdout


def test_a_decision_naming_files_that_do_not_exist_is_told_so(project: Project) -> None:
    recorded = decide(project.root, {**DRAFT, "touches": ["README.md", "ANSWER.md"]})
    assert recorded["touches_no_file"] == ["ANSWER.md"]
    assert "touches_no_file" not in decide(
        project.root, {**DRAFT, "title": "Orders keep a history"}
    )


def test_a_session_starts_with_the_owner_s_backlog_and_notes(project: Project) -> None:
    todo = decide(
        project.root,
        {"title": "Remind before keys expire", "status": "todo", "summary": "A calendar."},
    )
    done = decide(project.root)
    edit(project.root, {"number": todo["number"], "review": "accepted", "note": "Do it this week."})
    edit(project.root, {"number": done["number"], "review": "accepted", "note": "Check the sums."})
    begun = start(project, "s1")
    context = begun["hookSpecificOutput"]["additionalContext"]
    assert "not your task" in context
    assert (
        "nock: the owner's backlog — 1 todo(s) the owner accepted, 1 note(s) the owner left on"
        " decisions lately: `.nock/nock status` lists them." in context
    )
    assert "Remind before keys expire" not in context
    assert "backlog" not in begun.get("systemMessage", "")
    standing = json.loads(nock(project.root, "status", "--json").stdout)
    assert [item["number"] for item in standing["backlog"]] == [todo["number"]]


def test_the_standing_is_said_once_a_day_unless_something_new_calls(
    project: Project, page: str
) -> None:
    number = decide(project.root)["number"]
    assert "1 done unreviewed" in start(project, "s1")["hookSpecificOutput"]["additionalContext"]
    assert HookRunner(project, {"session_id": "s2"}).handle("SessionStart") is None
    decide(project.root, {**DRAFT, "title": "Keep the README short"})
    assert HookRunner(project, {"session_id": "s3"}).handle("SessionStart") is None
    post(page, number, {"review": "rejected", "note": "Postgres, please"})
    context = start(project, "s4")["hookSpecificOutput"]["additionalContext"]
    assert f"- rework [D{number}] Orders live in SQLite — the owner: Postgres, please" in context
    assert HookRunner(project, {"session_id": "s5"}).handle("SessionStart") is None


def test_every_studio_tab_has_its_panel_and_its_routes_only(page: str) -> None:
    for tab in TABS:
        assert f'studio.register("{tab.name}"' in (PAGES / f"{tab.name}.html").read_text()
    for path in ("nothing", "decisions/7", "decisions/extra"):
        with pytest.raises(urllib.error.HTTPError) as missing:
            urllib.request.urlopen(f"{page}{path}")
        assert missing.value.code == 404
    status, error = post(page, 1, {"review": "accepted"})
    assert status == 404 and "decision" in error["error"]
    request = urllib.request.Request(f"{page}decisions/1", data=b"{", method="POST")
    with pytest.raises(urllib.error.HTTPError) as malformed:
        urllib.request.urlopen(request)
    assert malformed.value.code == 400


def test_the_owner_s_call_is_listed_at_session_start_until_reviewed(
    project: Project, page: str
) -> None:
    call = decide(
        project.root,
        {
            "title": "Refunds never exceed the charge",
            "status": "done",
            "summary": "A rule would flag every refund larger than its charge.",
            "alternatives": [{"option": "Goodwill refunds may", "why_not": "none in the data"}],
            "tags": ["logika", "important"],
        },
    )
    asked = nock(project.root, "decide", json.dumps({**DRAFT, "status": "question"}))
    assert asked.returncode == 40 and "status" in asked.stderr
    begun = start(project, "s1")
    assert "1 important" in begun["systemMessage"]
    assert "important decisions awaiting review" in begun["systemMessage"]
    context = begun["hookSpecificOutput"]["additionalContext"]
    assert f"- [D{call['number']}] Refunds never exceed the charge" in context
    standing = json.loads(nock(project.root, "status", "--json").stdout)
    assert [item["number"] for item in standing["important"]] == [call["number"]]
    status, _ = post(page, call["number"], {"review": "rejected", "note": "Up to 110%."})
    assert status == 200
    context = start(project, "s2")["hookSpecificOutput"]["additionalContext"]
    assert "important decisions awaiting review" not in context
    assert (
        f"- rework [D{call['number']}] Refunds never exceed the charge — the owner: Up to 110%."
        in context
    )
    assert json.loads(nock(project.root, "status", "--json").stdout)["important"] == []


def test_an_earlier_nock_s_question_reads_as_an_important_decision(project: Project) -> None:
    number = decide(project.root)["number"]
    path = Decisions(project).path(number)
    written = json.loads(path.read_text())
    path.write_text(json.dumps({**written, "status": "question", "review": "accepted"}))
    read = Decisions(project).get(number)
    assert read["status"] == "done" and read["review"] == "accepted"
    assert read["tags"] == ["important", "storage", "technical"]
    listed = json.loads(nock(project.root, "decisions", "list", "--json").stdout)
    assert listed["counts"]["done"]["accepted"] == 1 and "question" not in listed["counts"]
    edit(project.root, {"number": number, "note": "Fine."})
    rewritten = json.loads(path.read_text())
    assert rewritten["status"] == "done" and "important" in rewritten["tags"]
    assert rewritten["review"] == "accepted"


def test_the_edit_hook_is_wired_for_edits_only(project: Project) -> None:
    settings = json.loads((project.root / ".claude" / "settings.json").read_text())
    (entry,) = settings["hooks"]["PostToolUse"]
    assert entry["matcher"] == "Edit|MultiEdit|Write|NotebookEdit"


def consult(project: Project, intent: str = "Move orders to Postgres.") -> str:
    consultation = {"intent": intent, "context": "SQLite is slow."}
    result = nock(project.root, "consult", json.dumps(consultation))
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout


def test_a_consultation_prints_the_advice_then_what_it_names(
    project: Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    number = decide(project.root)["number"]
    local = project.root / ".nock" / "local" / "config.toml"
    local.write_text(local.read_text() + '[checks.test]\ncommand = "true"\n')
    advice = {
        "advice": "Orders stay in SQLite unless the load changes: say why it has.",
        "decisions": [number],
        "tools": ["decisions list"],
        "checks": ["test"],
        "feedback": "No decision said what the load is.",
    }
    monkeypatch.setenv("FAKE_ADVICE", json.dumps(advice))
    printed = consult(project)
    assert printed.startswith("Orders stay in SQLite unless the load changes: say why it has.")
    assert f"- [D{number}] (done, unreviewed) Orders live in SQLite." in printed
    assert "- `.nock/nock decisions list [JSON]`: The standing decisions" in printed
    assert "Before you finish: `.nock/nock check test`." in printed
    roles = [row["role"] for row in project.store.rows("SELECT role FROM sessions")]
    assert roles == ["consultant"]
    (kept,) = (project.root / ".nock" / "local" / "consultations").glob("*.json")
    record = json.loads(kept.read_text())
    assert record["intent"] == "Move orders to Postgres." and record["submitted"] == advice


def test_advice_naming_what_does_not_exist_is_refused_and_fixed(
    project: Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    advice = {
        "advice": "Use the tool.",
        "decisions": [42],
        "tools": ["decisions lst"],
        "checks": ["lint"],
    }
    monkeypatch.setenv("FAKE_ADVICE", json.dumps(advice))
    printed = consult(project)
    assert printed.strip() == "Use the tool."
    log = project.store.rows("SELECT exit_code FROM calls WHERE tool = 'advise' ORDER BY id")
    assert [row["exit_code"] for row in log] == [40, 0]


def test_only_a_dispatched_consultant_submits_advice(project: Project) -> None:
    result = nock(project.root, "advise", json.dumps({"advice": "Do it."}))
    assert result.returncode == 43 and "only the consultant nock dispatches" in result.stderr


def test_a_consultant_that_answers_in_its_last_message_is_still_heard(
    project: Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FAKE_ADVICE", "silent")
    assert consult(project).strip() == "Nothing bears on it."


def test_the_consultant_off_dispatches_nothing_and_the_primer_asks_for_none(
    project: Project,
) -> None:
    primer = project.root / ".nock" / "context.md"
    assert "**Consult before you change code,**" in primer.read_text()
    config = project.root / ".nock" / "config.toml"
    config.write_text(config.read_text().replace("enabled = true", "enabled = false"))
    assert "consultant is off in this project" in consult(project)
    assert project.store.rows("SELECT role FROM sessions") == []
    HookRunner(project, {"session_id": "s1"}).handle("SessionStart")
    assert "consult" not in primer.read_text()


def test_a_title_a_standing_decision_has_is_refused_unless_forced(project: Project) -> None:
    first = decide(project.root)["number"]
    again = nock(project.root, "decide", json.dumps({**DRAFT, "title": "orders live in SQLite!"}))
    assert again.returncode == 1
    assert f"decision {first} already says this" in again.stderr + again.stdout
    near = nock(project.root, "decide", json.dumps({**DRAFT, "title": "Orders lives in SQLite"}))
    assert near.returncode == 1
    superseding = decide(project.root, {**DRAFT, "supersedes": [first]})["number"]
    forced = nock(project.root, "decide", json.dumps(DRAFT), "--force", "--json")
    assert forced.returncode == 0, forced.stderr
    assert json.loads(forced.stdout)["number"] == superseding + 1


def test_a_decision_that_should_not_have_been_recorded_is_deleted(project: Project) -> None:
    first = decide(project.root)["number"]
    second = decide(
        project.root, {**DRAFT, "title": "Orders move to Postgres", "supersedes": [first]}
    )["number"]
    result = nock(project.root, "decisions", "delete", str(second), "--json")
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"deleted": second}
    assert not Decisions(project).path(second).exists()
    assert Decisions(project).get(first)["superseded_by"] is None
    assert git(project.root, "log", "-1", "--format=%s") == (
        f"Decision {second}, deleted: Orders move to Postgres"
    )
    assert git(project.root, "status", "--porcelain") == ""
    assert nock(project.root, "decisions", "delete", str(second)).returncode == 44


def test_a_project_s_tag_vocabulary_is_the_only_tags_it_takes(project: Project, page: str) -> None:
    config = project.root / ".nock" / "config.toml"
    config.write_text(config.read_text() + '\n[decisions]\ntags = ["core", "web"]\n')
    git(project.root, "commit", "-qam", "Fix the tags")
    outside = nock(project.root, "decide", json.dumps(DRAFT))
    assert outside.returncode == 40
    assert "storage, technical: not in the project's tags (core, web, important" in outside.stderr
    recorded = decide(project.root, {**DRAFT, "tags": ["Core", "important"]})
    assert Decisions(project).get(recorded["number"])["tags"] == ["core", "important"]
    refused = nock(
        project.root,
        "decisions",
        "edit",
        json.dumps({"number": recorded["number"], "tags": ["ui"]}),
    )
    assert refused.returncode == 40 and "ui: not in the project's tags" in refused.stderr
    assert "core, web, important" in nock(project.root, "decide", "--help").stdout
    HookRunner(project, {"session_id": "s1"}).handle("SessionStart")
    assert (
        "Tags: `core`, `web` and `important`."
        in (project.root / ".nock" / "context.md").read_text()
    )
    with urllib.request.urlopen(f"{page}decisions") as response:
        listed = json.loads(response.read())
    assert listed["vocabulary"][:3] == ["core", "web", "important"]
    assert list(listed["tags"])[:2] == ["core", "important"]


def test_the_page_filters_the_important_and_shows_each_decision_s_tags() -> None:
    fragment = (PAGES / "decisions.html").read_text()
    assert 'chip("flag", "important"' in fragment
    assert "${tagChips(decision)}" in fragment
    assert "state.vocabulary" in fragment
