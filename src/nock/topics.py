"""Topics and items: what agents put before the owner. A topic is a piece of
work — a name, why it exists, a thread — holding items; an item is bare: a
title, a description under it, and, in each of its versions, a decision
(nock's own JSON: the answer, the alternatives weighed, done or todo, with
the project files it concerns), one asset — a project file (linked at the
commit it was at, or kept by content when it had uncommitted changes) or a
derived file (something made to show part of the project, with what it comes
from, when it applies and how to make it again) — or a decision with the
asset that shows it. An asset may hold several variants, takes on one
thing of one type, of which the owner prefers one before accepting it, and
views, HTML pages laying out its variants with nock's look. The owner alone gives an item its
verdict (accepted; rejected, to be reworked; dropped, rejected with nothing
to rework, closed; open until then), on the page or with `/nock-triage`;
both sides talk in the threads, a chat: the owner's message waits for the
agent's one answer (`pending`), and is withdrawn until it comes. Everything
lives in the store (`nock.shared`), the main checkout's `.nock/shared/`, as
events folded into these records (`nock.fold`): each change here is a few
event files (a version a folder), settled and committed at once, whichever
worktree writes it, so the owner sees it at once. Media — and every file a
message carries — is kept in `.nock/shared/media/` by sha256.

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
import subprocess
from collections import Counter
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Any, NotRequired, TypedDict, cast

from nock.errors import ConflictError, NotFoundError, PolicyError, UsageError
from nock.fold import ASSETS, EVENTS, ITEMS, STATUS, VERSIONS
from nock.notify import Notifications, Reason
from nock.records import ASSETS_FILE, DECISION_FILE, NEXT
from nock.render import Problem
from nock.shared import Settled, Shared, by_for
from nock.shared import unpreferred as asset_unpreferred
from nock.utils import now, read_json, write_json

if TYPE_CHECKING:
    from nock.project import Project

PROJECT_FILES = "project"
# What the prompt and edit hooks look for in every decision, in `local/`, each with
# its event folders' stamps: they fold a decision again only once it changed.
SUMMARIES_FILE = "item-summaries.json"
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
    assets: NotRequired[list[str]]
    """The asset items that show what it decided, by ref (`topic/slug`): a
    decision holds no file of its own but the project files it concerns."""


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
    set: NotRequired[bool]
    """The files are a set shown together, as one asset (before and after,
    desktop and phone): nothing to prefer."""
    views: NotRequired[list[View]]
    """HTML pages laying out the files: the variants (each favicon at several
    sizes) or the set."""


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
    """The topics and items, read from the store's fold and written to it as
    events: each change a few event files (a version a folder), settled —
    validated, completed and committed — at once."""

    def __init__(self, project: Project) -> None:
        self.project = project
        self.shared = Shared(project)
        self.fold = self.shared.fold
        self.drafted: list[Path] = []

    @property
    def directory(self) -> Path:
        """The main checkout's, whichever worktree writes: the owner looks there."""
        return self.shared.topics

    @property
    def map(self) -> Path:
        return self.shared.map

    # --- reading ----------------------------------------------------------------

    def names(self) -> list[str]:
        return self.fold.names()

    def topic(self, name: str) -> dict[str, Any]:
        record = self.fold.topic(name) if NAME.match(name) else None
        if record is None:
            renamed = [
                other
                for other in self.names()
                if name in (self.fold.topic(other) or {}).get("aliases", [])
            ]
            if renamed:
                record = self.fold.topic(renamed[0])
        if record is None:
            close = [other for other in self.names() if name in other or other in name]
            hint = f" — did you mean {', '.join(close[:3])}?" if close else ""
            raise NotFoundError(f"no topic {name!r}{hint} (`.nock/nock topics list`)")
        return record

    def items(self, name: str) -> list[dict[str, Any]]:
        """A topic's items, the newest first."""
        return self.fold.items(name)

    def every(self) -> list[dict[str, Any]]:
        return [item for name in self.names() for item in self.items(name)]

    def summaries(self) -> list[dict[str, Any]] | None:
        """Every decision as `every` lists it, in its order, but only what the
        hooks look for in it (`summary`, with `topic` and `ref`): a decision is
        folded again only once one of its event folders changed (each folder's
        modification time, which a new event file moves). None when one
        cannot be summed up, so the caller reads them all and fails as it would
        have."""
        path = self.project.local / SUMMARIES_FILE
        try:
            kept = json.loads(path.read_text())
        except (OSError, ValueError):
            kept = {}
        kept = kept if isinstance(kept, dict) else {}
        current: dict[str, Any] = {}
        listed: list[dict[str, Any]] = []
        if not self.directory.is_dir():
            return []
        for topic in sorted(path.name for path in self.directory.iterdir() if path.is_dir()):
            found = []
            for folder in sorted((self.directory / topic / ITEMS).glob("*/")):
                stamp = folder_stamp(folder)
                key = f"{topic}/{folder.name}"
                entry = kept.get(key)
                if not isinstance(entry, dict) or entry.get("stamp") != stamp:
                    try:
                        item = self.fold.item(topic, folder.name)
                        if item is None:
                            continue
                        entry = {"stamp": stamp, "summary": summary(item)}
                    except Exception:
                        return None
                current[key] = entry
                found.append({**entry["summary"], "topic": topic, "ref": key})
            listed += sorted(found, key=lambda item: item["created"], reverse=True)
        if current != kept:
            with contextlib.suppress(OSError):
                write_json(path, current)
        return listed

    def whole(self, summed: dict[str, Any]) -> dict[str, Any]:
        """The decision a summary is of, as `every` lists it."""
        return self.item(summed["ref"])

    def resolve(self, ref: str) -> tuple[str, str]:
        """A ref's topic and slug: `topic/slug`, or a ref it had before it moved."""
        ref = ref.strip().strip("/")
        topic, _, slug = ref.rpartition("/")
        if topic and NAME.match(topic) and NAME.match(slug) and self.fold.item(topic, slug):
            return topic, slug
        for item in self.every():
            if ref in item.get("aliases", []):
                return item["topic"], item["slug"]
        if topic:
            self.topic(topic)
        raise NotFoundError(f"no item {ref!r} — `.nock/nock items list {topic}` lists them")

    def item(self, ref: str) -> dict[str, Any]:
        topic, slug = self.resolve(ref)
        item = self.fold.item(topic, slug)
        assert item is not None
        return item

    def recipes(self, ref: str) -> list[str]:
        """The commands that make a decision's derived assets again: the
        recipes of each asset's latest version not written by Address my
        comments, so what `items remake` runs is always a recipe its author
        wrote."""
        item = self.item(ref)
        commands: list[str] = []
        for asset in item["assets"]:
            authored = [v for v in asset["versions"] if v.get("role") != ADDRESSER]
            for entry in authored[-1]["files"] if authored else []:
                command = (
                    (entry.get("recipe") or {}).get("command")
                    if entry["kind"] == "derived"
                    else None
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
        """A decision's version."""
        return self.shared.item_folder(topic, slug) / VERSIONS / str(version)

    def asset_folder(self, topic: str, slug: str, asset: str, version: int) -> Path:
        return self.shared.item_folder(topic, slug) / ASSETS / asset / VERSIONS / str(version)

    def decision(self, item: dict[str, Any], version: dict[str, Any]) -> dict[str, Any] | None:
        if not any(entry["kind"] == "decision" for entry in version["files"]):
            return None
        return read_json(
            self.folder(item["topic"], item["slug"], version["version"]) / DECISION_FILE
        )

    def asset(self, item: dict[str, Any], name: str) -> dict[str, Any]:
        found = next((asset for asset in item["assets"] if asset["name"] == name), None)
        if found is None:
            raise NotFoundError(f"{item['ref']} has no asset {name!r}")
        return found

    # --- where files are: the one layer that reads them -------------------------

    def located(
        self, topic: str, slug: str, asset: str, version: int, entry: dict[str, Any]
    ) -> Path:
        """Where an asset version's file is: in media by its sha256, beside its
        version, or — a project file linked at a commit — as it was then."""
        if entry.get("sha256"):
            return self.shared.blob(entry["sha256"])
        if entry["kind"] == "project" and entry.get("commit"):
            return self.at_commit(entry["path"], entry["commit"])
        return self.asset_folder(topic, slug, asset, version) / entry_name(entry)

    def at_commit(self, path: str, commit: str) -> Path:
        """A project file as it was at a commit, kept on this machine to be read."""
        target = self.project.local / "cache" / commit / path
        if not target.is_file():
            try:
                data = subprocess.run(
                    ["git", "show", f"{commit}:{path}"],
                    cwd=self.project.root,
                    capture_output=True,
                    check=True,
                ).stdout
            except subprocess.CalledProcessError:
                return target
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        return target

    def file(self, topic: str, slug: str, asset: str, version: int, name: str) -> Path:
        """Where one of an asset version's files is: only a file its record
        names, a video's captions or poster, or one of its views."""
        item = self.item(f"{topic}/{slug}")
        record = next(
            (v for v in self.asset(item, asset)["versions"] if v["version"] == version), None
        )
        listed = record and next(
            (entry for entry in record["files"] if entry_name(entry) == name), None
        )
        if not listed and record:
            beside = any(name in companions(entry).values() for entry in record["files"])
            viewed = any(view["name"] == name for view in record.get("views", []))
            if beside or viewed:
                blob = (record.get("blobs") or {}).get(name)
                folder = self.asset_folder(topic, slug, asset, version)
                return self.shared.blob(blob) if blob else folder / name
        if not listed:
            raise NotFoundError(
                f"{topic}/{slug} has no file {name} in version {version} of asset {asset}"
            )
        return self.located(topic, slug, asset, version, listed)

    def shown(self, item: dict[str, Any]) -> dict[str, Any]:
        """A decision with each version's decision read, and each asset with
        each version's files where they are, and its views."""
        versions = [
            {**version, "decision": self.decision(item, version)} for version in item["versions"]
        ]
        assets = []
        for asset in item["assets"]:
            shown_versions = []
            for version in asset["versions"]:
                number = version["version"]
                folder = self.asset_folder(item["topic"], item["slug"], asset["name"], number)
                blobs = version.get("blobs") or {}
                files = []
                for entry in version["files"]:
                    path = self.located(item["topic"], item["slug"], asset["name"], number, entry)
                    beside = {
                        f"{role}_where": str(
                            self.shared.blob(blobs[name]) if name in blobs else folder / name
                        )
                        for role, name in companions(entry).items()
                    }
                    files.append({**entry, "name": entry_name(entry), "where": str(path), **beside})
                views = [
                    {**view, "where": str(folder / view["name"])}
                    for view in version.get("views", [])
                ]
                shown_versions.append({**version, "files": files, "views": views})
            assets.append({**asset, "versions": shown_versions})
        thread = self.thread_shown(item["thread"], item["topic"], item["slug"])
        return {**item, "versions": versions, "assets": assets, "thread": thread}

    # --- attachments ------------------------------------------------------------

    def where(self, entry: dict[str, Any], topic: str, slug: str | None = None) -> Path:
        """Where an attachment is: in media, by its sha256."""
        return self.shared.blob(entry["sha256"])

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

    def attach(self, files: list[Path]) -> list[dict[str, Any]]:
        """What a message's draft says of the files it carries: each read and
        kept in media when the message is settled."""
        entries, names = [], set()
        for source in files:
            if not source.is_file():
                raise NotFoundError(f"{source}: no such file to attach")
            name = attachment_name(source.name)
            base, suffix, number = Path(name).stem, Path(name).suffix, 2
            while name in names:
                name, number = f"{base}-{number}{suffix}", number + 1
            names.add(name)
            entries.append({"path": str(source.resolve()), "name": name})
        return entries

    # --- rows -------------------------------------------------------------------

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
        latest = item["versions"][-1] if item["versions"] else {"files": []}
        kinds = sorted(
            {entry["kind"] for entry in latest["files"]}
            | {entry["kind"] for asset in item["assets"] for entry in latest_files(asset)}
        )
        preferred = {
            asset["name"]: asset["preferred"] for asset in item["assets"] if asset.get("preferred")
        }
        return {
            "ref": item["ref"],
            "title": item["title"],
            "verdict": item["verdict"],
            "kinds": kinds,
            **({"description": item["description"]} if item.get("description") else {}),
            **({"assets": len(item["assets"])} if item["assets"] else {}),
            **({"variants": len(variants_of(item))} if has_variants(item) else {}),
            **({"preferred": preferred} if preferred else {}),
            "versions": len(item["versions"]),
            "updated": item["updated"],
        }

    # --- searching --------------------------------------------------------------

    def item_text(self, item: dict[str, Any]) -> tuple[str, str]:
        """An item's title, and the rest of what it says, for search."""
        parts = [item.get("description") or "", *(entry["text"] for entry in item["thread"])]
        parts += [file["name"] for entry in item["thread"] for file in entry.get("attachments", [])]
        decision = self.decision(item, item["versions"][-1]) if item["versions"] else None
        if decision:
            parts.append(decision["answer"])
            parts += [f"{entry['option']} {entry['why_not']}" for entry in decision["alternatives"]]
        for asset in item["assets"]:
            parts += [asset["title"], asset.get("description") or ""]
            for entry in latest_files(asset):
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

    # --- writing ----------------------------------------------------------------

    def by(self, author: Author = Author.AGENT) -> dict[str, Any]:
        return by_for(self.project, str(author))

    def settle(
        self,
        written: list[Path],
        author: Author = Author.AGENT,
        removing: list[Path] | None = None,
    ) -> Settled:
        """Settle what nock just wrote: refused as a whole, its files gone, when
        the store finds a problem with it."""
        settled = self.shared.settle(self.by(author), only=written, removing=removing)
        if settled.problems:
            raise UsageError("; ".join(settled.problems))
        # A genuine cycle: the views read the topics.
        from nock.views import Views

        removed = {path.relative_to(self.directory).parts[0] for path in removing or []}
        Views(self.project).write(settled.topics | removed)
        return settled

    def draft(self, folder: Path, record: dict[str, Any]) -> Path:
        path = self.shared.draft(folder, record)
        self.drafted.append(path)
        return path

    @contextmanager
    def drafting(self) -> Iterator[None]:
        """What a change drafts, all gone again — and any folder it left
        empty — when the change fails before it is settled."""
        self.drafted = []
        try:
            yield
        except BaseException:
            for path in reversed(self.drafted):
                if path.is_dir():
                    shutil.rmtree(path, ignore_errors=True)
                else:
                    path.unlink(missing_ok=True)
                for parent in path.parents:
                    if parent == self.directory or not parent.is_relative_to(self.directory):
                        break
                    try:
                        parent.rmdir()
                    except OSError:
                        break
            raise
        finally:
            self.drafted = []

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
        with self.project.lock("topics"), self.drafting():
            existing = self.fold.topic(name)
            if existing is not None:
                standing = self.standing(existing)
                again = (
                    f" — it is {standing}; revive it:"
                    f' `.nock/nock topics update {name} --revive "why it is back"`'
                    if standing in CLOSED
                    else ": submit into it"
                )
                raise ConflictError(f"topic {name} exists{again}")
            folder = self.shared.topic_folder(name)
            written = [
                self.draft(
                    folder,
                    {
                        "kind": "created",
                        "description": draft["description"].strip(),
                        "state": str(state),
                    },
                )
            ]
            status = " ".join(str(draft.get("status") or "").split())
            if status:
                written.append(
                    self.draft(folder, {"kind": "state", "state": str(state), "status": status})
                )
            settled = self.settle(written)
            topic = self.topic(name)
            self.worked(name, self.recorded())
            return topic, settled.note

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
        with self.project.lock("topics"), self.drafting():
            topic = self.topic(name)
            name = topic["name"]
            folder = self.shared.topic_folder(name)
            was = self.standing(topic)
            owner_last = owner_wrote_last(topic["thread"])
            written: list[Path] = []
            if "description" in change:
                if not change["description"].strip():
                    raise UsageError("`description` is empty")
                written.append(
                    self.draft(
                        folder, {"kind": "described", "description": change["description"].strip()}
                    )
                )
            standing: dict[str, Any] = {}
            if "priority" in change:
                priority = int(change["priority"])
                if priority < 0:
                    raise UsageError("`priority` is 1 or more (1 first), or 0 to take it away")
                standing["priority"] = priority
            if revive is not None:
                if was not in CLOSED:
                    raise ConflictError(
                        f"topic {name} is {was}, not done or abandoned: submit into"
                        " it, no need to revive it"
                    )
                if State(change.get("state") or State.ACTIVE) in CLOSED:
                    raise UsageError("a revived topic is planned or active")
                note = revive.strip()
                if not note:
                    raise UsageError("`--revive` says why the topic is back")
                standing |= {
                    "state": str(State(change.get("state") or State.ACTIVE)),
                    "revived": True,
                    "note": note,
                }
            if "state" in change or "status" in change or revive is not None:
                # Each change of standing says the whole of it, as the thread keeps it:
                # a change of state without a status clears the status.
                state = State(change.get("state") or standing.get("state") or was)
                if "status" in change:
                    status = " ".join(str(change["status"] or "").split())
                elif state is not was:
                    status = ""
                else:
                    status = topic.get("status") or ""
                standing |= {"state": str(state), "status": status}
            if standing:
                written.append(self.draft(folder, {"kind": "state", **standing}))
            if reply is not None:
                said_in(topic["thread"], author, reply, self.writer(), files=bool(attachments))
                said: dict[str, Any] = {"kind": "message", "text": reply.strip()}
                if attachments:
                    said["attachments"] = self.attach(attachments)
                written.append(self.draft(folder, said))
            renamed = None
            if "name" in change and change["name"] != name:
                renamed = check_name(change["name"])
                if (self.directory / renamed).exists():
                    raise ConflictError(f"topic {renamed} exists")
                written.append(self.draft(folder, {"kind": "renamed", "name": renamed}))
            settled = self.settle(written, author)
            if renamed:
                name = renamed
                with self.project.store.connection() as connection:
                    connection.execute(
                        "UPDATE wrote SET topic = ? WHERE topic = ?", (renamed, topic["name"])
                    )
            topic = self.topic(name)
            if author is Author.AGENT and (reply is not None or standing):
                self.worked(name, self.recorded())
        if author is Author.AGENT:
            if was is not State.REVIEW and self.standing(topic) is State.REVIEW:
                self.owners_turn(name, Reason.REVIEW)
            elif reply is not None and owner_last:
                self.owners_turn(name, Reason.ANSWERED)
        return topic, settled.note

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
        with self.project.lock("topics"), self.drafting():
            self.topic(name)
            if self.items(name):
                raise ConflictError(f"topic {name} holds items: only an empty topic is deleted")
            folder = self.shared.topic_folder(name)
            shutil.rmtree(folder)
            return self.settle([], removing=[folder]).note

    # --- items ------------------------------------------------------------------

    def create_item(self, topic: str, draft: ItemDraft) -> tuple[dict[str, Any], str | None]:
        """A decision, with the assets that show it: its `decision` (or, for
        files that need review with no natural choice, a plain "Review"
        decision), each project file an asset, the derived files one asset
        (several only as its variants)."""
        title = draft["title"].strip()
        if not title:
            raise UsageError("`title` is empty")
        with self.project.lock("topics"), self.drafting():
            record = self.topic(topic)
            topic = record["name"]
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
            base, number = slug, 2
            while slug in taken or slug.isdigit() or self.shared.item_folder(topic, slug).exists():
                slug, number = f"{base}-{number}", number + 1
            description = " ".join(str(draft.get("description") or "").split())
            if not draft.get("decision") and not draft.get("files") and not draft.get("derived"):
                raise UsageError(
                    "an item holds something: give `decision`, `files`, `derived`, or several"
                )
            item = {"topic": topic, "slug": slug, "title": title, "assets": [], "versions": []}
            folder = self.shared.item_folder(topic, slug)
            created: dict[str, Any] = {"kind": "created", "title": title}
            if description:
                created["description"] = description
            self.draft(folder, created)
            decision = draft.get("decision") or {
                "answer": description or f"Review: {title}.",
            }
            self.decision_version(item, decision)
            self.asset_versions(item, draft, renew=False)
            settled = self.settle(list(self.drafted))
            self.worked(topic, self.recorded())
            return self.item(f"{topic}/{slug}"), settled.note

    def with_ref(self, topic: str, item: dict[str, Any]) -> dict[str, Any]:
        return {**item, "topic": topic, "ref": f"{topic}/{item['slug']}"}

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
        with self.project.lock("topics"), self.drafting():
            item = self.item(ref)
            topic, slug = item["topic"], item["slug"]
            folder = self.shared.item_folder(topic, slug)
            rejected = item["verdict"] == Verdict.REJECTED
            owner_last = owner_wrote_last(item["thread"])
            if change:
                if item["verdict"] != Verdict.OPEN:
                    raise ConflictError(
                        f"{item['ref']} is {item['verdict']}: it is not changed in place — "
                        f"give the change as a new version, `.nock/nock items update {item['ref']} --version '{{…}}'`"
                    )
                self.retitled(folder, change)
                content = {
                    key: value
                    for key, value in change.items()
                    if key not in ("title", "description")
                }
                if content.get("decision"):
                    self.decision_version(item, cast("Decision", content["decision"]))
                self.asset_versions(item, content, renew=False)
            if version is not None:
                self.retitled(folder, version)
                given = {
                    key: value
                    for key, value in version.items()
                    if key not in ("title", "description")
                }
                if (
                    not given.get("files")
                    and not given.get("derived")
                    and not given.get("decision")
                ):
                    # A new version of what it holds, as it is now: the decision again, its
                    # project files linked afresh.
                    self.decision_version(item, self.decision(item, item["versions"][-1]) or {})
                    self.asset_versions(item, {}, renew=True)
                else:
                    if given.get("decision"):
                        self.decision_version(item, cast("Decision", given["decision"]))
                    self.asset_versions(item, given, renew=False)
            if reply is not None:
                said_in(
                    item["thread"],
                    author,
                    reply,
                    self.writer(),
                    item.get("decided"),
                    files=bool(attachments),
                )
                said: dict[str, Any] = {"kind": "message", "text": reply.strip()}
                if attachments:
                    said["attachments"] = self.attach(attachments)
                self.draft(folder, said)
            moved = None
            if moving is not None:
                moved = self.move(item, moving)
                self.draft(folder, {"kind": "moved", "to": moved[0]})
            settled = self.settle(list(self.drafted), author)
            if moved:
                old = f"{topic}/{slug}"
                topic, slug = moved
                with self.project.store.connection() as connection:
                    for table in ("told", "shown_items"):
                        connection.execute(
                            f"UPDATE {table} SET item = ? WHERE item = ?", (f"{topic}/{slug}", old)
                        )
            if author is Author.AGENT and (change or version is not None or reply is not None):
                self.worked(topic, self.recorded())
        if author is Author.AGENT:
            if reply is not None and owner_last:
                self.owners_turn(topic, Reason.ANSWERED)
            elif version is not None and rejected:
                self.owners_turn(topic, Reason.REWORKED)
        return self.item(f"{topic}/{slug}"), settled.note

    def retitled(self, folder: Path, change: ItemChange) -> None:
        fields: dict[str, Any] = {}
        if "title" in change:
            if not str(change["title"] or "").strip():
                raise UsageError("`title` is empty")
            fields["title"] = change["title"].strip()
        if "description" in change:
            fields["description"] = " ".join(str(change["description"] or "").split())
        if fields:
            self.draft(folder, {"kind": "titled", **fields})

    def move(self, item: dict[str, Any], target: str) -> tuple[str, str]:
        """Where a decision re-filed in another topic goes: its slug kept unless
        taken there; its old ref becomes an alias, so citations of it still resolve."""
        source, slug = item["topic"], item["slug"]
        target = target.strip()
        if target == source:
            raise UsageError(f"{item['ref']} is in {target} already")
        self.topic(target)
        moved, number = slug, 2
        while self.shared.item_folder(target, moved).exists():
            moved, number = f"{slug}-{number}", number + 1
        return target, moved

    def decision_version(self, item: dict[str, Any], decision: Decision | dict[str, Any]) -> None:
        """A new version of the decision, in `versions/next/`."""
        folder = self.shared.item_folder(item["topic"], item["slug"]) / VERSIONS / NEXT
        if folder.exists():
            raise ConflictError(f"{item['topic']}/{item['slug']} has a version being written")
        data = checked_decision(decision)
        folder.mkdir(parents=True)
        self.drafted.append(folder)
        (folder / DECISION_FILE).write_bytes(data)

    def asset_versions(
        self, item: dict[str, Any], content: Content | dict[str, Any], renew: bool
    ) -> None:
        """The assets a change holds, each a new version of the asset it is (by
        its project path or its derived files' names) or a new asset: each
        project file an asset, the derived files one, several only as its
        variants. `renew`: every project-file asset again, linked as it is now."""
        assets = list(item.get("assets", []))
        for path in content.get("files") or []:
            entry = self.project_file(path)
            existing = next(
                (
                    asset
                    for asset in assets
                    if any(e.get("path") == entry["path"] for e in latest_files(asset))
                ),
                None,
            )
            name = existing["name"] if existing else self.asset_name(item, entry["path"])
            self.asset_version(item, name, entry["path"], [entry], [], [], False, existing is None)
        if renew:
            for asset in assets:
                files = latest_files(asset)
                if files and all(entry["kind"] == "project" for entry in files):
                    entries = [self.project_file(entry["path"]) for entry in files]
                    self.asset_version(
                        item, asset["name"], asset["title"], entries, [], [], False, False
                    )
        derived = content.get("derived")
        if not derived:
            if content.get("views"):
                raise UsageError("views lay out an asset's files: give its `derived` files too")
            return
        made = [self.derived_file(dict(given)) for given in derived]
        views = [self.view_file(dict(given)) for given in content.get("views") or []]
        names = {entry["name"] for entry, _, _ in made}
        existing = next(
            (
                asset
                for asset in assets
                if names & {entry_name(e) for e in latest_files(asset) if e["kind"] == "derived"}
            ),
            None,
        )
        if existing is None:
            derived_assets = [
                asset
                for asset in assets
                if any(e["kind"] == "derived" for e in latest_files(asset))
            ]
            existing = derived_assets[0] if len(derived_assets) == 1 else None
        variants = (
            bool(content["variants"])
            if "variants" in content
            else bool(existing and existing.get("variants"))
        )
        self.check_assets({"variants": variants}, [entry for entry, _, _ in made], bool(views))
        name = existing["name"] if existing else self.asset_name(item, item.get("title") or "asset")
        title = existing["title"] if existing else (item.get("title") or name)
        self.asset_version(item, name, title, [], made, views, variants, existing is None)

    def asset_name(self, item: dict[str, Any], words: str) -> str:
        taken = {asset["name"] for asset in item.get("assets", [])} | set(
            item.setdefault("planned", [])
        )
        base = slugged(words)
        name, number = base, 2
        while name in taken:
            name, number = f"{base}-{number}", number + 1
        item["planned"].append(name)
        return name

    def asset_version(
        self,
        item: dict[str, Any],
        name: str,
        title: str,
        projects: list[dict[str, Any]],
        made: list[tuple[dict[str, Any], bytes, dict[str, bytes]]],
        views: list[tuple[dict[str, Any], bytes]],
        variants: bool,
        new: bool,
    ) -> None:
        """A new version of one asset, in `assets/<name>/versions/next/`; a
        new asset's `created` first."""
        base = self.shared.item_folder(item["topic"], item["slug"]) / ASSETS / name
        names = (
            [entry["name"] for entry, _, _ in made]
            + [file for _, _, beside in made for file in beside]
            + [view["name"] for view, _ in views]
        )
        doubled = sorted({file for file in names if names.count(file) > 1})
        if doubled:
            raise UsageError(f"two files named {', '.join(doubled)}: rename one")
        if new:
            self.draft(base, {"kind": "created", "title": title})
        folder = base / VERSIONS / NEXT
        if folder.exists():
            raise ConflictError(
                f"{item['topic']}/{item['slug']} has an asset version being written"
            )
        folder.mkdir(parents=True)
        self.drafted.append(folder)
        for entry, data, beside in made:
            (folder / entry["name"]).write_bytes(data)
            for file, kept in beside.items():
                (folder / file).write_bytes(kept)
        for view, data in views:
            (folder / view["name"]).write_bytes(data)
        record: dict[str, Any] = {"files": [*projects, *(entry for entry, _, _ in made)]}
        if variants:
            record["variants"] = True
        if views:
            record["views"] = [view for view, _ in views]
        write_json(folder / ASSETS_FILE, record)

    def check_assets(
        self, item: dict[str, Any], entries: list[dict[str, Any]], views: bool = False
    ) -> None:
        """An asset holds one file, or variants of one type."""
        if len(entries) > 1 and not has_variants_flag(item):
            raise UsageError(
                "an asset holds one file: before and after are versions of one asset, and"
                " files shown with a decision are each an asset of it — several only as"
                ' variants, takes on one asset for the owner to prefer one (`"variants": true`)'
            )
        types = sorted({entry["type"] for entry in entries})
        if has_variants_flag(item) and len(types) > 1:
            raise UsageError(
                f"variants are takes on one asset, of one type — not {' and '.join(types)}:"
                " unrelated files are assets of their own"
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

    def project_file(self, given: str) -> dict[str, Any]:
        here = self.project.here.resolve()
        path = Path(given).expanduser()
        path = (path if path.is_absolute() else here / path).resolve()
        if not path.is_relative_to(here) or not path.is_file():
            raise UsageError(
                f"{given}: not a file in the repository — a project file is a path in it;"
                ' something made to show part of it goes in `derived` (`{"path": …, "from": […]}`)'
            )
        relative = str(path.relative_to(here))
        with path.open("rb") as handle:
            head = handle.read(65536)
        return {"kind": "project", "path": relative, "type": kind_of(relative, head)}

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
        if "/" in name or name in (DECISION_FILE, ASSETS_FILE):
            raise UsageError(f"{name}: not a file name to keep")
        recipe = {
            field: str(value).strip()
            for field, value in dict(given.get("recipe") or {}).items()
            if str(value).strip()
        }
        entry: dict[str, Any] = {
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
        with self.project.lock("topics"), self.drafting():
            item = self.item(ref)
            if item["verdict"] != Verdict.OPEN or any(
                entry["author"] == Author.OWNER for entry in item["thread"]
            ):
                raise PolicyError(
                    f"{item['ref']} has the owner's word on it: only an open item the owner has not"
                    " written on is deleted — give a new version instead"
                )
            folder = self.shared.item_folder(item["topic"], item["slug"])
            shutil.rmtree(folder)
            return self.settle([], removing=[folder]).note

    # --- the owner's word -------------------------------------------------------

    def prefer(
        self, ref: str, version: int, name: str | None, asset: str | None = None
    ) -> tuple[dict[str, Any], str | None]:
        """The owner's preferred variant in a version of an asset with
        variants, or none (`name` None): recorded and shown; a decision is
        accepted only once each asset with variants has one preferred. The
        asset is the one named, else the one with variants."""
        with self.project.lock("topics"), self.drafting():
            item = self.item(ref)
            candidates = [
                found
                for found in item["assets"]
                if (asset is None or found["name"] == asset) and found.get("variants")
            ]
            if not candidates:
                raise UsageError(f"{item['ref']} has no variants to prefer one of")
            chosen = candidates[0]
            if name is not None:
                for found in candidates:
                    record = next((v for v in found["versions"] if v["version"] == version), None)
                    names = [entry_name(entry) for entry in (record or {}).get("files", [])]
                    if name in names:
                        chosen = found
                        break
                else:
                    raise NotFoundError(f"{item['ref']} has no variant {name} in version {version}")
            folder = self.shared.item_folder(item["topic"], item["slug"]) / ASSETS / chosen["name"]
            path = self.draft(folder, {"kind": "preferred", "version": version, "name": name})
            settled = self.settle([path], Author.OWNER)
            return self.item(item["ref"]), settled.note

    def judge(self, ref: str, word: Word) -> tuple[dict[str, Any], str | None]:
        with self.project.lock("topics"), self.drafting():
            item = self.item(ref)
            verdict = verdict_of(word)
            if verdict is Verdict.ACCEPTED and unpreferred(item):
                raise ConflictError(
                    f"{item['ref']} has {len(variants_of(item))} variants: prefer one before accepting it"
                )
            path = self.verdict_draft(item, verdict, word)
            settled = self.settle([path], self.judging())
            return self.item(item["ref"]), settled.note

    def judging(self) -> Author:
        """Who gives a verdict: the owner, through the studio or `/nock-triage`;
        Tidy up's drops are its own."""
        return Author.AGENT if self.project.current_role() == TIDIER else Author.OWNER

    def verdict_draft(self, item: dict[str, Any], verdict: Verdict, word: Word | None) -> Path:
        record: dict[str, Any] = {"kind": "verdict", "verdict": str(verdict)}
        comment = str((word or {}).get("comment") or "").strip()
        if comment:
            record["comment"] = comment
        return self.draft(self.shared.item_folder(item["topic"], item["slug"]), record)

    def judge_topic(self, name: str, word: Word) -> tuple[list[str], str | None]:
        """The verdict on every open item of a topic; the comment in the topic's thread."""
        with self.project.lock("topics"), self.drafting():
            topic = self.topic(name)
            name = topic["name"]
            verdict = verdict_of(word)
            judged, written = [], []
            for item in self.items(name):
                # Accepting all leaves out what cannot be accepted yet: variants with none preferred.
                if awaits_owner(item) and not (verdict is Verdict.ACCEPTED and unpreferred(item)):
                    written.append(self.verdict_draft(item, verdict, None))
                    judged.append(item["ref"])
            if not judged:
                if any(awaits_owner(item) for item in self.items(name)):
                    raise ConflictError(
                        f"topic {name}: every open item has variants with none preferred — prefer one first"
                    )
                raise ConflictError(f"topic {name} has nothing open")
            comment = str(word.get("comment") or "").strip()
            if comment:
                written.append(
                    self.draft(
                        self.shared.topic_folder(name),
                        {"kind": "message", "text": comment, "verdict": str(verdict)},
                    )
                )
            settled = self.settle(written, self.judging())
            return judged, settled.note

    def withdraw(
        self,
        ref: str | None = None,
        topic: str | None = None,
        keep: Callable[[Path, dict[str, Any]], None] | None = None,
    ) -> str:
        """Take back the owner's message still waiting for its answer, in an
        item's thread (`ref`) or a topic's: its text, to write again; each
        file it carried is handed to `keep` first."""
        with self.project.lock("topics"), self.drafting():
            if ref is not None:
                record = self.item(ref)
                where = record["ref"]
                folder = self.shared.item_folder(record["topic"], record["slug"])
            elif topic is not None:
                record = self.topic(topic)
                where = record["name"]
                folder = self.shared.topic_folder(record["name"])
            else:
                raise UsageError("give `ref` or `topic`")
            if not pending(record["thread"], record.get("decided")):
                raise ConflictError(f"{where} has no message of yours waiting: nothing to withdraw")
            waiting = talk(record["thread"])[-1]
            for entry in waiting.get("attachments", []):
                path = self.where(entry, "")
                if keep is not None and path.is_file():
                    keep(path, entry)
            path = self.draft(folder, {"kind": "message", "withdraws": waiting["id"]})
            self.settle([path], Author.OWNER)
            return waiting["text"]

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
            if not any(by(version, {session}) for version in every_version(item)):
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
                for version in every_version(item)
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
        """The decisions neither rejected nor dropped with an asset whose latest
        version holds this project file or was derived from it, not yet shown this session; showing them is
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
            latest = (
                item["latest"]
                if summed is not None
                else [entry for asset in item["assets"] for entry in latest_files(asset)]
            )
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


def folder_stamp(folder: Path) -> list[list[Any]]:
    """What changes when a decision gains an event or an asset does: the
    modification time of each of its event folders and of its assets' folder."""
    places = [folder / EVENTS, folder / ASSETS, *sorted((folder / ASSETS).glob(f"*/{EVENTS}"))]
    stamp = []
    for place in places:
        try:
            status = place.stat()
        except OSError:
            continue
        stamp.append([str(place.relative_to(folder)), status.st_mtime_ns])
    return stamp


def summary(item: dict[str, Any]) -> dict[str, Any]:
    """What `news_for` and `governing` look for in a decision: who wrote its
    versions and its assets', the owner's word on it, and its assets' latest
    files."""
    return {
        "slug": item["slug"],
        "created": moment(item["created"]),
        "verdict": item["verdict"],
        "writers": [
            stamp[key]
            for stamp in every_version(item)
            for key in ("session", "parent")
            if key in stamp
        ],
        "word": owner_word(item),
        "moment": owner_moment(item),
        "latest": [
            {key: entry[key] for key in ("path", "from") if key in entry}
            for asset in item["assets"]
            for entry in latest_files(asset)
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


def has_variants_flag(item: dict[str, Any]) -> bool:
    return bool(item.get("variants") or item.get("options"))


def every_version(item: dict[str, Any]) -> list[dict[str, Any]]:
    """A decision's versions and its assets', each with who made it."""
    return [*item["versions"], *(v for asset in item.get("assets", []) for v in asset["versions"])]


def latest_files(asset: dict[str, Any]) -> list[dict[str, Any]]:
    return asset["versions"][-1]["files"] if asset["versions"] else []


def has_variants(item: dict[str, Any]) -> bool:
    """Whether one of a decision's assets holds variants in its latest version."""
    return any(asset.get("variants") for asset in item.get("assets", []))


def variants_of(item: dict[str, Any]) -> list[dict[str, Any]]:
    """The variants of a decision's first asset that has them."""
    for asset in item.get("assets", []):
        if asset.get("variants"):
            return latest_files(asset)
    return []


def unpreferred(item: dict[str, Any]) -> bool:
    """An asset with variants, none of its latest version's preferred: the
    decision is not to accept yet."""
    return any(asset_unpreferred(asset) for asset in item.get("assets", []))


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
    refs = [str(ref) for ref in decision.get("assets") or []]
    cited = {"assets": refs} if refs else {}
    return (
        json.dumps(
            {"answer": answer, "alternatives": alternatives, "status": status, **cited},
            indent=2,
            ensure_ascii=False,
        )
        + "\n"
    ).encode()
