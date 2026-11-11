"""The fold: `.nock/shared/topics/` read as topics and their decisions, each
decision holding its assets. Each one's events, in the order their file
names sort, make its state — the latest `state`, the latest `verdict` unless
a version of the decision or of one of its assets came after it, each
asset's preferred variant, the messages as its thread — in the records the
rest of nock reads (an "item" is a decision)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from nock.records import ASSETS_FILE, DECISION_FILE, EVENT_FILE

TOPICS = "topics"
EVENTS = "events"
ITEMS = "decisions"
ASSETS = "assets"
VERSIONS = "versions"
# A thread's entry recording a change of the topic's state or status.
STATUS = "status"
# Where a thread's attachments are addressed: `attachments/<sha256>/<name>`.
ATTACHMENTS = "attachments"


def read_events(folder: Path) -> list[dict[str, Any]]:
    """A folder's completed events, in order; drafts (any other name) are not
    events yet."""
    if not folder.is_dir():
        return []
    found = []
    for path in sorted(folder.iterdir()):
        matched = EVENT_FILE.match(path.name)
        if not matched:
            continue
        try:
            record = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(record, dict):
            record["key"] = path.stem
            found.append(record)
    return found


def stamp(event: dict[str, Any]) -> dict[str, Any]:
    """Who wrote an event and when, as records keep it."""
    by = event.get("by") or {}
    return {
        "moment": event.get("moment") or "",
        **{
            key: by[key]
            for key in ("author", "session", "role", "parent", "user", "host")
            if by.get(key)
        },
    }


def said(event: dict[str, Any]) -> dict[str, Any]:
    """A message event as a thread's entry."""
    by = event.get("by") or {}
    entry: dict[str, Any] = {
        "id": event["id"],
        "author": by.get("author") or "agent",
        "moment": event.get("moment") or "",
        "text": event.get("text") or "",
        **{key: by[key] for key in ("session", "role", "parent") if by.get(key)},
    }
    for field in ("verdict", "now"):
        if event.get(field):
            entry[field] = event[field]
    if event.get("note"):
        entry["kind"] = event["note"]
    if event.get("attachments"):
        entry["attachments"] = [
            {**file, "path": f"{ATTACHMENTS}/{file.get('sha256')}/{file.get('name')}"}
            for file in event["attachments"]
        ]
    return entry


def thread_of(events: list[dict[str, Any]], statuses: bool) -> list[dict[str, Any]]:
    """The messages (and, for a topic, its status entries) in order, each
    withdrawn message gone, each answer marked with what it answers."""
    thread: list[dict[str, Any]] = []
    for event in events:
        kind = event.get("kind")
        if kind == "message":
            if event.get("withdraws"):
                thread = [entry for entry in thread if entry.get("id") != event["withdraws"]]
                continue
            entry = said(event)
            if event.get("answers"):
                answered = next((e for e in thread if e.get("id") == event["answers"]), None)
                entry["answers"] = answered["moment"] if answered else event["answers"]
                entry["answers_id"] = event["answers"]
            thread.append(entry)
        elif kind == "verdict" and event.get("comment"):
            entry = said({**event, "text": event["comment"]})
            entry["verdict"] = event["verdict"]
            thread.append(entry)
        elif kind == "state" and statuses:
            entry = {
                "id": event["id"],
                "kind": STATUS,
                "author": (event.get("by") or {}).get("author") or "agent",
                "moment": event.get("moment") or "",
                "text": event.get("note") or event.get("status") or event.get("state") or "",
                **{
                    key: value
                    for key, value in stamp(event).items()
                    if key in ("session", "role", "parent")
                },
            }
            for field in ("state", "status"):
                if field in event:
                    entry[field] = event[field]
            if event.get("revived"):
                entry["revived"] = True
            thread.append(entry)
    return thread


