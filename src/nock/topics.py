"""Topics and items: what agents put before the owner. A topic is a piece of
work — a name, why it exists, a thread — holding items; an item is bare: a
title, a description under it, and, in each of its versions, one of: a
decision (nock's own JSON: the answer, the alternatives weighed, done or todo,
with the project files it concerns) or one asset — a project file (copied
when the version is made, so versions compare) or a derived file (something
made to show part of the project, with what it comes from, when it applies
and how to make it again). An asset may hold several variants, takes on one
thing of one type, of which the owner prefers one before accepting it, and
views, HTML pages laying out its variants with nock's look. The owner alone gives an item its
verdict (accepted; rejected, to be reworked; dropped, rejected with nothing
to rework, closed; open until then), on the page or with `/nock-triage`;
both sides talk in the threads, a chat: the owner's message waits for the
agent's one answer (`pending`), and is withdrawn until it comes. Everything lives in the main
checkout's `.nock/topics/TOPIC/` (a file over `LARGE` bytes under
`.nock/local/topics/` instead, uncommitted), committed as it is written,
whichever worktree writes it, so the owner sees it at once. The files the
owner attaches to a message are kept beside its thread, in the topic's or the
item's `attachments/MOMENT/`, the message naming each (`attachments`).

A topic's progress is its own: a `state` (planned, active, review, done, abandoned)
and a `status`, a line its agent keeps current as it works; each change is a
status entry in its thread, so the history stays. A done or abandoned topic
takes no new items; when its work comes back it is revived, set active again
with a note that says why, which reads as its description from then on. Every
record keeps who wrote it: the session, its role and, for a subagent or a
session nock dispatched, its parent session."""

from __future__ import annotations

import contextlib
import fnmatch
import hashlib
import json
import re
import shutil
from collections import Counter
from collections.abc import Callable
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Any, NotRequired, TypedDict

from nock.errors import ConflictError, NotFoundError, PolicyError, UsageError
from nock.notify import Notifications, Reason
from nock.render import Problem
from nock.utils import now, read_json, write_json

if TYPE_CHECKING:
    from nock.project import Project

TOPIC_FILE = "topic.json"
ITEM_FILE = "item.json"
# What the prompt and edit hooks look for in every item, in `local/`, each with
# its item file's stamp: they read one file, and an item file only once it changed.
SUMMARIES_FILE = "item-summaries.json"
DECISION_FILE = "decision.json"
PROJECT_FILES = "project"
# The folder beside a thread holding the files its messages carry: no item's slug.
ATTACHMENTS = "attachments"
MAP = "map.md"
GENERAL = "general"
# A thread's note that the item was split out of one holding several files.
SPLIT = "split"
# The git states in which a commit would land in the middle of someone's work.
BUSY_MARKERS = ("MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD", "rebase-merge", "rebase-apply")
# A file larger than this (most videos) is kept on this machine, uncommitted.
LARGE = 20 * 1024 * 1024
NAME = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
# How the map cites an item: `[topic/slug]`.
CITATION = re.compile(r"\[([a-z0-9][a-z0-9-]*/[a-z0-9][a-z0-9-]*)\](?!\()")
# How many rows a list shows before it is cut short (`--full` shows them all).
SHORT = 15
KINDS = {
    "image": (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".avif"),
    "video": (".mp4", ".webm", ".mov", ".m4v", ".ogv"),
    "pdf": (".pdf",),
    "html": (".html", ".htm"),
}


class Verdict(StrEnum):
    OPEN = "open"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    """Rework it as the thread says (a todo: do not do it)."""
    DROPPED = "dropped"
    """Rejected with nothing to rework (superseded, say): closed, nobody is asked to."""


class Status(StrEnum):
    DONE = "done"
    """Decided and carried out."""
    TODO = "todo"
    """Should be done, and is not yet."""


class State(StrEnum):
    """Where a topic's work is."""

    PLANNED = "planned"
    ACTIVE = "active"
    REVIEW = "review"
    """Built: only the owner's verdicts remain. It takes new items like an
    active one (a rework is a new version)."""
    DONE = "done"
    """Finished: it takes no new items until it is revived."""
    ABANDONED = "abandoned"
    """Given up: like done, it takes no new items until it is revived."""


# The states in which a topic takes no new items.
CLOSED = (State.DONE, State.ABANDONED)
# The states in which an agent's work in a topic is finished, as the stop hook counts it.
FINISHED = (State.REVIEW, *CLOSED)
# A thread's entry recording a change of the topic's state or status.
STATUS = "status"
# The studio's Tidy up: its writes are not committed one by one; the studio
# commits them together when it ends, so one revert undoes them.
TIDIER = "tidier"
# The studio's Address my comments: it may make an item's derived files again
# by their recipe (`items remake`), so a recipe in a version it wrote never runs.
ADDRESSER = "addresser"


class Author(StrEnum):
    OWNER = "owner"
    AGENT = "agent"


class Alternative(TypedDict):
    option: str
    why_not: str


class Decision(TypedDict):
    answer: str
    """What is decided and why, in markdown, for someone who knows what the
    system does but not how it is built; for the owner's call, the answer you
    propose and carry on with."""
    alternatives: NotRequired[list[Alternative]]
    """What you seriously weighed instead, and why not; none is a fine answer."""
    status: NotRequired[Status]
    """done (the default) or todo: should be done, and is not yet."""


class Recipe(TypedDict):
    command: NotRequired[str]
    """Run in the working tree by `sh -c`, writing the files again."""
    instruction: NotRequired[str]
    """What an agent does to make it again."""


Derived = TypedDict(
    "Derived",
    {
        "path": NotRequired[str],
        "text": NotRequired[str],
        "name": NotRequired[str],
        "from": NotRequired[list[str]],
        "when": NotRequired[str],
        "recipe": NotRequired[Recipe],
        "captions": NotRequired[str],
        "poster": NotRequired[str],
    },
)
"""A derived file: `path` (a file to copy) or `text` with a `name`; `from`,
the project files it shows; `when`, the condition it shows ("the payment
lapsed"); `recipe`, how to make it again. A video may carry `captions`, a
WebVTT file (by default `NAME.vtt` beside its `path`, when there is one), and
a `poster`, a picture shown before it plays."""


class View(TypedDict):
    """An HTML page laying out an asset's variants: `path` (a file to copy) or
    `text` with a `name` (`sizes.html`), and its `title`. It is shown with
    nock's look (`docs topics.views`) and reaches the version's files by
    their names, as relative addresses (`<img src="favicon-a.svg">`)."""

    path: NotRequired[str]
    text: NotRequired[str]
    name: NotRequired[str]
    title: NotRequired[str]


class Content(TypedDict):
    """What a version holds: a decision (with the project files it concerns),
    or one asset, a project or a derived file; several files only as variants."""

    decision: NotRequired[Decision]
    files: NotRequired[list[str]]
    """Project files, by their path in the repository, copied as they are now:
    one, or with a decision those it concerns."""
    derived: NotRequired[list[Derived]]
    variants: NotRequired[bool]
    """The files are variants: takes on one asset (three versions of one
    picture), of one type, for the owner to prefer one; never unrelated files,
    which are items of their own."""
    views: NotRequired[list[View]]
    """HTML pages laying out the variants (each favicon at several sizes)."""


class ItemDraft(Content):
    title: str
    """What it is, in a few words: "Checkout email", "Favicon"; for a decision,
    what was decided, as a statement. The details go in `description`."""
    description: NotRequired[str]
    """What the title leaves out, in a sentence or two, shown under it."""
    slug: NotRequired[str]
    """Its name in the topic (`topic/slug`); made from the title when left out."""


class ItemChange(Content):
    title: NotRequired[str]
    description: NotRequired[str]
    topic: NotRequired[str]
    """Move it to this existing topic: re-filing, whatever its verdict; its slug
    kept (suffixed if taken there), its old ref kept as an alias."""


class TopicDraft(TypedDict):
    name: str
    """Lowercase words joined by `-`: `checkout-emails`."""
    description: str
    """Why it exists, as part of what work, in a sentence or two."""
    state: NotRequired[State]
    """planned, active (the default): work under way, or review: built,
    only the owner's verdicts remain."""
    status: NotRequired[str]
    """Where the work is, in a line: "benchmarks running, about 2 h"."""


class TopicChange(TypedDict):
    name: NotRequired[str]
    description: NotRequired[str]
    state: NotRequired[State]
    """planned, active, review (built, only the owner's verdicts remain),
    done (finished) or abandoned; a change of state
    without a `status` clears the status."""
    status: NotRequired[str]
    """Where the work is, in a line, kept current at each milestone:
    "waiting for the gate on main"."""
    priority: NotRequired[int]
    """Its place in the owner's order, 1 first; the studio lists topics so,
    those without one after, newest activity first. 0 takes it away."""


