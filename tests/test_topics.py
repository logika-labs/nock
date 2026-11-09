"""Topics and items: agents open a topic per piece of work and submit bare
items into it — decisions, project files, derived files — committed on the
main checkout whichever worktree writes; the owner gives verdicts and talks
in the threads, on the page or with `/nock-triage`; agents hear of it, find
what awaits them in `topics list`, and an earlier nock's decisions and review
items move into topics once."""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from nock.chats import Kind, Turn
from nock.hooks import HookRunner
from nock.migration import Migration
from nock.project import Project
from nock.studio import PAGES, TABS, Studio
from nock.topics import Author, Topics, owner_word

from .conftest import git, nock

TOPIC = {"name": "orders", "description": "Where orders are kept, for the checkout work."}
DECISION: dict[str, Any] = {
    "title": "Orders live in SQLite",
    "decision": {
        "answer": "One file is enough for **orders** at today's load.",
        "alternatives": [{"option": "Postgres", "why_not": "a server to run, for load we lack"}],
    },
}


def run(directory: Path, *arguments: str) -> Any:
    result = nock(directory, *arguments, "--json")
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads(result.stdout) if result.stdout.strip() else None


def open_topic(directory: Path, topic: dict[str, str] = TOPIC) -> str:
    return run(directory, "topics", "create", json.dumps(topic))["name"]


def submit(directory: Path, item: dict[str, Any] = DECISION, topic: str = "orders") -> str:
    main = Path(git(directory, "rev-parse", "--path-format=absolute", "--git-common-dir")).parent
    if not (main / ".nock" / "topics" / topic).is_dir():
        open_topic(directory, {**TOPIC, "name": topic})
    return run(directory, "items", "create", topic, json.dumps(item))["ref"]


def judge(directory: Path, ref: str, verdict: str, comment: str = "") -> Any:
    word = {"verdict": verdict, **({"comment": comment} if comment else {})}
    return run(directory, "items", "judge", ref, json.dumps(word))


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


def post(address: str, route: str, body: dict[str, Any]) -> tuple[int, Any]:
    request = urllib.request.Request(
        f"{address}topics/{route}",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read())


def test_an_item_submitted_in_a_worktree_is_committed_on_the_main_checkout(
    project: Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    worktree = project.root.with_name("feature")
    git(project.root, "worktree", "add", "-q", "-b", "feature", str(worktree))
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "s1")
    ref = submit(worktree)
    assert ref == "orders/orders-live-in-sqlite"
    assert not (worktree / ".nock" / "topics" / "orders").exists()
    folder = project.root / ".nock" / "topics" / "orders" / "orders-live-in-sqlite"
    decision = json.loads((folder / "1" / "decision.json").read_text())
    assert decision["status"] == "done" and decision["alternatives"][0]["option"] == "Postgres"
    assert git(project.root, "log", "-1", "--format=%s") == (
        "Item orders/orders-live-in-sqlite: Orders live in SQLite"
    )
    assert git(project.root, "status", "--porcelain") == ""
    shown = run(project.root, "items", "show", ref)
    assert shown["verdict"] == "open" and shown["versions"][0]["session"] == "s1"
    again = submit(worktree)
    assert again == "orders/orders-live-in-sqlite-2"


def test_an_item_holds_something_and_a_project_file_is_in_the_repository(
    project: Project, tmp_path: Path
) -> None:
    open_topic(project.root)
    empty = nock(project.root, "items", "create", "orders", '{"title": "Nothing"}')
    assert empty.returncode == 40 and "give `decision`, `files`, `derived`" in empty.stderr
    outside = tmp_path / "shot.png"
    outside.write_bytes(b"\x89PNG\r\n")
    wrong = nock(
        project.root,
        "items",
        "create",
        "orders",
        json.dumps({"title": "A", "files": [str(outside)]}),
    )
    assert wrong.returncode == 40 and "goes in `derived`" in wrong.stderr
    nowhere = nock(project.root, "items", "create", "nowhere", json.dumps(DECISION))
    assert nowhere.returncode == 44 and "no topic 'nowhere'" in nowhere.stderr


def test_a_new_version_copies_project_files_as_they_are_now_and_reopens_the_item(
    project: Project, tmp_path: Path
) -> None:
    shot = tmp_path / "email.png"
    shot.write_bytes(b"\x89PNG one")
    picture = {
        "title": "The lapsed payment email",
        "derived": [
            {
                "path": str(shot),
                "from": ["README.md"],
                "when": "the payment lapsed",
                "recipe": {"command": "make email"},
            }
        ],
    }
    drawn = submit(project.root, picture)
    run(project.root, "items", "update", drawn, "--version", "{}")
    carried = run(project.root, "items", "show", drawn)["versions"][1]["files"][0]
    assert carried["name"] == "email.png" and carried["when"] == "the payment lapsed"
    assert Path(carried["where"]).read_bytes() == b"\x89PNG one"
    ref = submit(project.root, {"title": "The README", "files": ["README.md"]})
    judge(project.root, ref, "rejected", "Bolder subject line.")
    refused = nock(project.root, "items", "update", ref, '{"title": "Bolder"}')
    assert refused.returncode == 49 and "--version" in refused.stderr
    (project.root / "README.md").write_text("# demo, changed\n")
    git(project.root, "commit", "-qam", "Change the README")
    updated = run(project.root, "items", "update", ref, "--version", "{}")
    assert updated == {"ref": ref, "verdict": "open", "versions": 2}
    shown = run(project.root, "items", "show", ref)
    first, second = (version["files"] for version in shown["versions"])
    assert Path(first[0]["where"]).read_text() == "# demo\n"
    assert Path(second[0]["where"]).read_text() == "# demo, changed\n"
    assert shown["thread"][0] == {
        **shown["thread"][0],
        "author": "owner",
        "text": "Bolder subject line.",
        "verdict": "rejected",
    }
    run(project.root, "items", "update", ref, '{"title": "The README, bolder"}')
    assert run(project.root, "items", "show", ref)["versions"][-1]["version"] == 2


def test_only_an_open_item_the_owner_has_not_written_on_is_deleted(project: Project) -> None:
    ref = submit(project.root)
    keep = submit(project.root, {**DECISION, "title": "Orders are never deleted"})
    run(project.root, "items", "update", keep, "--reply", "Why not archive them?")
    judge(project.root, keep, "accepted")
    refused = nock(project.root, "items", "delete", keep)
    assert refused.returncode == 43 and "the owner's word" in refused.stderr
    run(project.root, "items", "delete", ref)
    assert not (project.root / ".nock" / "topics" / "orders" / "orders-live-in-sqlite").exists()
    not_empty = nock(project.root, "topics", "delete", "orders")
    assert not_empty.returncode == 49 and "holds items" in not_empty.stderr
    open_topic(project.root, {"name": "spare", "description": "Nothing yet."})
    run(project.root, "topics", "delete", "spare")
    assert git(project.root, "status", "--porcelain") == ""


