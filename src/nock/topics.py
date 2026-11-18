"""Topics: what agents put before the owner. A topic is a stream of work — a
name, why it exists, a state and a status — holding three kinds of thing:
decisions (done and carried on with: a title, a few lines on what it means
for the owner, maybe why), proposals (todos the agent wants done, with
roughly what they take, which the owner accepts — carried out at the agent's
next look at its inbox, then read as decisions — or rejects, which drops
them) and assets (files, by version, so two versions compare). The topic's
review is its main page, composed by the agent as blocks that tell the story
and show its items and assets inline. The owner leaves notes on anything,
pinned where they are, and sends them with a message in the topic's one
chat; Done on the review counts every decision without a note as fine.

Everything lives in the store (`nock.shared`), the main checkout's
`.nock/shared/`, as events folded into records (`nock.fold`): each change
here is a few event files (a version a folder), settled and committed at
once, whichever worktree writes it. Every record keeps who wrote it."""

from __future__ import annotations

import fnmatch
import re
import shutil
import subprocess
from collections.abc import Iterator
from contextlib import contextmanager
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Any

from nock.errors import ConflictError, NotFoundError, UsageError
from nock.fold import STATUS
from nock.notify import Notifications, Reason
from nock.render import Problem
from nock.shared import CLOSED as CLOSED_STATES
from nock.shared import MEMORY_LIMIT, Settled, Shared, by_for
from nock.utils import now, parse_moment

if TYPE_CHECKING:
    from nock.project import Project

# The word the owner reads for a topic, in the studio and every text for them.
WORD = "task"
WORDS = "tasks"
NAME = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
# How the memory cites an item: `[topic/slug]`.
CITATION = re.compile(r"\[([a-z0-9][a-z0-9-]*/[a-z0-9][a-z0-9-]*)\](?!\()")
# How long a change waits for the store's lock before it gives up, in seconds.
STORE_PATIENCE = 30.0
# The task the owner's notes on the memory's lines go in, with its chat.
MEMORY_TASK = "memory"
# The agent the studio sends when the owner asks for an answer now.
ANSWERER = "answerer"


class State(StrEnum):
    """Where a topic's work is."""

    PLANNED = "planned"
    ACTIVE = "active"
    REVIEW = "review"
    """Built, its review composed: only the owner's look remains."""
    DONE = "done"
    ABANDONED = "abandoned"


class Status(StrEnum):
    """Where an item stands."""

    DECISION = "decision"
    OPEN = "open"
    """A proposal waiting for the owner."""
    ACCEPTED = "accepted"
    """A proposal the owner accepted, not carried out yet."""
    REJECTED = "rejected"
    """Dropped: gone from the review, kept in the history."""


class Author(StrEnum):
    OWNER = "owner"
    AGENT = "agent"


# How a closed topic comes back, as an agent writes it.
REVIVE = 'a `state` event in its events/, `{"kind": "state", "state": "active", "revived": true, "note": "why it is back"}`'
CLOSED = (State.DONE, State.ABANDONED)
# The states in which an agent's work in a topic is finished, as the stop hook counts it.
FINISHED = (State.REVIEW, *CLOSED)
assert {str(state) for state in CLOSED} == set(CLOSED_STATES)


def moment(record: dict[str, Any] | None) -> str:
    return (record or {}).get("moment") or ""


def by(stamp: dict[str, Any], sessions: set[str]) -> bool:
    """Whether a session (or a subagent of it) wrote this."""
    return bool({stamp.get("session"), stamp.get("parent")} & sessions)


