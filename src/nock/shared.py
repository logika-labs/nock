"""The store: `.nock/shared/`, the collaboration state, committed in the
main checkout whichever worktree writes it. Its root, its media and its
committer are here, behind one interface, so a later team version can make
the directory its own repository without its callers changing.

Every change goes through `settle`: the files written under the root
(an agent's own, nock's, the studio's) are validated against their kinds
(`nock.records`), completed — moments, ids, who wrote them, version numbers,
media by sha256 — and committed on their own, with attribution trailers.
Events are immutable, one per file; a change that edits or removes one, or
that does not fit its kind, is left uncommitted and named as a problem."""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import shutil
import socket
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from nock.fold import ASSETS as ASSETS_DIR
from nock.fold import EVENTS, ITEMS, REVIEW, TOPICS, VERSIONS, Fold, read_events
from nock.git import Git, GitError
from nock.records import (
    ASSET,
    ASSET_FILE_NAME,
    EVENT_FILE,
    NEXT,
    REVIEW_FILE,
    SMALL_TEXT,
    block_problems,
    event_problems,
)
from nock.records import REVIEW as REVIEW_SHAPE
from nock.schema import Validator
from nock.utils import write_json

SHARED = Path(".nock") / "shared"
MEDIA = "media"
# What nock has learned about the project and its owner: short lines by
# subject, each pointing to the files with the detail; reflection keeps it.
MEMORY = "memory.md"
# The memory's size at most, in characters: the orchestrator reads it every time.
MEMORY_LIMIT = 8000
SETTINGS = "settings.toml"
# In `.nock/local/`: the settled changes not committed yet (`Shared.commit_or_keep`).
PENDING = "uncommitted.json"
NAME = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
SHA = re.compile(r"^[0-9a-f]{64}$")
# The git states in which a commit would land in the middle of someone's work.
BUSY_MARKERS = ("MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD", "rebase-merge", "rebase-apply")
# The states in which a topic takes no new items.
CLOSED = ("done", "abandoned")
FILE_KINDS = {
    "image": (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".avif"),
    "video": (".mp4", ".webm", ".mov", ".m4v", ".ogv"),
    "pdf": (".pdf",),
    "html": (".html", ".htm"),
}
TRAILERS = (
    ("Nock-User", "user"),
    ("Nock-On-Behalf", "on_behalf"),
    ("Nock-Session", "session"),
    ("Nock-Parent-Session", "parent"),
    ("Nock-Host", "host"),
)


def kind_of(name: str, content: bytes) -> str:
    """How a file is shown: image, video, pdf, html, text, or binary."""
    suffix = Path(name).suffix.lower()
    for kind, suffixes in FILE_KINDS.items():
        if suffix in suffixes:
            return kind
    try:
        content[:65536].decode()
    except UnicodeDecodeError:
        return "binary"
    return "text"


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def is_media(name: str, data: bytes) -> bool:
    """Media is kept by sha256 in `media/`: anything but small text (an HTML
    view is text, and stays beside its version)."""
    return kind_of(name, data) not in ("text", "html") or len(data) > SMALL_TEXT


def by_for(
    project: Any, author: str = "agent", writer: dict[str, str | None] | None = None
) -> dict[str, Any]:
    """Who writes: the owner (the studio) or an agent, on behalf of an
    interactive session or of an agent; the user, the sessions, the host.
    `writer` (session, parent, role) is the call's own unless given: a hook's
    is its payload's, a sweep's none."""
    given: dict[str, str | None] = project.writer() if writer is None else writer
    swept = writer is not None and not writer
    role = given.get("role") or (None if swept else "interactive")
    interactive = author == "owner" or (role == "interactive" and not given.get("parent"))
    if swept:
        interactive = False
    try:
        user = Git(project.root)("config", "user.email", check=False) or None
    except GitError:
        user = None
    return {
        "author": author,
        "on_behalf": "interactive" if interactive else "agent",
        "user": user,
        "session": given.get("session"),
        "parent": given.get("parent"),
        "role": role,
        "host": socket.gethostname(),
    }


def sweep(project: Any) -> Settled:
    """What a nock command or a hook finds changed under the store and not
    yet committed — written where no hook saw it — validated, completed and
    committed, its writer unknown; what does not hold is left as it is."""
    return Shared(project).settle_changes(lambda: by_for(project, writer={}))


@dataclass
class Settled:
    """What a settle did: the commit (or why there is none), what it wrote,
    and the problems it left uncommitted."""

    commit: str | None = None
    note: str | None = None
    written: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)
    topics: set[str] = field(default_factory=set)
    events: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class Group:
    """The changes of one topic's events, one item, or one other file:
    completed and committed together, or left together."""

    key: str
    paths: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)


@dataclass
class Part:
    """A decision's or an asset's share of one change."""

    committed: list[dict[str, Any]] = field(default_factory=list)
    records: list[tuple[Path, dict[str, Any]]] = field(default_factory=list)
    next: Path | None = None
    creates: bool = False


class Clock:
    """Moments for the events of one settle: now, and strictly later for each
    one after, so their files sort in the order they were written."""

    def __init__(self) -> None:
        self.last = datetime.now(UTC)
        self.first = True

    def next(self) -> datetime:
        current = datetime.now(UTC)
        if self.first:
            self.first = False
            self.last = current
        else:
            self.last = max(current, self.last + timedelta(milliseconds=1))
        return self.last


