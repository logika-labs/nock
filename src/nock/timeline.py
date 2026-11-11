"""The timeline: what happened in the topics, newest first, as the owner would
be told it — a topic opened, a topic's state or status changed or it came
back, an item submitted for review, a new version of one, an agent writing
in a thread (answering the owner, or not). Each event is read from the
committed topics, never stored, so it covers all of their history and reads
the same on every machine; its `key` names it for good. The studio's
Timeline shows them, and the browser's and the desktop's notifications are
these same events (`nock.notify`): one source."""

from __future__ import annotations

import re
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from nock.notify import Reason, seconds_between
from nock.topics import STATUS, Author, Topics, entry_name, moment

if TYPE_CHECKING:
    from nock.project import Project

# How much of a message or a description an event's preview holds.
PREVIEW = 280

# The files an asset's event shows the face of: its pictures and videos.
FACES = ("image", "video")


class Event(StrEnum):
    TOPIC = "topic"
    """An agent opened a topic."""
    STATE = "state"
    """A topic's state changed: to review, done, …"""
    STATUS = "status"
    """A topic's status line changed, its state the same."""
    REVIVED = "revived"
    """A done or abandoned topic came back."""
    ITEM = "item"
    """An item submitted for the owner: a decision or an asset."""
    VERSION = "version"
    """A new version of an item."""
    ANSWERED = "answered"
    """An agent answered the owner's message."""
    MESSAGE = "message"
    """An agent wrote in a thread, answering nothing."""


# The events that make it the owner's turn, by the reason nock tells them.
TURNS = {
    Reason.REVIEW: (Event.STATE,),
    Reason.ANSWERED: (Event.ANSWERED,),
    Reason.REWORKED: (Event.VERSION,),
}


# The kinds in the order they follow one another within one second.
ORDER = [str(kind) for kind in Event]

# What a state change says happened, by the state it came to.
CAME_TO = {
    "review": "ready for your review",
    "done": "done",
    "abandoned": "stopped",
    "active": "in progress",
    "planned": "planned",
}

# An agent's message this soon after a new version says what changed in it.
CHANGE_NOTE = 300

SENTENCE = re.compile(r"(?<=[.!?])\s+")


def clipped(text: str, limit: int = PREVIEW) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def first_sentence(text: str) -> tuple[str, str]:
    """TEXT's first sentence and the rest of it."""
    head, *rest = SENTENCE.split(" ".join(str(text or "").split()), maxsplit=1)
    return head, rest[0] if rest else ""


def counted(number: int, one: str, many: str) -> str:
    return f"{number} {one if number == 1 else many}"