def test_an_item_moves_to_another_topic_whatever_its_verdict_and_its_old_refs_resolve(
    project: Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    ref = submit(
        project.root, {"title": DECISION["title"], "derived": [{"text": "big", "name": "big.txt"}]}
    )
    item = project.root / ".nock" / "topics" / "orders" / "orders-live-in-sqlite" / "item.json"
    record = json.loads(item.read_text())
    item.write_text(json.dumps({**record, "aliases": ["7"]}))
    git(project.root, "commit", "-qam", "An earlier decision's number")
    run(project.root, "items", "update", ref, "--reply", "Why not Postgres?")
    judge(project.root, ref, "accepted")
    open_topic(project.root, {"name": "storage", "description": "Where data is kept."})
    taken = submit(project.root, DECISION, topic="storage")
    assert taken == "storage/orders-live-in-sqlite"
    (project.root / ".nock" / "topics" / "map.md").write_text(f"- [{ref}] and [D7] hold.\n")
    git(project.root, "add", "-A")
    git(project.root, "commit", "-qm", "The map")
    topics = Topics(project)
    monkeypatch.setattr("nock.topics.LARGE", 2)
    topics.update_item(ref, None, version={"derived": [{"text": "bigger", "name": "big.txt"}]})
    large = project.local / "topics" / "orders" / "orders-live-in-sqlite" / "2" / "big.txt"
    assert large.is_file()
    moved = run(project.root, "items", "update", ref, json.dumps({"topic": "storage"}))
    assert moved["ref"] == "storage/orders-live-in-sqlite-2"
    record = topics.item(moved["ref"])
    assert record["verdict"] == "open" and record["thread"][0]["text"] == "Why not Postgres?"
    assert [version["version"] for version in record["versions"]] == [1, 2]
    assert record["aliases"] == ["7", ref]
    assert topics.item("7")["ref"] == topics.item("D7")["ref"] == topics.item(ref)["ref"]
    assert topics.item("storage/7")["ref"] == moved["ref"]
    assert (
        project.local / "topics" / "storage" / "orders-live-in-sqlite-2" / "2" / "big.txt"
    ).is_file()
    assert topics.file("storage", "orders-live-in-sqlite-2", 1, "big.txt").read_text() == "big"
    assert topics.citation_problems() == []
    assert not (project.root / ".nock" / "topics" / "orders" / "orders-live-in-sqlite").exists()
    assert git(project.root, "status", "--porcelain") == ""
    judge(project.root, moved["ref"], "accepted")
    again = run(project.root, "items", "update", moved["ref"], json.dumps({"topic": "orders"}))
    assert again["ref"] == "orders/orders-live-in-sqlite-2" and again["verdict"] == "accepted"
    assert topics.item(ref)["aliases"] == ["7", ref, "storage/orders-live-in-sqlite-2"]
    refused = nock(project.root, "items", "update", ref, json.dumps({"topic": "nowhere"}))
    assert refused.returncode != 0 and "no topic 'nowhere'" in refused.stderr


def test_list_summarises_what_is_open_and_what_awaits_an_agent_unless_full(
    project: Project, page: str
) -> None:
    for number in range(20):
        submit(project.root, {**DECISION, "title": f"Decision number {number}"})
    asked = submit(
        project.root,
        {"title": "Pricing is per seat", "decision": {"answer": "Per seat, monthly."}},
        topic="pricing",
    )
    post(page, "reply", {"ref": asked, "text": "Why not per project?"})
    rejected = submit(project.root, {**DECISION, "title": "Refunds are manual"}, topic="pricing")
    post(page, "judge", {"ref": rejected, "verdict": "rejected"})
    listed = run(project.root, "items", "list")
    assert listed["summary"] == {
        "open": {"orders": 20, "pricing": 1},
        "awaiting_you": {"owner_wrote_last": [asked], "rejected": [rejected]},
    }
    assert len(listed["rows"]) == 15 and "--full" in listed["more"]
    full = run(project.root, "items", "list", "--full")
    assert "summary" not in full and len(full["rows"]) == 22
    topics = run(project.root, "topics", "list", "--full")["rows"]
    assert [row["name"] for row in topics] == ["pricing", "orders"]
    assert topics[0]["open"] == 1 and topics[0]["rejected"] == 1
    found = run(project.root, "items", "list", "--query", "per project seat", "--full")["rows"]
    assert found[0]["ref"] == asked
    assert run(project.root, "topics", "list", "--query", "seat", "--full")["rows"][0]["name"] == (
        "pricing"
    )


def test_a_topic_keeps_its_state_and_status_each_change_in_its_thread(project: Project) -> None:
    open_topic(project.root, {**TOPIC, "status": "reading the order code"})
    shown = run(project.root, "topics", "show", "orders")
    assert shown["state"] == "active" and shown["status"] == "reading the order code"
    run(project.root, "topics", "update", "orders", '{"status": "waiting for the gate on main"}')
    planned = run(project.root, "topics", "update", "orders", '{"state": "planned"}')
    assert planned == {"name": "orders", "state": "planned"}
    record = Topics(project).topic("orders")
    assert record["status"] == ""
    entries = [entry for entry in record["thread"] if entry.get("kind") == "status"]
    assert [(entry["state"], entry["status"]) for entry in entries] == [
        ("active", "reading the order code"),
        ("active", "waiting for the gate on main"),
        ("planned", ""),
    ]
    assert all(entry["role"] == "interactive" for entry in entries)
    wrong = nock(project.root, "topics", "update", "orders", '{"state": "finished"}')
    assert wrong.returncode == 40
    open_topic(project.root, {"name": "pricing", "description": "Seats.", "state": "planned"})
    listed = run(project.root, "topics", "list", "--state", "planned", "--full")["rows"]
    assert sorted(row["name"] for row in listed) == ["orders", "pricing"]
    assert run(project.root, "topics", "list", "--state", "done", "--full")["rows"] == []


def test_a_status_entry_answers_nothing_the_owner_said(project: Project) -> None:
    open_topic(project.root)
    topics = Topics(project)
    topics.update_topic("orders", {}, reply="Where are we?", author=Author.OWNER)
    run(project.root, "topics", "update", "orders", '{"status": "half done"}')
    assert topics.awaiting()["owner_wrote_last"] == ["orders"]
    assert topics.withdraw(topic="orders") == "Where are we?"
    thread = topics.topic("orders")["thread"]
    assert [entry.get("kind") for entry in thread] == ["status"]


def test_a_done_topic_takes_no_new_items_until_it_is_revived(project: Project) -> None:
    ref = submit(project.root)
    early = nock(project.root, "topics", "update", "orders", "--revive", "Back.")
    assert early.returncode == 49 and "no need to revive it" in early.stderr
    run(project.root, "topics", "update", "orders", '{"state": "done", "status": "shipped"}')
    again = nock(project.root, "items", "create", "orders", json.dumps(DECISION))
    assert again.returncode == 49 and "--revive" in again.stderr and "is done" in again.stderr
    made = nock(project.root, "topics", "create", json.dumps(TOPIC))
    assert made.returncode == 49 and "revive it" in made.stderr
    judge(project.root, ref, "accepted")
    run(project.root, "items", "update", ref, "--reply", "Thanks.")
    run(project.root, "topics", "update", "orders", '{"state": "abandoned"}')
    revived = run(
        project.root, "topics", "update", "orders", "--revive", "Orders move to a second region."
    )
    assert revived["state"] == "active"
    later = submit(project.root, {**DECISION, "title": "Orders replicate to the second region"})
    shown = run(project.root, "topics", "show", "orders")
    assert shown["description"] == "Orders move to a second region."
    assert [item["ref"] for item in shown["items"]] == [later, ref]
    assert shown["thread"][-1]["revived"] is True and shown["thread"][-1]["state"] == "active"


def test_what_a_subagent_writes_names_the_session_that_dispatched_it(
    project: Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    def about_to_run(command: str, **agent: str) -> None:
        payload = {"session_id": "lead", "tool_input": {"command": command}, **agent}
        assert HookRunner(project, payload).handle("PreToolUse") is None

    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "lead")
    about_to_run(f".nock/nock topics create '{json.dumps(TOPIC)}' --json")
    open_topic(project.root)
    about_to_run(
        f"cd {project.root} && .nock/nock items create orders '{json.dumps(DECISION)}' --json",
        agent_id="a1b2",
        agent_type="general-purpose",
    )
    about_to_run("git status")
    ref = submit(project.root)
    topic = Topics(project).topic("orders")
    assert topic["created"]["session"] == "lead" and "parent" not in topic["created"]
    shown = run(project.root, "items", "show", ref)
    assert shown["created"]["session"] == "a1b2" and shown["created"]["parent"] == "lead"
    assert shown["versions"][0]["role"] == "general-purpose"
    noted = project.store.rows("SELECT command, claimed FROM callers")
    assert [row["claimed"] for row in noted] == [1, 1]
    # The owner's word, recorded in another session: news to the one whose subagent made it.
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "triage")
    judge(project.root, ref, "rejected", "Not SQLite.")
    news = HookRunner(project, {"session_id": "lead"}).handle("UserPromptSubmit")
    assert news is not None and ref in news["hookSpecificOutput"]["additionalContext"]
    monkeypatch.setenv("NOCK_PARENT_SESSION", "lead")
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "dispatched")
    monkeypatch.setenv("NOCK_ROLE", "consultant")
    run(project.root, "topics", "update", "orders", '{"status": "consulted"}')
    entry = Topics(project).topic("orders")["thread"][-1]
    assert (entry["session"], entry["parent"], entry["role"]) == (
        "dispatched",
        "lead",
        "consultant",
    )