def talk(thread: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The chat's messages, without the status entries."""
    return [entry for entry in thread if entry.get("kind") == "message"]


def pending(thread: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The owner's message waiting for an agent's answer: their last, with no
    agent's message after it."""
    said = talk(thread)
    if said and said[-1]["author"] == Author.OWNER:
        return said[-1]
    return None


def in_order(topics: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Topics (with their `active` moment) in the owner's order: by priority,
    1 first, then those without one; newest activity first within each."""
    newest = sorted(topics, key=lambda topic: topic["active"], reverse=True)
    return sorted(
        newest, key=lambda topic: (0, topic["priority"]) if topic.get("priority") else (1, 0)
    )


def entry_name(entry: dict[str, Any]) -> str:
    return entry.get("path") or entry.get("name") or ""


def latest(asset: dict[str, Any]) -> dict[str, Any] | None:
    return asset["versions"][-1] if asset.get("versions") else None


def minutes_between(start: str | None, end: str | None) -> float | None:
    begun, ended = parse_moment(start), parse_moment(end)
    if begun is None or ended is None:
        return None
    return max((ended - begun).total_seconds() / 60, 0.0)


def progress(steps: list[dict[str, Any]], at: str) -> dict[str, Any] | None:
    """Where a topic's plan stands at a moment: the share of its estimate
    done, the current step, and the minutes left — the estimates left,
    corrected by the pace so far (actual over estimated, on the steps done),
    less the time the current step has run. Each step done keeps its
    estimate beside its actual minutes."""
    if not steps:
        return None
    shown = []
    for step in steps:
        actual = minutes_between(step["started"], step["done"]) if step["done"] else None
        shown.append({**step, "actual": None if actual is None else round(actual, 1)})
    done = [step for step in shown if step["done"]]
    total = sum(float(step["estimate"]) for step in shown) or 1.0
    estimated = sum(float(step["estimate"]) for step in done)
    spent = sum(step["actual"] or 0.0 for step in done)
    pace = spent / estimated if done and estimated else 1.0
    current = next((step for step in shown if step["started"] and not step["done"]), None)
    left = sum(float(step["estimate"]) for step in shown if not step["done"]) * pace
    if current is not None:
        left -= minutes_between(current["started"], at) or 0.0
    return {
        "steps": shown,
        "done": len(done),
        "share": round(estimated / total, 3),
        "current": current["title"] if current else None,
        "left": max(round(left), 0) if len(done) < len(shown) else 0,
        "pace": round(pace, 2),
    }


def target_of(note: dict[str, Any], review: dict[str, Any] | None = None) -> str:
    """What a note is on, in words an agent reads."""
    on = note.get("on") or {}
    parts = []
    if on.get("item"):
        parts.append(f"item {on['item']}")
    if on.get("asset"):
        version = f" v{on['version']}" if on.get("version") else ""
        line = f", line {on['line']}" if on.get("line") else ""
        side = f" ({on['side']})" if on.get("side") else ""
        parts.append(f"asset {on['asset']}{version}{line}{side}")
    if on.get("memory"):
        parts.append(f"the memory, line {on.get('line', '?')}")
    if on.get("block"):
        kind = ""
        if review is not None:
            block = next((b for b in review.get("blocks", []) if b["id"] == on["block"]), None)
            kind = f" ({block['kind']})" if block else ""
        version = f" of review v{on['review']}" if on.get("review") else ""
        parts.append(f"block {on['block']}{kind}{version}")
    said = "; ".join(parts) or "the topic"
    if on.get("quote"):
        said += f': "{on["quote"]}"'
    return said


class Topics:
    """The topics, read from the store's fold and written to it as events:
    each change a few event files, settled — validated, completed and
    committed — at once."""

    def __init__(self, project: Project) -> None:
        self.project = project
        self.shared = Shared(project)
        self.fold = self.shared.fold
        self.drafted: list[Path] = []

    @property
    def directory(self) -> Path:
        return self.shared.topics

    @property
    def memory(self) -> Path:
        return self.shared.memory

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
            raise NotFoundError(
                f"no topic {name!r}{hint} (`.nock/local/views/index.md` lists them)"
            )
        return record

    def items(self, name: str) -> list[dict[str, Any]]:
        return self.fold.items(name)

    def assets(self, name: str) -> list[dict[str, Any]]:
        return self.fold.assets(name)

    def review(self, name: str) -> dict[str, Any]:
        return self.fold.review(name)

    def every(self) -> list[dict[str, Any]]:
        return [item for name in self.names() for item in self.items(name)]

    def resolve(self, ref: str) -> tuple[str, str]:
        """A ref's topic and slug: `topic/slug`."""
        ref = ref.strip().strip("/")
        topic, _, slug = ref.rpartition("/")
        if topic and NAME.match(topic) and NAME.match(slug) and self.fold.item(topic, slug):
            return topic, slug
        if topic:
            self.topic(topic)
        raise NotFoundError(f"no item {ref!r} — `.nock/nock search` finds them")

    def item(self, ref: str) -> dict[str, Any]:
        topic, slug = self.resolve(ref)
        item = self.fold.item(topic, slug)
        assert item is not None
        return item

    def asset(self, topic: str, name: str) -> dict[str, Any]:
        found = self.fold.asset(topic, name) if NAME.match(name) else None
        if found is None:
            raise NotFoundError(f"topic {topic} has no asset {name!r}")
        return found

    def version_of(self, asset: dict[str, Any], version: int | None) -> dict[str, Any]:
        if not asset["versions"]:
            raise NotFoundError(f"asset {asset['name']} has no version yet")
        if version is None:
            return asset["versions"][-1]
        found = next((v for v in asset["versions"] if v["version"] == version), None)
        if found is None:
            raise NotFoundError(f"asset {asset['name']} has no version {version}")
        return found

    # --- where files are: the one layer that reads them -------------------------

    def asset_path(self, topic: str, name: str, version: int) -> Path:
        return self.shared.asset_folder(topic, name) / "versions" / str(version)

    def located(self, topic: str, name: str, version: dict[str, Any]) -> Path:
        """Where an asset version's file is: in media by its sha256, beside its
        version, or — a project file linked at a commit — as it was then."""
        entry = version["file"]
        if entry.get("sha256"):
            return self.shared.blob(entry["sha256"])
        if entry.get("kind") == "project" and entry.get("commit"):
            return self.at_commit(entry["path"], entry["commit"])
        return self.asset_path(topic, name, version["version"]) / entry_name(entry)

    def companion(self, topic: str, name: str, version: dict[str, Any], file: str) -> Path:
        """A video's captions or poster, beside its version or in media."""
        entry = version["file"]
        if file not in (entry.get("captions"), entry.get("poster")):
            raise NotFoundError(f"asset {name} has no file {file}")
        blob = (version.get("blobs") or {}).get(file)
        if blob:
            return self.shared.blob(blob)
        return self.asset_path(topic, name, version["version"]) / file

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

    def text_of(self, topic: str, name: str, version: int | None = None) -> str:
        asset = self.asset(topic, name)
        found = self.version_of(asset, version)
        try:
            return self.located(topic, name, found).read_text(errors="replace")
        except OSError:
            return ""

    def html_block(self, topic: str, version: int, file: str) -> Path:
        """An html block's file, beside its review's version."""
        review = self.review(topic)
        found = next((v for v in review["versions"] if v["version"] == version), None)
        if found is None or not any(
            block["kind"] == "html" and block.get("file") == file for block in found["blocks"]
        ):
            raise NotFoundError(f"review v{version} of {topic} has no html block {file}")
        return self.shared.review_folder(topic) / "versions" / str(version) / file

    def attachment(self, topic: str, path: str) -> Path:
        """One of the chat's attachments: only a file a message names."""
        for entry in self.topic(topic)["thread"]:
            for file in entry.get("attachments", []):
                if file["path"] == path:
                    return self.shared.blob(file["sha256"])
        raise NotFoundError(f"{topic} has no attachment {path}")

    def attached(self, said: dict[str, Any]) -> list[str]:
        return [str(self.shared.blob(file["sha256"])) for file in said.get("attachments", [])]

    # --- what stands --------------------------------------------------------------

    def unsent(self, topic: dict[str, Any]) -> list[dict[str, Any]]:
        """The owner's notes no message carried yet: drafts pinned where they are."""
        return [note for note in topic["notes"] if not note["sent"]]

    def carried(self, topic: dict[str, Any], message: dict[str, Any]) -> list[dict[str, Any]]:
        """The notes a message carries, each with what it is on."""
        review = self.current_review(topic["name"])
        notes = {note["id"]: note for note in topic["notes"]}
        found = []
        for identifier in message.get("notes") or []:
            note = notes.get(identifier)
            if note is not None:
                found.append({**note, "target": target_of(note, review)})
        return found

    def current_review(self, name: str) -> dict[str, Any] | None:
        versions = self.review(name)["versions"]
        return versions[-1] if versions else None

    def reviewed(self, topic: dict[str, Any]) -> bool:
        """Whether the owner pressed Done on the current review."""
        review = self.current_review(topic["name"])
        return review is not None and any(
            done["version"] == review["version"] for done in topic["reviewed"]
        )

    def waiting_on_owner(self, topic: dict[str, Any], items: list[dict[str, Any]]) -> list[str]:
        """What waits on the owner in a topic: its open proposals and its
        review, until Done; nothing in a closed topic."""
        if topic["state"] in CLOSED:
            return []
        found = [item["ref"] for item in items if item["status"] == Status.OPEN]
        if self.current_review(topic["name"]) and not self.reviewed(topic):
            found.append(f"{topic['name']}/review")
        return found

    def waiting_on_agent(self, topic: dict[str, Any], items: list[dict[str, Any]]) -> list[str]:
        """What waits on an agent: the owner's message unanswered, the
        proposals they accepted not carried out yet."""
        found = []
        if pending(topic["thread"]):
            found.append(f"{topic['name']}/chat")
        found += [item["ref"] for item in items if item["status"] == Status.ACCEPTED]
        return found

    def row(self, name: str) -> dict[str, Any]:
        """A topic as a list shows it: its state, what it holds, what waits."""
        topic = self.topic(name)
        items = self.items(name)
        assets = self.assets(name)
        review = self.current_review(name)
        moments = [
            topic["updated"],
            *(i["updated"] for i in items),
            *(a["updated"] for a in assets),
        ]
        if review:
            moments.append(review["moment"])
        return {
            "name": name,
            "state": topic["state"],
            "status": topic["status"],
            "description": (topic.get("revived") or {}).get("note") or topic["description"],
            **({"priority": topic["priority"]} if topic.get("priority") else {}),
            "decisions": sum(1 for item in items if item["status"] == Status.DECISION),
            "proposals": sum(1 for item in items if item["status"] != Status.DECISION),
            "open": sum(1 for item in items if item["status"] == Status.OPEN),
            "assets": len(assets),
            "review": review["version"] if review else None,
            "reviewed": self.reviewed(topic),
            "notes": len(self.unsent(topic)),
            "for_owner": self.waiting_on_owner(topic, items),
            "for_agent": self.waiting_on_agent(topic, items),
            "progress": progress(topic["plan"], now()),
            "active": max(moments),
        }

    def rows(self) -> list[dict[str, Any]]:
        return in_order([self.row(name) for name in self.names()])

    def summary(self) -> dict[str, Any]:
        """The topics as `nock status` counts them: what waits on the owner and on agents."""
        rows = self.rows()
        return {
            "active": sum(1 for row in rows if row["state"] in (State.ACTIVE, State.PLANNED)),
            "awaiting_you": {
                row["name"]: len(row["for_owner"]) for row in rows if row["for_owner"]
            },
            "awaiting_agents": {row["name"]: row["for_agent"] for row in rows if row["for_agent"]},
        }

    def comments(self) -> list[dict[str, Any]]:
        """The owner's messages waiting for an agent's answer, by topic, in
        the owner's order: each with the notes it carries and its files."""
        found = []
        for row in self.rows():
            topic = self.topic(row["name"])
            said = pending(topic["thread"])
            if said is None:
                continue
            found.append(
                {
                    "ref": row["name"],
                    "id": said["id"],
                    "text": said["text"],
                    "now": bool(said.get("now")),
                    "moment": said["moment"],
                    "notes": self.carried(topic, said),
                    "files": self.attached(said),
                }
            )
        return found

    # --- search -------------------------------------------------------------------

    def score(self, words: list[str], heading: str, body: str) -> float:
        """Every word first (more often higher), then all but one; a word
        found where a word starts counts more."""
        text = f"{heading} {heading} {body}".lower()
        found = 0.0
        hits = 0
        for word in words:
            count = len(re.findall(rf"\b{re.escape(word)}", text))
            inside = text.count(word) - count
            if count or inside:
                hits += 1
            found += count + 0.3 * inside
        if hits < max(1, len(words) - 1):
            return 0.0
        return hits * 10 + found

    def search_items(self, query: str, topic: str | None = None) -> list[dict[str, Any]]:
        words = [word for word in query.lower().split() if word]
        if not words:
            return []
        scored = []
        for name in [topic] if topic else self.names():
            for item in self.items(name):
                body = " ".join([item["means"], item["why"], item["takes"], item["ref"]])
                score = self.score(words, item["title"], body)
                if score:
                    scored.append((score, item))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [item for _, item in scored]

    def search_topics(self, query: str) -> list[str]:
        words = [word for word in query.lower().split() if word]
        if not words:
            return []
        scored = []
        for name in self.names():
            topic = self.topic(name)
            said = " ".join(entry.get("text") or "" for entry in topic["thread"])
            assets = " ".join(
                f"{asset['title']} {asset['description']} "
                + " ".join(entry_name(v["file"]) for v in asset["versions"])
                for asset in self.assets(name)
            )
            review = self.current_review(name)
            told = " ".join(
                str(block.get("text") or block.get("caption") or "")
                for block in (review or {}).get("blocks", [])
            )
            body = f"{topic['description']} {topic['status']} {said} {assets} {told}"
            score = self.score(words, name.replace("-", " "), body)
            if score:
                scored.append((score, name))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [name for _, name in scored]

    # --- writing ------------------------------------------------------------------

    def settle(self, written: list[Path], author: Author = Author.AGENT) -> Settled:
        """Settle what nock just wrote: refused as a whole, its files gone, when
        the store finds a problem with it."""
        settled = self.shared.settle(by_for(self.project, str(author)), only=written)
        if settled.problems:
            raise UsageError("; ".join(settled.problems))
        self.heard(settled)
        return settled

    def heard(self, settled: Settled) -> None:
        """What every settle does after: the views written again, the agents'
        work counted for the stop hook, and the owner told when it is their turn."""
        if settled.topics:
            # A genuine cycle: the views read the topics.
            from nock.views import Views

            Views(self.project).write(settled.topics)
        turns: dict[str, Reason] = {}
        for event in settled.events:
            stamp = event.get("by") or {}
            if stamp.get("author") != Author.AGENT:
                continue
            topic = event.get("topic")
            if not topic:
                continue
            if stamp.get("session"):
                self.project.store.insert(
                    "wrote",
                    {"session": stamp["session"], "parent": stamp.get("parent"), "topic": topic},
                )
            reason = turn_of(event)
            if reason is not None and topic not in turns:
                turns[topic] = reason
        for topic, reason in turns.items():
            self.owners_turn(topic, reason)

    def owners_turn(self, name: str, reason: Reason) -> None:
        """Tell the owner it is their turn in this topic (`nock.notify`)."""
        # A genuine cycle: the timeline reads the topics.
        from nock.timeline import Timeline

        try:
            row = self.row(name)
        except NotFoundError:
            return
        event = Timeline(self.project).latest(name, reason)
        Notifications(self.project).tell(name, reason, row, event=event)

    def draft(self, folder: Path, record: dict[str, Any], identifier: str | None = None) -> Path:
        path = self.shared.draft(folder, record, identifier)
        self.drafted.append(path)
        return path

    @contextmanager
    def drafting(self) -> Iterator[None]:
        """A change drafted and settled under the store's lock, so no other
        process settles its drafts as its own; all it drafted gone again —
        and any folder it left empty — when it fails before it is settled."""
        self.drafted = []
        with self.project.lock("shared", patience=STORE_PATIENCE):
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

    def write(
        self,
        name: str,
        records: list[dict[str, Any]],
        author: Author,
        identifier: str | None = None,
    ) -> Settled:
        """Topic events, drafted and settled as one change."""
        self.topic(name)
        folder = self.shared.topic_folder(name)
        with self.drafting():
            written = [
                self.draft(folder, record, identifier if place == 0 else None)
                for place, record in enumerate(records)
            ]
            return self.settle(written, author)

    # The owner's own, from the studio (or recorded on their word).

    def note(
        self,
        name: str,
        on: dict[str, Any],
        text: str,
        replaces: str | None = None,
        identifier: str | None = None,
    ) -> dict[str, Any]:
        """A note pinned on an item, an asset or a block of the review; with
        REPLACES, an edit of that one (empty text removes it). It waits as a
        draft until a message carries it."""
        topic = self.topic(name)
        if replaces:
            current = next((n for n in topic["notes"] if n["id"] == replaces), None)
            if current is None:
                raise NotFoundError(f"{name} has no note {replaces}")
            if current["sent"]:
                raise ConflictError("that note went with a message already: leave a new one")
        elif not text.strip():
            raise UsageError("a note says something")
        if identifier and any(n["id"] == identifier for n in topic["notes"]):
            return next(n for n in topic["notes"] if n["id"] == identifier)
        record: dict[str, Any] = {"kind": "note", "on": on, "text": text.strip()}
        if replaces:
            record["replaces"] = replaces
        self.write(name, [record], Author.OWNER, identifier)
        notes = self.topic(name)["notes"]
        return notes[-1] if notes else {"id": replaces, "text": ""}

    def send(
        self,
        name: str,
        text: str,
        attachments: list[dict[str, Any]] | None = None,
        identifier: str | None = None,
        now: bool = True,
    ) -> dict[str, Any]:
        """The owner's message in the topic's chat, carrying every unsent
        note; it may be empty. With NOW, an agent is to answer at once."""
        topic = self.topic(name)
        if identifier and any(entry["id"] == identifier for entry in topic["thread"]):
            return next(entry for entry in topic["thread"] if entry["id"] == identifier)
        notes = [note["id"] for note in self.unsent(topic)]
        record: dict[str, Any] = {"kind": "message", "text": text.strip()}
        if notes:
            record["notes"] = notes
        if attachments:
            record["attachments"] = attachments
        if now:
            record["now"] = True
        self.write(name, [record], Author.OWNER, identifier)
        return talk(self.topic(name)["thread"])[-1]

    def judge(self, ref: str, verdict: str) -> dict[str, Any]:
        """The owner's word on a proposal: accepted, to be carried out;
        rejected, dropped."""
        if verdict not in ("accepted", "rejected"):
            raise UsageError("a proposal is accepted or rejected")
        item = self.item(ref)
        if not item["proposed"]:
            raise UsageError(f"{ref} is a decision: only a proposal takes a verdict")
        if item["implemented"]:
            raise ConflictError(f"{ref} is carried out already")
        folder = self.shared.item_folder(item["topic"], item["slug"])
        with self.drafting():
            self.settle([self.draft(folder, {"kind": "verdict", "verdict": verdict})], Author.OWNER)
        return self.item(ref)

    def done(self, name: str) -> dict[str, Any]:
        """Done on the review: every decision without a note counts as fine.
        Unsent notes go with it as a message, for an agent to answer now;
        with nothing left for agents, the topic is done."""
        topic = self.topic(name)
        review = self.current_review(name)
        if review is None:
            raise UsageError(f"{name} has no review to be done with")
        records: list[dict[str, Any]] = []
        notes = [note["id"] for note in self.unsent(topic)]
        if notes:
            records.append({"kind": "message", "text": "", "notes": notes, "now": True})
        records.append({"kind": "reviewed", "version": review["version"]})
        self.write(name, records, Author.OWNER)
        topic = self.topic(name)
        items = self.items(name)
        if not self.waiting_on_agent(topic, items) and topic["state"] not in CLOSED:
            self.write(name, [{"kind": "state", "state": "done"}], Author.OWNER)
        return {"sent": bool(notes), "state": self.topic(name)["state"]}

    # --- the hooks' ---------------------------------------------------------------

    def writers(self, name: str) -> set[str]:
        """The sessions that did an agent's work in a topic."""
        return {
            value
            for row in self.project.store.rows(
                "SELECT session, parent FROM wrote WHERE topic = ?", (name,)
            )
            for value in (row["session"], row["parent"])
            if value
        }

    def news_for(self, session: str) -> list[dict[str, Any]]:
        """What the owner said in the topics this session worked in that it
        was not told yet — their messages, their word on proposals, Done on a
        review — each told once (the `told` table)."""
        told = {
            row["updated"]
            for row in self.project.store.rows(
                "SELECT updated FROM told WHERE session = ?", (session,)
            )
        }
        news = []
        for name in self.names():
            if session not in self.writers(name):
                continue
            topic = self.topic(name)
            found: list[dict[str, Any]] = []
            for entry in topic["thread"]:
                if entry["author"] != Author.OWNER or entry["id"] in told:
                    continue
                if entry["kind"] == "message":
                    found.append(
                        {
                            "kind": "message",
                            "id": entry["id"],
                            "topic": name,
                            "text": entry["text"],
                            "notes": self.carried(topic, entry),
                            "files": self.attached(entry),
                        }
                    )
                elif entry["kind"] == "reviewed":
                    found.append({"kind": "reviewed", "id": entry["id"], "topic": name})
            for item in self.items(name):
                verdict = item.get("verdict")
                if verdict and verdict["id"] not in told:
                    found.append(
                        {
                            "kind": verdict["verdict"],
                            "id": verdict["id"],
                            "topic": name,
                            "ref": item["ref"],
                            "title": item["title"],
                        }
                    )
            for entry in found:
                self.project.store.insert(
                    "told", {"session": session, "item": name, "updated": entry["id"]}
                )
            news += found
        return news

    def governing(self, session: str, path: str) -> list[dict[str, Any]]:
        """The topics whose assets' latest versions hold this project file or
        were derived from it, with their decisions, not yet shown this
        session; showing them is recorded."""
        shown = {
            row["item"]
            for row in self.project.store.rows(
                "SELECT item FROM shown_items WHERE session = ?", (session,)
            )
        }
        found = []
        for name in self.names():
            if name in shown:
                continue
            for asset in self.assets(name):
                version = latest(asset)
                if version is None:
                    continue
                entry = version["file"]
                if entry.get("path") == path or any(
                    fnmatch.fnmatchcase(path, source) for source in entry.get("from", [])
                ):
                    decisions = [
                        item for item in self.items(name) if item["status"] == Status.DECISION
                    ]
                    found.append({"topic": name, "asset": asset["name"], "decisions": decisions})
                    self.project.store.insert("shown_items", {"session": session, "item": name})
                    break
        return found

    def unstated(self, session: str) -> list[str]:
        """The planned or active topics this session (or a subagent of it)
        did its own work in whose state or status it never set."""
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
            if topic["state"] in FINISHED:
                continue
            if any(entry.get("kind") == STATUS and by(entry, mine) for entry in topic["thread"]):
                continue
            found.append(name)
        return found

    def recipes(self, name: str) -> list[str]:
        """The commands that make a topic's derived assets again: the recipe of
        each asset's latest version an answerer did not write."""
        commands: list[str] = []
        for asset in self.assets(name):
            authored = [v for v in asset["versions"] if v.get("role") != ANSWERER]
            entry = authored[-1]["file"] if authored else {}
            command = (entry.get("recipe") or {}).get("command")
            if command and command not in commands:
                commands.append(command)
        return commands

    # --- the memory -------------------------------------------------------------

    def memory_task(self) -> None:
        """The task the owner's notes on the memory go in, opened the first time."""
        if MEMORY_TASK in self.names():
            return
        folder = self.shared.topic_folder(MEMORY_TASK)
        with self.drafting():
            self.settle(
                [
                    self.draft(
                        folder,
                        {
                            "kind": "created",
                            "description": "The owner's corrections to what nock has learned"
                            " (`.nock/shared/memory.md`).",
                        },
                    )
                ],
                Author.OWNER,
            )

    def edit_memory(self, text: str) -> None:
        """The owner's own edit of the memory, committed as theirs."""
        with self.project.lock("shared", patience=STORE_PATIENCE):
            self.memory.parent.mkdir(parents=True, exist_ok=True)
            self.memory.write_text(text if text.endswith("\n") or not text else text + "\n")
            settled = self.shared.settle(
                by_for(self.project, str(Author.OWNER)), only=[self.memory]
            )
        if settled.problems:
            raise UsageError("; ".join(settled.problems))

    def memory_problems(self) -> list[Problem]:
        """The memory, held to what it is: small, and citing only items that exist."""
        if not self.memory.is_file():
            return []
        place = str(self.memory.relative_to(self.project.root))
        text = self.memory.read_text()
        problems = []
        if len(text) > MEMORY_LIMIT:
            problems.append(
                Problem(
                    f"the memory is {len(text):,} characters; at most {MEMORY_LIMIT:,}: prune"
                    " and merge lines, the detail stays in the files they point to",
                    place,
                    None,
                )
            )
        for line, said in enumerate(text.splitlines(), start=1):
            for match in CITATION.finditer(said):
                try:
                    self.resolve(match.group(1))
                except NotFoundError:
                    problems.append(Problem(f"[{match.group(0)[1:-1]}] is no item", place, line))
        return problems


def turn_of(event: dict[str, Any]) -> Reason | None:
    """Whether an agent's event makes it the owner's turn, and why."""
    kind = event.get("kind")
    if event.get("review") and kind == "version":
        return Reason.REVIEW
    if kind == "state" and event.get("state") == State.REVIEW:
        return Reason.REVIEW
    if kind == "message" and event.get("answers") and not event.get("item"):
        return Reason.ANSWERED
    if event.get("item") and kind == "created" and event.get("type") == "proposal":
        return Reason.PROPOSED
    return None
