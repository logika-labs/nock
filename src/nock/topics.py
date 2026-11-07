"""Topics and items: what agents put before the owner. A topic is a piece of
work — a name, why it exists, a thread — holding items; an item is bare: a
title and, in each of its versions, files of three kinds: a decision (nock's
own JSON: the answer, the alternatives weighed, done or todo), project files
(copied when the version is made, so versions compare) and derived files
(something made to show part of the project, with what it comes from, when
it applies and how to make it again). The owner alone gives an item its
verdict (accepted, rejected; open until then), on the page or with
`/nock-triage`; both sides talk in the threads, a chat: the owner's
message waits for the agent's one answer (`pending`), and is withdrawn
until it comes. Everything lives in the main
checkout's `.nock/topics/TOPIC/` (a file over `LARGE` bytes under
`.nock/local/topics/` instead, uncommitted), committed as it is written,
whichever worktree writes it, so the owner sees it at once.

A finished topic (every item decided) that comes back is revived: a note in
its thread says why, and reads as its description from then on; its items
from before stay, as earlier rounds."""

from __future__ import annotations

import fnmatch
import json
import re
import shutil
from collections import Counter
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Any, NotRequired, TypedDict

from nock.errors import ConflictError, NotFoundError, PolicyError, UsageError
from nock.render import Problem
from nock.utils import now, read_json, write_json

if TYPE_CHECKING:
    from nock.project import Project

TOPIC_FILE = "topic.json"
ITEM_FILE = "item.json"
DECISION_FILE = "decision.json"
PROJECT_FILES = "project"
MAP = "map.md"
GENERAL = "general"
# The git states in which a commit would land in the middle of someone's work.
BUSY_MARKERS = ("MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD", "rebase-merge", "rebase-apply")
# A file larger than this (most videos) is kept on this machine, uncommitted.
LARGE = 20 * 1024 * 1024
NAME = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
# How the map cites an item: `[topic/slug]`, or a migrated decision by its number, `[D7]`.
CITATION = re.compile(r"\[(?:D(\d+)|([a-z0-9][a-z0-9-]*/[a-z0-9][a-z0-9-]*))\](?!\()")
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


class Status(StrEnum):
    DONE = "done"
    """Decided and carried out."""
    TODO = "todo"
    """Should be done, and is not yet."""


class State(StrEnum):
    """Where a task is."""

    QUEUED = "queued"
    RUNNING = "running"
    WAITING = "waiting"
    """On the owner or another task: `waiting_on` says which."""
    DONE = "done"
    """Merged or finished: accepted by itself, its thread keeping the final report."""
    FAILED = "failed"
    """Open for the owner."""


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
    },
)
"""A derived file: `path` (a file to copy) or `text` with a `name`; `from`,
the project files it shows; `when`, the condition it shows ("the payment
lapsed"); `recipe`, how to make it again."""


class Content(TypedDict):
    """What a version holds: a decision, project files, derived files, or several."""

    decision: NotRequired[Decision]
    files: NotRequired[list[str]]
    """Project files, by their path in the repository, copied as they are now."""
    derived: NotRequired[list[Derived]]


class Task(TypedDict):
    """Work dispatched to an agent: what was asked, where it runs, where it is."""

    brief: str
    """What was asked, in a few lines."""
    branch: NotRequired[str]
    worktree: NotRequired[str]
    state: NotRequired[State]
    """queued (the default), running, waiting, done or failed."""
    waiting_on: NotRequired[str]
    """With `waiting`: `owner`, or the ref of the task it waits on."""


class ItemDraft(Content):
    title: str
    """What it is, in a line; for a decision, what was decided, as a statement."""
    slug: NotRequired[str]
    """Its name in the topic (`topic/slug`); made from the title when left out."""
    task: NotRequired[Task]
    """A task instead of files: work dispatched, kept current by its state."""


class ItemChange(Content):
    title: NotRequired[str]
    topic: NotRequired[str]
    """Move it to this existing topic: re-filing, whatever its verdict; its slug
    kept (suffixed if taken there), its old ref kept as an alias."""
    brief: NotRequired[str]
    branch: NotRequired[str]
    worktree: NotRequired[str]
    state: NotRequired[State]
    """A task's state: done accepts it, failed leaves it open for the owner."""
    waiting_on: NotRequired[str]


# What of a change is a task's.
TASK_FIELDS = ("brief", "branch", "worktree", "state", "waiting_on")


