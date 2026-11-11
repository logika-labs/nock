"""The timeline: what happened in the topics, newest first, as the owner would
be told it — a topic opened, a topic's state or status changed or it came
back, an item submitted for review, a new version of one, an agent writing
in a thread (answering the owner, or not). Each event is read from the
committed topics, never stored, so it covers all of their history and reads
the same on every machine; its `key` names it for good. The studio's
Timeline shows them, and the browser's and the desktop's notifications are
these same events (`nock.notify`): one source."""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING, Any

from nock.notify import Reason
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


def clipped(text: str, limit: int = PREVIEW) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


class Timeline:
    def __init__(self, project: Project) -> None:
        self.topics = Topics(project)

    def events(self, topic: str | None = None) -> list[dict[str, Any]]:
        """Every event (of TOPIC), the newest first."""
        found: list[dict[str, Any]] = []
        for name in [topic] if topic else self.topics.names():
            found += self.of_topic(name)
        # Within one second, what follows from another comes after it: a topic, then its items.
        found.sort(
            key=lambda event: (event["moment"], ORDER.index(event["kind"]), event["key"]),
            reverse=True,
        )
        return found

    def of_topic(self, name: str) -> list[dict[str, Any]]:
        record = self.topics.topic(name)
        created = moment(record.get("created"))
        found = [
            self.event(
                Event.TOPIC,
                f"topic:{name}",
                created or record.get("updated") or "",
                name,
                None,
                f"New topic {name}",
                record["description"],
                f"#topics/{name}",
            )
        ]
        state = None
        for entry in record["thread"]:
            if entry.get("kind") == STATUS:
                said = entry.get("status") or ""
                if entry.get("revived"):
                    kind, text = Event.REVIVED, f"{name} is back"
                    said = entry.get("text") or said
                elif entry.get("state") != (state or "active"):
                    kind, text = Event.STATE, f"{name} is {entry.get('state')}"
                elif entry["moment"] == created:
                    state = entry.get("state")
                    continue
                else:
                    kind, text = Event.STATUS, f"{name}: new status"
                state = entry.get("state")
                found.append(
                    self.event(
                        kind,
                        f"status:{name}:{entry['moment']}",
                        entry["moment"],
                        name,
                        None,
                        text,
                        said,
                        f"#topics/{name}",
                        state=state,
                    )
                )
            elif not entry.get("kind"):
                found += self.said(entry, name, None, "")
        for item in self.topics.items(name):
            found += self.of_item(item)
        return found

    def of_item(self, item: dict[str, Any]) -> list[dict[str, Any]]:
        ref, topic = item["ref"], item["topic"]
        found = []
        for version in item["versions"]:
            decision = next(
                (entry for entry in version["files"] if entry["kind"] == "decision"), None
            )
            files = [entry for entry in version["files"] if entry["kind"] != "decision"]
            what = "decision" if decision else "asset"
            if version["version"] == 1:
                kind, text = Event.ITEM, f"New {what} for review"
                key, address = f"item:{ref}", f"#topics/{ref}"
            else:
                kind, text = Event.VERSION, f"Version {version['version']} for review"
                key, address = (
                    f"version:{ref}:{version['version']}",
                    f"#topics/{ref}~v{version['version']}",
                )
            preview = item.get("description") or ""
            if decision and not preview:
                read = self.topics.decision(item, version) or {}
                preview = read.get("answer") or ""
            found.append(
                self.event(
                    kind,
                    key,
                    version["moment"],
                    topic,
                    ref,
                    text,
                    preview,
                    address,
                    title=item["title"],
                    what=what,
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
                found += self.said(entry, topic, ref, item["title"])
        return found

    def said(
        self, entry: dict[str, Any], topic: str, ref: str | None, title: str
    ) -> list[dict[str, Any]]:
        """An agent's message as an event; the owner's own words are none."""
        if entry["author"] != Author.AGENT:
            return []
        where = ref or topic
        kind = Event.ANSWERED if "answers" in entry else Event.MESSAGE
        text = "An agent answered you" if kind is Event.ANSWERED else "An agent wrote"
        files = len(entry.get("attachments") or [])
        preview = entry.get("text") or (f"{files} file{'' if files == 1 else 's'}" if files else "")
        return [
            self.event(
                kind,
                f"message:{where}:{entry['moment']}",
                entry["moment"],
                topic,
                ref,
                text,
                preview,
                f"#topics/{where}~chat",
                title=title,
            )
        ]

    def event(
        self,
        kind: Event,
        key: str,
        at: str,
        topic: str,
        ref: str | None,
        text: str,
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
            "text": text,
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
            heading = f"{event['topic']} {event.get('title') or ''}"
            faces = " ".join(face["file"] for face in event.get("faces") or [])
            body = f"{event['text']} {event['preview']} {faces}"
            points = self.topics.score(words, heading, body)
            if points:
                scored.append((points, event))
        scored.sort(key=lambda pair: -pair[0])
        return [event for _, event in scored]