def stamp_of(moment: datetime) -> str:
    return moment.strftime("%Y%m%dT%H%M%S.") + f"{moment.microsecond // 1000:03d}Z"


def moment_of(moment: datetime) -> str:
    return moment.replace(microsecond=0).isoformat().replace("+00:00", "Z")


class Shared:
    """The store: its root in the main checkout, its media, its committer."""

    def __init__(self, project: Any) -> None:
        self.project = project
        self.root: Path = project.root / SHARED
        self.fold = Fold(self.root)
        # The ids nock's own drafts are to be completed with, by draft file name.
        self.chosen: dict[str, str] = {}

    # --- places ---------------------------------------------------------------------

    @property
    def topics(self) -> Path:
        return self.root / TOPICS

    @property
    def media(self) -> Path:
        return self.root / MEDIA

    @property
    def memory(self) -> Path:
        return self.root / MEMORY

    def topic_folder(self, name: str) -> Path:
        return self.topics / name

    def item_folder(self, topic: str, slug: str) -> Path:
        return self.topics / topic / ITEMS / slug

    def asset_folder(self, topic: str, name: str) -> Path:
        return self.topics / topic / ASSETS_DIR / name

    def review_folder(self, topic: str) -> Path:
        return self.topics / topic / REVIEW

    # --- media ----------------------------------------------------------------------

    def keep(self, data: bytes) -> str:
        """Keep bytes in `media/` by their sha256."""
        sha = digest(data)
        target = self.media / sha
        if not target.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_name(f".{sha}.{os.getpid()}.tmp")
            temporary.write_bytes(data)
            temporary.replace(target)
        return sha

    def blob(self, sha: str) -> Path:
        """Where a media file is (it may be missing: never committed, or ignored)."""
        if not SHA.match(sha):
            raise ValueError(f"not a sha256: {sha!r}")
        return self.media / sha

    # --- drafts ---------------------------------------------------------------------

    def draft(self, folder: Path, record: dict[str, Any], identifier: str | None = None) -> Path:
        """Write an event as an agent would, into `folder/events/`; `settle`
        completes it, with `identifier` as its id when given."""
        path = folder / EVENTS / f"draft-{time.time_ns()}-{secrets.token_hex(3)}.json"
        write_json(path, record)
        if identifier is not None:
            self.chosen[path.name] = identifier
        return path

    # --- the write path -------------------------------------------------------------

    def changes(self) -> list[tuple[str, str]]:
        """What changed under the root since the last commit, as (git status
        code, path relative to the root)."""
        if not self.root.is_dir():
            return []
        git = Git(self.project.root)
        try:
            # No optional locks: a status taking the index's lock fails a commit beside it.
            output = git(
                "--no-optional-locks", "status", "--porcelain=v1", "-z", "--untracked-files=all", "--no-renames",
                "--", str(SHARED),
            )  # fmt: skip
        except GitError:
            return []
        found = []
        for chunk in output.split("\0"):
            if len(chunk) < 4:
                continue
            code, path = chunk[:2], chunk[3:]
            relative = Path(path).relative_to(SHARED) if path.startswith(str(SHARED)) else None
            if relative is not None:
                found.append((code, relative.as_posix()))
        return found

    def settle_changes(self, by: Callable[[], dict[str, Any]]) -> Settled:
        """`settle` everything changed under the root, the writer named only
        once there is something to settle: nothing changed, one `git status`."""
        if not self.root.is_dir() or not self.changes():
            return Settled()
        return self.settle(by())

    def settle(
        self,
        by: dict[str, Any],
        only: list[Path] | None = None,
        commit: bool = True,
        removing: list[Path] | None = None,
    ) -> Settled:
        """Validate, complete and commit what changed under the root (or only
        the files `only` names, which nock itself just wrote): each group
        that holds no problem is completed and committed; the others are left
        as they are, their problems returned. `removing` names whole folders
        nock itself deletes."""
        settled = Settled()
        with self.project.lock("shared"):
            waiting = self.commit_pending()
            wanted = {
                path.resolve().relative_to(self.root.resolve()).as_posix() for path in only or []
            }
            removed = [
                path.resolve().relative_to(self.root.resolve()).as_posix()
                for path in removing or []
            ]
            changes = [
                (code, path)
                for code, path in self.changes()
                if not any(path == place or path.startswith(f"{place}/") for place in waiting)
            ]
            changes = [
                (code, path)
                for code, path in changes
                if only is None
                or path in wanted
                or any(path == folder or path.startswith(f"{folder}/") for folder in removed)
                or any(path.startswith(f"{folder}/") for folder in self.folders_of(wanted))
                or any(path.startswith(f"{folder}/") for folder in wanted)
            ]
            if not changes:
                return settled
            groups = self.grouped(changes, removed)
            clock = Clock()
            touched: list[str] = []
            # A topic first, then its items and assets, then the review that shows them.
            ordered = sorted(groups.values(), key=lambda group: depth(group.key))
            for group in ordered:
                if group.problems:
                    settled.problems += group.problems
                    continue
                written = self.complete(group, by, clock, settled)
                if group.problems:
                    settled.problems += group.problems
                    continue
                touched += written
            if not touched:
                return settled
            settled.written = sorted(set(touched))
            if commit:
                settled.commit, settled.note = self.commit_or_keep(settled.written, by, settled)
        return settled

    def folders_of(self, wanted: set[str]) -> list[str]:
        """The version folders among the paths nock wrote: everything in them
        goes with them."""
        found = set()
        for path in wanted:
            parts = path.split("/")
            if len(parts) > 6 and parts[2] in (ITEMS, ASSETS_DIR) and parts[4] == VERSIONS:
                found.add("/".join(parts[:6]))
            if len(parts) > 5 and parts[2] == REVIEW and parts[3] == VERSIONS:
                found.add("/".join(parts[:5]))
        return sorted(found)

    def grouped(self, changes: list[tuple[str, str]], removed: list[str]) -> dict[str, Group]:
        groups: dict[str, Group] = {}
        for code, path in changes:
            parts = path.split("/")
            if parts[0] == TOPICS and len(parts) >= 3:
                if parts[2] in (ITEMS, ASSETS_DIR) and len(parts) >= 4:
                    key = "/".join(parts[:4])
                elif parts[2] == REVIEW:
                    key = "/".join(parts[:3])
                else:
                    key = "/".join(parts[:2])
            else:
                key = path
            group = groups.setdefault(key, Group(key))
            group.paths.append(path)
            if any(path == folder or path.startswith(f"{folder}/") for folder in removed):
                if code.strip() != "D":
                    group.problems.append(f"{path}: changed while its folder is removed")
                continue
            group.problems += self.change_problems(code, parts, path)
        return groups

    def change_problems(self, code: str, parts: list[str], path: str) -> list[str]:
        """What is wrong with one changed file, by where it is."""
        new = code == "??" or code.strip() == "A"
        where = f".nock/shared/{path}"
        if parts[0] in (MEMORY, SETTINGS) and len(parts) == 1:
            return []
        if parts[0] == MEDIA and len(parts) == 2:
            if code.strip() == "D":
                return []
            if not new or not SHA.match(parts[1]):
                return [f"{where}: media is named by its sha256 and never changed"]
            return []
        if parts[0] == "rounds":
            return []
        if parts[0] != TOPICS or len(parts) < 4:
            return [
                f"{where}: not a file nock keeps — topics/<topic>/events/,"
                " topics/<topic>/items/<item>/events/, topics/<topic>/assets/<asset>/,"
                " topics/<topic>/review/versions/next/, media/, memory.md,"
                " settings.toml (`.nock/nock docs files`)"
            ]
        if not new:
            return [
                f"{where}: events and versions are never changed or removed — write a new event"
                " (a state back, a note replaced) or a new version in versions/next/"
            ]
        if parts[2] == EVENTS and len(parts) == 4:
            return []
        if parts[2] == ITEMS and len(parts) == 6 and parts[4] == EVENTS:
            return []
        if parts[2] == ASSETS_DIR and len(parts) >= 6:
            if parts[4] == EVENTS and len(parts) == 6:
                return []
            if parts[4] == VERSIONS and len(parts) >= 7:
                return []
        if parts[2] == REVIEW and parts[3] == VERSIONS and len(parts) >= 6:
            return []
        return [f"{where}: not where an event or a version goes (`.nock/nock docs files`)"]

    # --- completing -----------------------------------------------------------------

    def complete(
        self, group: Group, by: dict[str, Any], clock: Clock, settled: Settled
    ) -> list[str]:
        """Complete one group's drafts and versions in place: what it wrote,
        removed or moved, as paths under the root; its problems on the group."""
        parts = group.key.split("/")
        if parts[0] == TOPICS and len(parts) == 2:
            return self.complete_topic(group, by, clock, settled)
        if parts[0] == TOPICS and len(parts) == 4 and parts[2] == ITEMS:
            return self.complete_item(group, by, clock, settled)
        if parts[0] == TOPICS and len(parts) == 4 and parts[2] == ASSETS_DIR:
            return self.complete_asset(group, by, clock, settled)
        if parts[0] == TOPICS and len(parts) == 3 and parts[2] == REVIEW:
            return self.complete_review(group, by, clock, settled)
        return group.paths

    def drafts(self, folder: Path, paths: list[str]) -> list[Path]:
        """The drafts among a group's new event files, in the order they were written."""
        found = []
        for path in paths:
            full = self.root / path
            if full.parent == folder / EVENTS and full.is_file() and full.suffix == ".json":
                found.append(full)
        return sorted(
            found,
            key=lambda path: (
                path.name
                if path.name.startswith("draft-")
                else f"~{path.stat().st_mtime_ns:020d}{path.name}"
            ),
        )

    def load(self, path: Path, group: Group) -> dict[str, Any] | None:
        try:
            record = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError) as error:
            group.problems.append(f"{self.shown(path)}: not readable JSON ({error})")
            return None
        return record

    def shown(self, path: Path) -> str:
        try:
            return path.relative_to(self.project.root).as_posix()
        except ValueError:
            return str(path)

    def envelope(
        self, record: dict[str, Any], by: dict[str, Any], clock: Clock, path: Path | None = None
    ) -> tuple[dict[str, Any], str]:
        moment = clock.next()
        chosen = self.chosen.pop(path.name, None) if path is not None else None
        identifier = chosen or secrets.token_hex(4)
        complete = {
            "kind": record["kind"],
            "moment": moment_of(moment),
            "id": identifier,
            "by": {key: value for key, value in by.items() if value is not None},
            **{key: value for key, value in record.items() if key != "kind"},
        }
        return complete, f"{stamp_of(moment)}-{identifier}.json"

    def records_of(
        self, folder: Path, place: str, paths: list[str], group: Group
    ) -> list[tuple[Path, dict[str, Any]]]:
        """A folder's new drafts, each checked against its kind."""
        records: list[tuple[Path, dict[str, Any]]] = []
        for path in self.drafts(folder, paths):
            record = self.load(path, group)
            if record is None:
                continue
            if EVENT_FILE.match(path.name):
                group.problems += [
                    f"{self.shown(path)}: {problem}"
                    for problem in event_problems(record, place, complete=True)
                ]
                continue
            problems = event_problems(record, place, complete=False)
            group.problems += [f"{self.shown(path)}: {problem}" for problem in problems]
            if record.get("kind") == "version":
                group.problems.append(
                    f"{self.shown(path)}: a version is a folder, versions/next/, not an event"
                )
            elif not problems:
                records.append((path, record))
        return records

    def complete_topic(
        self, group: Group, by: dict[str, Any], clock: Clock, settled: Settled
    ) -> list[str]:
        name = group.key.split("/")[1]
        folder = self.topics / name
        if folder.name != name or not NAME.match(name):
            group.problems.append(
                f".nock/shared/topics/{name}: a topic's name is lowercase letters, digits and `-`"
            )
            return []
        if not folder.is_dir():
            return group.paths
        committed = read_events(folder / EVENTS)
        thread = [event for event in committed if event.get("kind") == "message"]
        records = self.records_of(folder, "topic", group.paths, group)
        has_created = any(event.get("kind") == "created" for event in committed) or any(
            record["kind"] == "created" for _, record in records
        )
        if not has_created:
            group.problems.append(
                f".nock/shared/topics/{name}/events/: a new topic starts with a `created` event"
                " (`.nock/nock docs files.topic`)"
            )
        if committed and any(record["kind"] == "created" for _, record in records):
            group.problems.append(f".nock/shared/topics/{name}: the topic exists already")
        notes = {event["id"] for event in committed if event.get("kind") == "note"}
        reviews = {
            int(path.name)
            for path in (self.review_folder(name) / VERSIONS).glob("*")
            if path.name.isdigit()
        }
        for path, record in records:
            kind = record["kind"]
            if kind == "renamed":
                target = str(record.get("name") or "")
                if not NAME.match(target) or (self.topics / target).exists():
                    group.problems.append(
                        f"{self.shown(path)}: rename to a free topic name, not {target!r}"
                    )
            elif kind == "message":
                self.check_message(record, thread, notes, path, group)
            elif kind == "note":
                on = record["on"]
                if not any(on.get(key) for key in ("item", "asset", "block", "memory")):
                    group.problems.append(
                        f"{self.shown(path)}: a note is on an item, an asset or a block of the"
                        " review: `on` names one"
                    )
                if record.get("replaces") and record["replaces"] not in notes:
                    group.problems.append(f"{self.shown(path)}: `replaces` names no note here")
            elif kind == "reviewed" and record["version"] not in reviews:
                group.problems.append(
                    f"{self.shown(path)}: the review has no version {record['version']}"
                )
            if kind == "note":
                notes.add(self.chosen.get(path.name) or path.name)
        if group.problems:
            return []
        written = [
            path for path in group.paths if not (self.root / path).is_relative_to(folder / EVENTS)
        ]
        renamed_to = None
        for path, record in records:
            if record["kind"] == "message":
                self.attachments(record, group)
                self.answering(record, thread, by)
            if record["kind"] == "renamed":
                record["from"] = name
                renamed_to = record["name"]
            complete, file_name = self.envelope(record, by, clock, path)
            target = folder / EVENTS / file_name
            write_json(target, complete)
            path.unlink()
            if complete["kind"] == "message":
                thread.append(complete)
            settled.events.append({**complete, "topic": name})
            written += [self.relative(target), self.relative(path)]
        written += [self.relative(self.media / sha) for sha in self.kept(records)]
        settled.topics.add(name)
        if renamed_to:
            (self.topics / name).rename(self.topics / renamed_to)
            written += [f"{TOPICS}/{name}", f"{TOPICS}/{renamed_to}"]
            settled.topics.add(renamed_to)
        return written

    def kept(self, records: list[tuple[Path, dict[str, Any]]]) -> list[str]:
        return [
            file["sha256"]
            for _, record in records
            for file in record.get("attachments") or []
            if file.get("sha256")
        ]

    def relative(self, path: Path) -> str:
        return path.relative_to(self.root).as_posix()

    def check_message(
        self,
        record: dict[str, Any],
        thread: list[dict[str, Any]],
        notes: set[str],
        path: Path,
        group: Group,
    ) -> None:
        ids = {event["id"] for event in thread}
        if record.get("answers") and record["answers"] not in ids:
            group.problems.append(f"{self.shown(path)}: `answers` names no message of this chat")
        for identifier in record.get("notes") or []:
            if identifier not in notes:
                group.problems.append(f"{self.shown(path)}: no note {identifier} in this topic")
        topic = path.parent.parent.name
        for place, block in enumerate(record.get("blocks") or [], start=1):
            label = f"{self.shown(path)}, block {place}"
            group.problems += [f"{label}: {problem}" for problem in block_problems(block)]
            if not isinstance(block, dict):
                continue
            if block.get("kind") == "html":
                group.problems.append(f"{label}: a message shows no html block; the review does")
            if block.get("kind") == "item" and block.get("item") not in self.fold.slugs(topic):
                group.problems.append(f"{label}: no item {block.get('item')!r} in topic {topic}")
            if "asset" in block and block["asset"] not in self.fold.slugs(topic, ASSETS_DIR):
                group.problems.append(f"{label}: no asset {block['asset']!r} in topic {topic}")
        empty = not str(record.get("text") or "").strip()
        if (
            empty
            and not record.get("attachments")
            and not record.get("notes")
            and not record.get("now")
        ):
            group.problems.append(f"{self.shown(path)}: the message is empty")
        for file in record.get("attachments") or []:
            if "path" in file:
                source = Path(file["path"]).expanduser()
                if not source.is_absolute():
                    source = self.project.here / source
                if not source.is_file():
                    group.problems.append(f"{self.shown(path)}: no file {file['path']} to attach")
            elif not file.get("sha256") or not self.blob(file["sha256"]).is_file():
                group.problems.append(
                    f"{self.shown(path)}: an attachment gives `path` (a file to attach) or the"
                    " `sha256` of a file in media/"
                )

    def attachments(self, record: dict[str, Any], group: Group) -> None:
        """Each attached file kept in media/ by sha256."""
        files = []
        for file in record.get("attachments") or []:
            if "path" in file:
                source = Path(file["path"]).expanduser()
                if not source.is_absolute():
                    source = self.project.here / source
                data = source.read_bytes()
                name = file.get("name") or source.name
                files.append(
                    {
                        "name": name,
                        "type": kind_of(name, data),
                        "bytes": len(data),
                        "sha256": self.keep(data),
                    }
                )
            else:
                files.append(dict(file))
        if files:
            record["attachments"] = files

    def answering(
        self, record: dict[str, Any], thread: list[dict[str, Any]], by: dict[str, Any]
    ) -> None:
        """An agent's message after the owner's waiting one answers it."""
        if by.get("author") != "agent" or record.get("answers"):
            return
        if thread and (thread[-1].get("by") or {}).get("author") == "owner":
            record["answers"] = thread[-1]["id"]

    def open_topic(self, topic: str, where: str, group: Group, creating: bool) -> bool:
        """Whether a part's topic exists (and, for something new, is not closed)."""
        record = self.fold.topic(topic)
        if record is None:
            group.problems.append(
                f"{where}: no topic {topic} — start it with a `created` event in"
                f" topics/{topic}/events/"
            )
            return False
        if creating and record["state"] in CLOSED:
            group.problems.append(
                f"{where}: topic {topic} is {record['state']} — revive it first (a `state`"
                " event setting it active, with a `note` saying why it is back)"
            )
            return False
        return True

    def write_events(
        self,
        place: Path,
        records: list[tuple[Path | None, dict[str, Any]]],
        by: dict[str, Any],
        clock: Clock,
        settled: Settled,
        context: dict[str, Any],
    ) -> list[str]:
        written: list[str] = []
        for path, record in records:
            complete, file_name = self.envelope(record, by, clock, path)
            target = place / EVENTS / file_name
            write_json(target, complete)
            if path is not None:
                path.unlink()
                written.append(self.relative(path))
            settled.events.append({**complete, **context})
            written.append(self.relative(target))
        return written

    def complete_item(
        self, group: Group, by: dict[str, Any], clock: Clock, settled: Settled
    ) -> list[str]:
        """A decision's or a proposal's events, checked whole, then completed."""
        _, topic, _, slug = group.key.split("/")
        folder = self.item_folder(topic, slug)
        if not folder.exists():
            return group.paths
        where = f".nock/shared/{group.key}"
        if not NAME.match(slug):
            group.problems.append(f"{where}: an item's name is lowercase letters, digits and `-`")
            return []
        committed = read_events(folder / EVENTS)
        records = self.records_of(folder, "item", group.paths, group)
        creating = any(record["kind"] == "created" for _, record in records)
        if not self.open_topic(topic, where, group, creating):
            return []
        if committed and creating:
            group.problems.append(f"{where}: the item exists already")
        if not committed and not creating:
            group.problems.append(
                f"{where}/events/: a new item starts with a `created` event"
                " (`.nock/nock docs files.item`)"
            )
        events = [*committed, *(record for _, record in records)]
        created = next((event for event in events if event.get("kind") == "created"), {})
        proposal = created.get("type") == "proposal"
        verdict: str | None = None
        done = False
        for event in committed:
            if event.get("kind") == "verdict":
                verdict = event["verdict"]
            if event.get("kind") == "implemented":
                done = True
        for path, record in records:
            kind = record["kind"]
            if kind == "verdict":
                if not proposal:
                    group.problems.append(
                        f"{self.shown(path)}: only a proposal takes a verdict; a decision is done"
                    )
                elif done:
                    group.problems.append(
                        f"{self.shown(path)}: the proposal is carried out already"
                    )
                verdict = record["verdict"]
            if kind == "implemented":
                if not proposal or verdict != "accepted":
                    group.problems.append(
                        f"{self.shown(path)}: only a proposal the owner accepted is implemented"
                    )
                done = True
        if group.problems:
            return []
        written = self.write_events(
            folder, list(records), by, clock, settled, {"topic": topic, "item": slug}
        )
        settled.topics.add(topic)
        return written

    def complete_asset(
        self, group: Group, by: dict[str, Any], clock: Clock, settled: Settled
    ) -> list[str]:
        """An asset's events and its new version, checked whole, then completed."""
        _, topic, _, name = group.key.split("/")
        folder = self.asset_folder(topic, name)
        if not folder.exists():
            return group.paths
        where = f".nock/shared/{group.key}"
        if not NAME.match(name):
            group.problems.append(f"{where}: an asset's name is lowercase letters, digits and `-`")
            return []
        committed = read_events(folder / EVENTS)
        records = self.records_of(folder, "asset", group.paths, group)
        creating = any(record["kind"] == "created" for _, record in records)
        if not self.open_topic(topic, where, group, creating):
            return []
        next_folder = self.next_of(folder, group)
        if committed and creating:
            group.problems.append(f"{where}: the asset exists already")
        if not committed and not creating:
            group.problems.append(
                f"{where}/events/: a new asset starts with a `created` event"
                " (`.nock/nock docs files.asset`)"
            )
        if creating and next_folder is None:
            group.problems.append(
                f"{where}: a new asset holds its first version: versions/next/asset.json"
            )
        version = self.checked_asset(folder, next_folder, group) if next_folder else None
        if group.problems:
            return []
        context = {"topic": topic, "asset": name}
        written = self.write_events(
            folder,
            [(path, record) for path, record in records if record["kind"] == "created"],
            by,
            clock,
            settled,
            context,
        )
        if version is not None:
            written += self.apply_asset(version)
            written += self.write_events(
                folder,
                [(None, {"kind": "version", "version": version["number"]})],
                by,
                clock,
                settled,
                context,
            )
        written += self.write_events(
            folder,
            [(path, record) for path, record in records if record["kind"] != "created"],
            by,
            clock,
            settled,
            context,
        )
        settled.topics.add(topic)
        return written

    def next_of(self, folder: Path, group: Group) -> Path | None:
        """The folder's versions/next/, when the change holds one; any other
        new version folder is a problem."""
        found = None
        for path in group.paths:
            full = self.root / path
            if full.is_relative_to(folder / VERSIONS):
                if full.is_relative_to(folder / VERSIONS / NEXT):
                    found = folder / VERSIONS / NEXT
                else:
                    group.problems.append(
                        f".nock/shared/{path}: a new version goes in versions/next/; nock numbers it"
                    )
        return found

    def number(self, folder: Path) -> int:
        numbers = [
            int(path.name)
            for path in (folder / VERSIONS).iterdir()
            if path.is_dir() and path.name.isdigit()
        ]
        return max(numbers, default=0) + 1

    def checked_asset(self, folder: Path, next_folder: Path, group: Group) -> dict[str, Any] | None:
        """Check an asset's versions/next/ (nothing changed yet): what making
        it the next numbered version will write."""
        where = self.shown(next_folder)
        found = {
            path.relative_to(next_folder).as_posix()
            for path in next_folder.rglob("*")
            if path.is_file()
        }
        record_path = next_folder / ASSET_FILE_NAME
        if not record_path.is_file():
            group.problems.append(f"{where}: an asset's version is its asset.json and its file")
            return None
        record = self.load(record_path, group) or {}
        group.problems += [
            f"{where}/{ASSET_FILE_NAME}: {problem}"
            for problem in Validator().problems(record, ASSET)
        ]
        if group.problems:
            return None
        named = {ASSET_FILE_NAME}
        entry, _ = self.collected(record, next_folder, named, where, group, apply=False)
        group.problems += [
            f".nock/shared/{self.relative(next_folder / name)}: a version holds only the file"
            " its asset.json names (and a video's captions and poster)"
            for name in sorted(found - named)
        ]
        if group.problems:
            return None
        return {
            "folder": folder,
            "next": next_folder,
            "number": self.number(folder),
            "record": record,
            "file": entry,
            "where": where,
            "group": group,
        }

    def collected(
        self,
        record: dict[str, Any],
        next_folder: Path,
        named: set[str],
        where: str,
        group: Group,
        apply: bool,
    ) -> tuple[dict[str, Any], dict[str, str]]:
        """A version's file as its record keeps it: first only looked at, and
        only once everything holds, kept (media moved by sha256)."""
        blobs: dict[str, str] = dict(record.get("blobs") or {})
        entry = dict(record["file"])
        if entry["kind"] == "project":
            entry = self.linked(entry, where, group, apply)
        else:
            entry = self.derived(entry, next_folder, where, group, apply)
            named.add(entry.get("name") or "")
        for role in ("captions", "poster"):
            if entry.get(role):
                named.add(entry[role])
                self.companion(next_folder, entry[role], blobs, where, group, apply)
        return entry, blobs

    def apply_asset(self, version: dict[str, Any]) -> list[str]:
        """Make a checked versions/next/ the next numbered version."""
        next_folder: Path = version["next"]
        written = [self.relative(path) for path in next_folder.rglob("*") if path.is_file()]
        entry, blobs = self.collected(
            version["record"], next_folder, set(), version["where"], version["group"], True
        )
        record: dict[str, Any] = {"file": entry}
        if blobs:
            record["blobs"] = blobs
        write_json(next_folder / ASSET_FILE_NAME, record)
        written += [self.relative(self.media / sha) for sha in blobs.values()]
        if entry.get("sha256") and (self.media / entry["sha256"]).is_file():
            written.append(self.relative(self.media / entry["sha256"]))
        target = version["folder"] / VERSIONS / str(version["number"])
        next_folder.rename(target)
        written += [self.relative(path) for path in target.rglob("*") if path.is_file()]
        return written

    def complete_review(
        self, group: Group, by: dict[str, Any], clock: Clock, settled: Settled
    ) -> list[str]:
        """A new version of a topic's review: its blocks checked against the
        topic's items and assets, its HTML blocks' files beside it."""
        topic = group.key.split("/")[1]
        folder = self.review_folder(topic)
        where = f".nock/shared/{group.key}"
        if not self.open_topic(topic, where, group, creating=False):
            return []
        next_folder = self.next_of(folder, group)
        if next_folder is None:
            group.problems.append(f"{where}: a review is written in versions/next/review.json")
            return []
        shown = self.shown(next_folder)
        found = {
            path.relative_to(next_folder).as_posix()
            for path in next_folder.rglob("*")
            if path.is_file()
        }
        if REVIEW_FILE not in found:
            group.problems.append(f"{shown}: a review's version is its review.json")
            return []
        review = self.load(next_folder / REVIEW_FILE, group)
        if review is None:
            return []
        group.problems += [
            f"{shown}/{REVIEW_FILE}: {problem}"
            for problem in Validator().problems(review, REVIEW_SHAPE)
        ]
        if group.problems:
            return []
        items = set(self.fold.slugs(topic))
        assets = {
            name: len((self.fold.asset(topic, name) or {}).get("versions") or [])
            for name in self.fold.slugs(topic, ASSETS_DIR)
        }
        named = {REVIEW_FILE}
        ids: set[str] = set()
        for place, block in enumerate(review["blocks"], start=1):
            label = f"{shown}/{REVIEW_FILE}, block {place}"
            problems = block_problems(block)
            group.problems += [f"{label}: {problem}" for problem in problems]
            if problems:
                continue
            identifier = block.get("id") or f"b{place}"
            if identifier in ids:
                group.problems.append(f"{label}: another block has the id {identifier!r}")
            ids.add(identifier)
            kind = block["kind"]
            if kind == "item" and block["item"] not in items:
                group.problems.append(
                    f"{label}: no item {block['item']!r} in topic {topic} (its items/)"
                )
            if "asset" in block:
                count = assets.get(block["asset"])
                if count is None:
                    group.problems.append(
                        f"{label}: no asset {block['asset']!r} in topic {topic} (its assets/)"
                    )
                    continue
                for key in ("version", "from", "to"):
                    if block.get(key) and block[key] > count:
                        group.problems.append(
                            f"{label}: asset {block['asset']} has no version {block[key]}"
                        )
                if kind == "diff" and count < 2 and not block.get("from"):
                    group.problems.append(
                        f"{label}: a diff shows two versions; asset {block['asset']} has {count}"
                    )
            if kind == "html":
                name = block["file"]
                if "/" in name or name not in found or kind_of(name, b"") != "html":
                    group.problems.append(
                        f"{label}: an html block's file is an .html file beside review.json,"
                        f" not {name!r}"
                    )
                named.add(name)
        group.problems += [
            f".nock/shared/{self.relative(next_folder / name)}: a review's version holds only"
            " review.json and its html blocks' files"
            for name in sorted(found - named)
        ]
        if group.problems:
            return []
        number = self.number(folder) if (folder / VERSIONS).is_dir() else 1
        written = [self.relative(path) for path in next_folder.rglob("*") if path.is_file()]
        target = folder / VERSIONS / str(number)
        next_folder.rename(target)
        written += [self.relative(path) for path in target.rglob("*") if path.is_file()]
        written += self.write_events(
            folder,
            [(None, {"kind": "version", "version": number})],
            by,
            clock,
            settled,
            {"topic": topic, "review": True},
        )
        settled.topics.add(topic)
        return written

    def linked(
        self, entry: dict[str, Any], where: str, group: Group, apply: bool = True
    ) -> dict[str, Any]:
        """A project file linked as path@commit, or kept by content when it has
        uncommitted changes."""
        if entry.get("commit") or entry.get("sha256"):
            return entry
        given = str(entry.get("path") or "")
        here = self.project.here.resolve()
        path = Path(given).expanduser()
        path = (path if path.is_absolute() else here / path).resolve()
        if not given or not path.is_relative_to(here) or not path.is_file():
            group.problems.append(
                f"{where}: {given or 'a project file'} is not a file in the repository"
            )
            return entry
        relative = path.relative_to(here).as_posix()
        data = path.read_bytes()
        git = Git(here)
        clean = git.succeeds("ls-files", "--error-unmatch", "--", relative) and not git(
            "status", "--porcelain", "--", relative, check=False
        )
        linked: dict[str, Any] = {
            "kind": "project",
            "path": relative,
            "type": kind_of(relative, data),
            "bytes": len(data),
        }
        if clean:
            linked["commit"] = git("log", "-1", "--format=%H", "--", relative) or git.head()
        else:
            linked["sha256"] = self.keep(data) if apply else digest(data)
        return linked

    def derived(
        self,
        entry: dict[str, Any],
        next_folder: Path,
        where: str,
        group: Group,
        apply: bool = True,
    ) -> dict[str, Any]:
        name = str(entry.get("name") or "")
        source = next_folder / name
        if entry.get("sha256") and not source.is_file():
            if not self.blob(entry["sha256"]).is_file():
                group.problems.append(f"{where}: no media {entry['sha256']} for {name}")
            return entry
        if not name or "/" in name or name == ASSET_FILE_NAME or not source.is_file():
            group.problems.append(
                f"{where}: a derived file is named in asset.json and put beside it, not {name!r}"
            )
            return entry
        data = source.read_bytes()
        kept = {**entry, "type": kind_of(name, data), "bytes": len(data)}
        kept.setdefault("from", [])
        if is_media(name, data):
            if apply:
                kept["sha256"] = self.keep(data)
                source.unlink()
            else:
                kept["sha256"] = digest(data)
        return kept

    def companion(
        self,
        next_folder: Path,
        name: str,
        blobs: dict[str, str],
        where: str,
        group: Group,
        apply: bool = True,
    ) -> None:
        source = next_folder / name
        if name in blobs:
            return
        if "/" in name or not source.is_file():
            group.problems.append(f"{where}: no file {name!r} beside the version")
            return
        data = source.read_bytes()
        if is_media(name, data):
            if apply:
                blobs[name] = self.keep(data)
                source.unlink()
            else:
                blobs[name] = digest(data)

    # --- committing -----------------------------------------------------------------

    @property
    def pending(self) -> Path:
        """What was completed but could not be committed yet, kept on this
        machine: each change's paths, writer and subject."""
        return self.project.local / PENDING

    def commit_or_keep(
        self, paths: list[str], by: dict[str, Any], settled: Settled
    ) -> tuple[str | None, str | None]:
        """Commit a settled change; one that cannot be committed now (the
        main checkout mid-merge, git failing) is kept to be committed, as its
        writer's, by the next settle — its events are written either way."""
        subject = summary(settled)
        try:
            commit, note = self.commit(paths, by, settled, subject=subject)
        except GitError as error:
            commit, note = None, f"not committed yet: {error}"
        if commit is None and note is not None:
            entries = read_pending(self.pending)
            entries.append({"paths": paths, "by": by, "subject": subject})
            write_json(self.pending, entries)
            note += " — the next settle commits it"
        return commit, note

    def commit_pending(self) -> list[str]:
        """Commit each change kept by `commit_or_keep`, as its writer's; the
        paths of those that still cannot be."""
        entries = read_pending(self.pending)
        if not entries:
            return []
        left = []
        for entry in entries:
            try:
                commit, note = self.commit(
                    entry["paths"], entry["by"], Settled(), subject=entry["subject"]
                )
            except GitError:
                commit, note = None, "failed"
            if commit is None and note is not None:
                left.append(entry)
        if left:
            write_json(self.pending, left)
        else:
            self.pending.unlink(missing_ok=True)
        return [path for entry in left for path in entry["paths"]]

    def commit(
        self,
        paths: list[str],
        by: dict[str, Any],
        settled: Settled,
        subject: str | None = None,
        body: str = "",
    ) -> tuple[str | None, str | None]:
        """Commit these paths under the root, alone, in the main checkout, with
        the writer's trailers; unless that would land in the middle of a merge or
        rebase there. Every commit of the store is made under its lock, so
        nock's own never race."""
        with self.project.lock("shared"):
            return self.commit_locked(paths, by, settled, subject, body)

    def commit_locked(
        self,
        paths: list[str],
        by: dict[str, Any],
        settled: Settled,
        subject: str | None,
        body: str,
    ) -> tuple[str | None, str | None]:
        git = Git(self.project.root)
        git_directory = Path(git("rev-parse", "--absolute-git-dir"))
        busy = next((marker for marker in BUSY_MARKERS if (git_directory / marker).exists()), None)
        if busy is not None:
            return None, f"not committed: the main checkout is mid-operation ({busy})"
        tracked = set(git("ls-files", "-z", "--", str(SHARED)).split("\0"))
        specs = sorted(
            spec
            for spec in {str(SHARED / path) for path in paths}
            if (self.project.root / spec).exists()
            or spec in tracked
            or any(name.startswith(f"{spec}/") for name in tracked)
        )
        if not specs:
            return None, None
        git.changing("add", "--all", "--", *specs)
        staged = git("diff", "--cached", "--name-only", "--", *specs)
        if not staged.strip():
            return None, None
        trailers = "\n".join(f"{label}: {by.get(key) or 'unknown'}" for label, key in TRAILERS)
        git.changing(
            "commit", "--quiet", "--no-verify", "--only", "-m", subject or summary(settled),
            *(["-m", body.strip()] if body.strip() else []), "-m", trailers, "--", *specs,
        )  # fmt: skip
        return git.head(), None