class Fold:
    """The topics and items under `root` (`.nock/shared/`), read afresh."""

    def __init__(self, root: Path) -> None:
        self.root = root

    @property
    def directory(self) -> Path:
        return self.root / TOPICS

    def names(self) -> list[str]:
        if not self.directory.is_dir():
            return []
        return sorted(
            path.name
            for path in self.directory.iterdir()
            if path.is_dir() and read_events(path / EVENTS)
        )

    def topic(self, name: str) -> dict[str, Any] | None:
        events = read_events(self.directory / name / EVENTS)
        created = next((event for event in events if event.get("kind") == "created"), None)
        if created is None:
            return None
        record: dict[str, Any] = {
            "name": name,
            "description": created.get("description") or "",
            "state": created.get("state") or "active",
            "status": created.get("status") or "",
            "created": stamp(created),
            "updated": events[-1].get("moment") or "",
            "aliases": [],
            "thread": thread_of(events, statuses=True),
        }
        for event in events:
            kind = event.get("kind")
            if kind == "described":
                record["description"] = event["description"]
            elif kind == "renamed" and event.get("from"):
                record["aliases"].append(event["from"])
            elif kind == "state":
                if "state" in event and event["state"] != record["state"]:
                    record["status"] = ""
                if "state" in event:
                    record["state"] = event["state"]
                if "status" in event:
                    record["status"] = event["status"]
                if "priority" in event:
                    if event["priority"]:
                        record["priority"] = event["priority"]
                    else:
                        record.pop("priority", None)
        return record

    def slugs(self, topic: str) -> list[str]:
        folder = self.directory / topic / ITEMS
        if not folder.is_dir():
            return []
        return sorted(
            path.name for path in folder.iterdir() if path.is_dir() and read_events(path / EVENTS)
        )

    def item(self, topic: str, slug: str) -> dict[str, Any] | None:
        """A decision: its own events and versions, and its assets, each with
        its versions; its verdict stands only while no version of it or of an
        asset of it came after."""
        folder = self.directory / topic / ITEMS / slug
        events = read_events(folder / EVENTS)
        created = next((event for event in events if event.get("kind") == "created"), None)
        if created is None:
            return None
        assets = self.assets(folder)
        record: dict[str, Any] = {
            "slug": slug,
            "topic": topic,
            "ref": f"{topic}/{slug}",
            "title": created.get("title") or "",
            "description": created.get("description") or "",
            "aliases": list(created.get("aliases") or []),
            "verdict": "open",
            "decided": None,
            "created": stamp(created),
            "updated": max(
                [events[-1].get("moment") or "", *(asset["updated"] for asset in assets)]
            ),
            "thread": thread_of(events, statuses=False),
            "versions": [],
            "assets": assets,
        }
        verdict: dict[str, Any] | None = None
        for event in events:
            kind = event.get("kind")
            if kind == "titled":
                for field in ("title", "description"):
                    if field in event:
                        record[field] = event[field]
            elif kind == "version":
                record["versions"].append(self.version(folder, event))
            elif kind == "verdict":
                verdict = event
            elif kind == "moved" and event.get("from"):
                record["aliases"].append(event["from"])
        versioned = [event["key"] for event in events if event.get("kind") == "version"] + [
            asset["versioned"] for asset in assets
        ]
        if verdict is not None and verdict["key"] > max(versioned, default=""):
            record["verdict"] = verdict["verdict"]
            record["decided"] = stamp(verdict) if verdict["verdict"] != "open" else None
        return record

    def version(self, folder: Path, event: dict[str, Any]) -> dict[str, Any]:
        """A decision's version: its `decision.json` is beside it."""
        number = int(event["version"])
        files = []
        if (folder / VERSIONS / str(number) / DECISION_FILE).is_file():
            files.append({"kind": "decision", "name": DECISION_FILE})
        return {"version": number, **stamp(event), "files": files}

    def assets(self, folder: Path) -> list[dict[str, Any]]:
        """A decision's assets, in the order they were made."""
        place = folder / ASSETS
        if not place.is_dir():
            return []
        found = [self.asset(path) for path in sorted(place.iterdir()) if path.is_dir()]
        kept = [asset for asset in found if asset is not None]
        return sorted(kept, key=lambda asset: asset["created"]["moment"])

    def asset(self, folder: Path) -> dict[str, Any] | None:
        events = read_events(folder / EVENTS)
        created = next((event for event in events if event.get("kind") == "created"), None)
        if created is None:
            return None
        record: dict[str, Any] = {
            "name": folder.name,
            "title": created.get("title") or "",
            "description": created.get("description") or "",
            "created": stamp(created),
            "updated": events[-1].get("moment") or "",
            "versioned": "",
            "variants": False,
            "preferred": None,
            "versions": [],
        }
        for event in events:
            kind = event.get("kind")
            if kind == "titled":
                for field in ("title", "description"):
                    if field in event:
                        record[field] = event[field]
            elif kind == "version":
                number = int(event["version"])
                assets = read_json_or(folder / VERSIONS / str(number) / ASSETS_FILE, {})
                record["versions"].append(
                    {
                        "version": number,
                        **stamp(event),
                        "files": [dict(entry, local=False) for entry in assets.get("files") or []],
                        "views": [dict(view) for view in assets.get("views") or []],
                        "blobs": dict(assets.get("blobs") or {}),
                        "variants": bool(assets.get("variants")),
                    }
                )
                record["variants"] = bool(assets.get("variants"))
                record["versioned"] = event["key"]
            elif kind == "preferred":
                record["preferred"] = (
                    {"version": event["version"], "name": event["name"]}
                    if event.get("name")
                    else None
                )
        return record

    def items(self, topic: str) -> list[dict[str, Any]]:
        """A topic's decisions, the newest first."""
        found = [self.item(topic, slug) for slug in self.slugs(topic)]
        kept = [item for item in found if item is not None]
        return sorted(kept, key=lambda item: item["created"]["moment"], reverse=True)


def read_json_or(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return default