def test_a_session_that_never_said_where_its_topic_stands_is_asked_once(
    project: Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "s1")
    submit(project.root)
    stop = {"session_id": "s1", "stop_hook_active": False}
    assert HookRunner(project, {"session_id": "s2"}).handle("Stop") is None
    asked = HookRunner(project, stop).handle("Stop")
    assert asked is not None and asked["decision"] == "block"
    assert "orders" in asked["reason"] and "status" in asked["reason"]
    assert HookRunner(project, stop).handle("Stop") is None
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "s3")
    submit(project.root, {**DECISION, "title": "Orders are kept a year"})
    run(project.root, "topics", "update", "orders", '{"status": "two decisions in"}')
    assert HookRunner(project, {"session_id": "s3"}).handle("Stop") is None
    assert Topics(project).unstated("s1") == ["orders"]
    run(project.root, "topics", "update", "orders", '{"state": "done"}')
    assert Topics(project).unstated("s1") == []


def test_a_topic_in_review_waits_on_the_owner_and_its_work_counts_as_stated(
    project: Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "s1")
    ref = submit(project.root)
    stop = {"session_id": "s1", "stop_hook_active": False}
    asked = HookRunner(project, stop).handle("Stop")
    assert asked is not None and '"review"' in asked["reason"]
    reviewed = run(project.root, "topics", "update", "orders", '{"state": "review"}')
    assert reviewed == {"name": "orders", "state": "review"}
    assert Topics(project).unstated("s1") == []
    later = submit(project.root, {**DECISION, "title": "Orders are kept a year"})
    assert later.startswith("orders/")
    judge(project.root, ref, "rejected", "Not SQLite.")
    open_topic(project.root, {"name": "pricing", "description": "Seats.", "state": "review"})
    listed = run(project.root, "topics", "list", "--state", "review", "--full")["rows"]
    assert sorted(row["name"] for row in listed) == ["orders", "pricing"]
    closed = nock(
        project.root, "topics", "create", json.dumps({**TOPIC, "name": "x", "state": "done"})
    )
    assert closed.returncode == 40 and "review" in closed.stderr
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "s2")
    submit(project.root, {**DECISION, "title": "Orders are archived"}, "pricing")
    assert Topics(project).unstated("s2") == []


