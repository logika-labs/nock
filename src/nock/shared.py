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
from nock.fold import EVENTS, ITEMS, TOPICS, VERSIONS, Fold, read_events
from nock.git import Git, GitError
from nock.records import (
    ASSETS,
    ASSETS_FILE,
    DECISION,
    DECISION_FILE,
    EVENT_FILE,
    NEXT,
    SMALL_TEXT,
    event_problems,
    shape_problems,
)
from nock.utils import write_json

SHARED = Path(".nock") / "shared"
MEDIA = "media"
MAP = "map.md"
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
    def map(self) -> Path:
        return self.root / MAP

    def topic_folder(self, name: str) -> Path:
        return self.topics / name

    def item_folder(self, topic: str, slug: str) -> Path:
        return self.topics / topic / ITEMS / slug

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
            # A topic before its decisions: a new decision may be in a topic made with it.
            ordered = sorted(groups.values(), key=lambda group: len(group.key.split("/")))
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
            if commit and by.get("role") != "tidier":
                settled.commit, settled.note = self.commit_or_keep(settled.written, by, settled)
        return settled

    def folders_of(self, wanted: set[str]) -> list[str]:
        """The version folders among the paths nock wrote: everything in them
        goes with them."""
        found = set()
        for path in wanted:
            parts = path.split("/")
            if len(parts) > 6 and parts[4] == VERSIONS:
                found.add("/".join(parts[:6]))
            if len(parts) > 8 and parts[4] == ASSETS_DIR and parts[6] == VERSIONS:
                found.add("/".join(parts[:8]))
        return sorted(found)

    def grouped(self, changes: list[tuple[str, str]], removed: list[str]) -> dict[str, Group]:
        groups: dict[str, Group] = {}
        for code, path in changes:
            parts = path.split("/")
            if parts[0] == TOPICS and len(parts) >= 3:
                key = (
                    "/".join(parts[:4])
                    if parts[2] == ITEMS and len(parts) >= 4
                    else "/".join(parts[:2])
                )
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
        if parts[0] in (MAP, SETTINGS) and len(parts) == 1:
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
                f"{where}: not a file nock keeps — topics/<topic>/events/, "
                "topics/<topic>/decisions/<decision>/events/, versions/ or assets/<asset>/,"
                " media/, map.md, settings.toml"
                " (`.nock/nock docs files`)"
            ]
        if not new:
            return [
                f"{where}: events and versions are never changed or removed — write a new event"
                " (a verdict back to open, a state back) or a new version in versions/next/"
            ]
        if parts[2] == EVENTS and len(parts) == 4:
            return []
        if parts[2] == ITEMS and len(parts) >= 6:
            if parts[4] == EVENTS and len(parts) == 6:
                return []
            if parts[4] == VERSIONS and len(parts) >= 7:
                return []
            if parts[4] == ASSETS_DIR and len(parts) >= 8:
                if parts[6] == EVENTS and len(parts) == 8:
                    return []
                if parts[6] == VERSIONS and len(parts) >= 9:
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
        if parts[0] == TOPICS and len(parts) == 4:
            return self.complete_item(group, by, clock, settled)
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
        records: list[tuple[Path, dict[str, Any]]] = []
        for path in self.drafts(folder, group.paths):
            record = self.load(path, group)
            if record is None:
                continue
            if EVENT_FILE.match(path.name):
                group.problems += [
                    f"{self.shown(path)}: {problem}"
                    for problem in event_problems(record, "topic", complete=True)
                ]
                continue
            problems = event_problems(record, "topic", complete=False)
            group.problems += [f"{self.shown(path)}: {problem}" for problem in problems]
            if not problems:
                records.append((path, record))
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
        for path, record in records:
            if record["kind"] == "renamed":
                target = str(record.get("name") or "")
                if not NAME.match(target) or (self.topics / target).exists():
                    group.problems.append(
                        f"{self.shown(path)}: rename to a free topic name, not {target!r}"
                    )
            if record["kind"] == "message":
                self.check_message(record, thread, path, group)
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
        self, record: dict[str, Any], thread: list[dict[str, Any]], path: Path, group: Group
    ) -> None:
        ids = {event["id"] for event in thread}
        for field_name in ("answers", "withdraws"):
            if record.get(field_name) and record[field_name] not in ids:
                group.problems.append(
                    f"{self.shown(path)}: `{field_name}` names no message of this thread"
                )
        if (
            not str(record.get("text") or "").strip()
            and not record.get("attachments")
            and not record.get("withdraws")
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
        if by.get("author") != "agent" or record.get("answers") or record.get("withdraws"):
            return
        shown = [event for event in thread if not event.get("withdraws")]
        withdrawn = {event["withdraws"] for event in thread if event.get("withdraws")}
        shown = [event for event in shown if event["id"] not in withdrawn]
        if shown and (shown[-1].get("by") or {}).get("author") == "owner":
            record["answers"] = shown[-1]["id"]

    def complete_item(
        self, group: Group, by: dict[str, Any], clock: Clock, settled: Settled
    ) -> list[str]:
        """A decision's change: its own drafts and new version, and each of its
        assets' drafts and new versions; checked whole, then completed."""
        _, topic, _, slug = group.key.split("/")
        folder = self.item_folder(topic, slug)
        if not folder.exists():
            return group.paths
        where = f".nock/shared/{group.key}"
        if not NAME.match(slug):
            group.problems.append(
                f"{where}: a decision's name is lowercase letters, digits and `-`"
            )
            return []
        topic_record = self.fold.topic(topic)
        if topic_record is None:
            group.problems.append(
                f"{where}: no topic {topic} — start it with a `created` event in"
                f" topics/{topic}/events/"
            )
            return []
        own = self.part(folder, "decision", group)
        assets = {
            name: self.part(folder / ASSETS_DIR / name, "asset", group)
            for name in sorted(
                {
                    Path(path).parts[5]
                    for path in group.paths
                    if len(Path(path).parts) > 6 and Path(path).parts[4] == ASSETS_DIR
                }
            )
        }
        creating = own.creates
        if own.committed and creating:
            group.problems.append(f"{where}: the decision exists already")
        if not own.committed and not creating:
            group.problems.append(
                f"{where}/events/: a new decision starts with a `created` event"
                " (`.nock/nock docs files.decision`)"
            )
        if creating and not own.next:
            group.problems.append(
                f"{where}: a new decision holds its first version: versions/next/decision.json"
            )
        if creating and topic_record["state"] in CLOSED:
            group.problems.append(
                f"{where}: topic {topic} is {topic_record['state']} — revive it first (a `state`"
                " event setting it active, with a `note` saying why it is back)"
            )
        for name, part in assets.items():
            place = f"{where}/{ASSETS_DIR}/{name}"
            if not NAME.match(name):
                group.problems.append(
                    f"{place}: an asset's name is lowercase letters, digits and `-`"
                )
            if part.committed and part.creates:
                group.problems.append(f"{place}: the asset exists already")
            if not part.committed and not part.creates:
                group.problems.append(
                    f"{place}/events/: a new asset starts with a `created` event"
                    " (`.nock/nock docs files.asset`)"
                )
            if part.creates and not part.next:
                group.problems.append(
                    f"{place}: a new asset holds its first version: versions/next/assets.json"
                )
        thread = [event for event in own.committed if event.get("kind") == "message"]
        for path, record in own.records:
            if record["kind"] == "message":
                self.check_message(record, thread, path, group)
            if record["kind"] == "moved":
                target = str(record.get("to") or "")
                if target == topic or self.fold.topic(target) is None:
                    group.problems.append(
                        f"{self.shown(path)}: `to` names another existing topic, not {target!r}"
                    )
        if group.problems:
            return []
        decision_version = (
            self.complete_version(folder, own.next, group, "decision") if own.next else None
        )
        asset_versions: dict[str, dict[str, Any]] = {}
        for name, part in assets.items():
            if part.next:
                checked = self.complete_version(
                    folder / ASSETS_DIR / name, part.next, group, "asset"
                )
                if checked is not None:
                    asset_versions[name] = checked
        for name, part in assets.items():
            for path, record in part.records:
                if record["kind"] == "preferred":
                    self.check_preferred(
                        record, folder / ASSETS_DIR / name, path, group, asset_versions.get(name)
                    )
        for path, record in own.records:
            if record["kind"] == "verdict" and record["verdict"] == "accepted":
                self.check_accepted(folder, assets, asset_versions, path, group)
        if group.problems:
            return []
        written: list[str] = []
        moved_to = None

        def write(
            place: Path, path: Path | None, record: dict[str, Any], asset: str | None
        ) -> None:
            complete, file_name = self.envelope(record, by, clock, path)
            target = place / EVENTS / file_name
            write_json(target, complete)
            if path is not None:
                path.unlink()
                written.append(self.relative(path))
            if complete["kind"] == "message":
                thread.append(complete)
            settled.events.append(
                {**complete, "topic": topic, "item": slug, **({"asset": asset} if asset else {})}
            )
            written.append(self.relative(target))

        for path, record in own.records:
            if record["kind"] == "created":
                write(folder, path, record, None)
        if decision_version is not None:
            written += self.apply_version(decision_version)
            write(folder, None, {"kind": "version", "version": decision_version["number"]}, None)
        for name, part in assets.items():
            place = folder / ASSETS_DIR / name
            for path, record in part.records:
                if record["kind"] == "created":
                    write(place, path, record, name)
            if name in asset_versions:
                version = asset_versions[name]
                written += self.apply_version(version)
                write(place, None, {"kind": "version", "version": version["number"]}, name)
            for path, record in part.records:
                if record["kind"] != "created":
                    write(place, path, record, name)
        for path, record in own.records:
            if record["kind"] == "created":
                continue
            if record["kind"] == "message":
                self.attachments(record, group)
                self.answering(record, thread, by)
            if record["kind"] == "moved":
                record["from"] = f"{topic}/{slug}"
                moved_to = record["to"]
            write(folder, path, record, None)
        written += [self.relative(self.media / sha) for sha in self.kept(own.records)]
        settled.topics.add(topic)
        if moved_to:
            target_folder = self.item_folder(moved_to, slug)
            moved_slug = slug
            counter = 2
            while target_folder.exists():
                moved_slug = f"{slug}-{counter}"
                target_folder = self.item_folder(moved_to, moved_slug)
                counter += 1
            target_folder.parent.mkdir(parents=True, exist_ok=True)
            folder.rename(target_folder)
            written += [self.relative(folder), self.relative(target_folder)]
            settled.topics.add(moved_to)
        return written

    def part(self, folder: Path, place: str, group: Group) -> Part:
        """A decision's or an asset's share of a change: its committed events,
        its drafts checked, its new version folder."""
        part = Part(committed=read_events(folder / EVENTS))
        paths = [
            path
            for path in group.paths
            if (self.root / path).is_relative_to(folder)
            and not (place == "decision" and (self.root / path).is_relative_to(folder / ASSETS_DIR))
        ]
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
                part.records.append((path, record))
        next_folder = folder / VERSIONS / NEXT
        for path in paths:
            full = self.root / path
            if full.is_relative_to(folder / VERSIONS):
                if full.is_relative_to(next_folder):
                    part.next = next_folder
                else:
                    group.problems.append(
                        f".nock/shared/{path}: a new version goes in versions/next/; nock numbers it"
                    )
        part.creates = any(record["kind"] == "created" for _, record in part.records)
        return part

    def check_preferred(
        self,
        record: dict[str, Any],
        folder: Path,
        path: Path,
        group: Group,
        new: dict[str, Any] | None,
    ) -> None:
        asset = self.fold.asset(folder)
        versions = list((asset or {}).get("versions") or [])
        if new is not None:
            versions.append(
                {"version": new["number"], "files": new["files"], "variants": new["variants"]}
            )
        version = next((v for v in versions if v["version"] == record["version"]), None)
        if version is None or not version.get("variants"):
            group.problems.append(
                f"{self.shown(path)}: version {record['version']} of the asset has no variants to"
                " prefer one of"
            )
            return
        if record.get("name") is None:
            return
        if record["name"] not in [entry_name(entry) for entry in version["files"]]:
            group.problems.append(
                f"{self.shown(path)}: version {record['version']} has no variant {record['name']!r}"
            )

    def check_accepted(
        self,
        folder: Path,
        assets: dict[str, Part],
        new: dict[str, dict[str, Any]],
        path: Path,
        group: Group,
    ) -> None:
        """A decision is accepted only once each asset with variants has one preferred."""
        names = sorted(
            {p.name for p in (folder / ASSETS_DIR).iterdir() if p.is_dir()}
            if (folder / ASSETS_DIR).is_dir()
            else set()
        )
        for name in names:
            asset = self.fold.asset(folder / ASSETS_DIR / name) or {
                "versions": [],
                "preferred": None,
            }
            asset = {**asset, "versions": list(asset["versions"])}
            if name in new:
                version = new[name]
                asset["versions"].append(
                    {
                        "version": version["number"],
                        "files": version["files"],
                        "variants": version["variants"],
                    }
                )
            for _, record in assets[name].records if name in assets else []:
                if record["kind"] == "preferred":
                    asset["preferred"] = {"version": record["version"], "name": record.get("name")}
            if unpreferred(asset):
                group.problems.append(
                    f"{self.shown(path)}: asset {name} has variants — prefer one (a `preferred`"
                    " event in its events/) before accepting the decision"
                )

    def complete_version(
        self, folder: Path, next_folder: Path, group: Group, place: str
    ) -> dict[str, Any] | None:
        """Check a decision's or an asset's versions/next/ (nothing changed
        yet): what making it the next numbered version will write."""
        where = self.shown(next_folder)
        numbers = [
            int(path.name)
            for path in (folder / VERSIONS).iterdir()
            if path.is_dir() and path.name.isdigit()
        ]
        number = max(numbers, default=0) + 1
        found = {
            path.relative_to(next_folder).as_posix()
            for path in next_folder.rglob("*")
            if path.is_file()
        }
        if place == "decision":
            stray = sorted(found - {DECISION_FILE})
            if DECISION_FILE not in found:
                group.problems.append(f"{where}: a decision's version is its decision.json")
                return None
            decision = self.load(next_folder / DECISION_FILE, group)
            if decision is not None:
                group.problems += [
                    f"{where}/{DECISION_FILE}: {problem}"
                    for problem in shape_problems(decision, DECISION)
                ]
            group.problems += [
                f"{where}/{name}: a decision holds no files — they are its assets, each in"
                " assets/<asset>/versions/next/"
                for name in stray
            ]
            if group.problems:
                return None
            return {
                "place": place,
                "folder": folder,
                "next": next_folder,
                "number": number,
                "decision": decision,
                "files": [],
                "variants": False,
            }
        assets_path = next_folder / ASSETS_FILE
        if not assets_path.is_file():
            group.problems.append(f"{where}: an asset's version is its assets.json and its files")
            return None
        assets = self.load(assets_path, group) or {}
        group.problems += [
            f"{where}/{ASSETS_FILE}: {problem}" for problem in shape_problems(assets, ASSETS)
        ]
        if group.problems:
            return None
        if not assets.get("files"):
            group.problems.append(f"{where}/{ASSETS_FILE}: an asset's version holds a file")
            return None
        named = {ASSETS_FILE}
        files, _ = self.collected(assets, next_folder, named, where, group, apply=False)
        views = []
        for view in assets.get("views") or []:
            target = next_folder / view["name"]
            if "/" in view["name"] or not target.is_file() or kind_of(view["name"], b"") != "html":
                group.problems.append(
                    f"{where}: a view is an HTML file beside the version, not {view['name']!r}"
                )
                continue
            named.add(view["name"])
            views.append({**view, "bytes": target.stat().st_size})
        group.problems += [
            f"{where}: {problem}" for problem in asset_rules(files, bool(assets.get("variants")))
        ]
        group.problems += [
            f".nock/shared/{self.relative(next_folder / name)}: a version holds only the files"
            " its assets.json names"
            for name in sorted(found - named)
        ]
        if group.problems:
            return None
        return {
            "place": place,
            "folder": folder,
            "next": next_folder,
            "number": number,
            "assets": assets,
            "views": views,
            "files": files,
            "variants": bool(assets.get("variants")),
            "where": where,
            "group": group,
        }

    def collected(
        self,
        assets: dict[str, Any],
        next_folder: Path,
        named: set[str],
        where: str,
        group: Group,
        apply: bool,
    ) -> tuple[list[dict[str, Any]], dict[str, str]]:
        """A version's files as its record keeps them: first only looked at,
        and only once everything holds, kept (media moved by sha256)."""
        blobs: dict[str, str] = dict(assets.get("blobs") or {})
        files = []
        for given in assets.get("files") or []:
            entry = dict(given)
            if entry["kind"] == "project":
                entry = self.linked(entry, where, group, apply)
            else:
                entry = self.derived(entry, next_folder, blobs, where, group, apply)
                named.add(entry.get("name") or "")
            for role in ("captions", "poster"):
                if entry.get(role):
                    named.add(entry[role])
                    self.companion(next_folder, entry[role], blobs, where, group, apply)
            files.append(entry)
        return files, blobs

    def apply_version(self, version: dict[str, Any]) -> list[str]:
        """Make a checked versions/next/ the next numbered version."""
        next_folder: Path = version["next"]
        written = [self.relative(path) for path in next_folder.rglob("*") if path.is_file()]
        if version["place"] == "decision":
            write_json(
                next_folder / DECISION_FILE,
                {"alternatives": [], "status": "done", **version["decision"]},
            )
        else:
            files, blobs = self.collected(
                version["assets"], next_folder, set(), version["where"], version["group"], True
            )
            record: dict[str, Any] = {"files": files}
            if version["variants"]:
                record["variants"] = True
            if version["views"]:
                record["views"] = version["views"]
            if blobs:
                record["blobs"] = blobs
            write_json(next_folder / ASSETS_FILE, record)
            written += [self.relative(self.media / sha) for sha in blobs.values()]
            written += [
                self.relative(self.media / entry["sha256"])
                for entry in files
                if entry.get("sha256") and (self.media / entry["sha256"]).is_file()
            ]
        target = version["folder"] / VERSIONS / str(version["number"])
        next_folder.rename(target)
        written += [self.relative(path) for path in target.rglob("*") if path.is_file()]
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
        blobs: dict[str, str],
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
        if not name or "/" in name or name in (DECISION_FILE, ASSETS_FILE) or not source.is_file():
            group.problems.append(
                f"{where}: a derived file is named in assets.json and put beside it, not {name!r}"
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
        where = f"{event['topic']}/{event['item']}" if event.get("item") else event.get("topic", "")
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


def entry_name(entry: dict[str, Any]) -> str:
    return entry.get("path") or entry["name"]


def unpreferred(asset: dict[str, Any]) -> bool:
    """An asset whose latest version holds variants, none of them preferred:
    its decision cannot be accepted yet."""
    if not asset["versions"]:
        return False
    latest = asset["versions"][-1]
    files = latest["files"]
    if not latest.get("variants") or len(files) < 2:
        return False
    preferred = asset.get("preferred") or {}
    return not (
        preferred.get("version") == latest["version"]
        and any(entry_name(entry) == preferred.get("name") for entry in files)
    )


def asset_rules(files: list[dict[str, Any]], variants: bool) -> list[str]:
    """An asset's version: one file, or variants of one type, of which the
    owner prefers one."""
    if len(files) > 1 and not variants:
        return [
            "an asset holds one file — several only as variants to prefer one of"
            ' (`"variants": true`); before and after are versions of one asset, and files'
            " shown with a decision are each an asset of it"
        ]
    types = sorted({entry.get("type") or "" for entry in files})
    if variants and len(types) > 1:
        return [f"variants are takes on one asset, of one type — not {' and '.join(types)}"]
    return []


def remove_tree(path: Path) -> None:
    shutil.rmtree(path, ignore_errors=True)
