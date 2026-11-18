"""The fold: `.nock/shared/topics/` read as topics, each holding its items
(decisions and proposals), its assets (files, by version) and its review (the
page the agent composed, by version). Each one's events, in the order their
file names sort, make its state — the latest `state`, a proposal's verdict
and whether it was carried out, the owner's notes and which message carried
them, the chat — in the records the rest of nock reads."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from nock.records import ASSET_FILE_NAME, EVENT_FILE, REVIEW_FILE

TOPICS = "topics"
EVENTS = "events"
ITEMS = "items"
ASSETS = "assets"
REVIEW = "review"
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
    """A message event as the chat's entry."""
    by = event.get("by") or {}
    entry: dict[str, Any] = {
        "id": event["id"],
        "kind": "message",
        "author": by.get("author") or "agent",
        "moment": event.get("moment") or "",
        "text": event.get("text") or "",
        "notes": list(event.get("notes") or []),
        **{key: by[key] for key in ("session", "role", "parent") if by.get(key)},
    }
    if event.get("now"):
        entry["now"] = True
    if event.get("blocks"):
        entry["blocks"] = [
            {**block, "id": block.get("id") or f"m{place}"}
            for place, block in enumerate(event["blocks"], start=1)
            if isinstance(block, dict)
        ]
    if event.get("answers"):
        entry["answers"] = event["answers"]
    if event.get("attachments"):
        entry["attachments"] = [
            {**file, "path": f"{ATTACHMENTS}/{file.get('sha256')}/{file.get('name')}"}
            for file in event["attachments"]
        ]
    return entry


