#!/usr/bin/env python3
"""Move a project's topics from the layout nock kept them in before
`.nock/shared/` — `.nock/topics/TOPIC/topic.json`, `SLUG/item.json` and its
version folders, large files under `.nock/local/topics/` — into the store, and
its round records from `.nock/reflections/` to `.nock/shared/rounds/`, in one
commit. A one-off, run once on a project when the store lands; nock itself
never reads the old layout.

    python3 scripts/move-to-shared.py PROJECT_ROOT [--dry-run]

It imports nock from this checkout's `src/` (or `--nock PATH`) for the store's
own helpers, and reads the old layout itself. Each topic's history becomes its
events, each decision item a decision, each asset item an asset of the
decision its thread ties it to ("Screenshots: [ref]", "illustrates [ref]") or
of a "Review: …" decision wrapping it; moments, writers and aliases are kept,
and what each session was told of the owner's word stays told."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import secrets
import shutil
import subprocess
import sys
from datetime import UTC
from pathlib import Path
from typing import Any

NOCK_PROTOCOLS = ("nock.toolbox", "nock.map", "nock.fit")
LOGIKA_PROTOCOLS = ("logika.rules", "logika.analytics")
TOPIC_FILE = "topic.json"
ITEM_FILE = "item.json"
DECISION_FILE = "decision.json"
ASSETS_FILE = "assets.json"
ASSETS_DIR = "assets"
STATUS = "status"
MAP = "map.md"
NAME = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")


def load_nock(path: Path) -> None:
    sys.path.insert(0, str(path))
    global Project, Shared, Topics, owner_word, is_media, kind_of, slugged, now, parse_moment
    global read_json, write_json, NotFoundError
    from nock.errors import NotFoundError
    from nock.project import Project
    from nock.shared import Shared, is_media, kind_of
    from nock.topics import Topics, owner_word, slugged
    from nock.utils import now, parse_moment, read_json, write_json


class Old:
    """The topics as an earlier nock kept them: read, never written."""

    def __init__(self, project: Any) -> None:
        self.directory = project.root / ".nock" / "topics"
        self.large = project.local / "topics"
        self.map = self.directory / MAP

    def names(self) -> list[str]:
        if not self.directory.is_dir():
            return []
        return sorted(path.parent.name for path in self.directory.glob(f"*/{TOPIC_FILE}"))

    def topic(self, name: str) -> dict[str, Any]:
        return read_json(self.directory / name / TOPIC_FILE)

    def items(self, name: str) -> list[dict[str, Any]]:
        found = [read_json(path) for path in (self.directory / name).glob(f"*/{ITEM_FILE}")]
        for item in found:
            item["topic"] = name
            item["ref"] = f"{name}/{item['slug']}"
        return sorted(
            found, key=lambda item: (item.get("created") or {}).get("moment") or "", reverse=True
        )

    def every(self) -> list[dict[str, Any]]:
        return [item for name in self.names() for item in self.items(name)]

    def folder(self, topic: str, slug: str, version: int) -> Path:
        return self.directory / topic / slug / str(version)

    def located(self, topic: str, slug: str, version: int, entry: dict[str, Any]) -> Path:
        base = self.large if entry.get("local") else self.directory
        stored = f"project/{entry['path']}" if entry["kind"] == "project" else entry["name"]
        return base / topic / slug / str(version) / stored

    def where(self, entry: dict[str, Any], topic: str, slug: str | None = None) -> Path:
        base = self.large if entry.get("local") else self.directory
        return (base / topic / slug if slug else base / topic) / entry["path"]


def state_of(topic: dict[str, Any]) -> str:
    return topic.get("state") or "active"


def companions(entry: dict[str, Any]) -> dict[str, str]:
    return {role: entry[role] for role in ("captions", "poster") if entry.get(role)}


def has_variants(item: dict[str, Any]) -> bool:
    return bool(item.get("variants"))


def legacy_word(item: dict[str, Any]) -> str:
    """The owner's word on an item as the old layout's sessions were told it."""
    decided = item.get("decided") or {}
    moments = [decided.get("moment") or ""]
    moments += [entry["moment"] for entry in item["thread"] if entry["author"] == "owner"]
    said = max(moments)
    if not said:
        return ""
    word = {
        "verdict": item.get("verdict"),
        "decided": item.get("decided"),
        "messages": [
            [entry["moment"], entry.get("session"), entry.get("parent")]
            for entry in item["thread"]
            if entry["author"] == "owner"
        ],
    }
    digest = hashlib.sha256(json.dumps(word, sort_keys=True).encode()).hexdigest()
    return f"{said} {digest[:12]}"


def committed(project: Any, paths: list[str], message: str) -> str | None:
    git = project.git
    git("add", "--all", "--", *paths)
    git("commit", "--quiet", "--no-verify", "--only", "-m", message, "--", *paths)
    return None


class Storing:
    """The move to the store: `.nock/topics/` (and its large files under
    `.nock/local/topics/`) becomes `.nock/shared/`, one immutable file per
    event, in one commit. Each topic's history becomes its events — created,
    each status entry a `state`, each message a `message` — and each item's
    its `created`, a `version` per version (its folder `versions/N/`: the
    decision, `assets.json`, small text beside it, everything else in
    `media/` by sha256; a project file copied then becomes a link to the
    commit that made the version when its content matches, else it is kept
    by content), its messages, its verdict and its preferred variant. Every
    event keeps its moment and who wrote it; the map moves too."""

    def __init__(self, project: Project) -> None:
        self.project = project
        self.topics = Old(project)
        self.store = Shared(project)
        self.old = project.root / ".nock" / "topics"

    def pending(self) -> bool:
        return self.old.is_dir() and any(self.old.glob(f"*/{TOPIC_FILE}"))

    def run(self) -> dict[str, Any]:
        counts = {"topics": 0, "items": 0, "events": 0, "links": 0, "media": 0}
        with self.project.lock("topics"):
            self.user = self.project.git("config", "user.email", check=False) or None
            self.moved = self.reflections()
            told = self.told()
            self.ties()
            try:
                for name in self.topics.names():
                    self.topic(name, counts)
            finally:
                if hasattr(self, "reader"):
                    assert self.reader.stdin is not None
                    self.reader.stdin.close()
                    self.reader.wait()
            if self.topics.map.is_file():
                self.store.map.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(self.topics.map, self.store.map)
            shutil.rmtree(self.old, ignore_errors=True)
            shutil.rmtree(self.topics.large, ignore_errors=True)
            paths = [".nock/shared"]
            for old in (".nock/topics", ".nock/reflections"):
                if self.tracked(old):
                    paths.append(old)
            counts["rounds"] = self.moved
            problem = committed(
                self.project,
                paths,
                f"Topics and rounds are in the store, .nock/shared/: {counts['topics']} topic(s),"
                f" {counts['items']} item(s), {counts['events']} event(s), {self.moved} round"
                " record(s)",
            )
            self.tell_again(told)
        return {**counts, **({"not_committed": problem} if problem else {})}

    def reflections(self) -> int:
        """Each round recorded under `.nock/reflections/`, kept for each protocol
        that round covered: nock's for `nock.toolbox`, `nock.map` and `nock.fit`,
        the logika round's for `logika.rules` and `logika.analytics`."""
        old = self.project.root / ".nock" / "reflections"
        if not old.is_dir():
            return 0
        moved = 0
        for kind, names in (("", NOCK_PROTOCOLS), ("logika", LOGIKA_PROTOCOLS)):
            folder = old / kind if kind else old
            for round_folder in sorted(folder.iterdir()) if folder.is_dir() else []:
                if not (round_folder / "record.json").is_file():
                    continue
                for name in names:
                    target = self.store.root / "rounds" / name / round_folder.name
                    shutil.copytree(round_folder, target, dirs_exist_ok=True)
                    record = read_json(target / "record.json")
                    write_json(target / "record.json", {**record, "protocol": name})
                moved += 1
        shutil.rmtree(old)
        return moved

    def told(self) -> list[tuple[str, str]]:
        """Which sessions have been told the owner's latest word on which items."""
        words = {item["ref"]: legacy_word(item) for item in self.topics.every()}
        return [
            (row["session"], row["item"])
            for row in self.project.store.rows("SELECT session, item, updated FROM told")
            if words.get(row["item"]) and row["updated"] == words[row["item"]]
        ]

    def tell_again(self, told: list[tuple[str, str]]) -> None:
        """What a session was told still counts as told: the owner's word as the
        store now reads it."""
        topics = Topics(self.project)
        for session, ref in told:
            try:
                word = owner_word(topics.item(ref))
            except NotFoundError:
                continue
            if word:
                self.project.store.insert(
                    "told", {"session": session, "item": ref, "updated": word}
                )

    def tracked(self, path: str) -> bool:
        return bool(self.project.git("ls-files", "--", path))

    def by(self, stamp: dict[str, Any] | None, author: str | None = None) -> dict[str, Any]:
        stamp = stamp or {}
        who = author or stamp.get("author") or "agent"
        role = stamp.get("role")
        interactive = who == "owner" or (role in (None, "interactive") and not stamp.get("parent"))
        return {
            key: value
            for key, value in {
                "author": who,
                "on_behalf": "interactive" if interactive else "agent",
                "user": self.user,
                "session": stamp.get("session"),
                "parent": stamp.get("parent"),
                "role": role,
            }.items()
            if value is not None
        }

    def write(
        self,
        folder: Path,
        events: list[tuple[str, dict[str, Any]]],
        counts: dict[str, int],
    ) -> dict[str, str]:
        """Write events, each `(moment, record with its by)`, in order: their
        files named by their moment, a millisecond apart within one second so
        they sort as they were said. The ids given, by moment."""
        ids: dict[str, str] = {}
        last = ""
        milliseconds = 0
        for moment, record in events:
            base = moment_stamp(moment)
            milliseconds = milliseconds + 1 if base == last else 0
            last = base
            identifier = secrets.token_hex(4)
            complete = {
                "kind": record.pop("kind"),
                "moment": moment,
                "id": identifier,
                "by": record.pop("by"),
                **record,
            }
            write_json(
                folder / "events" / f"{base}.{milliseconds:03d}Z-{identifier}.json", complete
            )
            if complete["kind"] == "message":
                ids.setdefault(moment, identifier)
            counts["events"] += 1
        return ids

    def topic(self, name: str, counts: dict[str, int]) -> None:
        topic = self.topics.topic(name)
        folder = self.store.topic_folder(name)
        created = topic.get("created") or {}
        first = created.get("moment") or topic.get("updated") or now()
        statuses = [entry for entry in topic["thread"] if entry.get("kind") == STATUS]
        events: list[tuple[str, dict[str, Any]]] = [
            (
                first,
                {
                    "kind": "created",
                    "by": self.by(created),
                    "description": topic["description"],
                    "state": "active" if statuses else str(state_of(topic)),
                },
            )
        ]
        events += self.thread(topic["thread"], name, None, statuses=True)
        last_state = {"state": "active", "status": ""}
        for entry in statuses:
            if entry.get("state"):
                last_state["status"] = (
                    "" if entry["state"] != last_state["state"] else last_state["status"]
                )
                last_state["state"] = entry["state"]
            if "status" in entry:
                last_state["status"] = entry.get("status") or ""
        now_state = {"state": str(state_of(topic)), "status": topic.get("status") or ""}
        final: dict[str, Any] = {}
        if statuses and now_state != last_state:
            final |= now_state
        if topic.get("priority"):
            final["priority"] = topic["priority"]
        if final:
            events.append(
                (topic.get("updated") or first, {"kind": "state", "by": self.by(created), **final})
            )
        events.sort(key=lambda pair: pair[0])
        ids = self.write(folder, events, counts)
        self.link_answers(folder, ids)
        counts["topics"] += 1
        for item in self.topics.items(name):
            self.item(name, item, counts)

    def thread(
        self,
        thread: list[dict[str, Any]],
        topic: str,
        slug: str | None,
        statuses: bool,
    ) -> list[tuple[str, dict[str, Any]]]:
        events: list[tuple[str, dict[str, Any]]] = []
        for entry in thread:
            if entry.get("kind") == STATUS:
                if statuses:
                    record: dict[str, Any] = {"kind": "state", "by": self.by(entry, "agent")}
                    for key in ("state", "status"):
                        if key in entry:
                            record[key] = entry.get(key) or ""
                    if entry.get("revived"):
                        record["revived"] = True
                        record["note"] = entry.get("text") or ""
                    events.append((entry["moment"], record))
                continue
            text = entry.get("text") or ""
            record = {"kind": "message", "by": self.by(entry, entry.get("author")), "text": text}
            if entry.get("kind") in ("task", "split", "revival"):
                record["note"] = entry["kind"]
            if entry.get("kind") == "revival" and statuses:
                record = {
                    "kind": "state",
                    "by": self.by(entry, "agent"),
                    "state": "active",
                    "revived": True,
                    "note": text,
                }
            if entry.get("verdict") and record["kind"] == "message":
                record["verdict"] = entry["verdict"]
            files = []
            for file in entry.get("attachments", []):
                path = self.topics.where(file, topic, slug)
                if path.is_file():
                    files.append(
                        {
                            "name": file["name"],
                            "type": file.get("type") or kind_of(file["name"], b""),
                            "bytes": path.stat().st_size,
                            "sha256": self.store.keep(path.read_bytes()),
                        }
                    )
            if files:
                record["attachments"] = files
            if not text and not files and record["kind"] == "message":
                record["text"] = "(no text)"
            if entry.get("answers"):
                record["answers_moment"] = entry["answers"]
            events.append((entry["moment"], record))
        return events

    def item(self, topic: str, item: dict[str, Any], counts: dict[str, int]) -> None:
        """A decision item as a decision, its project files its assets, and the
        asset items its thread or theirs ties to it as assets of it too; an
        asset item tied to none as an asset of a "Review" decision wrapping it."""
        if item["ref"] in self.attached:
            return
        decided_kind = any(
            entry["kind"] == "decision"
            for version in item["versions"]
            for entry in version["files"]
        )
        folder = self.store.item_folder(topic, item["slug"])
        created = item.get("created") or {}
        first = created.get("moment") or item.get("updated") or now()
        title = item["title"] if decided_kind else f"Review: {item['title']}"
        # The asset items it now holds keep their refs, as its aliases.
        aliases = [
            *item.get("aliases", []),
            *(other["ref"] for other in self.tied.get(item["ref"], [])),
        ]
        events: list[tuple[str, dict[str, Any]]] = [
            (
                first,
                {
                    "kind": "created",
                    "by": self.by(created),
                    "title": title,
                    **({"description": item["description"]} if item.get("description") else {}),
                    **({"aliases": aliases} if aliases else {}),
                },
            )
        ]
        number = 0
        for version in item["versions"]:
            decision = self.topics.folder(topic, item["slug"], version["version"]) / DECISION_FILE
            if decided_kind and not decision.is_file():
                continue
            number += 1
            target = folder / "versions" / str(number)
            target.mkdir(parents=True, exist_ok=True)
            if decided_kind:
                shutil.copy2(decision, target / DECISION_FILE)
            else:
                answer = item.get("description") or f"Review {item['title']}."
                write_json(
                    target / DECISION_FILE,
                    {"answer": answer, "alternatives": [], "status": "done"},
                )
            events.append(
                (
                    version.get("moment") or first,
                    {"kind": "version", "by": self.by(version), "version": number},
                )
            )
            if not decided_kind:
                break
        events += self.thread(item["thread"], topic, item["slug"], statuses=False)
        latest_asset = self.assets(topic, item, folder, counts)
        for other in self.tied.get(item["ref"], []):
            events += self.thread(other["thread"], other["topic"], other["slug"], statuses=False)
            latest_asset = max(latest_asset, self.assets(other["topic"], other, folder, counts))
        decided = item.get("decided")
        if item["verdict"] != "open" and decided:
            moment = decided.get("moment") or item.get("updated") or first
            events.append(
                (
                    moment,
                    {
                        "kind": "verdict",
                        "by": self.by(decided, "owner"),
                        "verdict": item["verdict"],
                    },
                )
            )
            accepted_too = all(
                other["verdict"] == item["verdict"] for other in self.tied.get(item["ref"], [])
            )
            for other in self.tied.get(item["ref"], []):
                # A screenshot the owner rejected asks for rework of what it shows.
                said = other.get("decided") or {}
                if other["verdict"] == "rejected" and said.get("moment"):
                    events.append(
                        (
                            said["moment"],
                            {
                                "kind": "verdict",
                                "by": self.by(said, "owner"),
                                "verdict": "rejected",
                            },
                        )
                    )
            if latest_asset > moment and accepted_too:
                # Its assets were judged as items of their own, the same way: the verdict
                # still holds after them, rather than the move reopening what was decided.
                events.append(
                    (
                        latest_asset,
                        {
                            "kind": "verdict",
                            "by": self.by(decided, "owner"),
                            "verdict": item["verdict"],
                        },
                    )
                )
        order = {"created": 0}
        events.sort(key=lambda pair: (pair[0], order.get(pair[1]["kind"], 1)))
        ids = self.write(folder, events, counts)
        self.link_answers(folder, ids)
        counts["items"] += 1

    def assets(self, topic: str, item: dict[str, Any], folder: Path, counts: dict[str, int]) -> str:
        """An item's files, by version, as assets of the decision in `folder`:
        each project file an asset, its derived files one (with its variants
        and views); a version only where a file changed. The latest moment."""
        made: dict[str, dict[str, Any]] = {}
        latest = ""
        for version in item["versions"]:
            number = version["version"]
            old = self.topics.folder(topic, item["slug"], number)
            commit = self.made_by(old)
            derived = [entry for entry in version["files"] if entry["kind"] == "derived"]
            groups: list[tuple[str, str, list[dict[str, Any]]]] = [
                (slugged(entry["path"]), entry["path"], [entry])
                for entry in version["files"]
                if entry["kind"] == "project"
            ]
            if derived:
                groups.append(
                    (
                        item["slug"],
                        item["title"],
                        derived,
                    )
                )
            for name, title, entries in groups:
                record = self.asset_record(
                    topic, item, number, old, commit, entries, version, counts
                )
                kept = made.get(name)
                if kept is not None and kept["last"] == record["digest"]:
                    continue
                if kept is None:
                    kept = made[name] = {"versions": 0, "last": None, "title": title, "events": []}
                    kept["events"].append(
                        (
                            version.get("moment") or "",
                            {"kind": "created", "by": self.by(version), "title": title},
                        )
                    )
                kept["versions"] += 1
                kept["last"] = record["digest"]
                target = folder / ASSETS_DIR / name / "versions" / str(kept["versions"])
                target.mkdir(parents=True, exist_ok=True)
                for file_name, data in record["beside"].items():
                    (target / file_name).write_bytes(data)
                write_json(target / ASSETS_FILE, record["assets"])
                moment = version.get("moment") or ""
                kept["events"].append(
                    (
                        moment,
                        {"kind": "version", "by": self.by(version), "version": kept["versions"]},
                    )
                )
                latest = max(latest, moment)
        preferred = item.get("preferred")
        for name, kept in made.items():
            if preferred and name == item["slug"]:
                at = next(
                    (
                        index
                        for index, (_, record) in enumerate(kept["events"])
                        if record["kind"] == "version"
                    ),
                    None,
                )
                if at is not None:
                    decided = item.get("decided") or {}
                    kept["events"].append(
                        (
                            decided.get("moment") or item.get("updated") or "",
                            {
                                "kind": "preferred",
                                "by": self.by(decided, "owner"),
                                "version": kept["versions"],
                                "name": preferred["name"],
                            },
                        )
                    )
            kept["events"].sort(
                key=lambda pair: (pair[0], 0 if pair[1]["kind"] == "created" else 1)
            )
            self.write(folder / ASSETS_DIR / name, kept["events"], counts)
        return latest

    def asset_record(
        self,
        topic: str,
        item: dict[str, Any],
        number: int,
        old: Path,
        commit: str | None,
        entries: list[dict[str, Any]],
        version: dict[str, Any],
        counts: dict[str, int],
    ) -> dict[str, Any]:
        """One asset's version from an old version's files: its `assets.json`,
        the small text kept beside it, and a digest to tell a change."""
        files: list[dict[str, Any]] = []
        blobs: dict[str, str] = {}
        beside: dict[str, bytes] = {}
        for entry in entries:
            source = self.topics.located(topic, item["slug"], number, entry)
            data = source.read_bytes() if source.is_file() else b""
            if entry["kind"] == "project":
                linked: dict[str, Any] = {
                    "kind": "project",
                    "path": entry["path"],
                    "type": entry.get("type") or kind_of(entry["path"], data),
                    "bytes": len(data),
                }
                then = self.at(commit, entry["path"]) if commit else None
                if then is not None and then == data:
                    linked["commit"] = commit
                    counts["links"] += 1
                elif data:
                    linked["sha256"] = self.store.keep(data)
                    counts["media"] += 1
                files.append(linked)
                continue
            kept: dict[str, Any] = {
                key: entry[key]
                for key in ("kind", "name", "type", "from", "when", "recipe", "captions", "poster")
                if key in entry
            }
            kept["bytes"] = len(data)
            if is_media(entry["name"], data):
                kept["sha256"] = self.store.keep(data)
                counts["media"] += 1
            else:
                beside[entry["name"]] = data
            for name in companions(entry).values():
                path = old / name
                if path.is_file():
                    content = path.read_bytes()
                    if is_media(name, content):
                        blobs[name] = self.store.keep(content)
                    else:
                        beside[name] = content
            files.append(kept)
        views = []
        if any(entry["kind"] == "derived" for entry in entries):
            for view in version.get("views", []):
                path = old / view["name"]
                if path.is_file():
                    beside[view["name"]] = path.read_bytes()
                    views.append(
                        {
                            "name": view["name"],
                            "title": view.get("title") or "",
                            "bytes": path.stat().st_size,
                        }
                    )
        assets: dict[str, Any] = {"files": files}
        if len(files) > 1 and has_variants(item):
            assets["variants"] = True
        if views:
            assets["views"] = views
        if blobs:
            assets["blobs"] = blobs
        # What tells one version from the next: the files' content, not the commit
        # a project file was linked at.
        plain = json.loads(json.dumps(assets))
        for entry in plain["files"]:
            entry.pop("commit", None)
        contents = sorted((name, hashlib.sha256(data).hexdigest()) for name, data in beside.items())
        digest = hashlib.sha256(json.dumps([plain, contents], sort_keys=True).encode()).hexdigest()
        return {"assets": assets, "beside": beside, "digest": digest}

    def ties(self) -> None:
        """Which asset items belong to which decision: one a decision's thread
        names ("Screenshots: [ref]"), or whose own thread names the decision it
        illustrates; each asset item to one decision at most."""
        every = {item["ref"]: item for item in self.topics.every()}
        decisions = {
            ref
            for ref, item in every.items()
            if any(e["kind"] == "decision" for v in item["versions"] for e in v["files"])
        }
        self.tied: dict[str, list[dict[str, Any]]] = {}
        self.attached: set[str] = set()

        def tie(asset: str, decision: str) -> None:
            if asset in self.attached or asset in decisions or decision not in decisions:
                return
            if asset == decision or asset not in every:
                return
            self.attached.add(asset)
            self.tied.setdefault(decision, []).append(every[asset])

        for ref in sorted(decisions):
            for entry in every[ref]["thread"]:
                text = entry.get("text") or ""
                if SCREENSHOTS.search(text):
                    for cited in REFERENCE.findall(text):
                        tie(cited, ref)
        for ref, item in sorted(every.items()):
            if ref in decisions:
                continue
            for entry in item["thread"]:
                text = entry.get("text") or ""
                if ILLUSTRATES.search(text):
                    for cited in REFERENCE.findall(text):
                        tie(ref, cited)
                        break

    def link_answers(self, folder: Path, ids: dict[str, str]) -> None:
        """An answer names the message it answers by id, as the store does."""
        for path in sorted((folder / "events").glob("*.json")):
            record = read_json(path)
            moment = record.pop("answers_moment", None)
            if moment is None:
                continue
            if moment in ids:
                record["answers"] = ids[moment]
            write_json(path, record)

    def made_by(self, folder: Path) -> str | None:
        """The commit that made a version's folder in the old layout: every
        folder's read from one `git log` the first time one is asked for."""
        if not hasattr(self, "added"):
            self.added: dict[str, str] = {}
            output = self.project.git(
                "log", "--diff-filter=A", "--name-only", "--format=commit %H", "--",
                ".nock/topics", check=False,
            )  # fmt: skip
            commit = ""
            for line in output.splitlines():
                if line.startswith("commit "):
                    commit = line.removeprefix("commit ")
                elif line.strip():
                    parts = Path(line.strip()).parts
                    # .nock/topics/TOPIC/SLUG/N/…: the oldest commit adding it wins.
                    if len(parts) > 5:
                        self.added["/".join(parts[:5])] = commit
        return self.added.get(folder.relative_to(self.project.root).as_posix())

    def at(self, commit: str, path: str) -> bytes | None:
        """A file as it was at a commit, through one `git cat-file --batch`."""
        if not hasattr(self, "reader"):
            self.reader = subprocess.Popen(
                ["git", "cat-file", "--batch"],
                cwd=self.project.root,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
            )
        assert self.reader.stdin is not None and self.reader.stdout is not None
        self.reader.stdin.write(f"{commit}:{path}\n".encode())
        self.reader.stdin.flush()
        header = self.reader.stdout.readline().decode().split()
        if len(header) < 3 or header[1] != "blob":
            return None
        data = self.reader.stdout.read(int(header[2]))
        self.reader.stdout.read(1)
        return data