def read_pending(path: Path) -> list[dict[str, Any]]:
    try:
        entries = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return []
    return entries if isinstance(entries, list) else []


def summary(settled: Settled) -> str:
    """A commit's subject: what the events were, in a line."""
    said = []
    for event in settled.events:
        where = "/".join(
            str(event[key]) for key in ("topic", "item", "asset") if event.get(key)
        ) + ("/review" if event.get("review") else "")
        kind = event.get("kind", "")
        detail = {
            "verdict": event.get("verdict"),
            "state": event.get("state") or event.get("status"),
            "version": f"version {event.get('version')}" if event.get("version") else None,
        }.get(kind)
        said.append(f"{where} {detail or kind}".strip())
    unique = list(dict.fromkeys(said))
    text = "; ".join(unique[:4]) + (f"; and {len(unique) - 4} more" if len(unique) > 4 else "")
    return f"nock: {text}" if text else "nock: shared files"


def depth(key: str) -> int:
    """The order groups are completed in: a topic, its items and assets, its review."""
    parts = key.split("/")
    if parts[0] != TOPICS:
        return 3
    if len(parts) == 2:
        return 0
    return 2 if len(parts) == 3 else 1


def entry_name(entry: dict[str, Any]) -> str:
    return entry.get("path") or entry["name"]


def remove_tree(path: Path) -> None:
    shutil.rmtree(path, ignore_errors=True)