def thread_of(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The chat: the messages, the review being done and the status entries, in order."""
    thread: list[dict[str, Any]] = []
    for event in events:
        kind = event.get("kind")
        if kind == "message":
            thread.append(said(event))
        elif kind == "reviewed":
            thread.append(
                {
                    "id": event["id"],
                    "kind": "reviewed",
                    "author": (event.get("by") or {}).get("author") or "owner",
                    "moment": event.get("moment") or "",
                    "version": event.get("version"),
                    "text": "",
                }
            )
        elif kind == "state":
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


def notes_of(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The owner's notes as they stand: each the latest of its edits, a
    removed one gone, each with the message (or Done) that carried it, if any."""
    current: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    carried: dict[str, str] = {}
    for event in events:
        kind = event.get("kind")
        if kind == "note":
            replaced = event.get("replaces")
            chain = next((key for key, note in current.items() if note["id"] == replaced), None)
            note = {
                "id": event["id"],
                "on": dict(event.get("on") or {}),
                "text": event.get("text") or "",
                **stamp(event),
            }
            if chain is None:
                chain = event["id"]
                order.append(chain)
            current[chain] = note
        elif kind == "message":
            for identifier in event.get("notes") or []:
                carried.setdefault(identifier, event["id"])
    found = []
    for chain in order:
        note = current[chain]
        if not note["text"].strip():
            continue
        found.append({**note, "sent": carried.get(note["id"])})
    return found


def plan_of(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The topic's steps as its latest plan lists them, each with when it was
    started and done; a step kept across plans by its title."""
    steps: list[dict[str, Any]] = []
    for event in events:
        kind = event.get("kind")
        if kind == "plan":
            known = {step["title"]: step for step in steps}
            steps = [
                {
                    "title": given["title"],
                    "estimate": given["estimate"],
                    "started": (known.get(given["title"]) or {}).get("started"),
                    "done": (known.get(given["title"]) or {}).get("done"),
                }
                for given in event.get("steps") or []
                if isinstance(given, dict)
            ]
        elif kind == "step":
            step = next((s for s in steps if s["title"] == event.get("title")), None)
            if step is None:
                continue
            if event.get("state") == "started" and not step["started"]:
                step["started"] = event.get("moment")
            if event.get("state") == "done":
                step["done"] = event.get("moment")
                step["started"] = step["started"] or event.get("moment")
    return steps


def folder_stamp(folder: Path) -> list[list[Any]]:
    """What changes when a folder gains an event or a version: the
    modification time of its events and versions folders."""
    found: list[list[Any]] = []
    for place in (EVENTS, VERSIONS):
        try:
            found.append([place, os.stat(folder / place).st_mtime_ns])
        except OSError:
            continue
    return found


class Fold:
    """The topics under `root` (`.nock/shared/`): each item, asset and review
    folded again only once its folders changed (`folder_stamp`), so a
    long-lived reader (the studio) re-reads only what moved."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.folded: dict[Path, tuple[list[list[Any]], str]] = {}

    @property
    def directory(self) -> Path:
        return self.root / TOPICS

    def names(self) -> list[str]:
        if not self.directory.is_dir():
            return []
        return sorted(
            path.name
            for path in self.directory.iterdir()
            if path.is_dir() and has_events(path / EVENTS)
        )

    def cached(self, folder: Path, build: Any) -> Any:
        """What `build()` makes of FOLDER, kept until its folders change; a
        fresh copy each read."""
        mark = folder_stamp(folder)
        kept = self.folded.get(folder)
        if kept is not None and kept[0] == mark:
            return json.loads(kept[1])
        record = build()
        self.folded[folder] = (mark, json.dumps(record))
        return record

    def topic(self, name: str) -> dict[str, Any] | None:
        folder = self.directory / name
        return self.cached(folder, lambda: self.folded_topic(name, folder))

    def folded_topic(self, name: str, folder: Path) -> dict[str, Any] | None:
        events = read_events(folder / EVENTS)
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
            "thread": thread_of(events),
            "notes": notes_of(events),
            "reviewed": [
                {"version": event["version"], **stamp(event)}
                for event in events
                if event.get("kind") == "reviewed"
            ],
            "revived": None,
            "plan": plan_of(events),
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
                if event.get("revived"):
                    record["revived"] = {"note": event.get("note") or "", **stamp(event)}
                if "priority" in event:
                    if event["priority"]:
                        record["priority"] = event["priority"]
                    else:
                        record.pop("priority", None)
        return record

    def slugs(self, topic: str, place: str = ITEMS) -> list[str]:
        folder = self.directory / topic / place
        if not folder.is_dir():
            return []
        return sorted(
            path.name for path in folder.iterdir() if path.is_dir() and has_events(path / EVENTS)
        )

    def item(self, topic: str, slug: str) -> dict[str, Any] | None:
        folder = self.directory / topic / ITEMS / slug
        return self.cached(folder, lambda: self.folded_item(topic, slug, folder))

    def folded_item(self, topic: str, slug: str, folder: Path) -> dict[str, Any] | None:
        """A decision or a proposal: a proposal accepted is to be carried out,
        and once it is, reads as a decision with what was done; rejected, it
        is dropped."""
        events = read_events(folder / EVENTS)
        created = next((event for event in events if event.get("kind") == "created"), None)
        if created is None:
            return None
        record: dict[str, Any] = {
            "slug": slug,
            "topic": topic,
            "ref": f"{topic}/{slug}",
            "type": created.get("type") or "decision",
            "proposed": created.get("type") == "proposal",
            "title": created.get("title") or "",
            "means": created.get("means") or "",
            "why": created.get("why") or "",
            "takes": created.get("takes") or "",
            "status": "decision" if created.get("type") != "proposal" else "open",
            "created": stamp(created),
            "order": created["key"],
            "updated": events[-1].get("moment") or "",
            "aliases": [],
            "verdict": None,
            "implemented": None,
            "history": [],
        }
        for event in events:
            kind = event.get("kind")
            if kind in ("revised", "implemented"):
                fields = {
                    field: event[field]
                    for field in ("title", "means", "why", "takes")
                    if field in event
                }
                record.update(fields)
                record["history"].append({"kind": kind, **stamp(event), **fields})
                if kind == "implemented" and record["proposed"]:
                    record["type"] = "decision"
                    record["status"] = "decision"
                    record["implemented"] = stamp(event)
            elif kind == "verdict" and record["proposed"] and record["implemented"] is None:
                record["verdict"] = {"verdict": event["verdict"], "id": event["id"], **stamp(event)}
                record["status"] = event["verdict"]
                record["history"].append(
                    {"kind": "verdict", "verdict": event["verdict"], **stamp(event)}
                )
            elif kind == "moved" and event.get("from"):
                record["aliases"].append(event["from"])
        return record

    def items(self, topic: str) -> list[dict[str, Any]]:
        """A topic's items, in the order they were made."""
        found = [self.item(topic, slug) for slug in self.slugs(topic)]
        kept = [item for item in found if item is not None]
        return sorted(kept, key=lambda item: item["order"])

    def asset(self, topic: str, name: str) -> dict[str, Any] | None:
        folder = self.directory / topic / ASSETS / name
        return self.cached(folder, lambda: self.folded_asset(topic, name, folder))

    def folded_asset(self, topic: str, name: str, folder: Path) -> dict[str, Any] | None:
        events = read_events(folder / EVENTS)
        created = next((event for event in events if event.get("kind") == "created"), None)
        if created is None:
            return None
        record: dict[str, Any] = {
            "name": name,
            "topic": topic,
            "ref": f"{topic}:{name}",
            "order": created["key"],
            "title": created.get("title") or "",
            "description": created.get("description") or "",
            "created": stamp(created),
            "updated": events[-1].get("moment") or "",
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
                kept = read_json_or(folder / VERSIONS / str(number) / ASSET_FILE_NAME, {})
                record["versions"].append(
                    {
                        "version": number,
                        **stamp(event),
                        "file": dict(kept.get("file") or {}),
                        "blobs": dict(kept.get("blobs") or {}),
                    }
                )
        return record

    def assets(self, topic: str) -> list[dict[str, Any]]:
        found = [self.asset(topic, name) for name in self.slugs(topic, ASSETS)]
        kept = [asset for asset in found if asset is not None]
        return sorted(kept, key=lambda asset: asset["order"])

    def review(self, topic: str) -> dict[str, Any]:
        """The topic's review: each version's summary and blocks, every
        block with its id (its own, else its place: `b1`, `b2`, …)."""
        folder = self.directory / topic / REVIEW
        return self.cached(folder, lambda: self.folded_review(folder))

    def folded_review(self, folder: Path) -> dict[str, Any]:
        versions = []
        for event in read_events(folder / EVENTS):
            if event.get("kind") != "version":
                continue
            number = int(event["version"])
            kept = read_json_or(folder / VERSIONS / str(number) / REVIEW_FILE, {})
            blocks = []
            for place, block in enumerate(kept.get("blocks") or [], start=1):
                if isinstance(block, dict):
                    blocks.append({**block, "id": block.get("id") or f"b{place}"})
            versions.append(
                {
                    "version": number,
                    **stamp(event),
                    "summary": kept.get("summary") or "",
                    "blocks": blocks,
                }
            )
        return {"versions": versions}


def has_events(folder: Path) -> bool:
    """Whether a folder holds a completed event, by its files' names alone."""
    try:
        return any(EVENT_FILE.match(path.name) for path in folder.iterdir())
    except OSError:
        return False


def read_json_or(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return default