# A decision's message naming the asset items that show it, and an asset item's naming its decision.
SCREENSHOTS = re.compile(r"^\s*(screenshots?|assets?|shown in|see)\b", re.IGNORECASE)
ILLUSTRATES = re.compile(r"\billustrates\b", re.IGNORECASE)
REFERENCE = re.compile(r"\[?\b([a-z0-9][a-z0-9-]*/[a-z0-9][a-z0-9-]*)\b\]?")


def moment_stamp(moment: str) -> str:
    """An event file's stamp from a moment, to the second: `20261111T163015`."""
    parsed = parse_moment(moment)
    if parsed is None:
        return "19700101T000000"
    return parsed.astimezone(UTC).strftime("%Y%m%dT%H%M%S")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("root", type=Path, help="the project's main checkout")
    parser.add_argument("--dry-run", action="store_true", help="count, write nothing")
    parser.add_argument(
        "--nock", type=Path, default=Path(__file__).resolve().parents[1] / "src",
        help="where the nock package is (this checkout's src/ by default)",
    )  # fmt: skip
    arguments = parser.parse_args()
    load_nock(arguments.nock)
    project = Project.discover(arguments.root.resolve())
    storing = Storing(project)
    if not storing.pending():
        print(json.dumps({"moved": False, "why": "no .nock/topics/ to move"}))
        return 0
    if arguments.dry_run:
        old = Old(project)
        items = old.every()
        reflections = project.root / ".nock" / "reflections"
        print(json.dumps({
            "topics": len(old.names()),
            "items": len(items),
            "versions": sum(len(item["versions"]) for item in items),
            "rounds": len(list(reflections.glob("*/record.json"))) + len(
                list(reflections.glob("logika/*/record.json"))
            ),
        }))  # fmt: skip
        return 0
    print(json.dumps(storing.run()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