class Word(TypedDict):
    """The owner's verdict, with what they say about it."""

    verdict: Verdict
    comment: NotRequired[str]
    rework: NotRequired[bool]
    """With rejected: false drops the item instead — closed, nothing to rework
    (superseded, say), so no agent is asked to; true, the default, asks for rework."""


def verdict_of(word: Word) -> Verdict:
    """The verdict a word gives: rejected without rework is dropped."""
    verdict = Verdict(word["verdict"])
    if verdict is Verdict.OPEN:
        raise UsageError("a verdict is accepted, rejected or dropped")
    if word.get("rework") is False:
        if verdict not in (Verdict.REJECTED, Verdict.DROPPED):
            raise UsageError("`rework` goes with rejected: false drops the item")
        return Verdict.DROPPED
    return verdict


def check_name(name: str, what: str = "topic") -> str:
    name = name.strip()
    if not NAME.match(name):
        raise UsageError(
            f"{name!r} is not a {what} name: lowercase letters, digits and `-`, at most 64 — `checkout-emails`"
        )
    return name


def slugged(title: str) -> str:
    words = re.findall(r"[a-z0-9]+", title.lower())
    text = "-".join(words[:6])[:48].strip("-")
    return text or "item"


def kind_of(name: str, content: bytes) -> str:
    """How the page shows a file: image, video, pdf, html, text, or binary."""
    suffix = Path(name).suffix.lower()
    for kind, suffixes in KINDS.items():
        if suffix in suffixes:
            return kind
    try:
        content[:65536].decode()
    except UnicodeDecodeError:
        return "binary"
    return "text"


def moment(record: dict[str, Any] | None) -> str:
    return (record or {}).get("moment") or ""


def message(
    author: Author, text: str, writer: dict[str, str | None], files: bool = False, **extra: Any
) -> dict[str, Any]:
    """A thread's message; one carrying `files` may say nothing else."""
    if not text.strip() and not files:
        raise UsageError("the message is empty")
    return {
        "author": str(author),
        "moment": now(),
        "text": text.strip(),
        **{key: value for key, value in writer.items() if value},
        **extra,
    }


def state_of(topic: dict[str, Any], items: list[dict[str, Any]] | None = None) -> State:
    """Where a topic's work stands. One from before topics had a state (not
    yet migrated) reads as the migration will set it: done once every item
    in it is decided, otherwise active."""
    if topic.get("state"):
        return State(topic["state"])
    if items and all(item["verdict"] != Verdict.OPEN for item in items):
        return State.DONE
    return State.ACTIVE