def test_a_studio_older_than_its_code_asks_to_be_restarted_unless_it_would_cut_something_off(
    project: Project,
) -> None:
    server = Studio(project, 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:

        def standing() -> dict[str, Any]:
            with urllib.request.urlopen(f"{server.address}restart") as response:
                return json.loads(response.read())

        assert standing()["stale"] is False and standing()["busy"] == []
        server.started -= 1
        assert standing()["stale"] is True
        tidy = server.chats.create(Kind.TIDY)
        server.chats.save(tidy)
        server.chats.turns[tidy["id"]] = Turn(started=tidy["created"])
        assert standing()["busy"] == ["Tidy up is running"]
        refused = urllib.request.Request(f"{server.address}restart", b"{}", method="POST")
        with pytest.raises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(refused)
        assert (
            error.value.code == 409
            and "Tidy up is running" in json.loads(error.value.read())["error"]
        )
        assert not server.restarting
    finally:
        server.shutdown()
        server.server_close()


def test_a_restart_starts_the_studio_again_in_place_on_its_port(project: Project) -> None:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    process = subprocess.Popen(
        [str(project.root / ".nock" / "nock"), "studio", json.dumps({"port": port})],
        cwd=project.root,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    address = f"http://127.0.0.1:{port}/restart"

    def standing() -> dict[str, Any] | None:
        try:
            with urllib.request.urlopen(address, timeout=2) as response:
                return json.loads(response.read())
        except OSError:
            return None

    def answered(check: Any) -> dict[str, Any]:
        for _ in range(200):
            seen = standing()
            if seen is not None and check(seen):
                return seen
            time.sleep(0.05)
        raise AssertionError("the studio did not answer as expected")

    try:
        first = answered(lambda seen: True)
        assert first["stale"] is False
        code = project.root / ".nock" / "core" / "nock" / "studio.py"
        later = code.stat().st_mtime_ns + 1_000_000_000
        os.utime(code, ns=(later, later))
        assert answered(lambda seen: seen["stale"])["instance"] == first["instance"]
        request = urllib.request.Request(address, b"{}", method="POST")
        with urllib.request.urlopen(request) as response:
            assert json.loads(response.read()) == {"restarting": True}
        again = answered(lambda seen: seen["instance"] != first["instance"])
        assert again["stale"] is False and process.poll() is None
    finally:
        process.terminate()
        output, _ = process.communicate(timeout=10)
    assert "nock: restarting the studio" in output
    assert output.count(f"http://127.0.0.1:{port}/") == 2


def test_topics_with_a_priority_come_first_in_order_then_the_newest(
    project: Project, page: str
) -> None:
    for name in ("ledger", "pricing", "orders", "billing", "emails"):
        submit(project.root, topic=name)
    for name, priority in (("ledger", 3), ("pricing", 1), ("billing", 2)):
        run(project.root, "topics", "update", name, json.dumps({"priority": priority}))
    with urllib.request.urlopen(f"{page}topics") as response:
        shown = [topic["name"] for topic in json.loads(response.read())["topics"]]
    listed = [row["name"] for row in run(project.root, "topics", "list", "--full")["rows"]]
    assert shown == listed == ["pricing", "billing", "ledger", "emails", "orders"]


def test_only_an_agents_own_work_in_a_topic_asks_for_its_status(
    project: Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "author")
    ref = submit(project.root)
    directory = Topics(project).directory
    record = json.loads((directory / "orders" / "topic.json").read_text())
    del record["state"], record["status"]
    (directory / "orders" / "topic.json").write_text(json.dumps(record))
    task = {
        "slug": "build-it",
        "title": "Build it",
        "aliases": [],
        "verdict": "open",
        "decided": None,
        "created": {"moment": "2020-01-01T00:00:00Z", "session": "keeper", "role": "interactive"},
        "updated": "2020-01-02T00:00:00Z",
        "thread": [
            {
                "author": "agent",
                "moment": "2020-01-02T00:00:00Z",
                "text": "Half done.",
                "session": "keeper",
            }
        ],
        "versions": [
            {"version": 1, "moment": "2020-01-01T00:00:00Z", "session": "keeper", "files": []}
        ],
        "task": {"brief": "Build the orders page.", "state": "running"},
    }
    (directory / "orders" / "build-it").mkdir()
    (directory / "orders" / "build-it" / "item.json").write_text(json.dumps(task))
    git(project.root, "add", "-A")
    git(project.root, "commit", "-q", "-m", "Topics from before states")
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "keeper")
    run(project.root, "topics", "migrate")
    judge(project.root, ref, "accepted", "Fine.")
    assert Topics(project).topic("orders")["thread"][0]["session"] == "keeper"
    assert Topics(project).unstated("keeper") == []
    assert Topics(project).unstated("author") == ["orders"]
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "helper")
    monkeypatch.setenv("NOCK_PARENT_SESSION", "keeper")
    run(project.root, "items", "update", ref, "--reply", "It holds.")
    assert Topics(project).unstated("keeper") == ["orders"]


def test_the_owner_judges_on_the_page_and_the_submitting_session_hears_once(
    project: Project, page: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "s1")
    ref = submit(project.root)
    other = submit(project.root, {**DECISION, "title": "Orders are kept a year"})
    with urllib.request.urlopen(page) as response:
        shown = response.read().decode()
    assert '<a href="#topics" data-tab-link="topics">Work</a>' in shown
    assert "<!-- nock:" not in shown
    with urllib.request.urlopen(f"{page}topics") as response:
        listed = json.loads(response.read())
    (topic,) = listed["topics"]
    assert topic["counts"] == {"open": 2, "accepted": 0, "rejected": 0, "dropped": 0}
    assert topic["items"][1]["versions"][0]["decision"]["answer"].startswith("One file")
    status, _ = post(page, "judge", {"ref": ref, "verdict": "maybe"})
    assert status == 400
    # A verdict on the page takes no comment: the words go through the chat.
    status, _ = post(page, "judge", {"ref": ref, "verdict": "rejected", "comment": "Postgres."})
    assert status == 400
    post(page, "reply", {"ref": ref, "text": "Postgres."})
    status, _ = post(page, "judge", {"ref": ref, "verdict": "rejected"})
    assert status == 200
    assert git(project.root, "status", "--porcelain") == ""

    prompt = HookRunner(project, {"session_id": "s1"}).handle("UserPromptSubmit")
    assert prompt is not None
    told = prompt["hookSpecificOutput"]["additionalContext"]
    assert f"[{ref}] Orders live in SQLite — rejected: Postgres." in told
    assert HookRunner(project, {"session_id": "s1"}).handle("UserPromptSubmit") is None
    assert HookRunner(project, {"session_id": "s2"}).handle("UserPromptSubmit") is None

    status, judged = post(page, "judge", {"topic": "orders", "verdict": "accepted"})
    assert status == 200 and judged["judged"] == [other]
    post(page, "reply", {"topic": "orders", "text": "All good otherwise."})
    assert Topics(project).topic("orders")["thread"][-1]["author"] == "owner"


def told(project: Project, session: str) -> str:
    output = HookRunner(project, {"session_id": session}).handle("UserPromptSubmit")
    return output["hookSpecificOutput"]["additionalContext"] if output else ""


def test_a_session_is_never_told_back_the_owner_s_word_it_recorded_itself(
    project: Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "lead")
    ref = submit(project.root)
    other = submit(project.root, {**DECISION, "title": "Orders are kept a year"})
    judge(project.root, ref, "rejected", "Superseded by later work.")
    assert told(project, "lead") == ""
    run(project.root, "topics", "judge", "orders", json.dumps({"verdict": "accepted"}))
    assert told(project, "lead") == ""
    # A subagent of it records the owner's word for it: still its own.
    monkeypatch.setenv("NOCK_PARENT_SESSION", "lead")
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "helper")
    judge(project.root, other, "rejected", "Two years.")
    assert told(project, "lead") == ""
    monkeypatch.delenv("NOCK_PARENT_SESSION")
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "triage")
    judge(project.root, other, "accepted", "A year is fine after all.")
    assert f"[{other}]" in told(project, "lead") and f"[{ref}]" not in told(project, "lead")


