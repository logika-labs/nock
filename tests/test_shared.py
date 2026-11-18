"""The store, `.nock/shared/`: what an agent writes there — events as files,
versions as folders — is validated, completed (moments, ids, who wrote it,
version numbers, media by sha256) and committed alone with attribution
trailers; what doesn't fit is left uncommitted and named; the fold reads it
all back as topics and items."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from nock.fold import Fold
from nock.project import Project
from nock.records import EVENT_FILE
from nock.shared import Shared, by_for, digest

from .conftest import git

AGENT = {
    "author": "agent",
    "on_behalf": "agent",
    "user": "test@example.com",
    "session": "s-1",
    "parent": "s-0",
    "role": "subagent",
    "host": "box",
}
OWNER = {**AGENT, "author": "owner", "on_behalf": "interactive", "session": None, "parent": None}


def write(path: Path, record: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(record, bytes):
        path.write_bytes(record)
    else:
        path.write_text(record if isinstance(record, str) else json.dumps(record))
    return path


@pytest.fixture
def shared(project: Project) -> Shared:
    return Shared(project)


def open_topic(shared: Shared, name: str = "orders") -> None:
    write(
        shared.topics / name / "events" / "new.json",
        {"kind": "created", "description": "Where orders are kept."},
    )
    assert not shared.settle(AGENT).problems


def submit_decision(shared: Shared, topic: str = "orders", slug: str = "sqlite") -> Path:
    folder = shared.topics / topic / "items" / slug
    write(
        folder / "events" / "a.json",
        {
            "kind": "created",
            "type": "decision",
            "title": "Orders live in SQLite",
            "means": "One file.",
        },
    )
    settled = shared.settle(AGENT)
    assert not settled.problems, settled.problems
    return folder


def test_an_agents_event_is_completed_and_committed_alone_with_trailers(
    shared: Shared, project: Project
) -> None:
    (project.root / "src.py").write_text("print(1)\n")
    write(
        shared.topics / "orders" / "events" / "whatever.json",
        {"kind": "created", "description": "Where orders are kept."},
    )
    settled = shared.settle(AGENT)
    assert settled.problems == [] and settled.commit
    (event,) = (shared.topics / "orders" / "events").iterdir()
    assert EVENT_FILE.match(event.name)
    record = json.loads(event.read_text())
    assert record["kind"] == "created" and len(record["id"]) == 8
    assert record["by"]["session"] == "s-1" and record["by"]["author"] == "agent"
    body = git(project.root, "log", "-1", "--format=%B")
    for line in (
        "Nock-User: test@example.com",
        "Nock-On-Behalf: agent",
        "Nock-Session: s-1",
        "Nock-Parent-Session: s-0",
        "Nock-Host: box",
    ):
        assert line in body
    # Only the shared paths went in: the code being changed stays the branch's.
    assert git(project.root, "show", "--name-only", "--format=", "HEAD").splitlines() == [
        f".nock/shared/topics/orders/events/{event.name}"
    ]
    assert "src.py" in git(project.root, "status", "--porcelain")
    topic = Fold(shared.root).topic("orders")
    assert topic and topic["description"] == "Where orders are kept." and topic["state"] == "active"


def test_a_bad_edit_is_left_uncommitted_and_named(shared: Shared, project: Project) -> None:
    open_topic(shared)
    head = git(project.root, "rev-parse", "HEAD")
    write(shared.topics / "orders" / "events" / "x.json", {"kind": "state", "state": "finished"})
    write(shared.topics / "orders" / "events" / "y.json", "{not json")
    settled = shared.settle(AGENT)
    assert settled.commit is None and git(project.root, "rev-parse", "HEAD") == head
    joined = " ".join(settled.problems)
    assert "'finished' is not one of" in joined and "not readable JSON" in joined
    assert (shared.topics / "orders" / "events" / "x.json").is_file()
    # A committed event is never edited: changing one is refused, its group left.
    (shared.topics / "orders" / "events" / "x.json").unlink()
    (shared.topics / "orders" / "events" / "y.json").unlink()
    (event,) = (shared.topics / "orders" / "events").iterdir()
    event.write_text(event.read_text().replace("Where", "Why"))
    assert "never changed or removed" in " ".join(shared.settle(AGENT).problems)
    git(project.root, "checkout", "--", str(event))
    # An agent cannot fill in who it is, nor pretend to be the owner.
    write(
        shared.topics / "orders" / "events" / "z.json",
        {"kind": "message", "text": "hi", "by": {"author": "owner"}},
    )
    assert "leave out by" in " ".join(shared.settle(AGENT).problems)


def test_an_item_needs_its_topic(shared: Shared) -> None:
    folder = shared.topics / "orders" / "items" / "sqlite"
    write(
        folder / "events" / "a.json",
        {"kind": "created", "type": "decision", "title": "Orders live in SQLite", "means": "m"},
    )
    assert "no topic orders" in " ".join(shared.settle(AGENT).problems)
    write(
        shared.topics / "orders" / "events" / "new.json",
        {"kind": "created", "description": "Where orders are kept."},
    )
    # The topic first, then its item, in one settle.
    settled = shared.settle(AGENT)
    assert not settled.problems, settled.problems
    item = Fold(shared.root).item("orders", "sqlite")
    assert item is not None and item["status"] == "decision"
    assert [event["kind"] for event in settled.events] == ["created", "created"]


def test_a_proposals_verdict_and_what_was_done_fold_in_order(shared: Shared) -> None:
    open_topic(shared)
    folder = shared.topics / "orders" / "items" / "archive"
    write(
        folder / "events" / "a.json",
        {"kind": "created", "type": "proposal", "title": "Archive", "means": "m", "takes": "a day"},
    )
    shared.settle(AGENT)
    write(folder / "events" / "v.json", {"kind": "verdict", "verdict": "accepted"})
    shared.settle(OWNER)
    item = Fold(shared.root).item("orders", "archive")
    assert item and item["status"] == "accepted" and item["verdict"]["author"] == "owner"
    write(folder / "events" / "r.json", {"kind": "revised", "takes": "two days"})
    write(folder / "events" / "i.json", {"kind": "implemented", "means": "Archived nightly."})
    assert not shared.settle(AGENT).problems
    item = Fold(shared.root).item("orders", "archive")
    assert item and item["status"] == "decision" and item["takes"] == "two days"
    assert [entry["kind"] for entry in item["history"]] == ["verdict", "revised", "implemented"]
    write(folder / "events" / "w.json", {"kind": "verdict", "verdict": "rejected"})
    assert "carried out already" in " ".join(shared.settle(OWNER).problems)


def test_the_chat_answers_and_carries_notes(shared: Shared) -> None:
    open_topic(shared)
    events = shared.topics / "orders" / "events"
    write(events / "n.json", {"kind": "note", "on": {"item": "sqlite"}, "text": "Why?"})
    shared.settle(OWNER)
    topic = Fold(shared.root).topic("orders")
    assert topic
    (note,) = topic["notes"]
    assert note["sent"] is None
    write(events / "o.json", {"kind": "message", "text": "", "notes": [note["id"]], "now": True})
    shared.settle(OWNER)
    asked = Fold(shared.root).topic("orders")
    assert asked
    question = asked["thread"][-1]
    assert question["author"] == "owner" and question["now"] is True
    assert asked["notes"][0]["sent"] == question["id"]
    write(events / "a.json", {"kind": "message", "text": "Load is low."})
    shared.settle(AGENT)
    answered = Fold(shared.root).topic("orders")
    assert answered and answered["thread"][-1]["answers"] == question["id"]
    write(events / "bad.json", {"kind": "message", "text": "x", "answers": "deadbeef"})
    assert "names no message" in " ".join(shared.settle(AGENT).problems)
    (events / "bad.json").unlink()
    write(events / "nn.json", {"kind": "note", "on": {}, "text": "on nothing"})
    assert "a note is on" in " ".join(shared.settle(OWNER).problems)
    (events / "nn.json").unlink()
    write(events / "e.json", {"kind": "message", "text": " "})
    assert "the message is empty" in " ".join(shared.settle(OWNER).problems)


def test_a_topics_state_rename_and_revival(shared: Shared) -> None:
    open_topic(shared)
    events = shared.topics / "orders" / "events"
    write(events / "s.json", {"kind": "state", "status": "gate running", "priority": 2})
    write(events / "t.json", {"kind": "state", "state": "done"})
    shared.settle(AGENT)
    topic = Fold(shared.root).topic("orders")
    assert topic and topic["state"] == "done" and topic["status"] == "" and topic["priority"] == 2
    folder = shared.topics / "orders" / "items" / "late"
    write(
        folder / "events" / "a.json",
        {"kind": "created", "type": "decision", "title": "Late", "means": "m"},
    )
    assert "revive it first" in " ".join(shared.settle(AGENT).problems)
    (folder / "events" / "a.json").unlink()
    write(events / "r.json", {"kind": "state", "state": "active", "revived": True, "note": "Back."})
    write(events / "n.json", {"kind": "renamed", "name": "storage"})
    settled = shared.settle(AGENT)
    assert not settled.problems, settled.problems
    assert not (shared.topics / "orders").exists()
    topic = Fold(shared.root).topic("storage")
    assert topic and topic["state"] == "active" and topic["aliases"] == ["orders"]
    assert topic["thread"][-1]["revived"] is True


def add_asset(shared: Shared, name: str, files: dict[str, Any], record: dict[str, Any]) -> Path:
    folder = shared.topics / "orders" / "assets" / name
    if not (folder / "events").is_dir():
        write(folder / "events" / "a.json", {"kind": "created", "title": name.title()})
    for file_name, content in files.items():
        write(folder / "versions" / "next" / file_name, content)
    write(folder / "versions" / "next" / "asset.json", record)
    return folder


def test_an_asset_links_project_files_and_keeps_media(shared: Shared, project: Project) -> None:
    open_topic(shared)
    (project.root / "app.py").write_text("print('hi')\n")
    git(project.root, "add", "app.py")
    git(project.root, "commit", "-qm", "app")
    head = git(project.root, "rev-parse", "HEAD")
    asset = add_asset(shared, "app", {}, {"file": {"kind": "project", "path": "app.py"}})
    assert not shared.settle(AGENT).problems
    entry = json.loads((asset / "versions" / "1" / "asset.json").read_text())["file"]
    assert entry["commit"] == head and entry["type"] == "text" and "sha256" not in entry
    # The after: a second version of the same asset; a file with uncommitted
    # changes is kept by its content.
    (project.root / "app.py").write_text("print('changed')\n")
    add_asset(shared, "app", {}, {"file": {"kind": "project", "path": "app.py"}})
    assert not shared.settle(AGENT).problems
    entry = json.loads((asset / "versions" / "2" / "asset.json").read_text())["file"]
    assert entry["sha256"] == digest(b"print('changed')\n") and "commit" not in entry
    found = Fold(shared.root).asset("orders", "app")
    assert found and [version["version"] for version in found["versions"]] == [1, 2]
    # A picture goes to media by sha256; small text stays beside its version.
    picture = b"\x89PNG\r\n\x1a\n" + bytes(range(256))
    shot = add_asset(
        shared,
        "receipt",
        {"receipt.png": picture},
        {"file": {"kind": "derived", "name": "receipt.png", "recipe": {"command": "make shot"}}},
    )
    assert not shared.settle(AGENT).problems
    entry = json.loads((shot / "versions" / "1" / "asset.json").read_text())["file"]
    assert entry["sha256"] == digest(picture) and entry["type"] == "image"
    assert not (shot / "versions" / "1" / "receipt.png").exists()
    assert shared.blob(entry["sha256"]).read_bytes() == picture
    assert f".nock/shared/media/{entry['sha256']}" in git(project.root, "ls-files")


def test_a_new_version_goes_in_versions_next(shared: Shared) -> None:
    open_topic(shared)
    asset = add_asset(shared, "notes", {"a.md": "a"}, {"file": {"kind": "derived", "name": "a.md"}})
    assert not shared.settle(AGENT).problems
    write(asset / "versions" / "7" / "asset.json", {"file": {"kind": "derived", "name": "a.md"}})
    assert "nock numbers it" in " ".join(shared.settle(AGENT).problems)


def test_nock_settles_only_what_it_wrote(shared: Shared) -> None:
    open_topic(shared)
    stray = write(
        shared.topics / "orders" / "events" / "stray.json", {"kind": "message", "text": "mine"}
    )
    path = shared.draft(shared.topics / "orders", {"kind": "message", "text": "the owner's"})
    settled = shared.settle(OWNER, only=[path])
    assert not settled.problems and settled.commit
    assert stray.is_file()
    topic = Fold(shared.root).topic("orders")
    assert topic and [entry["author"] for entry in topic["thread"]] == ["owner"]


def test_by_for_names_the_writer(project: Project, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "s-9")
    by = by_for(project)
    assert by["author"] == "agent" and by["on_behalf"] == "interactive" and by["session"] == "s-9"
    assert by_for(project, "owner")["author"] == "owner"
    subprocess.run(["git", "config", "user.email", "dev@example.com"], cwd=project.root, check=True)
    assert by_for(project)["user"] == "dev@example.com"