class Timeline:
    def __init__(self, project: Project) -> None:
        self.topics = Topics(project)

    def events(self, topic: str | None = None) -> list[dict[str, Any]]:
        """Every event (of TOPIC), the newest first; a topic's status changes
        with nothing between them one event, the latest, with their `count`."""
        found: list[dict[str, Any]] = []
        for name in [topic] if topic else self.topics.names():
            found += self.of_topic(name)
        # Within one second, what follows from another comes after it: a topic, then its items.
        found.sort(
            key=lambda event: (event["moment"], ORDER.index(event["kind"]), event["key"]),
            reverse=True,
        )
        folded: list[dict[str, Any]] = []
        for event in found:
            last = folded[-1] if folded else None
            if (
                last
                and event["kind"] == last["kind"] == Event.STATUS
                and event["topic"] == last["topic"]
            ):
                last["count"] = last.get("count", 1) + 1
                last["preview"] = event["preview"]
                continue
            folded.append(event)
        return folded

    def of_topic(self, name: str) -> list[dict[str, Any]]:
        record = self.topics.topic(name)
        created = moment(record.get("created"))
        items = self.topics.items(name)
        opening, rest = first_sentence(record["description"])
        found = [
            self.event(
                Event.TOPIC,
                f"topic:{name}",
                created or record.get("updated") or "",
                name,
                None,
                "started",
                opening,
                rest,
                f"#topics/{name}",
            )
        ]
        state, status = None, ""
        for entry in record["thread"]:
            if entry.get("kind") == STATUS:
                said = entry.get("status") or ""
                before, status = status, said
                preview, extra = "", {}
                if entry.get("revived"):
                    kind, phrase = Event.REVIVED, "back in progress"
                    said = entry.get("text") or said
                elif entry.get("state") != (state or "active"):
                    kind = Event.STATE
                    phrase = CAME_TO.get(entry.get("state") or "", f"is {entry.get('state')}")
                    if entry.get("state") == "review":
                        preview = self.waiting(items, entry["moment"])
                elif entry["moment"] == created:
                    state = entry.get("state")
                    continue
                else:
                    kind, phrase = Event.STATUS, "progress"
                    preview, extra = before, {"muted": True}
                state = entry.get("state")
                found.append(
                    self.event(
                        kind,
                        f"status:{name}:{entry['moment']}",
                        entry["moment"],
                        name,
                        None,
                        phrase,
                        said,
                        preview,
                        f"#topics/{name}",
                        state=state,
                        **extra,
                    )
                )
            elif not entry.get("kind"):
                found += self.said(entry, record["thread"], name, None, opening)
        for item in items:
            found += self.of_item(item)
        return found

    def waiting(self, items: list[dict[str, Any]], at: str) -> str:
        """What waited for the owner's verdict at AT: "3 decisions, 2 to look at"."""
        decisions = assets = 0
        for item in items:
            versions = [version for version in item["versions"] if version["moment"] <= at]
            decided = moment(item.get("decided"))
            if not versions or (item.get("verdict") != "open" and decided and decided <= at):
                continue
            if any(entry["kind"] == "decision" for entry in versions[-1]["files"]):
                decisions += 1
            else:
                assets += 1
        said = [counted(decisions, "decision", "decisions")] if decisions else []
        return ", ".join(said + ([f"{assets} to look at"] if assets else []))

    def of_item(self, item: dict[str, Any]) -> list[dict[str, Any]]:
        ref, topic = item["ref"], item["topic"]
        found = []
        versions = item["versions"]
        for at, version in enumerate(versions):
            decision = next(
                (entry for entry in version["files"] if entry["kind"] == "decision"), None
            )
            files = [entry for entry in version["files"] if entry["kind"] != "decision"]
            what = "decision" if decision else "asset"
            if version["version"] == 1:
                kind, key, address = Event.ITEM, f"item:{ref}", f"#topics/{ref}"
                phrase = "decision for you" if decision else "to look at"
                if decision:
                    preview = (self.topics.decision(item, version) or {}).get("answer") or ""
                else:
                    preview = item.get("description") or ""
            else:
                kind, phrase = Event.VERSION, f"updated (v{version['version']})"
                key, address = (
                    f"version:{ref}:{version['version']}",
                    f"#topics/{ref}~v{version['version']}",
                )
                following = versions[at + 1]["moment"] if at + 1 < len(versions) else None
                preview = self.change_note(item["thread"], version["moment"], following)
            found.append(
                self.event(
                    kind,
                    key,
                    version["moment"],
                    topic,
                    ref,
                    phrase,
                    item["title"],
                    preview,
                    address,
                    what=what,
                    verdict=item.get("verdict") or "open",
                    faces=[
                        {"file": entry_name(entry), "type": entry["type"]}
                        for entry in files
                        if entry["type"] in FACES
                    ]
                    or None,
                    version=version["version"],
                )
            )
        for entry in item["thread"]:
            if not entry.get("kind"):
                found += self.said(entry, item["thread"], topic, ref, item["title"])
        return found

    def change_note(self, thread: list[dict[str, Any]], at: str, following: str | None) -> str:
        """What changed in the version made at AT, if an agent said so right after it."""
        for entry in thread:
            if (
                entry["author"] == Author.AGENT
                and not entry.get("kind")
                and entry["moment"] >= at
                and (following is None or entry["moment"] < following)
                and seconds_between(at, entry["moment"]) <= CHANGE_NOTE
            ):
                return entry.get("text") or ""
        return ""

    def said(
        self,
        entry: dict[str, Any],
        thread: list[dict[str, Any]],
        topic: str,
        ref: str | None,
        title: str,
    ) -> list[dict[str, Any]]:
        """An agent's message as an event; the owner's own words are none. One
        answering the owner is titled by the first line of what it answers."""
        if entry["author"] != Author.AGENT:
            return []
        where = ref or topic
        files = len(entry.get("attachments") or [])
        text = entry.get("text") or (f"{files} file{'' if files == 1 else 's'}" if files else "")
        if "answers" in entry:
            asked = next(
                (
                    said
                    for said in thread
                    if said["author"] == Author.OWNER and said["moment"] == entry["answers"]
                ),
                None,
            )
            question = (asked or {}).get("text") or ""
            kind, phrase = Event.ANSWERED, "replied to you"
            title = next((line for line in question.splitlines() if line.strip()), title)
        else:
            kind, phrase = Event.MESSAGE, "left a note"
        return [
            self.event(
                kind,
                f"message:{where}:{entry['moment']}",
                entry["moment"],
                topic,
                ref,
                phrase,
                title,
                text,
                f"#topics/{where}~chat",
            )
        ]

    def event(
        self,
        kind: Event,
        key: str,
        at: str,
        topic: str,
        ref: str | None,
        phrase: str,
        title: str,
        preview: str,
        address: str,
        **extra: Any,
    ) -> dict[str, Any]:
        return {
            "key": key,
            "kind": str(kind),
            "moment": at,
            "topic": topic,
            "ref": ref,
            "phrase": phrase,
            "title": clipped(title),
            "preview": clipped(preview),
            "address": address,
            **{name: value for name, value in extra.items() if value is not None},
        }

    def latest(self, topic: str, kinds: tuple[Event, ...]) -> dict[str, Any] | None:
        """The topic's newest event of these kinds: what an agent just wrote."""
        return next((event for event in self.events(topic) if event["kind"] in kinds), None)

    def matching(self, events: list[dict[str, Any]], query: str) -> list[dict[str, Any]]:
        """The events holding the words searched for, the strongest match first."""
        words = query.lower().split()
        if not words:
            return events
        scored = []
        for event in events:
            heading = f"{event['topic']} {event['title']}"
            faces = " ".join(face["file"] for face in event.get("faces") or [])
            body = f"{event['phrase']} {event['title']} {event['preview']} {faces}"
            points = self.topics.score(words, heading, body)
            if points:
                scored.append((points, event))
        scored.sort(key=lambda pair: -pair[0])
        return [event for _, event in scored]
