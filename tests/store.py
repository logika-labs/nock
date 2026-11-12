"""What the tests do to the topics, through the store's own interface
(`nock.topics.Topics`, which writes events into `.nock/shared/` and settles
them) — the decisions, versions, verdicts and messages an agent or the owner
writes — and what they read back. Each takes the directory the work is in,
a worktree's as well as the main checkout's."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

from nock.project import Project
from nock.topics import (
    Author,
    ItemChange,
    ItemDraft,
    TopicChange,
    TopicDraft,
    Topics,
    Word,
    in_order,
)

TOPIC: dict[str, Any] = {
    "name": "orders",
    "description": "Where orders are kept, for the checkout work.",
}
DECISION: dict[str, Any] = {
    "title": "Orders live in SQLite",
    "decision": {
        "answer": "One file is enough for **orders** at today's load.",
        "alternatives": [{"option": "Postgres", "why_not": "a server to run, for load we lack"}],
    },
}


def topics_in(directory: Path) -> Topics:
    return Topics(Project.discover(directory))


def open_topic(directory: Path, topic: dict[str, Any] = TOPIC) -> str:
    record, _ = topics_in(directory).create_topic(cast(TopicDraft, topic))
    return record["name"]


def submit(directory: Path, item: dict[str, Any] = DECISION, topic: str = "orders") -> str:
    """A decision in TOPIC (opened first when it is new), as an agent records it."""
    topics = topics_in(directory)
    if topic not in topics.names():
        open_topic(directory, {**TOPIC, "name": topic})
    record, _ = topics_in(directory).create_item(topic, cast(ItemDraft, item))
    return record["ref"]


def judge(directory: Path, ref: str, verdict: str, comment: str = "") -> dict[str, Any]:
    """The owner's verdict, told to whoever recorded it as said (it is theirs)."""
    word = {"verdict": verdict, **({"comment": comment} if comment else {})}
    topics = topics_in(directory)
    record, _ = topics.judge(ref, cast(Word, word))
    topics.tell_writer([record["ref"]])
    return {"ref": record["ref"], "verdict": record["verdict"]}


def judge_topic(
    directory: Path, name: str, verdict: str, comment: str = "", rework: bool = True
) -> list[str]:
    """The owner's verdict on every open decision of a topic, told to whoever
    recorded each as said."""
    word: dict[str, Any] = {"verdict": verdict}
    if comment:
        word["comment"] = comment
    if not rework:
        word["rework"] = False
    topics = topics_in(directory)
    judged, _ = topics.judge_topic(name, cast(Word, word))
    topics.tell_writer(judged)
    return judged


def update_topic(
    directory: Path,
    name: str,
    change: dict[str, Any] | None = None,
    reply: str | None = None,
    revive: str | None = None,
) -> dict[str, Any]:
    record, _ = topics_in(directory).update_topic(
        name, cast(TopicChange, change or {}), reply, revive
    )
    return record


def update_item(
    directory: Path,
    ref: str,
    change: dict[str, Any] | None = None,
    version: dict[str, Any] | None = None,
    reply: str | None = None,
    author: Author = Author.AGENT,
) -> dict[str, Any]:
    record, _ = topics_in(directory).update_item(
        ref,
        cast(ItemChange, change) if change else None,
        cast(ItemChange, version) if version is not None else None,
        reply,
        author,
    )
    return record


def shown(directory: Path, ref: str) -> dict[str, Any]:
    """A decision with its versions' answers, its assets' files where they are, its thread."""
    topics = topics_in(directory)
    return topics.shown(topics.item(ref))


def topic_shown(directory: Path, name: str) -> dict[str, Any]:
    """A topic: its row, its decisions' rows, its thread with each file's `where`."""
    topics = topics_in(directory)
    record = topics.topic(name)
    return {
        **topics.row(name),
        "items": [topics.item_row(item) for item in topics.items(name)],
        "thread": topics.thread_shown(record["thread"], record["name"]),
    }


def rows(directory: Path, state: str | None = None) -> list[dict[str, Any]]:
    """Every topic's row in the owner's order (priority, then newest activity)."""
    topics = topics_in(directory)
    found = in_order([topics.row(name) for name in topics.names()])
    return [row for row in found if state is None or row["state"] == state]


def item_rows(directory: Path) -> list[dict[str, Any]]:
    topics = topics_in(directory)
    return [topics.item_row(item) for item in topics.every()]


def answered(record: dict[str, Any]) -> bool:
    """Whether the last message in a record's thread answers the owner's."""
    return bool(record["thread"]) and "answers" in record["thread"][-1]
