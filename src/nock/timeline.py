"""The history: what happened in the topics, read from them as events,
newest first — a topic opened or changing state, its review ready or done, an
item added, revised, carried out or judged, an asset made or given a new
version, a message in the chat. Each has a stable key, a phrase, a title, a
preview and its address in the studio (`#/t/TOPIC`, `/item/SLUG`,
`/asset/NAME`, `/chat`). Nothing is stored, so it reads the same on every
machine; the notifications (`nock.notify`) are these events."""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING, Any

from nock.fold import read_events
from nock.notify import Reason
from nock.topics import Author, Topics, entry_name

if TYPE_CHECKING:
    from nock.project import Project

PREVIEW = 280


class Kind(StrEnum):
    OPENED = "opened"
    STATE = "state"
    REVIEW = "review"
    REVIEWED = "reviewed"
    ITEM = "item"
    REVISED = "revised"
    IMPLEMENTED = "implemented"
    VERDICT = "verdict"
    ASSET = "asset"
    REPLY = "reply"
    MESSAGE = "message"


# The events that make it the owner's turn, by why.
TURNS = {
    Reason.REVIEW: (Kind.REVIEW, Kind.STATE),
    Reason.ANSWERED: (Kind.REPLY,),
    Reason.PROPOSED: (Kind.ITEM,),
}


def clipped(text: str, limit: int = PREVIEW) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


class Timeline:
    def __init__(self, project: Project) -> None:
        self.topics = Topics(project)

    def events(self, topic: str | None = None, limit: int | None = None) -> list[dict[str, Any]]:
        """Every event of the topics (or of one), newest first."""
        found: list[dict[str, Any]] = []
        for name in [topic] if topic else self.topics.names():
            found += self.of_topic(name)
        found.sort(key=lambda event: (event["moment"], event["key"]), reverse=True)
        return found[:limit] if limit else found

    def event(
        self,
        name: str,
        kind: Kind,
        source: dict[str, Any],
        phrase: str,
        title: str,
        preview: str = "",
        address: str = "",
    ) -> dict[str, Any]:
        stamp = source.get("by") or {}
        return {
            "key": source.get("id") or source.get("key") or "",
            "topic": name,
            "kind": str(kind),
            "phrase": phrase,
            "title": title,
            "preview": clipped(preview),
            "moment": source.get("moment") or "",
            "author": stamp.get("author") or source.get("author") or "agent",
            "address": f"#/t/{name}{address}",
        }

    def of_topic(self, name: str) -> list[dict[str, Any]]:
        topics = self.topics
        folder = topics.shared.topic_folder(name)
        found: list[dict[str, Any]] = []
        for event in read_events(folder / "events"):
            kind = event.get("kind")
            if kind == "created":
                found.append(
                    self.event(
                        name, Kind.OPENED, event, "opened", name, event.get("description", "")
                    )
                )
            elif kind == "state" and ("state" in event or event.get("status")):
                state = event.get("state")
                phrase = (
                    "came back"
                    if event.get("revived")
                    else ("is in review" if state == "review" else f"is {state}")
                    if state
                    else "changed status"
                )
                found.append(
                    self.event(
                        name,
                        Kind.STATE,
                        event,
                        phrase,
                        name,
                        event.get("note") or event.get("status") or "",
                    )
                )
            elif kind == "message":
                owner = (event.get("by") or {}).get("author") == Author.OWNER
                notes = len(event.get("notes") or [])
                carried = f" with {notes} note{'s' if notes != 1 else ''}" if notes else ""
                found.append(
                    self.event(
                        name,
                        Kind.MESSAGE if owner else Kind.REPLY,
                        event,
                        f"you wrote{carried}"
                        if owner
                        else "an agent answered"
                        if event.get("answers")
                        else "an agent wrote",
                        name,
                        event.get("text") or "",
                        "/chat",
                    )
                )
            elif kind == "reviewed":
                found.append(
                    self.event(name, Kind.REVIEWED, event, "you finished reviewing it", name)
                )
        for event in read_events(topics.shared.review_folder(name) / "events"):
            if event.get("kind") != "version":
                continue
            review = next(
                (v for v in topics.review(name)["versions"] if v["version"] == event["version"]),
                None,
            )
            phrase = "the review is ready" if event["version"] == 1 else "the review was revised"
            found.append(
                self.event(
                    name, Kind.REVIEW, event, phrase, name, (review or {}).get("summary", "")
                )
            )
        for item in topics.items(name):
            folder = topics.shared.item_folder(name, item["slug"])
            for event in read_events(folder / "events"):
                kind = event.get("kind")
                address = f"/item/{item['slug']}"
                if kind == "created":
                    what = "a proposal" if event.get("type") == "proposal" else "a decision"
                    found.append(
                        self.event(
                            name,
                            Kind.ITEM,
                            {**event, "type": event.get("type")},
                            what,
                            event.get("title") or "",
                            event.get("means") or "",
                            address,
                        )
                    )
                    found[-1]["type"] = event.get("type")
                elif kind == "revised":
                    found.append(
                        self.event(
                            name,
                            Kind.REVISED,
                            event,
                            "revised",
                            item["title"],
                            event.get("means") or "",
                            address,
                        )
                    )
                elif kind == "implemented":
                    found.append(
                        self.event(
                            name,
                            Kind.IMPLEMENTED,
                            event,
                            "carried out",
                            item["title"],
                            event.get("means") or "",
                            address,
                        )
                    )
                elif kind == "verdict":
                    found.append(
                        self.event(
                            name,
                            Kind.VERDICT,
                            event,
                            f"you {event['verdict']}",
                            item["title"],
                            "",
                            address,
                        )
                    )
        for asset in topics.assets(name):
            folder = topics.shared.asset_folder(name, asset["name"])
            for event in read_events(folder / "events"):
                if event.get("kind") != "version":
                    continue
                version = next(
                    (v for v in asset["versions"] if v["version"] == event["version"]), None
                )
                file = entry_name((version or {}).get("file") or {})
                phrase = "a new asset" if event["version"] == 1 else f"version {event['version']}"
                found.append(
                    self.event(
                        name,
                        Kind.ASSET,
                        event,
                        phrase,
                        asset["title"],
                        file,
                        f"/asset/{asset['name']}",
                    )
                )
        return found

    def latest(self, topic: str, reason: Reason) -> dict[str, Any] | None:
        """The topic's newest event of the kinds a reason tells of: what an agent just wrote."""
        kinds = {str(kind) for kind in TURNS[reason]}
        for event in self.events(topic):
            if event["kind"] not in kinds or event["author"] != Author.AGENT:
                continue
            if reason is Reason.PROPOSED and event.get("type") != "proposal":
                continue
            return event
        return None
