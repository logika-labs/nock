"""What the tests do to the topics: an agent's work written as the files an
agent writes under `.nock/shared/topics/` and settled as that agent's
(`Shared.settle`, then `Topics.heard`, as the hooks do); the owner's through
`nock.topics.Topics`, as the studio does. Each takes the directory the work
is in, a worktree's as well as the main checkout's."""

from __future__ import annotations

import json
import secrets
from pathlib import Path
from typing import Any

from nock.project import Project
from nock.shared import Settled, Shared, by_for
from nock.topics import Topics

AGENT = {"session": "agent-session", "role": "interactive"}


def topics_in(directory: Path) -> Topics:
    return Topics(Project.discover(directory))


def shared_root(directory: Path) -> Path:
    return Project.discover(directory).root / ".nock" / "shared" / "topics"


def draft(folder: Path, record: dict[str, Any]) -> Path:
    path = folder / "events" / f"new-{secrets.token_hex(4)}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record))
    return path


def settle(directory: Path, writer: dict[str, Any] | None = None) -> Settled:
    """Everything an agent wrote under the store, settled as its own."""
    project = Project.discover(directory)
    own = project.writer()
    chosen = dict(writer or (own if own.get("session") else AGENT))
    settled = Shared(project).settle_changes(lambda: by_for(project, writer=chosen))
    Topics(project).heard(settled)
    return settled


def held(directory: Path, writer: dict[str, Any] | None = None) -> Settled:
    """`settle`, failing the test on a problem."""
    settled = settle(directory, writer)
    assert not settled.problems, settled.problems
    return settled


def open_topic(
    directory: Path,
    name: str = "orders",
    description: str = "Where orders are kept, for the checkout work.",
    status: str | None = None,
) -> str:
    folder = shared_root(directory) / name
    draft(folder, {"kind": "created", "description": description})
    if status:
        draft(folder, {"kind": "state", "state": "active", "status": status})
    held(directory)
    return name


def state(directory: Path, topic: str, **fields: Any) -> None:
    draft(shared_root(directory) / topic, {"kind": "state", **fields})
    held(directory)


def item(
    directory: Path,
    topic: str,
    slug: str,
    kind: str = "decision",
    title: str = "Orders live in SQLite",
    means: str = "One file to back up; no server to run.",
    writer: dict[str, Any] | None = None,
    **fields: Any,
) -> str:
    """A decision (or a proposal) in TOPIC, opened first when it is new."""
    if not (shared_root(directory) / topic / "events").is_dir():
        open_topic(directory, topic)
    folder = shared_root(directory) / topic / "items" / slug
    draft(folder, {"kind": "created", "type": kind, "title": title, "means": means, **fields})
    held(directory, writer)
    return f"{topic}/{slug}"


def submit(directory: Path, topic: str = "orders", slug: str = "sqlite") -> str:
    """A decision, as an agent records it."""
    return item(directory, topic, slug)


def propose(
    directory: Path, topic: str = "orders", slug: str = "archive", takes: str = "a day"
) -> str:
    return item(
        directory,
        topic,
        slug,
        kind="proposal",
        title="Archive orders after a year",
        means="Old orders leave the hot table.",
        takes=takes,
    )


def item_event(directory: Path, ref: str, record: dict[str, Any]) -> Settled:
    topic, slug = ref.split("/")
    draft(shared_root(directory) / topic / "items" / slug, record)
    return settle(directory)


def asset(
    directory: Path,
    topic: str,
    name: str,
    content: str | bytes = "first\n",
    file_name: str = "notes.md",
    title: str = "Notes",
    **entry: Any,
) -> None:
    """An asset's first version, or its next one: a derived file."""
    folder = shared_root(directory) / topic / "assets" / name
    if not (folder / "events").is_dir():
        draft(folder, {"kind": "created", "title": title})
    version = folder / "versions" / "next"
    version.mkdir(parents=True, exist_ok=True)
    data = content.encode() if isinstance(content, str) else content
    (version / file_name).write_bytes(data)
    (version / "asset.json").write_text(
        json.dumps({"file": {"kind": "derived", "name": file_name, **entry}})
    )
    held(directory)


def compose(
    directory: Path,
    topic: str,
    blocks: list[dict[str, Any]],
    summary: str = "What changed",
    files: dict[str, str] | None = None,
) -> Settled:
    """A new version of the topic's review."""
    version = shared_root(directory) / topic / "review" / "versions" / "next"
    version.mkdir(parents=True, exist_ok=True)
    (version / "review.json").write_text(json.dumps({"summary": summary, "blocks": blocks}))
    for name, text in (files or {}).items():
        (version / name).write_text(text)
    return settle(directory)


def reply(directory: Path, topic: str, text: str, **fields: Any) -> Settled:
    """An agent's message in the topic's chat."""
    draft(shared_root(directory) / topic, {"kind": "message", "text": text, **fields})
    return settle(directory)