class TopicDraft(TypedDict):
    name: str
    """Lowercase words joined by `-`: `checkout-emails`."""
    description: str
    """Why it exists, as part of what work, in a sentence or two."""


class TopicChange(TypedDict):
    name: NotRequired[str]
    description: NotRequired[str]


class Word(TypedDict):
    """The owner's verdict, with what they say about it."""

    verdict: Verdict
    comment: NotRequired[str]


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


def message(author: Author, text: str, session: str | None, **extra: Any) -> dict[str, Any]:
    if not text.strip():
        raise UsageError("the message is empty")
    return {
        "author": str(author),
        "moment": now(),
        "text": text.strip(),
        **({"session": session} if session else {}),
        **extra,
    }


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

    def resolve(self, ref: str) -> tuple[str, str]:
        """A ref's topic and slug: `topic/slug`, a number an item keeps as an
        alias (`170`, `D170`, `topic/170`), or a ref it had before it moved."""
        ref = ref.strip().strip("/")
        topic, _, slug = ref.rpartition("/")
        if topic and (self.directory / topic / slug / ITEM_FILE).is_file():
            return topic, slug
        alias = slug.removeprefix("D")
        for item in self.every():
            aliases = item.get("aliases", [])
            if ref in aliases or (
                alias.isdigit() and alias in aliases and topic in ("", item["topic"])
            ):
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

    def folder(self, topic: str, slug: str, version: int) -> Path:
        return self.directory / topic / slug / str(version)

    def decision(self, item: dict[str, Any], version: dict[str, Any]) -> dict[str, Any] | None:
        if not any(entry["kind"] == "decision" for entry in version["files"]):
            return None
        return read_json(
            self.folder(item["topic"], item["slug"], version["version"]) / DECISION_FILE
        )

    def file(self, topic: str, slug: str, version: int, name: str) -> Path:
        """Where one of a version's files is: only a file its record names."""
        item = self.item(f"{topic}/{slug}")
        record = next((entry for entry in item["versions"] if entry["version"] == version), None)
        listed = record and next(
            (entry for entry in record["files"] if entry_name(entry) == name), None
        )
        if not listed:
            raise NotFoundError(f"item {topic}/{slug} has no file {name} in version {version}")
        base = self.large if listed.get("local") else self.directory
        return base / topic / slug / str(version) / stored(listed)

    def shown(self, item: dict[str, Any]) -> dict[str, Any]:
        """An item with each version's decision read and each file's path."""
        versions = []
        for version in item["versions"]:
            files = []
            for entry in version["files"]:
                if entry["kind"] == "decision":
                    continue
                base = self.large if entry.get("local") else self.directory
                path = base / item["topic"] / item["slug"] / str(version["version"]) / stored(entry)
                files.append({**entry, "name": entry_name(entry), "where": str(path)})
            versions.append({**version, "decision": self.decision(item, version), "files": files})
        return {**item, "versions": versions}

    def current_description(self, topic: dict[str, Any]) -> str:
        """The latest revival note, once the topic came back; its description before."""
        revivals = [entry for entry in topic["thread"] if entry.get("kind") == "revival"]
        return revivals[-1]["text"] if revivals else topic["description"]

    def activity(self, topic: dict[str, Any], items: list[dict[str, Any]]) -> str:
        moments = [topic["updated"], *(item["updated"] for item in items)]
        return max(moments)

    def finished(self, topic: dict[str, Any], items: list[dict[str, Any]]) -> bool:
        """Every item decided, and no revival since the last verdict."""
        if not items or any(item["verdict"] == Verdict.OPEN for item in items):
            return False
        decided = max(moment(item.get("decided")) for item in items)
        revived = [entry["moment"] for entry in topic["thread"] if entry.get("kind") == "revival"]
        return not revived or max(revived) < decided

    def counts(self, items: list[dict[str, Any]]) -> dict[str, int]:
        counted = Counter(item["verdict"] for item in items)
        return {verdict: counted.get(verdict, 0) for verdict in map(str, Verdict)}

    def row(self, name: str) -> dict[str, Any]:
        topic = self.topic(name)
        items = self.items(name)
        return {
            "name": name,
            "description": self.current_description(topic),
            **self.counts(items),
            "finished": self.finished(topic, items),
            "active": self.activity(topic, items),
        }

    def awaiting(self) -> dict[str, list[str]]:
        """What waits on an agent: the threads where the owner wrote last, and
        the items they rejected, not yet reworked."""
        threads, rejected = [], []
        for name in self.names():
            topic = self.topic(name)
            if topic["thread"] and topic["thread"][-1]["author"] == Author.OWNER:
                threads.append(name)
            for item in self.items(name):
                if item["thread"] and item["thread"][-1]["author"] == Author.OWNER:
                    threads.append(item["ref"])
                if item["verdict"] == Verdict.REJECTED:
                    rejected.append(item["ref"])
        return {"owner_wrote_last": threads, "rejected": rejected}

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
        if item.get("task"):
            kinds = ["task"]
        return {
            "ref": item["ref"],
            "title": item["title"],
            "verdict": item["verdict"],
            **({"state": item["task"]["state"]} if item.get("task") else {}),
            "kinds": kinds,
            "versions": len(item["versions"]),
            "updated": item["updated"],
        }

    # --- searching --------------------------------------------------------------

    def item_text(self, item: dict[str, Any]) -> tuple[str, str]:
        """An item's title, and the rest of what it says, for search."""
        parts = [entry["text"] for entry in item["thread"]]
        if item.get("task"):
            parts += [item["task"]["brief"], item["task"].get("branch") or ""]
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
        heading, body = heading.lower(), body.lower()
        matched = [word for word in words if word in heading or word in body]
        if not matched:
            return 0
        weight = sum(3 * heading.count(word) + body.count(word) for word in matched)
        return len(matched) * 1000 + min(weight, 999)

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

    def recorded(self) -> dict[str, Any]:
        return {
            "moment": now(),
            "session": self.project.current_session(),
            "role": self.project.current_role() or "interactive",
        }

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
        with self.project.lock("topics"):
            if (self.directory / name / TOPIC_FILE).is_file():
                topic, items = self.topic(name), self.items(name)
                again = (
                    f' — it is finished; revive it: `.nock/nock topics update {name} --revive "why it is back"`'
                    if self.finished(topic, items)
                    else ": submit into it"
                )
                raise ConflictError(f"topic {name} exists{again}")
            topic = {
                "name": name,
                "description": draft["description"].strip(),
                "created": self.recorded(),
                "thread": [],
            }
            path = self.save_topic(topic)
            return topic, self.commit([path], f"Topic {name}: {topic['description'][:80]}")

    def update_topic(
        self,
        name: str,
        change: TopicChange,
        reply: str | None = None,
        revive: str | None = None,
        author: Author = Author.AGENT,
    ) -> tuple[dict[str, Any], str | None]:
        if not change and reply is None and revive is None:
            raise UsageError("nothing to do: give a change, `--reply`, or `--revive`")
        with self.project.lock("topics"):
            topic = self.topic(name)
            session = self.project.current_session()
            touched = [self.directory / name]
            if "description" in change:
                if not change["description"].strip():
                    raise UsageError("`description` is empty")
                topic["description"] = change["description"].strip()
            if revive is not None:
                if not self.finished(topic, self.items(name)):
                    raise ConflictError(
                        f"topic {name} is not finished: submit into it, no need to revive it"
                    )
                topic["thread"].append(message(author, revive, session, kind="revival"))
            if reply is not None:
                topic["thread"].append(said_in(topic["thread"], author, reply, session))
            if "name" in change and change["name"] != name:
                renamed = check_name(change["name"])
                if (self.directory / renamed).exists():
                    raise ConflictError(f"topic {renamed} exists")
                (self.directory / name).rename(self.directory / renamed)
                if (self.large / name).is_dir():
                    (self.large / name).rename(self.large / renamed)
                topic["name"] = renamed
                touched.append(self.directory / renamed)
            self.save_topic(topic)
            said = "revived" if revive is not None else "updated"
            return topic, self.commit(touched, f"Topic {topic['name']}, {said}")

    def delete_topic(self, name: str) -> str | None:
        with self.project.lock("topics"):
            self.topic(name)
            if self.items(name):
                raise ConflictError(f"topic {name} holds items: only an empty topic is deleted")
            shutil.rmtree(self.directory / name)
            return self.commit([self.directory / name], f"Topic {name}, deleted")

    # --- items ------------------------------------------------------------------

    def create_item(self, topic: str, draft: ItemDraft) -> tuple[dict[str, Any], str | None]:
        title = draft["title"].strip()
        if not title:
            raise UsageError("`title` is empty")
        with self.project.lock("topics"):
            record = self.topic(topic)
            items = self.items(topic)
            if self.finished(record, items):
                raise ConflictError(
                    f"topic {topic} is finished: if this brings it back, revive it first —"
                    f' `.nock/nock topics update {topic} --revive "why it is back"` — or open another topic'
                )
            slug = check_name(draft["slug"], "slug") if "slug" in draft else slugged(title)
            taken = {item["slug"] for item in items}
            if "slug" in draft and slug in taken:
                raise ConflictError(f"{topic}/{slug} exists: update it, or give another slug")
            base, number = slug, 2
            while slug in taken or slug.isdigit():
                slug, number = f"{base}-{number}", number + 1
            stamp = self.recorded()
            item: dict[str, Any] = {
                "slug": slug,
                "title": title,
                "aliases": [],
                "verdict": str(Verdict.OPEN),
                "decided": None,
                "created": stamp,
                "updated": stamp["moment"],
                "thread": [],
                "versions": [],
            }
            if "task" in draft:
                if any(key in draft for key in ("decision", "files", "derived")):
                    raise UsageError("a task holds nothing else: submit files as their own item")
                item["task"] = {"brief": "", "state": str(State.QUEUED), "started": None}
                self.set_task(item, dict(draft["task"]))
                item["versions"].append({"version": 1, **stamp, "files": []})
            else:
                self.add_version(topic, item, draft, None)
            path = self.save_item(topic, item)
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
    ) -> tuple[dict[str, Any], str | None]:
        if not change and version is None and reply is None:
            raise UsageError("nothing to do: give a change, `--version`, or `--reply`")
        change = ItemChange(**change) if change else None
        moving = change.pop("topic", None) if change else None
        with self.project.lock("topics"):
            item = self.item(ref)
            said = []
            touched = [self.directory / item["topic"] / item["slug"]]
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
                tasked = {key: value for key, value in change.items() if key in TASK_FIELDS}
                content = {
                    key: value
                    for key, value in change.items()
                    if key != "title" and key not in TASK_FIELDS
                }
                if item.get("task") and content:
                    raise UsageError("a task holds nothing else: submit files as their own item")
                if tasked:
                    if not item.get("task"):
                        raise UsageError(f"{', '.join(tasked)}: only a task has them")
                    self.set_task(item, tasked)
                if content:
                    latest = item["versions"].pop()
                    self.add_version(topic, item, content, latest)
                said.append("updated")
            if version is not None:
                if item.get("task"):
                    raise UsageError("a task has no versions: change its state, or reply")
                if "title" in version:
                    item["title"] = version["title"].strip() or item["title"]
                self.add_version(topic, item, version, item["versions"][-1])
                item["verdict"] = str(Verdict.OPEN)
                item["decided"] = None
                said.append(f"version {item['versions'][-1]['version']}")
            if reply is not None:
                said_now = said_in(
                    item["thread"],
                    author,
                    reply,
                    self.project.current_session(),
                    item.get("decided"),
                )
                item["thread"].append(said_now)
                said.append("answered" if "answers" in said_now else "replied")
            if item.get("task") and author is Author.AGENT:
                item["task"]["heard"] = now()
            path = self.save_item(topic, item)
            return self.with_ref(topic, item), self.commit(
                [*touched, path.parent, self.large / topic / item["slug"]],
                f"Item {topic}/{item['slug']}, {', '.join(said)}: {item['title']}",
            )

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
        while moved in taken:
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

    def set_task(self, item: dict[str, Any], fields: dict[str, Any]) -> None:
        """Fold a task's fields in: running starts its clock, waiting names
        what on, done accepts it by itself, failed leaves it open."""
        task = item["task"]
        for key in ("brief", "branch", "worktree"):
            if key in fields:
                task[key] = str(fields[key]).strip() or None
        if not task.get("brief"):
            raise UsageError("a task's `brief` is empty: say what was asked")
        state = State(fields.get("state") or task["state"])
        waiting_on = str(fields.get("waiting_on") or "").strip() or None
        if state is State.WAITING:
            waiting_on = waiting_on or task.get("waiting_on")
            if not waiting_on:
                raise UsageError("`waiting` says on what: `waiting_on` is `owner` or a task's ref")
            if waiting_on != "owner":
                self.resolve(waiting_on)
        else:
            waiting_on = None
        task["state"], task["waiting_on"] = str(state), waiting_on
        if state is not State.QUEUED and not task.get("started"):
            task["started"] = now()
        task["heard"] = now()
        if state is State.DONE:
            item["verdict"] = str(Verdict.ACCEPTED)
            item["decided"] = {
                "moment": now(),
                "session": self.project.current_session(),
                "by": "done",
            }
        elif item["verdict"] == Verdict.ACCEPTED and item.get("decided", {}).get("by") == "done":
            item["verdict"], item["decided"] = str(Verdict.OPEN), None

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
        carried: list[tuple[dict[str, Any], bytes]] = []
        if derived is None and previous is not None:
            for entry in previous["files"]:
                if entry["kind"] == "derived":
                    base = self.large if entry.get("local") else self.directory
                    source = base / topic / item["slug"] / str(previous["version"]) / entry["name"]
                    carried.append((entry, source.read_bytes()))
        if not decision and not files and not derived and not carried:
            raise UsageError(
                "an item holds something: give `decision`, `files`, `derived`, or several"
            )
        made: list[tuple[dict[str, Any], bytes]] = []
        if decision:
            made.append(({"kind": "decision", "name": DECISION_FILE}, checked_decision(decision)))
        for path in files or []:
            made.append(self.project_file(path))
        for given in derived or []:
            made.append(self.derived_file(dict(given)))
        made += carried
        names = [stored(entry) for entry, _ in made]
        doubled = sorted({name for name in names if names.count(name) > 1})
        if doubled:
            raise UsageError(f"two files named {', '.join(doubled)}: rename one")
        folder = self.folder(topic, item["slug"], number)
        if in_place and old_folder is not None:
            shutil.rmtree(old_folder, ignore_errors=True)
            shutil.rmtree(self.large / topic / item["slug"] / str(number), ignore_errors=True)
        entries = []
        for entry, data in made:
            local = len(data) > LARGE
            target = (self.large if local else self.directory) / topic / item["slug"] / str(number)
            target = target / stored(entry)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            if entry["kind"] != "decision":
                entry = {**entry, "bytes": len(data), "local": local}
            entries.append(entry)
        folder.mkdir(parents=True, exist_ok=True)
        stamp = self.recorded()
        record = {"version": number, **stamp, "files": entries}
        item["versions"].append(record)

    def project_file(self, given: str) -> tuple[dict[str, Any], bytes]:
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
        return {"kind": "project", "path": relative, "type": kind_of(relative, data)}, data

    def derived_file(self, given: dict[str, Any]) -> tuple[dict[str, Any], bytes]:
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
        return entry, data

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

    def judge(self, ref: str, word: Word) -> tuple[dict[str, Any], str | None]:
        with self.project.lock("topics"):
            item = self.item(ref)
            self.give(item, word)
            path = self.save_item(item["topic"], item)
            return item, self.commit(
                [path], f"Item {item['ref']}, {word['verdict']}: {item['title']}"
            )

    def give(self, item: dict[str, Any], word: Word) -> None:
        verdict = Verdict(word["verdict"])
        if verdict is Verdict.OPEN:
            raise UsageError("a verdict is accepted or rejected")
        item["verdict"] = str(verdict)
        item["decided"] = {"moment": now(), "session": self.project.current_session()}
        comment = str(word.get("comment") or "").strip()
        if comment:
            item["thread"].append(
                message(Author.OWNER, comment, self.project.current_session(), verdict=str(verdict))
            )

    def judge_topic(self, name: str, word: Word) -> tuple[list[str], str | None]:
        """The verdict on every open item of a topic; the comment in the topic's thread."""
        with self.project.lock("topics"):
            topic = self.topic(name)
            judged, paths = [], []
            for item in self.items(name):
                if awaits_owner(item):
                    self.give(item, Word(verdict=word["verdict"]))
                    paths.append(self.save_item(name, item))
                    judged.append(item["ref"])
            if not judged:
                raise ConflictError(f"topic {name} has nothing open")
            comment = str(word.get("comment") or "").strip()
            if comment:
                topic["thread"].append(
                    message(
                        Author.OWNER,
                        comment,
                        self.project.current_session(),
                        verdict=str(word["verdict"]),
                    )
                )
                paths.append(self.save_topic(topic))
            return judged, self.commit(
                paths, f"Topic {name}, {word['verdict']}: {len(judged)} item(s)"
            )

    def withdraw(self, ref: str | None = None, topic: str | None = None) -> str:
        """Take back the owner's message still waiting for its answer, in an
        item's thread (`ref`) or a topic's: its text, to write again."""
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
            text = record["thread"].pop()["text"]
            if ref is not None:
                path = self.save_item(record["topic"], record)
            else:
                path = self.save_topic(record)
            self.commit(
                [path], f"{'Item' if ref is not None else 'Topic'} {where}, a message withdrawn"
            )
            return text

    def reply(self, ref: str, text: str, author: Author) -> str | None:
        """A message in a topic's thread (a ref without `/`) or an item's."""
        if "/" in ref.strip("/") or ref.strip().removeprefix("D").isdigit():
            return self.update_item(ref, None, reply=text, author=author)[1]
        return self.update_topic(ref, {}, reply=text, author=author)[1]

    # --- telling the agents -----------------------------------------------------

    def news_for(self, session: str) -> list[dict[str, Any]]:
        """The items this session made on which the owner has said something
        (a verdict, a message) it has not been told yet; telling it is recorded."""
        told = {
            (row["item"], row["updated"])
            for row in self.project.store.rows(
                "SELECT item, updated FROM told WHERE session = ?", (session,)
            )
        }
        news = []
        for item in self.every():
            if session not in {version.get("session") for version in item["versions"]}:
                continue
            said = owner_moment(item)
            if not said or (item["ref"], said) in told:
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
            said = owner_moment(item)
            if not said or (refs is not None and item["ref"] not in refs):
                continue
            sessions = {
                version["session"] for version in item["versions"] if version.get("session")
            }
            for session in sorted(sessions):
                if (session, item["ref"], said) not in told:
                    self.project.store.insert(
                        "told", {"session": session, "item": item["ref"], "updated": said}
                    )
                    marked += 1
        return marked

    def governing(self, session: str, path: str) -> list[dict[str, Any]]:
        """The items not rejected whose latest version holds this project file
        or was derived from it, not yet shown this session; showing them is
        recorded."""
        shown = {
            row["item"]
            for row in self.project.store.rows(
                "SELECT item FROM shown_items WHERE session = ?", (session,)
            )
        }
        found = []
        for item in self.every():
            if item["verdict"] == Verdict.REJECTED or item["ref"] in shown:
                continue
            latest = item["versions"][-1]["files"]
            if any(
                entry.get("path") == path
                or any(fnmatch.fnmatchcase(path, source) for source in entry.get("from", []))
                for entry in latest
            ):
                found.append(item)
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
                ref = match.group(1) or match.group(2)
                try:
                    self.resolve(ref)
                except NotFoundError:
                    problems.append(Problem(f"[{match.group(0)[1:-1]}] is no item", place, line))
        return problems

    def commit(self, paths: list[Path], message: str) -> str | None:
        root = self.project.root
        relative = [
            str(path.relative_to(root)) for path in paths if path.is_relative_to(self.directory)
        ]
        return committed(self.project, relative, message) if relative else None