def test_two_verdicts_within_one_second_are_two_words_of_the_owner() -> None:
    said = "2026-01-01T00:00:00Z"
    rejected = {
        "verdict": "rejected",
        "decided": {"moment": said, "session": "helper", "parent": "lead"},
        "thread": [{"author": "owner", "moment": said, "text": "Two years.", "session": "helper"}],
    }
    accepted = {
        **rejected,
        "verdict": "accepted",
        "decided": {"moment": said, "session": "triage"},
        "thread": [
            *rejected["thread"],
            {"author": "owner", "moment": said, "text": "A year is fine.", "session": "triage"},
        ],
    }
    assert owner_word(rejected) != owner_word(accepted)
    assert owner_word(rejected).startswith(said) and owner_word(accepted).startswith(said)
    assert owner_word({"verdict": "open", "decided": None, "thread": []}) == ""


def test_a_migrated_item_s_submitter_is_the_session_that_made_it_not_the_migrating_one(
    project: Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    decisions = project.root / ".nock" / "decisions"
    decisions.mkdir(parents=True, exist_ok=True)
    (decisions / "0001.json").write_text(
        json.dumps(
            {
                "number": 1,
                "title": "Orders live in SQLite",
                "summary": "One file.",
                "status": "done",
                "review": "unreviewed",
                "tags": ["storage"],
                "recorded": {"moment": "2026-01-01T00:00:00Z", "session": "maker"},
                "updated": "2026-01-01T00:00:00Z",
            }
        )
    )
    git(project.root, "add", "-A")
    git(project.root, "commit", "-qm", "An earlier nock's decision")
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "migrator")
    run(project.root, "topics", "migrate")
    item = Topics(project).item("1")
    assert item["created"]["session"] == "maker"
    assert [version["session"] for version in item["versions"]] == ["maker"]
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "triage")
    judge(project.root, item["ref"], "rejected", "Postgres.")
    assert told(project, "migrator") == ""
    assert f"[{item['ref']}]" in told(project, "maker")


def test_a_dropped_item_is_closed_asks_no_rework_and_is_news_to_no_one(
    project: Project, page: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "maker")
    ref = submit(project.root, {"title": "The README's intro", "files": ["README.md"]})
    other = submit(project.root, {**DECISION, "title": "Orders are kept a year"})
    third = submit(project.root, {**DECISION, "title": "Orders are archived"})
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "triage")
    refused = nock(project.root, "items", "judge", ref, '{"verdict": "accepted", "rework": false}')
    assert refused.returncode == 40, refused.stdout + refused.stderr
    dropped = run(
        project.root,
        "items",
        "judge",
        ref,
        json.dumps({"verdict": "rejected", "rework": False, "comment": "Superseded."}),
    )
    assert dropped["verdict"] == "dropped"
    assert told(project, "maker") == ""
    status, _ = post(page, "judge", {"ref": other, "verdict": "dropped"})
    assert status == 200 and told(project, "maker") == ""
    topics = Topics(project)
    assert topics.awaiting()["rejected"] == []
    assert topics.summary()["open"] == {"orders": 1}
    assert topics.row("orders")["dropped"] == 2
    payload = {"session_id": "maker", "tool_input": {"file_path": str(project.root / "README.md")}}
    assert HookRunner(project, payload).handle("PostToolUse") is None
    judged = run(
        project.root,
        "topics",
        "judge",
        "orders",
        json.dumps({"verdict": "rejected", "rework": False}),
    )
    assert judged == {"judged": [third], "verdict": "dropped"}
    assert topics.item(third)["verdict"] == "dropped"
    # A new version reopens a dropped item, like any decided one.
    run(
        project.root,
        "items",
        "update",
        third,
        "--version",
        json.dumps({"title": "Archived yearly"}),
    )
    assert topics.item(third)["verdict"] == "open"


def chat_of(address: str, ref: str) -> dict[str, Any]:
    with urllib.request.urlopen(f"{address}topics") as response:
        listed = json.loads(response.read())
    items = [item for topic in listed["topics"] for item in topic["items"]]
    return next(item["chat"] for item in items if item["ref"] == ref)


def test_the_owner_s_message_waits_for_the_agent_s_one_answer_and_is_withdrawn_until_then(
    project: Project, page: str
) -> None:
    ref = submit(project.root)
    assert chat_of(page, ref) == {"pending": False, "unseen": 0, "answered": False}
    post(page, "reply", {"ref": ref, "text": "Why not Postgres?"})
    assert chat_of(page, ref)["pending"] is True
    status, refused = post(page, "reply", {"ref": ref, "text": "And MySQL?"})
    assert status == 400 and "withdraw it" in refused["error"]
    status, taken = post(page, "withdraw", {"ref": ref})
    assert status == 200 and taken == {"text": "Why not Postgres?"}
    assert Topics(project).item(ref)["thread"] == []
    status, nothing = post(page, "withdraw", {"ref": ref})
    assert status == 400 and "nothing to withdraw" in nothing["error"]
    post(page, "reply", {"ref": ref, "text": "Why not Postgres, then?"})
    answered = run(project.root, "items", "update", ref, "--reply", "A server to run.")
    asked = Topics(project).item(ref)["thread"][0]["moment"]
    assert answered["answered"] == asked
    assert chat_of(page, ref) == {"pending": False, "unseen": 1, "answered": True}
    assert "answered" not in run(project.root, "items", "update", ref, "--reply", "And backups.")
    assert chat_of(page, ref)["unseen"] == 2
    status, _ = post(page, "seen", {"ref": ref})
    assert status == 200 and chat_of(page, ref)["unseen"] == 0
    # A verdict given after the owner's message is the answer: the chat opens again.
    post(page, "reply", {"ref": ref, "text": "Hm."})
    post(page, "judge", {"ref": ref, "verdict": "rejected"})
    assert chat_of(page, ref)["pending"] is False
    status, _ = post(page, "reply", {"ref": ref, "text": "Postgres, please."})
    assert status == 200
    # A topic's chat is the same.
    post(page, "reply", {"topic": "orders", "text": "Is this all?"})
    status, _ = post(page, "reply", {"topic": "orders", "text": "Hello?"})
    assert status == 400
    assert run(project.root, "topics", "update", "orders", "--reply", "Yes.")["answered"]
    status, _ = post(page, "seen", {"topic": "nowhere"})
    assert status == 404


