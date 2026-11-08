"""Topics and items: what agents put before the owner. A topic is a piece of
work — a name, why it exists, a thread — holding items; an item is bare: a
title and, in each of its versions, one of: a decision (nock's own JSON: the
answer, the alternatives weighed, done or todo, with the project files it
concerns), a project file (copied when the version is made, so versions
compare) or a derived file (something made to show part of the project, with
what it comes from, when it applies and how to make it again). One asset per
item; several only as options, variants of one asset side by side, of which
the owner may prefer one. The owner alone gives an item its
verdict (accepted, rejected; open until then), on the page or with
`/nock-triage`; both sides talk in the threads, a chat: the owner's
message waits for the agent's one answer (`pending`), and is withdrawn
until it comes. Everything lives in the main
checkout's `.nock/topics/TOPIC/` (a file over `LARGE` bytes under
`.nock/local/topics/` instead, uncommitted), committed as it is written,
whichever worktree writes it, so the owner sees it at once.

A topic's progress is its own: a `state` (planned, active, done, abandoned)
and a `status`, a line its agent keeps current as it works; each change is a
status entry in its thread, so the history stays. A done or abandoned topic
takes no new items; when its work comes back it is revived, set active again
with a note that says why, which reads as its description from then on. Every
record keeps who wrote it: the session, its role and, for a subagent or a
session nock dispatched, its parent session."""

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
# A thread's note that the item was split out of one holding several files.
SPLIT = "split"
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
    """Where a topic's work is."""

    PLANNED = "planned"
    ACTIVE = "active"
    DONE = "done"
    """Finished: it takes no new items until it is revived."""
    ABANDONED = "abandoned"
    """Given up: like done, it takes no new items until it is revived."""


# The states in which a topic takes no new items.
CLOSED = (State.DONE, State.ABANDONED)
# A thread's entry recording a change of the topic's state or status.
STATUS = "status"


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
    """What a version holds: a decision (with the project files it concerns),
    or one file, project or derived; several files only as options."""

    decision: NotRequired[Decision]
    files: NotRequired[list[str]]
    """Project files, by their path in the repository, copied as they are now:
    one, or with a decision those it concerns."""
    derived: NotRequired[list[Derived]]
    options: NotRequired[bool]
    """The files are options: variants of one asset (three takes on one
    picture), of one type, shown side by side for the owner to prefer one;
    never unrelated files, which are items of their own."""


class ItemDraft(Content):
    title: str
    """What it is, in a line; for a decision, what was decided, as a statement."""
    slug: NotRequired[str]
    """Its name in the topic (`topic/slug`); made from the title when left out."""


class ItemChange(Content):
    title: NotRequired[str]
    topic: NotRequired[str]
    """Move it to this existing topic: re-filing, whatever its verdict; its slug
    kept (suffixed if taken there), its old ref kept as an alias."""


class TopicDraft(TypedDict):
    name: str
    """Lowercase words joined by `-`: `checkout-emails`."""
    description: str
    """Why it exists, as part of what work, in a sentence or two."""
    state: NotRequired[State]
    """planned, or active (the default): work under way."""
    status: NotRequired[str]
    """Where the work is, in a line: "eval running, about 2 h"."""


class TopicChange(TypedDict):
    name: NotRequired[str]
    description: NotRequired[str]
    state: NotRequired[State]
    """planned, active, done (finished) or abandoned; a change of state
    without a `status` clears the status."""
    status: NotRequired[str]
    """Where the work is, in a line, kept current at each milestone:
    "waiting for the gate on main"."""


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


def message(
    author: Author, text: str, writer: dict[str, str | None], **extra: Any
) -> dict[str, Any]:
    if not text.strip():
        raise UsageError("the message is empty")
    return {
        "author": str(author),
        "moment": now(),
        "text": text.strip(),
        **{key: value for key, value in writer.items() if value},
        **extra,
    }