def pending(thread: list[dict[str, Any]], decided: dict[str, Any] | None = None) -> bool:
    """The owner wrote last, and not with a verdict: their message waits for
    the agent's answer, and the chat is closed to them until it comes. A
    verdict given since (`decided`) overrides it: the verdict is the answer."""
    if not thread or thread[-1]["author"] != Author.OWNER or thread[-1].get("verdict"):
        return False
    return moment(decided) < thread[-1]["moment"]


def said_in(
    thread: list[dict[str, Any]],
    author: Author,
    text: str,
    session: str | None,
    decided: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """A message for this thread: the owner's only once their last has its
    answer (or they withdraw it); the agent's answers the owner's waiting one,
    and may follow it with more."""
    if author is Author.OWNER and pending(thread, decided):
        raise ConflictError(
            "your last message waits for the agent's answer: withdraw it to change it"
        )
    if author is Author.AGENT and pending(thread, decided):
        return message(author, text, session, answers=thread[-1]["moment"])
    return message(author, text, session)


def chat_state(
    thread: list[dict[str, Any]], seen: str | None, decided: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Where a thread stands for the owner: `pending`, their message waiting
    for its answer; `unseen`, the agent's messages since they last looked
    (or last wrote), and whether one of them is the answer they waited for.
    A thread they never opened nor wrote in shows nothing as new."""
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


def awaits_owner(item: dict[str, Any]) -> bool:
    """Open, and the owner's to look at: a task only once it failed."""
    if item["verdict"] != Verdict.OPEN:
        return False
    return not item.get("task") or item["task"]["state"] == State.FAILED


def owner_moment(item: dict[str, Any]) -> str:
    """When the owner last said something on an item: a verdict (not a task
    accepted by being done) or a message."""
    decided = item.get("decided") or {}
    moments = [moment(decided) if decided.get("by") != "done" else ""]
    moments += [entry["moment"] for entry in item["thread"] if entry["author"] == Author.OWNER]
    return max(moments)


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


def entry_name(entry: dict[str, Any]) -> str:
    return entry.get("path") or entry["name"]


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
