"""The studio's page and what the owner does on it, through its API as the
page calls it: the tasks and their counts, a task whole, notes, Send (an
answer now: an agent waiting on its inbox, else one dispatched in the
background, its turn streamed), Accept and Reject, Done, the html blocks with
their bridge, the memory, and the rounds' hints with Run, snooze and settings."""

from __future__ import annotations

import json
import time
import urllib.request
from typing import Any

from nock.project import Project

from .conftest import get, git, post
from .store import asset, compose, propose, submit, topics_in


def settled_run(page: str, identifier: str) -> dict[str, Any]:
    """A run, once it is no longer running."""
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        run = get(page, f"run/{identifier}")["run"]
        if run["status"] != "running":
            return run
        time.sleep(0.2)
    raise AssertionError("the run is still running")


def test_the_front_page_counts_active_tasks_and_what_waits_on_the_owner(
    project: Project, page: str
) -> None:
    root = project.root
    submit(root)
    propose(root)
    compose(root, "orders", [{"kind": "item", "item": "archive"}], summary="Orders, archived")
    front = get(page, "topics")
    assert front["word"] == "task" and front["words"] == "tasks"
    assert [entry["topic"] for entry in front["active"]] == ["orders"]
    assert {(entry["kind"], entry["topic"]) for entry in front["pending"]} == {
        ("proposal", "orders"),
        ("review", "orders"),
    }
    (task,) = front["tasks"]
    assert task["summary"] == "Orders, archived"
    assert [entry["slug"] for entry in task["items"]] == ["sqlite", "archive"]
    assert front["hints"][0]["protocol"] == "nock.fit"
    before = get(page, "stamp")["stamp"]
    topics_in(root).note("orders", {"item": "sqlite"}, "Fine")
    assert get(page, "stamp")["stamp"] != before


def test_a_task_whole_with_its_assets_review_and_html_bridge(project: Project, page: str) -> None:
    root = project.root
    submit(root)
    asset(root, "orders", "schema", "a\n", file_name="schema.sql")
    asset(root, "orders", "schema", "b\n", file_name="schema.sql")
    compose(
        root,
        "orders",
        [{"kind": "diff", "asset": "schema"}, {"kind": "html", "file": "flow.html"}],
        files={"flow.html": "<html><head></head><body><p>flow</p></body></html>"},
    )
    whole = get(page, "topic/orders")
    (schema,) = whole["assets"]
    assert [version["text"] for version in schema["versions"]] == ["a\n", "b\n"]
    with urllib.request.urlopen(page + schema["versions"][1]["address"].lstrip("/")) as response:
        assert response.read() == b"b\n"
    assert whole["review"]["versions"][0]["blocks"][1]["id"] == "b2"
    with urllib.request.urlopen(f"{page}api/html/orders/1/flow.html") as response:
        html = response.read().decode()
    assert "window.nock" in html and "<p>flow</p>" in html
    status, _ = post(page, "verdict", {"ref": "orders/sqlite", "verdict": "accepted"})
    assert status == 400


def test_a_note_and_send_reach_an_agent_waiting_on_its_inbox(project: Project, page: str) -> None:
    root = project.root
    submit(root)
    (project.local / "inbox-listening.json").write_text(json.dumps({"waiter": time.time() + 600}))
    status, noted = post(
        page,
        "note",
        {"topic": "orders", "on": {"item": "sqlite"}, "text": "Why?", "id": "0000aaaa"},
    )
    assert status == 200 and noted["note"]["id"] == "0000aaaa"
    status, sent = post(page, "send", {"topic": "orders", "text": "", "id": "1111bbbb"})
    assert status == 200 and sent["run"] == {"listening": True, "topic": "orders"}
    assert sent["message"]["notes"] == ["0000aaaa"]
    urged = json.loads((project.local / "inbox-now.json").read_text())
    assert urged == ["1111bbbb"]


def test_send_dispatches_an_answer_that_streams_and_replies_in_the_chat(
    project: Project, page: str, monkeypatch: Any
) -> None:
    root = project.root
    monkeypatch.setenv("FAKE_SHARED", str(root / ".nock" / "shared"))
    submit(root)
    status, sent = post(page, "send", {"topic": "orders", "text": "Backed up?"})
    assert status == 200 and sent["run"]["status"] == "running", sent
    run = settled_run(page, sent["run"]["id"])
    assert run["status"] == "done", run
    kinds = [event["kind"] for event in run["events"]]
    assert {"thinking", "tool", "result", "text"} <= set(kinds)
    thread = topics_in(root).topic("orders")["thread"]
    reply = thread[-1]
    assert reply["author"] == "agent" and reply["text"] == "You said: Backed up?"
    assert run["message"] == reply["id"] and reply["answers"] == sent["message"]["id"]
    assert git(root, "status", "--porcelain", "--", ".nock/shared") == ""
    # The next answer resumes the chat's session.
    status, again = post(page, "send", {"topic": "orders", "text": "And restores?"})
    assert settled_run(page, again["run"]["id"])["status"] == "done"
    log = json.loads((project.local / "runs-sessions.json").read_text())
    assert log["orders"]


def test_done_on_the_review_closes_the_task(project: Project, page: str) -> None:
    root = project.root
    submit(root)
    compose(root, "orders", [{"kind": "item", "item": "sqlite"}])
    status, done = post(page, "done", {"topic": "orders"})
    assert status == 200 and done == {"sent": False, "state": "done", "run": None}


def test_the_memory_is_read_edited_and_noted(project: Project, page: str) -> None:
    root = project.root
    memory = get(page, "memory")
    assert memory["text"].startswith("# What nock has learned here") and memory["notes"] == []
    status, saved = post(page, "memory", {"text": "- orders live in SQLite\n"})
    assert status == 200 and saved["text"] == "- orders live in SQLite\n"
    assert "memory.md" in git(root, "show", "--name-only", "--format=", "HEAD")
    status, _ = post(
        page, "note", {"topic": "memory", "on": {"memory": True, "line": 1}, "text": "Postgres now"}
    )
    assert status == 200
    (note,) = get(page, "memory")["notes"]
    assert note["target"] == "the memory, line 1"


def test_a_round_runs_from_its_hint_and_is_snoozed_or_set(project: Project, page: str) -> None:
    status, started = post(page, "rounds/run", {"name": "nock.fit"})
    assert status == 200 and started["run"]["topic"] == "round-nock-fit"
    status, twice = post(page, "rounds/run", {"name": "nock.fit"})
    assert status == 400 and "running already" in twice["error"]
    run = settled_run(page, started["run"]["id"])
    assert run["status"] == "done", run
    assert "round-nock-fit" in topics_in(project.root).names()
    status, snoozed = post(page, "rounds/snooze", {"name": "audit.tests", "days": 3})
    assert status == 200 and snoozed["round"]["snooze_until"]
    status, changed = post(page, "rounds/set", {"name": "audit.tests", "threshold": 50})
    assert status == 200 and changed["round"]["measure"]["threshold"] == 50
    rounds = {row["protocol"]: row for row in get(page, "rounds")["rounds"]}
    assert rounds["audit.tests"]["measure"]["threshold"] == 50