def state_of(topic: dict[str, Any]) -> State:
    return State(topic.get("state") or State.ACTIVE)


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
            "state": str(state_of(topic)),
            **({"status": topic["status"]} if topic.get("status") else {}),
            "description": self.current_description(topic),
            **self.counts(items),
            "active": self.activity(topic, items),
        }

    def awaiting(self) -> dict[str, list[str]]:
        """What waits on an agent: the threads where the owner wrote last, and
        the items they rejected, not yet reworked."""
        threads, rejected = [], []
        for name in self.names():
            topic = self.topic(name)
            said = talk(topic["thread"])
            if said and said[-1]["author"] == Author.OWNER:
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
        return {
            "ref": item["ref"],
            "title": item["title"],
            "verdict": item["verdict"],
            "kinds": kinds,
            **({"options": True} if item.get("options") else {}),
            **({"preferred": item["preferred"]} if item.get("preferred") else {}),
            "versions": len(item["versions"]),
            "updated": item["updated"],
        }

    # --- searching --------------------------------------------------------------

    def item_text(self, item: dict[str, Any]) -> tuple[str, str]:
        """An item's title, and the rest of what it says, for search."""
        parts = [entry["text"] for entry in item["thread"]]
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

    def recorded(self) -> dict[str, Any]:
        return {"moment": now(), **self.project.writer()}

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
            raise UsageError("a topic opens planned or active: its work is still to do")
        with self.project.lock("topics"):
            if (self.directory / name / TOPIC_FILE).is_file():
                again = (
                    f" — it is {state_of(self.topic(name))}; revive it:"
                    f' `.nock/nock topics update {name} --revive "why it is back"`'
                    if state_of(self.topic(name)) in CLOSED
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
            raise UsageError(
                "nothing to do: give a change (`state`, `status`, …), `--reply`, or `--revive`"
            )
        with self.project.lock("topics"):
            topic = self.topic(name)
            touched = [self.directory / name]
            said = []
            if "description" in change:
                if not change["description"].strip():
                    raise UsageError("`description` is empty")
                topic["description"] = change["description"].strip()
                said.append("updated")
            standing: dict[str, Any] = {
                key: value for key, value in change.items() if key in ("state", "status")
            }
            if revive is not None:
                if state_of(topic) not in CLOSED:
                    raise ConflictError(
                        f"topic {name} is {state_of(topic)}, not done or abandoned: submit into"
                        " it, no need to revive it"
                    )
                if State(standing.get("state") or State.ACTIVE) in CLOSED:
                    raise UsageError("a revived topic is planned or active")
            if standing or revive is not None:
                self.set_standing(topic, standing, revive)
                said.append("revived" if revive is not None else str(state_of(topic)))
            if reply is not None:
                topic["thread"].append(said_in(topic["thread"], author, reply, self.writer()))
                said.append("replied")
            if "name" in change and change["name"] != name:
                renamed = check_name(change["name"])
                if (self.directory / renamed).exists():
                    raise ConflictError(f"topic {renamed} exists")
                (self.directory / name).rename(self.directory / renamed)
                if (self.large / name).is_dir():
                    (self.large / name).rename(self.large / renamed)
                topic["name"] = renamed
                touched.append(self.directory / renamed)
                said.append(f"renamed from {name}")
            self.save_topic(topic)
            line = f": {topic['status']}" if standing and topic.get("status") else ""
            return topic, self.commit(
                touched, f"Topic {topic['name']}, {', '.join(said or ['updated'])}{line}"
            )

    def writer(self) -> dict[str, str | None]:
        return self.project.writer()

    def set_standing(
        self, topic: dict[str, Any], change: dict[str, Any], revived: str | None
    ) -> None:
        """A new state or status, kept in the topic and recorded as a status
        entry in its thread; a revival sets it active with its note. A change
        of state without a status clears the status."""
        state = State(change.get("state") or (State.ACTIVE if revived else state_of(topic)))
        if "status" in change:
            status = " ".join(str(change["status"] or "").split())
        elif state is not state_of(topic):
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
        wrote to, whose state or status it never set."""
        mine = {session}
        found = []
        for name in self.names():
            topic = self.topic(name)
            if state_of(topic) in CLOSED:
                continue
            stamps = [
                topic.get("created") or {},
                *(entry for entry in topic["thread"] if entry["author"] == Author.AGENT),
            ]
            for item in self.items(name):
                stamps += [item.get("created") or {}, *item["versions"]]
                stamps += [entry for entry in item["thread"] if entry["author"] == Author.AGENT]
            if not any(by(stamp, mine) for stamp in stamps):
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
            return self.commit([self.directory / name], f"Topic {name}, deleted")

    # --- items ------------------------------------------------------------------

    def create_item(self, topic: str, draft: ItemDraft) -> tuple[dict[str, Any], str | None]:
        title = draft["title"].strip()
        if not title:
            raise UsageError("`title` is empty")
        with self.project.lock("topics"):
            record = self.topic(topic)
            items = self.items(topic)
            if state_of(record) in CLOSED:
                raise ConflictError(
                    f"topic {topic} is {state_of(record)}: if this brings it back, revive it first —"
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
                content = {key: value for key, value in change.items() if key != "title"}
                if content:
                    latest = item["versions"].pop()
                    self.add_version(topic, item, content, latest)
                said.append("updated")
            if version is not None:
                if "title" in version:
                    item["title"] = version["title"].strip() or item["title"]
                self.add_version(topic, item, version, item["versions"][-1])
                item["verdict"] = str(Verdict.OPEN)
                item["decided"] = None
                said.append(f"version {item['versions'][-1]['version']}")
            if reply is not None:
                said_now = said_in(
                    item["thread"], author, reply, self.writer(), item.get("decided")
                )
                item["thread"].append(said_now)
                said.append("answered" if "answers" in said_now else "replied")
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
        if "options" in content:
            item["options"] = bool(content["options"])
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
        self.check_assets(item, [entry for entry, _ in made])
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

    def check_assets(self, item: dict[str, Any], entries: list[dict[str, Any]]) -> None:
        """One asset per item: a decision (with the project files it
        concerns), or one file; several only as options of one type."""
        files = [entry for entry in entries if entry["kind"] != "decision"]
        if len(files) < len(entries):
            if item.get("options"):
                raise UsageError(
                    "a decision has no options: its alternatives say what else was weighed"
                )
            derived = [entry["name"] for entry in files if entry["kind"] == "derived"]
            if derived:
                raise UsageError(
                    f"a decision holds no derived file: submit {derived[0]} as an item of its"
                    " own, and cite it in the answer"
                )
            return
        if len(files) > 1 and not item.get("options"):
            raise UsageError(
                "an item holds one file: submit each as an item of its own — several only"
                ' as options, variants of one asset for the owner to prefer one (`"options": true`)'
            )
        types = sorted({entry["type"] for entry in files})
        if item.get("options") and len(types) > 1:
            raise UsageError(
                f"options are variants of one asset, of one type — not {' and '.join(types)}:"
                " unrelated files are items of their own"
            )

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

    def prefer(self, ref: str, version: int, name: str | None) -> tuple[dict[str, Any], str | None]:
        """The owner's preferred option in a version of an item with options,
        or none (`name` None): recorded and shown, changing nothing else."""
        with self.project.lock("topics"):
            item = self.item(ref)
            if not item.get("options"):
                raise UsageError(f"{item['ref']} has no options to prefer one of")
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
                    raise NotFoundError(f"{item['ref']} has no option {name} in version {version}")
                item["preferred"] = {"version": version, "name": name}
            path = self.save_item(item["topic"], item)
            said = (
                f"option {name} of version {version} preferred" if name else "no option preferred"
            )
            return item, self.commit([path], f"Item {item['ref']}, {said}: {item['title']}")

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
                    message(Author.OWNER, comment, self.writer(), verdict=str(word["verdict"]))
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
            waiting = talk(record["thread"])[-1]
            record["thread"].remove(waiting)
            text = waiting["text"]
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
            if not any(by(version, {session}) for version in item["versions"]):
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


def by(stamp: dict[str, Any], sessions: set[str]) -> bool:
    """Whether one of these sessions wrote it, itself or through a subagent."""
    return stamp.get("session") in sessions or stamp.get("parent") in sessions


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
) -> dict[str, Any]:
    """A message for this thread: the owner's only once their last has its
    answer (or they withdraw it); the agent's answers the owner's waiting one,
    and may follow it with more."""
    if author is Author.OWNER and pending(thread, decided):
        raise ConflictError(
            "your last message waits for the agent's answer: withdraw it to change it"
        )
    if author is Author.AGENT and pending(thread, decided):
        return message(author, text, writer, answers=talk(thread)[-1]["moment"])
    return message(author, text, writer)


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


def awaits_owner(item: dict[str, Any]) -> bool:
    """Open: the owner's to look at."""
    return item["verdict"] == Verdict.OPEN


def owner_moment(item: dict[str, Any]) -> str:
    """When the owner last said something on an item: a verdict or a message."""
    decided = item.get("decided") or {}
    moments = [moment(decided)]
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