def test_a_session_starts_with_what_is_new_in_topics_and_what_awaits_it_once_a_day(
    project: Project, page: str
) -> None:
    ref = submit(project.root)
    submit(project.root, {**DECISION, "title": "Emails go out at nine"}, topic="emails")
    submit(project.root, {**DECISION, "title": "Emails are plain text"}, topic="emails")
    begun = start(project, "s1")
    context = begun["hookSpecificOutput"]["additionalContext"]
    assert "nock: 3 new in Topics (emails: 2, orders: 1)" in context
    assert "3 new in Topics" in begun["systemMessage"]
    assert HookRunner(project, {"session_id": "s2"}).handle("SessionStart") is None
    post(page, "reply", {"ref": ref, "text": "Postgres."})
    post(page, "judge", {"ref": ref, "verdict": "rejected"})
    context = start(project, "s3")["hookSpecificOutput"]["additionalContext"]
    assert f"- rework {ref} (`--version`)" in context
    assert HookRunner(project, {"session_id": "s4"}).handle("SessionStart") is None
    standing = run(project.root, "status")
    assert standing["topics"]["awaiting_you"]["rejected"] == [ref]


def test_an_edit_to_a_file_an_item_holds_shows_the_item_once(project: Project) -> None:
    ref = submit(project.root, {"title": "The README's first line", "files": ["README.md"]})
    payload = {"session_id": "s1", "tool_input": {"file_path": str(project.root / "README.md")}}
    output = HookRunner(project, payload).handle("PostToolUse")
    assert output is not None
    assert (
        f"- [{ref}] (open) The README's first line"
        in output["hookSpecificOutput"]["additionalContext"]
    )
    assert HookRunner(project, payload).handle("PostToolUse") is None


def test_the_map_check_holds_its_citations(project: Project) -> None:
    ref = submit(project.root)
    (project.root / ".nock" / "topics" / "map.md").write_text(
        f"- [{ref}] holds; [orders/gone] not.\n"
    )
    result = nock(project.root, "check", "nock-map")
    assert result.returncode == 1 and "[orders/gone] is no item" in result.stdout + result.stderr
    assert f"[{ref}]" not in (result.stdout + result.stderr).replace("[orders/gone]", "")


def test_every_studio_tab_has_its_panel_and_its_routes_only(page: str) -> None:
    assert [tab.name for tab in TABS] == ["topics", "experiment"]
    for tab in TABS:
        assert f'studio.register("{tab.name}"' in (PAGES / f"{tab.name}.html").read_text()
    for path in ("nothing", "decisions", "review", "topics/extra", "topics/file/a/b/1/c"):
        with pytest.raises(urllib.error.HTTPError) as missing:
            urllib.request.urlopen(f"{page}{path}")
        assert missing.value.code == 404
    status, _ = post(page, "nothing", {})
    assert status == 404


def test_a_version_s_files_are_served_as_they_are(
    project: Project, page: str, tmp_path: Path
) -> None:
    (project.root / "docs").mkdir()
    (project.root / "docs" / "guide.md").write_text("# Guide\n")
    git(project.root, "add", "-A")
    git(project.root, "commit", "-qm", "A guide")
    ref = submit(project.root, {"title": "The guide", "files": ["docs/guide.md"]})
    slug = ref.split("/")[1]
    with urllib.request.urlopen(f"{page}topics/file/orders/{slug}/1/docs/guide.md") as response:
        assert response.read() == b"# Guide\n"


def test_search_finds_what_the_owner_sees_and_not_what_nock_keeps_aside(
    project: Project, page: str, tmp_path: Path
) -> None:
    (tmp_path / "notes.md").write_text("The zephyr pass reads settled files.\n")
    shown = {
        "title": "The pass's notes",
        "derived": [
            {
                "path": str(tmp_path / "notes.md"),
                "name": "notes.md",
                "from": ["src/ledger.py"],
                "recipe": {"instruction": "Read the ledger and write the notes."},
            }
        ],
    }
    ref = submit(project.root, shown)
    decided = submit(project.root)
    topics = Topics(project)
    item = topics.item(decided)
    item["thread"].append(
        {
            "author": "agent",
            "moment": "2020-01-01T00:00:00Z",
            "text": "Split from a ledger item.",
            "kind": "split",
        }
    )
    topics.save_item("orders", item)
    topics.reply(decided, "Is postgres ever worth it?", Author.OWNER)

    def search(query: str) -> Any:
        with urllib.request.urlopen(f"{page}topics/search/{urllib.parse.quote(query)}") as response:
            return json.loads(response.read())

    assert search("zephyr settled") == {"topics": [], "items": [ref]}
    assert search("ledger") == {"topics": [], "items": []}
    assert search("postgres")["items"] == [decided]
    assert search("notes.md")["items"] == [ref]
    assert search("checkout sqlite") == {"topics": [], "items": [decided]}
    assert search("checkout orders") == {"topics": ["orders"], "items": [decided]}


FFMPEG = shutil.which("ffmpeg") or next(
    (
        path
        for path in ("/opt/homebrew/bin/ffmpeg", "/usr/local/bin/ffmpeg")
        if Path(path).is_file()
    ),
    None,
)


@pytest.mark.skipif(FFMPEG is None, reason="ffmpeg makes the video")
def test_a_video_keeps_its_captions_and_poster_beside_it_and_search_reads_the_captions(
    project: Project, page: str, tmp_path: Path
) -> None:
    video = tmp_path / "run.mp4"
    subprocess.run(
        [
            str(FFMPEG),
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc=duration=2:size=160x120:rate=10",
            "-pix_fmt",
            "yuv420p",
            str(video),
        ],
        check=True,
    )
    (tmp_path / "run.vtt").write_text(
        "WEBVTT\n\n1\n00:00:00.000 --> 00:00:02.000\nThe agent opens the ledger page.\n"
    )
    (tmp_path / "poster.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    ref = submit(
        project.root,
        {
            "title": "The run",
            "derived": [{"path": str(video), "poster": str(tmp_path / "poster.png")}],
        },
    )
    shown = run(project.root, "items", "show", ref)["versions"][0]["files"][0]
    assert (shown["type"], shown["captions"], shown["poster"]) == (
        "video",
        "run.vtt",
        "run.poster.png",
    )
    assert Path(shown["captions_where"]).read_text().startswith("WEBVTT")
    assert Path(shown["poster_where"]).is_file()
    slug = ref.split("/")[1]
    with urllib.request.urlopen(f"{page}topics/file/orders/{slug}/1/run.vtt") as response:
        assert b"opens the ledger page" in response.read()
    with urllib.request.urlopen(
        f"{page}topics/search/{urllib.parse.quote('opens the ledger')}"
    ) as response:
        assert json.loads(response.read())["items"] == [ref]
    run(project.root, "items", "update", ref, "--version", json.dumps({"title": "The run, again"}))
    again = run(project.root, "items", "show", ref)["versions"][1]["files"][0]
    assert Path(again["captions_where"]).read_text() == Path(shown["captions_where"]).read_text()
    (tmp_path / "notes.md").write_text("# Notes\n")
    result = nock(
        project.root,
        "items",
        "create",
        "orders",
        json.dumps(
            {
                "title": "Notes",
                "derived": [
                    {"path": str(tmp_path / "notes.md"), "captions": str(tmp_path / "run.vtt")}
                ],
            }
        ),
    )
    assert result.returncode != 0 and "only a video" in result.stdout + result.stderr