def talk(thread: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """A thread's messages, without its status entries: what the owner and
    the agents said to each other."""
    return [entry for entry in thread if entry.get("kind") != STATUS]


class Topics:
    def __init__(self, project: Project) -> None:
        self.project = project

    @property
    def directory(self) -> Path:
        """The main checkout's, whichever worktree writes: the owner looks there."""
        return self.project.root / ".nock" / "topics"

    @property
    def large(self) -> Path:
        return self.project.local / "topics"

    @property
    def map(self) -> Path:
        return self.directory / MAP

    # --- reading ----------------------------------------------------------------

    def names(self) -> list[str]:
        if not self.directory.is_dir():
            return []
        return sorted(path.parent.name for path in self.directory.glob(f"*/{TOPIC_FILE}"))

    def topic(self, name: str) -> dict[str, Any]:
        path = self.directory / name / TOPIC_FILE
        if not NAME.match(name) or not path.is_file():
            close = [other for other in self.names() if name in other or other in name]
            hint = f" — did you mean {', '.join(close[:3])}?" if close else ""
            raise NotFoundError(f"no topic {name!r}{hint} (`.nock/nock topics list`)")
        return read_json(path)

    def items(self, name: str) -> list[dict[str, Any]]:
        """A topic's items, the newest first."""
        found = [read_json(path) for path in (self.directory / name).glob(f"*/{ITEM_FILE}")]
        for item in found:
            item["topic"] = name
            item["ref"] = f"{name}/{item['slug']}"
        return sorted(found, key=lambda item: moment(item["created"]), reverse=True)

    def every(self) -> list[dict[str, Any]]:
        return [item for name in self.names() for item in self.items(name)]

    def summaries(self) -> list[dict[str, Any]] | None:
        """Every item as `every` lists it, in its order, but only what the
        hooks look for in it (`summary`, with `file`, `topic` and `ref`): an
        item file is read again only once it changed (its modification time,
        size and inode). None when an item cannot be summed up, so the caller
        reads them all as before and fails as it would have."""
        path = self.project.local / SUMMARIES_FILE
        try:
            kept = json.loads(path.read_text())
        except (OSError, ValueError):
            kept = {}
        kept = kept if isinstance(kept, dict) else {}
        current: dict[str, Any] = {}
        listed: list[dict[str, Any]] = []
        for name in self.names():
            found = []
            for file in (self.directory / name).glob(f"*/{ITEM_FILE}"):
                status = file.stat()
                stamp = [status.st_mtime_ns, status.st_size, status.st_ino]
                key = str(file.relative_to(self.directory))
                entry = kept.get(key)
                if not isinstance(entry, dict) or entry.get("stamp") != stamp:
                    try:
                        entry = {"stamp": stamp, "summary": summary(read_json(file))}
                    except Exception:
                        return None
                current[key] = entry
                found.append(
                    {
                        **entry["summary"],
                        "file": str(file),
                        "topic": name,
                        "ref": f"{name}/{entry['summary']['slug']}",
                    }
                )
            listed += sorted(found, key=lambda item: item["created"], reverse=True)
        if current != kept:
            with contextlib.suppress(OSError):
                write_json(path, current)
        return listed

    def whole(self, summed: dict[str, Any]) -> dict[str, Any]:
        """The item a summary is of, as `every` lists it."""
        item = read_json(Path(summed["file"]))
        item["topic"] = summed["topic"]
        item["ref"] = summed["ref"]
        return item

    def resolve(self, ref: str) -> tuple[str, str]:
        """A ref's topic and slug: `topic/slug`, or a ref it had before it moved."""
        ref = ref.strip().strip("/")
        topic, _, slug = ref.rpartition("/")
        if topic and (self.directory / topic / slug / ITEM_FILE).is_file():
            return topic, slug
        for item in self.every():
            if ref in item.get("aliases", []):
                return item["topic"], item["slug"]
        if topic:
            self.topic(topic)
        raise NotFoundError(f"no item {ref!r} — `.nock/nock items list {topic}` lists them")

    def item(self, ref: str) -> dict[str, Any]:
        topic, slug = self.resolve(ref)
        item = read_json(self.directory / topic / slug / ITEM_FILE)
        item["topic"] = topic
        item["ref"] = f"{topic}/{slug}"
        return item

    def recipes(self, ref: str) -> list[str]:
        """The commands that make an item's derived files again: the recipes
        of its latest version not written by Address my comments, so what
        `items remake` runs is always a recipe the item's author wrote."""
        item = self.item(ref)
        authored = [version for version in item["versions"] if version.get("role") != ADDRESSER]
        commands: list[str] = []
        for entry in authored[-1]["files"] if authored else []:
            command = (
                (entry.get("recipe") or {}).get("command") if entry["kind"] == "derived" else None
            )
            if command and command not in commands:
                commands.append(command)
        if not commands:
            raise NotFoundError(
                f"{item['ref']} has no recipe command to make it again: follow its recipe's"
                " instruction, if it has one (`.nock/nock items show`)"
            )
        return commands

    def folder(self, topic: str, slug: str, version: int) -> Path:
        return self.directory / topic / slug / str(version)

    def decision(self, item: dict[str, Any], version: dict[str, Any]) -> dict[str, Any] | None:
        if not any(entry["kind"] == "decision" for entry in version["files"]):
            return None
        return read_json(
            self.folder(item["topic"], item["slug"], version["version"]) / DECISION_FILE
        )

    # --- where files are: the one layer that reads and writes them ----------------

    def located(self, topic: str, slug: str, version: int, entry: dict[str, Any]) -> Path:
        """Where a version's file is kept: in its version's folder, or under
        `.nock/local/topics/` when it is large (`"local": true`)."""
        base = self.large if entry.get("local") else self.directory
        return base / topic / slug / str(version) / stored(entry)

    def write_file(
        self, topic: str, slug: str, version: int, entry: dict[str, Any], data: bytes
    ) -> dict[str, Any]:
        """Keep a version's file where `located` finds it: the entry, with its size and place."""
        local = len(data) > LARGE
        kept = {**entry, "bytes": len(data), "local": local}
        target = self.located(topic, slug, version, kept)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return kept

    def file(self, topic: str, slug: str, version: int, name: str) -> Path:
        """Where one of a version's files is: only a file its record names, a
        video's captions or poster, or one of its views."""
        item = self.item(f"{topic}/{slug}")
        record = next((entry for entry in item["versions"] if entry["version"] == version), None)
        listed = record and next(
            (entry for entry in record["files"] if entry_name(entry) == name), None
        )
        if not listed and record:
            beside = any(name in companions(entry).values() for entry in record["files"])
            viewed = any(view["name"] == name for view in record.get("views", []))
            if beside or viewed:
                return self.folder(topic, slug, version) / name
        if not listed:
            raise NotFoundError(f"item {topic}/{slug} has no file {name} in version {version}")
        return self.located(topic, slug, version, listed)

    def shown(self, item: dict[str, Any]) -> dict[str, Any]:
        """An item with each version's decision read, each file's path and its views."""
        versions = []
        for version in item["versions"]:
            number = version["version"]
            folder = self.folder(item["topic"], item["slug"], number)
            files = []
            for entry in version["files"]:
                if entry["kind"] == "decision":
                    continue
                path = self.located(item["topic"], item["slug"], number, entry)
                beside = {
                    f"{role}_where": str(folder / name) for role, name in companions(entry).items()
                }
                files.append({**entry, "name": entry_name(entry), "where": str(path), **beside})
            views = [
                {**view, "where": str(folder / view["name"])} for view in version.get("views", [])
            ]
            versions.append(
                {
                    **version,
                    "decision": self.decision(item, version),
                    "files": files,
                    "views": views,
                }
            )
        thread = self.thread_shown(item["thread"], item["topic"], item["slug"])
        return {**item, "versions": versions, "thread": thread}

    # --- attachments ------------------------------------------------------------

    def beside(self, base: Path, topic: str, slug: str | None) -> Path:
        """A thread's own folder under `base`: its topic's, or its item's."""
        return base / topic / slug if slug else base / topic

    def where(self, entry: dict[str, Any], topic: str, slug: str | None = None) -> Path:
        """Where an attachment is kept: beside its thread, or on this machine when large."""
        base = self.large if entry.get("local") else self.directory
        return self.beside(base, topic, slug) / entry["path"]

    def attached(self, said: dict[str, Any], topic: str, slug: str | None = None) -> list[str]:
        return [str(self.where(entry, topic, slug)) for entry in said.get("attachments", [])]

    def thread_shown(
        self, thread: list[dict[str, Any]], topic: str, slug: str | None = None
    ) -> list[dict[str, Any]]:
        """A thread with each attachment's `where`, its path to read."""
        return [
            {
                **entry,
                "attachments": [
                    {**file, "where": str(self.where(file, topic, slug))}
                    for file in entry["attachments"]
                ],
            }
            if entry.get("attachments")
            else entry
            for entry in thread
        ]

    def attachment(self, topic: str, slug: str | None, path: str) -> Path:
        """Where one of a thread's attachments is: only a file a message names."""
        thread = self.item(f"{topic}/{slug}")["thread"] if slug else self.topic(topic)["thread"]
        for entry in thread:
            for file in entry.get("attachments", []):
                if file["path"] == path:
                    return self.where(file, topic, slug)
        where = f"{topic}/{slug}" if slug else topic
        raise NotFoundError(f"{where} has no attachment {path}")

    def attach(
        self, topic: str, slug: str | None, files: list[Path], stamp: str
    ) -> list[dict[str, Any]]:
        """Keep these files (moved, each under its own name) beside a thread,
        in a folder of their message's own: what the message records of them."""
        if not files:
            return []
        label = stamp.replace("-", "").replace(":", "")
        folder, number = label, 2
        while any(
            (self.beside(base, topic, slug) / ATTACHMENTS / folder).exists()
            for base in (self.directory, self.large)
        ):
            folder, number = f"{label}-{number}", number + 1
        entries, names = [], set()
        for source in files:
            if not source.is_file():
                raise NotFoundError(f"{source}: no such file to attach")
            name = attachment_name(source.name)
            base, suffix, number = Path(name).stem, Path(name).suffix, 2
            while name in names:
                name, number = f"{base}-{number}{suffix}", number + 1
            names.add(name)
            size = source.stat().st_size
            with source.open("rb") as handle:
                kind = kind_of(name, handle.read(65536))
            entry = {
                "name": name,
                "type": kind,
                "bytes": size,
                "path": f"{ATTACHMENTS}/{folder}/{name}",
                "local": size > LARGE,
            }
            target = self.where(entry, topic, slug)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(source, target)
            entries.append(entry)
        return entries

    def unattach(
        self,
        said: dict[str, Any],
        topic: str,
        slug: str | None,
        keep: Callable[[Path, dict[str, Any]], None] | None,
    ) -> None:
        """A withdrawn message's files, handed to `keep` (which may move them
        away) and removed with their folder."""
        for entry in said.get("attachments", []):
            path = self.where(entry, topic, slug)
            if keep is not None and path.is_file():
                keep(path, entry)
            path.unlink(missing_ok=True)
            with contextlib.suppress(OSError):
                path.parent.rmdir()

    def current_description(self, topic: dict[str, Any]) -> str:
        """The latest revival note, once the topic came back; its description before."""
        revivals = [
            entry
            for entry in topic["thread"]
            if entry.get("kind") == "revival" or entry.get("revived")
        ]
        return revivals[-1]["text"] if revivals else topic["description"]

    def activity(self, topic: dict[str, Any], items: list[dict[str, Any]]) -> str:
        moments = [topic["updated"], *(item["updated"] for item in items)]
        return max(moments)

    def counts(self, items: list[dict[str, Any]]) -> dict[str, int]:
        counted = Counter(item["verdict"] for item in items)
        return {verdict: counted.get(verdict, 0) for verdict in map(str, Verdict)}

    def row(self, name: str) -> dict[str, Any]:
        topic = self.topic(name)
        items = self.items(name)
        return {
            "name": name,
            "state": str(state_of(topic, items)),
            **({"status": topic["status"]} if topic.get("status") else {}),
            **({"priority": topic["priority"]} if topic.get("priority") else {}),
            "description": self.current_description(topic),
            **self.counts(items),
            "active": self.activity(topic, items),
        }

    def comments(self) -> list[dict[str, Any]]:
        """The owner's comments waiting for an agent's answer: each thread
        whose last word is theirs and no verdict answered it (`pending`), as
        its ref (a topic's name, an item's `topic/slug`), title (an item's), the
        comment's text and the paths of the files it carries; in the
        owner's order of topics."""
        found = []
        for name in [row["name"] for row in in_order([self.row(name) for name in self.names()])]:
            topic = self.topic(name)
            if pending(topic["thread"]):
                said = talk(topic["thread"])[-1]
                found.append(
                    {
                        "ref": name,
                        "title": "",
                        "text": said["text"],
                        "files": self.attached(said, name),
                    }
                )
            for item in self.items(name):
                if pending(item["thread"], item.get("decided")):
                    said = talk(item["thread"])[-1]
                    found.append(
                        {
                            "ref": item["ref"],
                            "title": item["title"],
                            "text": said["text"],
                            "files": self.attached(said, name, item["slug"]),
                        }
                    )
        return found

    def awaiting(self) -> dict[str, list[str]]:
        """What waits on an agent: the threads where the owner wrote last, and
        the items they rejected, not yet reworked."""
        threads, rejected = [], []
        attached: dict[str, list[str]] = {}
        for name in self.names():
            topic = self.topic(name)
            said = talk(topic["thread"])
            if said and said[-1]["author"] == Author.OWNER:
                threads.append(name)
                if said[-1].get("attachments"):
                    attached[name] = self.attached(said[-1], name)
            for item in self.items(name):
                if item["thread"] and item["thread"][-1]["author"] == Author.OWNER:
                    threads.append(item["ref"])
                    if item["thread"][-1].get("attachments"):
                        attached[item["ref"]] = self.attached(
                            item["thread"][-1], name, item["slug"]
                        )
                if item["verdict"] == Verdict.REJECTED:
                    rejected.append(item["ref"])
        found: dict[str, Any] = {"owner_wrote_last": threads, "rejected": rejected}
        if attached:
            found["attachments"] = attached
        return found

    def summary(self) -> dict[str, Any]:
        """The open items by topic, and what waits on an agent."""
        open_counts = {}
        for name in self.names():
            count = sum(1 for item in self.items(name) if awaits_owner(item))
            if count:
                open_counts[name] = count
        return {
            "open": dict(sorted(open_counts.items(), key=lambda pair: (-pair[1], pair[0]))),
            "awaiting_you": self.awaiting(),
        }

    def item_row(self, item: dict[str, Any]) -> dict[str, Any]:
        latest = item["versions"][-1]
        kinds = sorted({entry["kind"] for entry in latest["files"]})
        return {
            "ref": item["ref"],
            "title": item["title"],
            "verdict": item["verdict"],
            "kinds": kinds,
            **({"description": item["description"]} if item.get("description") else {}),
            **({"variants": len(variants_of(item))} if has_variants(item) else {}),
            **({"preferred": item["preferred"]} if item.get("preferred") else {}),
            "versions": len(item["versions"]),
            "updated": item["updated"],
        }

    # --- searching --------------------------------------------------------------

    def item_text(self, item: dict[str, Any]) -> tuple[str, str]:
        """An item's title, and the rest of what it says, for search."""
        parts = [item.get("description") or "", *(entry["text"] for entry in item["thread"])]
        parts += [file["name"] for entry in item["thread"] for file in entry.get("attachments", [])]
        latest = item["versions"][-1]
        decision = self.decision(item, latest)
        if decision:
            parts.append(decision["answer"])
            parts += [f"{entry['option']} {entry['why_not']}" for entry in decision["alternatives"]]
        for entry in latest["files"]:
            parts += [entry_name(entry), *entry.get("from", []), entry.get("when") or ""]
        parts += item.get("aliases", [])
        return item["title"], " ".join(parts)

    def score(self, words: list[str], heading: str, body: str) -> float:
        """How strongly a heading and a body match the words searched for: by
        how many of the words they hold (each found where a word starts), then
        how often, the heading's three times — so what holds every word always
        comes first, then what holds all but one, and so on down."""
        found = [
            len(occurrences(word, heading)) * 3 + len(occurrences(word, body)) for word in words
        ]
        matched = sum(1 for count in found if count)
        if not matched:
            return 0
        return matched * 1000 + min(sum(found), 999)

    def search_items(self, query: str, topic: str | None = None) -> list[dict[str, Any]]:
        words = query.lower().split()
        found = []
        for name in [topic] if topic else self.names():
            record = self.topic(name)
            context = f"{name} {self.current_description(record)}"
            for item in self.items(name):
                title, body = self.item_text(item)
                points = self.score(words, title, f"{body} {context}")
                if points:
                    found.append((points, item))
        # The best match first; among equals, the newest.
        found.sort(key=lambda pair: pair[1]["updated"], reverse=True)
        found.sort(key=lambda pair: -pair[0])
        return [item for _, item in found]

    def search_topics(self, query: str) -> list[str]:
        words = query.lower().split()
        found = []
        for name in self.names():
            record = self.topic(name)
            heading = name.replace("-", " ")
            body = " ".join(
                [
                    record["description"],
                    record.get("status") or "",
                    *(entry["text"] for entry in record["thread"]),
                    *(" ".join(self.item_text(item)) for item in self.items(name)),
                ]
            )
            points = self.score(words, heading, body)
            if points:
                found.append((points, name))
        found.sort(key=lambda pair: -pair[0])
        return [name for _, name in found]

    # --- topics -----------------------------------------------------------------

    def standing(self, topic: dict[str, Any]) -> State:
        return state_of(topic, None if topic.get("state") else self.items(topic["name"]))

    def recorded(self) -> dict[str, Any]:
        return {"moment": now(), **self.project.writer()}

    def worked(self, topic: str, stamp: dict[str, Any]) -> None:
        """An agent's own work in a topic, as the stop hook counts it: kept
        apart from what migrations rewrite and from the owner's verdicts,
        which carry sessions too but are nobody's work there."""
        if stamp.get("session"):
            self.project.store.insert(
                "wrote",
                {"session": stamp["session"], "parent": stamp.get("parent"), "topic": topic},
            )

    def save_topic(self, topic: dict[str, Any]) -> Path:
        topic["updated"] = now()
        path = self.directory / topic["name"] / TOPIC_FILE
        write_json(path, topic)
        return path

    def create_topic(self, draft: TopicDraft) -> tuple[dict[str, Any], str | None]:
        name = check_name(draft["name"])
        if not draft["description"].strip():
            raise UsageError(
                "`description` is empty: say why the topic exists, as part of what work"
            )
        state = State(draft.get("state") or State.ACTIVE)
        if state in CLOSED:
            raise UsageError(
                "a topic opens planned, active or review: done and abandoned are for finished work"
            )
        with self.project.lock("topics"):
            if (self.directory / name / TOPIC_FILE).is_file():
                again = (
                    f" — it is {self.standing(self.topic(name))}; revive it:"
                    f' `.nock/nock topics update {name} --revive "why it is back"`'
                    if self.standing(self.topic(name)) in CLOSED
                    else ": submit into it"
                )
                raise ConflictError(f"topic {name} exists{again}")
            topic: dict[str, Any] = {
                "name": name,
                "description": draft["description"].strip(),
                "state": str(state),
                "status": "",
                "created": self.recorded(),
                "thread": [],
            }
            if str(draft.get("status") or "").strip():
                self.set_standing(topic, {"status": draft.get("status")}, None)
            path = self.save_topic(topic)
            self.worked(name, topic["created"])
            return topic, self.commit([path], f"Topic {name}: {topic['description'][:80]}")

    def update_topic(
        self,
        name: str,
        change: TopicChange,
        reply: str | None = None,
        revive: str | None = None,
        author: Author = Author.AGENT,
        attachments: list[Path] | None = None,
    ) -> tuple[dict[str, Any], str | None]:
        if not change and reply is None and revive is None:
            raise UsageError(
                "nothing to do: give a change (`state`, `status`, …), `--reply`, or `--revive`"
            )
        with self.project.lock("topics"):
            topic = self.topic(name)
            touched = [self.directory / name]
            said = []
            was = self.standing(topic)
            owner_last = owner_wrote_last(topic["thread"])
            if "description" in change:
                if not change["description"].strip():
                    raise UsageError("`description` is empty")
                topic["description"] = change["description"].strip()
                said.append("updated")
            if "priority" in change:
                priority = int(change["priority"])
                if priority < 0:
                    raise UsageError("`priority` is 1 or more (1 first), or 0 to take it away")
                if priority:
                    topic["priority"] = priority
                else:
                    topic.pop("priority", None)
                said.append(f"priority {priority}" if priority else "no priority")
            standing: dict[str, Any] = {
                key: value for key, value in change.items() if key in ("state", "status")
            }
            if revive is not None:
                if self.standing(topic) not in CLOSED:
                    raise ConflictError(
                        f"topic {name} is {self.standing(topic)}, not done or abandoned: submit into"
                        " it, no need to revive it"
                    )
                if State(standing.get("state") or State.ACTIVE) in CLOSED:
                    raise UsageError("a revived topic is planned or active")
            if standing or revive is not None:
                self.set_standing(topic, standing, revive)
                said.append("revived" if revive is not None else str(self.standing(topic)))
            if reply is not None:
                said_now = said_in(
                    topic["thread"], author, reply, self.writer(), files=bool(attachments)
                )
                if attachments:
                    said_now["attachments"] = self.attach(
                        name, None, attachments, said_now["moment"]
                    )
                topic["thread"].append(said_now)
                said.append("replied")
                if author == Author.AGENT:
                    self.worked(topic["name"], topic["thread"][-1])
            if "name" in change and change["name"] != name:
                renamed = check_name(change["name"])
                if (self.directory / renamed).exists():
                    raise ConflictError(f"topic {renamed} exists")
                (self.directory / name).rename(self.directory / renamed)
                if (self.large / name).is_dir():
                    (self.large / name).rename(self.large / renamed)
                topic["name"] = renamed
                with self.project.store.connection() as connection:
                    connection.execute(
                        "UPDATE wrote SET topic = ? WHERE topic = ?", (renamed, name)
                    )
                touched.append(self.directory / renamed)
                said.append(f"renamed from {name}")
            self.save_topic(topic)
            line = f": {topic['status']}" if standing and topic.get("status") else ""
            commit = self.commit(
                touched, f"Topic {topic['name']}, {', '.join(said or ['updated'])}{line}"
            )
        if author is Author.AGENT:
            if was is not State.REVIEW and self.standing(topic) is State.REVIEW:
                self.owners_turn(topic["name"], Reason.REVIEW)
            elif reply is not None and owner_last:
                self.owners_turn(topic["name"], Reason.ANSWERED)
        return topic, commit

    def writer(self) -> dict[str, str | None]:
        return self.project.writer()

    def owners_turn(self, name: str, reason: Reason) -> None:
        """Tell the owner it is their turn in this topic (`nock.notify`);
        never for Tidy up, which the owner started and watches."""
        if self.project.current_role() == TIDIER:
            return
        # A genuine cycle: the timeline reads the topics.
        from nock.timeline import TURNS, Timeline

        event = Timeline(self.project).latest(name, TURNS[reason])
        Notifications(self.project).tell(name, reason, self.items(name), event=event)

    def set_standing(
        self, topic: dict[str, Any], change: dict[str, Any], revived: str | None
    ) -> None:
        """A new state or status, kept in the topic and recorded as a status
        entry in its thread; a revival sets it active with its note. A change
        of state without a status clears the status."""
        state = State(change.get("state") or (State.ACTIVE if revived else self.standing(topic)))
        if "status" in change:
            status = " ".join(str(change["status"] or "").split())
        elif state is not self.standing(topic):
            status = ""
        else:
            status = topic.get("status") or ""
        note = (revived or "").strip()
        if revived is not None and not note:
            raise UsageError("`--revive` says why the topic is back")
        topic["state"], topic["status"] = str(state), status
        entry = message(Author.AGENT, note or status or str(state), self.writer(), kind=STATUS)
        entry.update({"state": str(state), "status": status})
        if revived is not None:
            entry["revived"] = True
        topic["thread"].append(entry)

    def unstated(self, session: str) -> list[str]:
        """The planned or active topics this session (or a subagent of it)
        did its own work in — opened, or submitted, versioned or answered an
        item there — whose state or status it never set. A migration's
        rewrites and the owner's verdicts are no one's work there."""
        mine = {session}
        worked = {
            row["topic"]
            for row in self.project.store.rows(
                "SELECT DISTINCT topic FROM wrote WHERE session = ? OR parent = ?",
                (session, session),
            )
        }
        found = []
        for name in self.names():
            if name not in worked:
                continue
            topic = self.topic(name)
            if self.standing(topic) in FINISHED:
                continue
            if any(entry.get("kind") == STATUS and by(entry, mine) for entry in topic["thread"]):
                continue
            found.append(name)
        return found

    def delete_topic(self, name: str) -> str | None:
        with self.project.lock("topics"):
            self.topic(name)
            if self.items(name):
                raise ConflictError(f"topic {name} holds items: only an empty topic is deleted")
            shutil.rmtree(self.directory / name)
            shutil.rmtree(self.large / name, ignore_errors=True)
            return self.commit([self.directory / name], f"Topic {name}, deleted")

    # --- items ------------------------------------------------------------------

    def create_item(self, topic: str, draft: ItemDraft) -> tuple[dict[str, Any], str | None]:
        title = draft["title"].strip()
        if not title:
            raise UsageError("`title` is empty")
        with self.project.lock("topics"):
            record = self.topic(topic)
            items = self.items(topic)
            if self.standing(record) in CLOSED:
                raise ConflictError(
                    f"topic {topic} is {self.standing(record)}: if this brings it back, revive it first —"
                    f' `.nock/nock topics update {topic} --revive "why it is back"` — or open another topic'
                )
            slug = check_name(draft["slug"], "slug") if "slug" in draft else slugged(title)
            taken = {item["slug"] for item in items}
            if "slug" in draft and slug in taken:
                raise ConflictError(f"{topic}/{slug} exists: update it, or give another slug")
            if "slug" in draft and slug == ATTACHMENTS:
                raise UsageError(
                    f"{ATTACHMENTS} is the folder of a topic's attachments: give another slug"
                )
            base, number = slug, 2
            while slug in taken or slug.isdigit() or slug == ATTACHMENTS:
                slug, number = f"{base}-{number}", number + 1
            stamp = self.recorded()
            item: dict[str, Any] = {
                "slug": slug,
                "title": title,
                "description": " ".join(str(draft.get("description") or "").split()),
                "aliases": [],
                "verdict": str(Verdict.OPEN),
                "decided": None,
                "created": stamp,
                "updated": stamp["moment"],
                "thread": [],
                "versions": [],
            }
            self.add_version(topic, item, draft, None)
            path = self.save_item(topic, item)
            self.worked(topic, stamp)
            return self.with_ref(topic, item), self.commit(
                [path.parent], f"Item {topic}/{slug}: {title}"
            )

    def with_ref(self, topic: str, item: dict[str, Any]) -> dict[str, Any]:
        return {**item, "topic": topic, "ref": f"{topic}/{item['slug']}"}

    def save_item(self, topic: str, item: dict[str, Any]) -> Path:
        item["updated"] = now()
        path = self.directory / topic / item["slug"] / ITEM_FILE
        write_json(path, {key: value for key, value in item.items() if key not in ("topic", "ref")})
        return path

    def update_item(
        self,
        ref: str,
        change: ItemChange | None,
        version: ItemChange | None = None,
        reply: str | None = None,
        author: Author = Author.AGENT,
        attachments: list[Path] | None = None,
    ) -> tuple[dict[str, Any], str | None]:
        if not change and version is None and reply is None:
            raise UsageError("nothing to do: give a change, `--version`, or `--reply`")
        change = ItemChange(**change) if change else None
        moving = change.pop("topic", None) if change else None
        with self.project.lock("topics"):
            item = self.item(ref)
            said = []
            touched = [self.directory / item["topic"] / item["slug"]]
            rejected = item["verdict"] == Verdict.REJECTED
            owner_last = owner_wrote_last(item["thread"])
            if moving is not None:
                said.append(self.move(item, moving))
            topic = item["topic"]
            if change:
                if item["verdict"] != Verdict.OPEN:
                    raise ConflictError(
                        f"{item['ref']} is {item['verdict']}: it is not changed in place — "
                        f"give the change as a new version, `.nock/nock items update {item['ref']} --version '{{…}}'`"
                    )
                if "title" in change:
                    if not change["title"].strip():
                        raise UsageError("`title` is empty")
                    item["title"] = change["title"].strip()
                if "description" in change:
                    item["description"] = " ".join(str(change["description"] or "").split())
                content = {
                    key: value
                    for key, value in change.items()
                    if key not in ("title", "description")
                }
                if content:
                    latest = item["versions"].pop()
                    self.add_version(topic, item, content, latest)
                said.append("updated")
                self.worked(topic, self.recorded())
            if version is not None:
                if "title" in version:
                    item["title"] = version["title"].strip() or item["title"]
                if "description" in version:
                    item["description"] = " ".join(str(version["description"] or "").split())
                given = {
                    key: value
                    for key, value in version.items()
                    if key not in ("title", "description")
                }
                self.add_version(topic, item, given, item["versions"][-1])
                item["verdict"] = str(Verdict.OPEN)
                item["decided"] = None
                said.append(f"version {item['versions'][-1]['version']}")
                self.worked(topic, item["versions"][-1])
            if reply is not None:
                said_now = said_in(
                    item["thread"],
                    author,
                    reply,
                    self.writer(),
                    item.get("decided"),
                    files=bool(attachments),
                )
                if attachments:
                    said_now["attachments"] = self.attach(
                        topic, item["slug"], attachments, said_now["moment"]
                    )
                item["thread"].append(said_now)
                said.append("answered" if "answers" in said_now else "replied")
                if author == Author.AGENT:
                    self.worked(topic, said_now)
            path = self.save_item(topic, item)
            commit = self.commit(
                [*touched, path.parent, self.large / topic / item["slug"]],
                f"Item {topic}/{item['slug']}, {', '.join(said)}: {item['title']}",
            )
        if author is Author.AGENT:
            if reply is not None and owner_last:
                self.owners_turn(topic, Reason.ANSWERED)
            elif version is not None and rejected:
                self.owners_turn(topic, Reason.REWORKED)
        return self.with_ref(topic, item), commit

    def move(self, item: dict[str, Any], target: str) -> str:
        """Re-file an item in another topic, whatever its verdict: its folders
        (and large files) moved, its slug kept unless taken there, its old ref
        an alias, so citations of it still resolve."""
        source, slug = item["topic"], item["slug"]
        target = target.strip()
        if target == source:
            raise UsageError(f"{item['ref']} is in {target} already")
        self.topic(target)
        taken = {other["slug"] for other in self.items(target)}
        moved, number = slug, 2
        while moved in taken or moved == ATTACHMENTS:
            moved, number = f"{slug}-{number}", number + 1
        (self.directory / target).mkdir(parents=True, exist_ok=True)
        (self.directory / source / slug).rename(self.directory / target / moved)
        if (self.large / source / slug).is_dir():
            (self.large / target).mkdir(parents=True, exist_ok=True)
            (self.large / source / slug).rename(self.large / target / moved)
        old, new = item["ref"], f"{target}/{moved}"
        item["aliases"] = [*item.get("aliases", []), old]
        item["slug"], item["topic"], item["ref"] = moved, target, new
        with self.project.store.connection() as connection:
            for table in ("told", "shown_items"):
                connection.execute(f"UPDATE {table} SET item = ? WHERE item = ?", (new, old))
        return f"moved from {old}"

    def add_version(
        self,
        topic: str,
        item: dict[str, Any],
        content: Content | dict[str, Any],
        previous: dict[str, Any] | None,
    ) -> None:
        """Write a version from the content given, what it leaves out carried
        from `previous` (project files copied again as they are now). When
        `previous` is the latest version it is replaced in place."""
        if "variants" in content:
            item["variants"] = bool(content["variants"])
        in_place = previous is not None and (
            not item["versions"] or item["versions"][-1] is not previous
        )
        number = previous["version"] if in_place and previous else len(item["versions"]) + 1
        if not in_place and item["versions"]:
            number = item["versions"][-1]["version"] + 1
        old_folder = (
            self.folder(topic, item["slug"], previous["version"]) if previous is not None else None
        )
        decision = content.get("decision")
        if decision is None and previous is not None:
            decision = self.decision({"topic": topic, "slug": item["slug"]}, previous)
        files = content.get("files")
        if files is None and previous is not None:
            files = [entry["path"] for entry in previous["files"] if entry["kind"] == "project"]
        derived = content.get("derived")
        carried: list[tuple[dict[str, Any], bytes, dict[str, bytes]]] = []
        if derived is None and previous is not None and old_folder is not None:
            for entry in previous["files"]:
                if entry["kind"] == "derived":
                    source = self.located(topic, item["slug"], previous["version"], entry)
                    kept = {
                        name: (old_folder / name).read_bytes()
                        for name in companions(entry).values()
                    }
                    carried.append((entry, source.read_bytes(), kept))
        views: list[tuple[dict[str, Any], bytes]] = []
        if content.get("views") is not None:
            views = [self.view_file(dict(given)) for given in content.get("views") or []]
        elif previous is not None and old_folder is not None:
            views = [
                (dict(view), (old_folder / view["name"]).read_bytes())
                for view in previous.get("views", [])
            ]
        if not decision and not files and not derived and not carried:
            raise UsageError(
                "an item holds something: give `decision`, `files`, `derived`, or several"
            )
        made: list[tuple[dict[str, Any], bytes, dict[str, bytes]]] = []
        if decision:
            made.append(
                ({"kind": "decision", "name": DECISION_FILE}, checked_decision(decision), {})
            )
        for path in files or []:
            made.append(self.project_file(path))
        for given in derived or []:
            made.append(self.derived_file(dict(given)))
        made += carried
        self.check_assets(item, [entry for entry, _, _ in made], bool(views))
        names = (
            [stored(entry) for entry, _, _ in made]
            + [name for _, _, beside in made for name in beside]
            + [view["name"] for view, _ in views]
        )
        doubled = sorted({name for name in names if names.count(name) > 1})
        if doubled:
            raise UsageError(f"two files named {', '.join(doubled)}: rename one")
        folder = self.folder(topic, item["slug"], number)
        if in_place and old_folder is not None:
            shutil.rmtree(old_folder, ignore_errors=True)
            shutil.rmtree(self.large / topic / item["slug"] / str(number), ignore_errors=True)
        entries = []
        for entry, data, beside in made:
            for name, kept in beside.items():
                (folder / name).parent.mkdir(parents=True, exist_ok=True)
                (folder / name).write_bytes(kept)
            written = self.write_file(topic, item["slug"], number, entry, data)
            entries.append(entry if entry["kind"] == "decision" else written)
        folder.mkdir(parents=True, exist_ok=True)
        laid_out = []
        for view, data in views:
            (folder / view["name"]).write_bytes(data)
            laid_out.append(
                {"name": view["name"], "title": view.get("title") or "", "bytes": len(data)}
            )
        stamp = self.recorded()
        record = {"version": number, **stamp, "files": entries}
        if laid_out:
            record["views"] = laid_out
        item["versions"].append(record)

    def check_assets(
        self, item: dict[str, Any], entries: list[dict[str, Any]], views: bool = False
    ) -> None:
        """One asset per item: a decision (with the project files it
        concerns), or one file; several only as variants of one type."""
        files = [entry for entry in entries if entry["kind"] != "decision"]
        if len(files) < len(entries):
            if has_variants(item):
                raise UsageError(
                    "a decision has no variants: its alternatives say what else was weighed"
                )
            if views:
                raise UsageError("a decision has no views: views lay out an asset's variants")
            derived = [entry["name"] for entry in files if entry["kind"] == "derived"]
            if derived:
                raise UsageError(
                    f"a decision holds no derived file: submit {derived[0]} as an item of its"
                    " own, and cite it in the answer"
                )
            return
        if len(files) > 1 and not has_variants(item):
            raise UsageError(
                "an item holds one asset: submit each file as an item of its own — several only"
                ' as variants, takes on one asset for the owner to prefer one (`"variants": true`)'
            )
        types = sorted({entry["type"] for entry in files})
        if has_variants(item) and len(types) > 1:
            raise UsageError(
                f"variants are takes on one asset, of one type — not {' and '.join(types)}:"
                " unrelated files are items of their own"
            )

    def view_file(self, given: dict[str, Any]) -> tuple[dict[str, Any], bytes]:
        if "text" in given:
            name = str(given.get("name") or "").strip()
            data = str(given["text"]).encode()
        elif "path" in given:
            path = Path(given["path"]).expanduser()
            path = path if path.is_absolute() else Path.cwd() / path
            if not path.is_file():
                raise UsageError(f"{given['path']}: no such file")
            name = str(given.get("name") or path.name)
            data = path.read_bytes()
        else:
            raise UsageError("a view gives `path` (an HTML file to copy) or `text` with `name`")
        if "/" in name or Path(name).suffix.lower() not in (".html", ".htm"):
            raise UsageError(f"{name or 'a view'}: a view is an HTML file, named `sizes.html`")
        return {"name": name, "title": str(given.get("title") or "").strip()}, data

    def project_file(self, given: str) -> tuple[dict[str, Any], bytes, dict[str, bytes]]:
        here = self.project.here.resolve()
        path = Path(given).expanduser()
        path = (path if path.is_absolute() else here / path).resolve()
        if not path.is_relative_to(here) or not path.is_file():
            raise UsageError(
                f"{given}: not a file in the repository — a project file is a path in it;"
                ' something made to show part of it goes in `derived` (`{"path": …, "from": […]}`)'
            )
        relative = str(path.relative_to(here))
        data = path.read_bytes()
        entry: dict[str, Any] = {
            "kind": "project",
            "path": relative,
            "type": kind_of(relative, data),
        }
        beside = video_companions(entry, path.name, path, None, None)
        return entry, data, beside

    def derived_file(self, given: dict[str, Any]) -> tuple[dict[str, Any], bytes, dict[str, bytes]]:
        source = None
        if "text" in given:
            name = str(given.get("name") or "").strip()
            if not name:
                raise UsageError("a derived `text` needs its `name`: `email.md`")
            data = str(given["text"]).encode()
        elif "path" in given:
            path = Path(given["path"]).expanduser()
            path = path if path.is_absolute() else Path.cwd() / path
            if not path.is_file():
                raise UsageError(f"{given['path']}: no such file")
            name = str(given.get("name") or path.name)
            data = path.read_bytes()
            source = path
        else:
            raise UsageError("a derived file gives `path` (a file to copy) or `text` with `name`")
        if "/" in name or name in (DECISION_FILE, ITEM_FILE, PROJECT_FILES):
            raise UsageError(f"{name}: not a file name to keep")
        recipe = {
            field: str(value).strip()
            for field, value in dict(given.get("recipe") or {}).items()
            if str(value).strip()
        }
        entry = {
            "kind": "derived",
            "name": name,
            "type": kind_of(name, data),
            "from": [str(source) for source in given.get("from", [])],
            "when": str(given.get("when") or "").strip() or None,
            "recipe": recipe or None,
        }
        beside = video_companions(entry, name, source, given.get("captions"), given.get("poster"))
        return entry, data, beside

    def delete_item(self, ref: str) -> str | None:
        with self.project.lock("topics"):
            item = self.item(ref)
            if item["verdict"] != Verdict.OPEN or any(
                entry["author"] == Author.OWNER for entry in item["thread"]
            ):
                raise PolicyError(
                    f"{item['ref']} has the owner's word on it: only an open item the owner has not"
                    " written on is deleted — give a new version instead"
                )
            folder = self.directory / item["topic"] / item["slug"]
            shutil.rmtree(folder)
            shutil.rmtree(self.large / item["topic"] / item["slug"], ignore_errors=True)
            return self.commit([folder], f"Item {item['ref']}, deleted: {item['title']}")

    # --- the owner's word -------------------------------------------------------

    def prefer(self, ref: str, version: int, name: str | None) -> tuple[dict[str, Any], str | None]:
        """The owner's preferred variant in a version of an item with variants,
        or none (`name` None): recorded and shown; only an item whose latest
        version's variant is preferred is accepted."""
        with self.project.lock("topics"):
            item = self.item(ref)
            if not has_variants(item):
                raise UsageError(f"{item['ref']} has no variants to prefer one of")
            if name is None:
                item["preferred"] = None
            else:
                record = next(
                    (entry for entry in item["versions"] if entry["version"] == version), None
                )
                names = [
                    entry_name(entry)
                    for entry in (record or {}).get("files", [])
                    if entry["kind"] != "decision"
                ]
                if name not in names:
                    raise NotFoundError(f"{item['ref']} has no variant {name} in version {version}")
                item["preferred"] = {"version": version, "name": name}
            path = self.save_item(item["topic"], item)
            said = (
                f"variant {name} of version {version} preferred" if name else "no variant preferred"
            )
            return item, self.commit([path], f"Item {item['ref']}, {said}: {item['title']}")

    def judge(self, ref: str, word: Word) -> tuple[dict[str, Any], str | None]:
        with self.project.lock("topics"):
            item = self.item(ref)
            self.give(item, word)
            path = self.save_item(item["topic"], item)
            return item, self.commit(
                [path], f"Item {item['ref']}, {item['verdict']}: {item['title']}"
            )

    def give(self, item: dict[str, Any], word: Word) -> None:
        verdict = verdict_of(word)
        if verdict is Verdict.ACCEPTED and unpreferred(item):
            raise ConflictError(
                f"{item['ref']} has {len(variants_of(item))} variants: prefer one before accepting it"
            )
        item["verdict"] = str(verdict)
        item["decided"] = {"moment": now(), **self.writer()}
        comment = str(word.get("comment") or "").strip()
        if comment:
            item["thread"].append(
                message(Author.OWNER, comment, self.writer(), verdict=str(verdict))
            )

    def judge_topic(self, name: str, word: Word) -> tuple[list[str], str | None]:
        """The verdict on every open item of a topic; the comment in the topic's thread."""
        with self.project.lock("topics"):
            topic = self.topic(name)
            verdict = verdict_of(word)
            judged, paths = [], []
            for item in self.items(name):
                # Accepting all leaves out what cannot be accepted yet: variants with none preferred.
                if awaits_owner(item) and not (verdict is Verdict.ACCEPTED and unpreferred(item)):
                    self.give(item, Word(verdict=verdict))
                    paths.append(self.save_item(name, item))
                    judged.append(item["ref"])
            if not judged:
                if any(awaits_owner(item) for item in self.items(name)):
                    raise ConflictError(
                        f"topic {name}: every open item has variants with none preferred — prefer one first"
                    )
                raise ConflictError(f"topic {name} has nothing open")
            comment = str(word.get("comment") or "").strip()
            if comment:
                topic["thread"].append(
                    message(Author.OWNER, comment, self.writer(), verdict=str(verdict))
                )
                paths.append(self.save_topic(topic))
            return judged, self.commit(paths, f"Topic {name}, {verdict}: {len(judged)} item(s)")

    def withdraw(
        self,
        ref: str | None = None,
        topic: str | None = None,
        keep: Callable[[Path, dict[str, Any]], None] | None = None,
    ) -> str:
        """Take back the owner's message still waiting for its answer, in an
        item's thread (`ref`) or a topic's: its text, to write again; each
        file it carried is handed to `keep` first, then removed."""
        with self.project.lock("topics"):
            if ref is not None:
                record = self.item(ref)
                where = record["ref"]
            elif topic is not None:
                record = self.topic(topic)
                where = topic
            else:
                raise UsageError("give `ref` or `topic`")
            if not pending(record["thread"], record.get("decided")):
                raise ConflictError(f"{where} has no message of yours waiting: nothing to withdraw")
            waiting = talk(record["thread"])[-1]
            record["thread"].remove(waiting)
            text = waiting["text"]
            if ref is not None:
                self.unattach(waiting, record["topic"], record["slug"], keep)
                path = self.save_item(record["topic"], record)
            else:
                self.unattach(waiting, record["name"], None, keep)
                path = self.save_topic(record)
            self.commit(
                [path.parent],
                f"{'Item' if ref is not None else 'Topic'} {where}, a message withdrawn",
            )
            return text

    def reply(
        self, ref: str, text: str, author: Author, attachments: list[Path] | None = None
    ) -> str | None:
        """A message in a topic's thread (a ref without `/`) or an item's,
        with the files it carries."""
        if "/" in ref.strip("/"):
            return self.update_item(ref, None, reply=text, author=author, attachments=attachments)[
                1
            ]
        return self.update_topic(ref, {}, reply=text, author=author, attachments=attachments)[1]

    # --- telling the agents -----------------------------------------------------

    def news_for(self, session: str) -> list[dict[str, Any]]:
        """The items this session made on which the owner has said something
        (a verdict, a message) it has not been told yet; telling it is
        recorded. A dropped item is closed: nothing on it is news."""
        told = {
            (row["item"], row["updated"])
            for row in self.project.store.rows(
                "SELECT item, updated FROM told WHERE session = ?", (session,)
            )
        }
        news = []
        summed = self.summaries()
        if summed is not None:
            for entry in summed:
                if entry["verdict"] == Verdict.DROPPED or session not in entry["writers"]:
                    continue
                said = entry["word"]
                if (
                    not said
                    or (entry["ref"], said) in told
                    or (entry["ref"], entry["moment"]) in told
                ):
                    continue
                news.append(self.whole(entry))
                self.project.store.insert(
                    "told", {"session": session, "item": entry["ref"], "updated": said}
                )
            return news
        for item in self.every():
            if item["verdict"] == Verdict.DROPPED:
                continue
            if not any(by(version, {session}) for version in item["versions"]):
                continue
            said = owner_word(item)
            if not said or (item["ref"], said) in told or (item["ref"], owner_moment(item)) in told:
                continue
            news.append(item)
            self.project.store.insert(
                "told", {"session": session, "item": item["ref"], "updated": said}
            )
        return news

    def mark_told(self, refs: set[str] | None = None) -> int:
        """Record the owner's word so far on these items (all, without refs)
        as told to every session that made a version of them, so `news_for`
        announces only what is said later; how many tellings it recorded."""
        told = {
            (row["session"], row["item"], row["updated"])
            for row in self.project.store.rows("SELECT session, item, updated FROM told")
        }
        marked = 0
        for item in self.every():
            said = owner_word(item)
            if not said or (refs is not None and item["ref"] not in refs):
                continue
            sessions = {
                version[key]
                for version in item["versions"]
                for key in ("session", "parent")
                if version.get(key)
            }
            for session in sorted(sessions):
                if (session, item["ref"], said) not in told:
                    self.project.store.insert(
                        "told", {"session": session, "item": item["ref"], "updated": said}
                    )
                    marked += 1
        return marked

    def tell_writer(self, refs: list[str]) -> None:
        """The owner's word on these items, just recorded by this session (or
        a subagent of it, or one nock dispatched), as told to it: a session is
        never told back what it wrote itself. Only for the commands an agent
        runs on the owner's word; the studio is the owner's own page, whatever
        session started it."""
        writer = self.writer()
        sessions = sorted(filter(None, {writer.get("session"), writer.get("parent")}))
        for ref in refs:
            item = self.item(ref)
            said = owner_word(item)
            for session in sessions:
                self.project.store.insert(
                    "told", {"session": session, "item": item["ref"], "updated": said}
                )

    def governing(self, session: str, path: str) -> list[dict[str, Any]]:
        """The items neither rejected nor dropped whose latest version holds
        this project file or was derived from it, not yet shown this session; showing them is
        recorded."""
        shown = {
            row["item"]
            for row in self.project.store.rows(
                "SELECT item FROM shown_items WHERE session = ?", (session,)
            )
        }
        found = []
        summed = self.summaries()
        for item in summed if summed is not None else self.every():
            if item["verdict"] in (Verdict.REJECTED, Verdict.DROPPED) or item["ref"] in shown:
                continue
            latest = item["latest"] if summed is not None else item["versions"][-1]["files"]
            if any(
                entry.get("path") == path
                or any(fnmatch.fnmatchcase(path, source) for source in entry.get("from", []))
                for entry in latest
            ):
                found.append(self.whole(item) if summed is not None else item)
                self.project.store.insert("shown_items", {"session": session, "item": item["ref"]})
        return found

    # --- the map ----------------------------------------------------------------

    def citation_problems(self) -> list[Problem]:
        """Every map citation of an item that does not exist."""
        if not self.map.is_file():
            return []
        place = str(self.map.relative_to(self.project.root))
        problems = []
        for line, text in enumerate(self.map.read_text().splitlines(), start=1):
            for match in CITATION.finditer(text):
                try:
                    self.resolve(match.group(1))
                except NotFoundError:
                    problems.append(Problem(f"[{match.group(0)[1:-1]}] is no item", place, line))
        return problems

    def commit(self, paths: list[Path], message: str) -> str | None:
        if self.project.current_role() == TIDIER:
            return None
        root = self.project.root
        relative = [
            str(path.relative_to(root)) for path in paths if path.is_relative_to(self.directory)
        ]
        return committed(self.project, relative, message) if relative else None


def summary(item: dict[str, Any]) -> dict[str, Any]:
    """What `news_for` and `governing` look for in an item: who wrote its
    versions (`by`), the owner's word on it, and its latest version's files."""
    return {
        "slug": item["slug"],
        "created": moment(item["created"]),
        "verdict": item["verdict"],
        "writers": [
            stamp[key]
            for stamp in item["versions"]
            for key in ("session", "parent")
            if key in stamp
        ],
        "word": owner_word(item),
        "moment": owner_moment(item),
        "latest": [
            {key: entry[key] for key in ("path", "from") if key in entry}
            for entry in item["versions"][-1]["files"]
        ],
    }


def by(stamp: dict[str, Any], sessions: set[str]) -> bool:
    """Whether one of these sessions wrote it, itself or through a subagent."""
    return stamp.get("session") in sessions or stamp.get("parent") in sessions


def owner_wrote_last(thread: list[dict[str, Any]]) -> bool:
    said = talk(thread)
    return bool(said) and said[-1]["author"] == Author.OWNER


def pending(thread: list[dict[str, Any]], decided: dict[str, Any] | None = None) -> bool:
    """The owner wrote last, and not with a verdict: their message waits for
    the agent's answer, and the chat is closed to them until it comes. A
    verdict given since (`decided`) overrides it: the verdict is the answer.
    A status entry is no answer."""
    said = talk(thread)
    if not said or said[-1]["author"] != Author.OWNER or said[-1].get("verdict"):
        return False
    return moment(decided) < said[-1]["moment"]


def said_in(
    thread: list[dict[str, Any]],
    author: Author,
    text: str,
    writer: dict[str, str | None],
    decided: dict[str, Any] | None = None,
    files: bool = False,
) -> dict[str, Any]:
    """A message for this thread: the owner's only once their last has its
    answer (or they withdraw it); the agent's answers the owner's waiting one,
    and may follow it with more."""
    if author is Author.OWNER and pending(thread, decided):
        raise ConflictError(
            "your last message waits for the agent's answer: withdraw it to change it"
        )
    if author is Author.AGENT and pending(thread, decided):
        return message(author, text, writer, files, answers=talk(thread)[-1]["moment"])
    return message(author, text, writer, files)


def chat_state(
    thread: list[dict[str, Any]], seen: str | None, decided: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Where a thread stands for the owner: `pending`, their message waiting
    for its answer; `unseen`, the agent's messages since they last looked
    (or last wrote), and whether one of them is the answer they waited for.
    A thread they never opened nor wrote in shows nothing as new; a status
    entry is never new."""
    thread = talk(thread)
    wrote = [index for index, entry in enumerate(thread) if entry["author"] == Author.OWNER]
    after = thread[wrote[-1] + 1 :] if wrote else thread
    new = [
        entry
        for entry in after
        if entry["author"] == Author.AGENT and (seen is None or entry["moment"] > seen)
    ]
    if not wrote and seen is None:
        new = []
    return {
        "pending": pending(thread, decided),
        "unseen": len(new),
        "answered": any("answers" in entry for entry in new),
    }


def in_order(topics: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Topics (records or rows, with their `active` moment) in the owner's
    order: by priority, 1 first, then those without one; newest activity
    first within each."""
    newest = sorted(topics, key=lambda topic: topic["active"], reverse=True)
    return sorted(
        newest, key=lambda topic: (0, topic["priority"]) if topic.get("priority") else (1, 0)
    )


def awaits_owner(item: dict[str, Any]) -> bool:
    """Open: the owner's to look at."""
    return item["verdict"] == Verdict.OPEN


def occurrences(word: str, text: str) -> list[str]:
    """Where a searched word is found in a text: wherever a word of it starts
    with it, whatever the case ("cli" in "CLI's" and "clients", not "decline")."""
    return re.findall(rf"(?<![a-z0-9]){re.escape(word.lower())}", text.lower())


def has_variants(item: dict[str, Any]) -> bool:
    """Whether an item's files are variants of one asset."""
    return bool(item.get("variants"))


def variants_of(item: dict[str, Any]) -> list[dict[str, Any]]:
    """The latest version's files, when they are an asset's variants."""
    files = [entry for entry in item["versions"][-1]["files"] if entry["kind"] != "decision"]
    return files if has_variants(item) else files[:1]


def unpreferred(item: dict[str, Any]) -> bool:
    """Several variants, none of the latest version's preferred: not to accept yet."""
    found = variants_of(item)
    preferred = item.get("preferred") or {}
    latest = item["versions"][-1]["version"]
    return len(found) > 1 and not (
        preferred.get("version") == latest
        and any(entry_name(entry) == preferred.get("name") for entry in found)
    )


def owner_moment(item: dict[str, Any]) -> str:
    """When the owner last said something on an item: a verdict or a message."""
    decided = item.get("decided") or {}
    moments = [moment(decided)]
    moments += [entry["moment"] for entry in item["thread"] if entry["author"] == Author.OWNER]
    return max(moments)


def owner_word(item: dict[str, Any]) -> str:
    """The owner's word so far on an item, as a session is told it: when it
    was last said, and which word it is. Moments are to the second, so two
    sessions' verdicts within one second share a moment; the verdict, who
    recorded it and the owner's messages tell them apart. Empty while the
    owner has said nothing."""
    said = owner_moment(item)
    if not said:
        return ""
    word = {
        "verdict": item.get("verdict"),
        "decided": item.get("decided"),
        "messages": [
            [entry["moment"], entry.get("session"), entry.get("parent")]
            for entry in item["thread"]
            if entry["author"] == Author.OWNER
        ],
    }
    digest = hashlib.sha256(json.dumps(word, sort_keys=True).encode()).hexdigest()
    return f"{said} {digest[:12]}"


def committed(project: Project, paths: list[str], message: str) -> str | None:
    """Commit these paths (files written or removed) in the main checkout —
    unless that would land in the middle of a merge or rebase there; then
    say so, and leave them as they are."""
    git = project.git
    git_directory = Path(git("rev-parse", "--absolute-git-dir"))
    busy = next((marker for marker in BUSY_MARKERS if (git_directory / marker).exists()), None)
    if busy is not None:
        return f"not committed: the main checkout is mid-operation ({busy}); {', '.join(paths)} written"
    git("add", "--all", "--", *paths)
    git("commit", "--quiet", "--no-verify", "--only", "-m", message, "--", *paths)
    return None


def attachment_name(name: str) -> str:
    """A file's own name, as it is kept: no folders, nothing hidden."""
    name = Path(name.replace("\\", "/")).name.strip().lstrip(".")
    if not name:
        raise UsageError("an attachment needs a name")
    return name


def entry_name(entry: dict[str, Any]) -> str:
    return entry.get("path") or entry["name"]


def companions(entry: dict[str, Any]) -> dict[str, str]:
    """A video's files kept beside it, by role: its `captions` and `poster`."""
    return {role: entry[role] for role in ("captions", "poster") if entry.get(role)}


def video_companions(
    entry: dict[str, Any],
    name: str,
    source: Path | None,
    captions: str | None,
    poster: str | None,
) -> dict[str, bytes]:
    """A video's captions (WebVTT: the path given, else `NAME.vtt` beside its
    source) and poster, recorded in its entry and returned to be kept beside
    it in its version's folder."""
    stem = Path(name).stem
    found: dict[str, bytes] = {}
    if (captions is not None or poster is not None) and entry["type"] != "video":
        raise UsageError(f"{name}: only a video has `captions` or a `poster`")
    if entry["type"] != "video":
        return found
    vtt = Path(captions).expanduser() if captions else None
    if vtt is None and source is not None and source.with_suffix(".vtt").is_file():
        vtt = source.with_suffix(".vtt")
    if vtt is not None:
        vtt = vtt if vtt.is_absolute() else Path.cwd() / vtt
        if not vtt.is_file():
            raise UsageError(f"{captions}: no such captions file")
        text = vtt.read_bytes()
        if not text.lstrip(b"\xef\xbb\xbf").startswith(b"WEBVTT"):
            raise UsageError(f"{vtt.name}: captions are a WebVTT file, starting `WEBVTT`")
        entry["captions"] = f"{stem}.vtt"
        found[entry["captions"]] = text
    if poster:
        picture = Path(poster).expanduser()
        picture = picture if picture.is_absolute() else Path.cwd() / picture
        if not picture.is_file() or kind_of(picture.name, b"") != "image":
            raise UsageError(f"{poster}: a poster is a picture file")
        entry["poster"] = f"{stem}.poster{picture.suffix.lower()}"
        found[entry["poster"]] = picture.read_bytes()
    return found


def stored(entry: dict[str, Any]) -> str:
    """Where a file is kept inside its version's folder."""
    if entry["kind"] == "project":
        return f"{PROJECT_FILES}/{entry['path']}"
    return entry["name"]


def checked_decision(decision: Decision | dict[str, Any]) -> bytes:
    answer = str(decision.get("answer") or "").strip()
    if not answer:
        raise UsageError("the decision's `answer` is empty")
    alternatives = [
        {"option": str(entry["option"]).strip(), "why_not": str(entry["why_not"]).strip()}
        for entry in decision.get("alternatives") or []
    ]
    status = str(Status(decision.get("status") or Status.DONE))
    return (
        json.dumps(
            {"answer": answer, "alternatives": alternatives, "status": status},
            indent=2,
            ensure_ascii=False,
        )
        + "\n"
    ).encode()