def test_the_owner_asks_and_the_answer_names_items_that_exist(
    project: Project, page: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    ref = submit(project.root)
    monkeypatch.setenv(
        "FAKE_ANSWER", json.dumps({"answer": "In SQLite.", "items": ["orders/nope"]})
    )
    # Its answer refused, the agent's last message is what it said.
    fallen = run(project.root, "topics", "ask", "Where do orders live?")
    assert fallen["answer"] == "answered" and fallen["items"] == []
    monkeypatch.setenv("FAKE_ANSWER", json.dumps({"answer": "In **SQLite**.", "items": [ref]}))
    status, started = post(page, "ask", {"question": "Where do orders live?"})
    assert status == 200 and started["running"] is True
    status, error = post(page, "ask", {"question": "And refunds?"})
    assert status == 400 and "being answered" in error["error"]
    deadline = time.monotonic() + 60
    while True:
        with urllib.request.urlopen(f"{page}topics") as response:
            asked = json.loads(response.read())["ask"]
        if not asked["running"]:
            break
        assert time.monotonic() < deadline
        time.sleep(0.2)
    assert asked["answer"] == "In **SQLite**." and asked["items"] == [ref]


def test_an_ask_is_cancelled(project: Project, page: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FAKE_ANSWER", "slow")
    post(page, "ask", {"question": "Anything?"})
    status, cancelled = post(page, "ask/cancel", {})
    assert status == 200 and cancelled["problem"] == "cancelled" and not cancelled["running"]


def test_only_an_asked_agent_submits_an_answer(project: Project) -> None:
    result = nock(project.root, "topics", "answer", json.dumps({"answer": "Yes."}))
    assert result.returncode == 43 and "only an agent the studio's Ask dispatched" in result.stderr


def test_an_earlier_nock_s_decisions_and_review_items_move_into_topics_once(
    project: Project,
) -> None:
    decisions = project.root / ".nock" / "decisions"
    decisions.mkdir(parents=True, exist_ok=True)
    recorded = {"moment": "2026-01-01T00:00:00Z", "session": "s1", "role": "interactive"}
    base = {
        "status": "done",
        "evidence": [],
        "alternatives": [],
        "touches": [],
        "supersedes": [],
        "superseded_by": None,
        "note": None,
        "reviewed": None,
        "elaborating": False,
        "recorded": recorded,
        "updated": "2026-01-02T00:00:00Z",
    }
    (decisions / "0007.json").write_text(
        json.dumps(
            {
                **base,
                "number": 7,
                "title": "Orders live in SQLite",
                "review": "accepted",
                "summary": "One file.",
                "tags": ["important", "storage", "core"],
                "touches": ["README.md"],
                "note": "Fine for now.",
                "reviewed": {"moment": "2026-01-03T00:00:00Z", "session": "s9"},
            }
        )
    )
    (decisions / "0008.json").write_text(
        json.dumps(
            {
                **base,
                "number": 8,
                "title": "Keep it short",
                "review": "unreviewed",
                "summary": "Yes.",
                "tags": [],
            }
        )
    )
    (decisions / "map.md").write_text("- [D7] holds.\n")
    version = project.root / ".nock" / "review" / "email" / "report" / "1"
    version.mkdir(parents=True)
    (version / "text.txt").write_text("Three anomalies.\n")
    (version / "version.json").write_text(
        json.dumps(
            {
                "key": "email/report",
                "version": 1,
                "title": "The report email",
                "tags": ["emails"],
                "files": [{"name": "text.txt", "kind": "text", "bytes": 17, "local": False}],
                "note": "The first cut.",
                "decision": 7,
                "recipe": {"command": "make report"},
                "regenerated": None,
                "verdict": "rejected",
                "feedback": "Shorter.",
                "reviewed": {"moment": "2026-01-04T00:00:00Z", "session": None},
                "recorded": recorded,
            }
        )
    )
    git(project.root, "add", "-A")
    git(project.root, "commit", "-qm", "An earlier nock's records")
    outcome = Migration(project).run()
    assert outcome["topics"] == {"emails": 1, "general": 1, "storage": 1}
    topics = Topics(project)
    seven = topics.item("7")
    assert seven["ref"] == "storage/orders-live-in-sqlite" and seven["verdict"] == "accepted"
    assert seven["thread"][0]["author"] == "owner" and seven["thread"][0]["text"] == "Fine for now."
    answer = topics.decision(seven, seven["versions"][0])
    assert answer is not None and "Applies to `README.md`." in answer["answer"]
    assert topics.item("general/keep-it-short")["verdict"] == "open"
    report = topics.item("emails/email-report")
    assert report["verdict"] == "rejected" and report["versions"][0]["files"][0]["recipe"] == {
        "command": "make report"
    }
    assert [entry["text"] for entry in report["thread"]] == [
        "Version 1: The first cut.",
        "Version 1 illustrates [storage/orders-live-in-sqlite].",
        "On version 1: Shorter.",
    ]
    assert not decisions.exists() and not (project.root / ".nock" / "review").exists()
    assert (project.root / ".nock" / "topics" / "map.md").read_text() == "- [D7] holds.\n"
    assert topics.citation_problems() == []
    assert git(project.root, "status", "--porcelain") == ""
    assert Migration(project).run() == {"migrated": False}
    assert outcome["marked_told"] == 2
    assert HookRunner(project, {"session_id": "s1"}).handle("UserPromptSubmit") is None
    topics.reply("7", "Revisit at scale.", Author.OWNER)
    prompt = HookRunner(project, {"session_id": "s1"}).handle("UserPromptSubmit")
    assert prompt is not None
    told = prompt["hookSpecificOutput"]["additionalContext"]
    assert "[storage/orders-live-in-sqlite]" in told and "emails/email-report" not in told


def test_a_project_migrated_before_marks_what_the_owner_said_as_told_once(
    project: Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "s1")
    ref = submit(project.root)
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "triage")
    judge(project.root, ref, "accepted", "Fine.")
    assert run(project.root, "topics", "migrate", "--mark-seen") == {
        "migrated": False,
        "marked_told": 1,
    }
    assert run(project.root, "topics", "migrate", "--mark-seen")["marked_told"] == 0
    assert HookRunner(project, {"session_id": "s1"}).handle("UserPromptSubmit") is None


def test_a_topic_not_yet_given_a_state_reads_as_the_migration_will_set_it(
    project: Project,
) -> None:
    decided, waiting = submit(project.root), submit(project.root, topic="pricing")
    judge(project.root, decided, "accepted")
    directory = Topics(project).directory
    for name in ("orders", "pricing"):
        record = json.loads((directory / name / "topic.json").read_text())
        del record["state"], record["status"]
        (directory / name / "topic.json").write_text(json.dumps(record))
    states = {
        row["name"]: row["state"] for row in run(project.root, "topics", "list", "--full")["rows"]
    }
    assert states == {"orders": "done", "pricing": "active"}
    assert waiting.startswith("pricing/")


def test_topics_get_their_state_once_and_task_items_become_notes(project: Project) -> None:
    decided, waiting = submit(project.root), submit(project.root, topic="pricing")
    judge(project.root, decided, "accepted")
    open_topic(project.root, {"name": "empty", "description": "Nothing yet."})
    directory = Topics(project).directory
    for name in ("orders", "pricing", "empty"):
        record = json.loads((directory / name / "topic.json").read_text())
        del record["state"], record["status"]
        (directory / name / "topic.json").write_text(json.dumps(record))
    task = {
        "slug": "build-it",
        "title": "Build it",
        "aliases": [],
        "verdict": "open",
        "decided": None,
        "created": {"moment": "2020-01-01T00:00:00Z", "session": "lead", "role": "interactive"},
        "updated": "2020-01-02T00:00:00Z",
        "thread": [{"author": "agent", "moment": "2020-01-02T00:00:00Z", "text": "Half done."}],
        "versions": [{"version": 1, "moment": "2020-01-01T00:00:00Z", "files": []}],
        "task": {"brief": "Build the pricing page.", "branch": "pricing", "state": "running"},
    }
    (directory / "pricing" / "build-it").mkdir()
    (directory / "pricing" / "build-it" / "item.json").write_text(json.dumps(task))
    git(project.root, "add", "-A")
    git(project.root, "commit", "-q", "-m", "Topics from before states")
    result = run(project.root, "topics", "migrate")
    assert result["stated"] == {"topics": {"active": 2, "done": 1}, "tasks": 1}
    states = {
        row["name"]: row["state"] for row in run(project.root, "topics", "list", "--full")["rows"]
    }
    assert states == {"orders": "done", "pricing": "active", "empty": "active"}
    assert [item["ref"] for item in Topics(project).items("pricing")] == [waiting]
    note = Topics(project).topic("pricing")["thread"][0]
    assert note["kind"] == "task" and "Build the pricing page." in note["text"]
    assert "Half done." in note["text"] and note["session"] == "lead"
    assert run(project.root, "topics", "migrate") == {"migrated": False}
    assert git(project.root, "status", "--porcelain") == ""


def test_an_item_holds_one_asset_or_options_of_one_the_owner_may_prefer(
    project: Project, page: str
) -> None:
    def text(name: str, words: str = "x") -> dict[str, str]:
        return {"text": words, "name": name}

    open_topic(project.root)
    two = nock(
        project.root, "items", "create", "orders",
        json.dumps({"title": "Two", "derived": [text("a.md"), text("b.md")]}),
    )  # fmt: skip
    assert two.returncode == 40 and "an item holds one file" in two.stderr
    pictured = nock(
        project.root, "items", "create", "orders",
        json.dumps({**DECISION, "derived": [text("a.md")]}),
    )  # fmt: skip
    assert pictured.returncode == 40 and "a decision holds no derived file" in pictured.stderr
    mixed = nock(
        project.root, "items", "create", "orders",
        json.dumps({"title": "Mixed", "options": True, "derived": [text("a.md"), text("b.svg", "<svg/>")]}),
    )  # fmt: skip
    assert mixed.returncode == 40 and "of one type" in mixed.stderr
    submit(project.root, {**DECISION, "files": ["README.md"]})
    ref = submit(
        project.root,
        {"title": "The banner", "options": True, "derived": [text(f"{name}.md") for name in "abc"]},
    )
    row = next(row for row in run(project.root, "items", "list")["rows"] if row["ref"] == ref)
    assert row["options"] is True and "preferred" not in row
    assert post(page, "prefer", {"ref": ref, "version": 1, "name": "b.md"}) == (
        200,
        {"preferred": {"version": 1, "name": "b.md"}},
    )
    assert run(project.root, "items", "show", ref)["preferred"] == {"version": 1, "name": "b.md"}
    row = next(row for row in run(project.root, "items", "list")["rows"] if row["ref"] == ref)
    assert row["preferred"] == {"version": 1, "name": "b.md"}
    assert post(page, "prefer", {"ref": ref, "version": 1, "name": "z.md"})[0] == 404
    assert post(page, "prefer", {"ref": "orders/orders-live-in-sqlite", "version": 1})[0] != 200
    assert post(page, "prefer", {"ref": ref, "version": 1}) == (200, {"preferred": None})
    assert git(project.root, "status", "--porcelain") == ""


def test_an_item_holding_several_files_splits_into_one_item_per_file_once(
    project: Project,
) -> None:
    ref = submit(
        project.root,
        {
            "title": "Texts",
            "options": True,
            "derived": [{"text": n, "name": f"{n}.md"} for n in "ab"],
        },
    )
    topics = Topics(project)
    topics.update_item(
        ref, None, version={"derived": [{"text": n, "name": f"{n}.md"} for n in "abc"]}
    )
    topics.reply(ref, "Shorter, all of them.", Author.OWNER)
    judge(project.root, ref, "rejected")
    path = project.root / ".nock" / "topics" / "orders" / "texts" / "item.json"
    record = json.loads(path.read_text())
    del record["options"]
    path.write_text(json.dumps(record))
    git(project.root, "commit", "-qam", "An item from before one asset per item")
    assert Migration(project).run() == {"migrated": False, "split": {"items": 1, "into": 3}}
    pieces = [topics.item(f"orders/texts{suffix}") for suffix in ("", "-b", "-c")]
    assert [piece["title"] for piece in pieces] == ["Texts", "Texts — b.md", "Texts — c.md"]
    assert [[version["version"] for version in piece["versions"]] for piece in pieces] == [
        [1, 2],
        [1, 2],
        [2],
    ]
    for piece, name in zip(pieces, "abc", strict=True):
        assert piece["verdict"] == "rejected"
        assert {entry["name"] for version in piece["versions"] for entry in version["files"]} == {
            f"{name}.md"
        }
        note, *thread = piece["thread"]
        assert note["kind"] == "split" and "[orders/texts-c]" in note["text"]
        assert [entry["text"] for entry in thread] == ["Shorter, all of them."]
    assert topics.file("orders", "texts-c", 2, "c.md").read_text() == "c"
    assert git(project.root, "status", "--porcelain") == ""
    assert Migration(project).run() == {"migrated": False}
