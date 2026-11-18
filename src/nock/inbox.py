"""The inbox: what the owner said that an agent should act on — a message in
a topic's chat (sent for an answer now, or not), with the notes it carries; a
proposal they accepted, to carry out, or rejected, to leave; Done on a
review — and that no agent has acted on yet. Acted on is the store's, the
same for every reader (an agent's answer, a proposal carried out); shown is
each reader's own (`inbox_shown`), so a reader is not shown the same entry
twice. `nock inbox --wait` blocks until something is there, returning a
message at once and the rest once the owner has been quiet a while, so a
look through the studio lands as one batch."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from nock.topics import Status, Topics, pending
from nock.utils import parse_moment, read_json, write_json

if TYPE_CHECKING:
    from nock.project import Project

# The entries by priority, the first first.
KINDS = ("now", "message", "accepted", "rejected", "reviewed")
LISTENING = "inbox-listening.json"
# The owner's messages sent for an answer now while an agent listened, by id.
URGED = "inbox-now.json"


class Inbox:
    def __init__(self, project: Project, reader: str | None = None) -> None:
        self.project = project
        self.topics = Topics(project)
        self.reader = reader or project.writer().get("session") or "unknown"
        path = project.local / URGED
        try:
            self.urged = set(read_json(path)) if path.is_file() else set()
        except Exception:
            self.urged = set()

    def entries(self, every: bool = False) -> list[dict[str, Any]]:
        """What waits on an agent, by priority, the reader's own topics first
        in each; without `every`, only what this reader has not been shown."""
        shown_to_me = self.shown(self.reader)
        shown_to_any = self.shown(None)
        found = []
        for name in self.topics.names():
            topic = self.topics.topic(name)
            mine = self.wrote_in(name)
            said = pending(topic["thread"])
            if said is not None:
                urged = said.get("now") or said["id"] in self.urged
                found.append(
                    {
                        "kind": "now" if urged else "message",
                        "key": said["id"],
                        "ref": name,
                        "text": said["text"],
                        "notes": [
                            {"on": note["target"], "text": note["text"]}
                            for note in self.topics.carried(topic, said)
                        ],
                        "moment": said["moment"],
                        "yours": mine,
                        **(
                            {"attachments": self.topics.attached(said)}
                            if said.get("attachments")
                            else {}
                        ),
                    }
                )
            for item in self.topics.items(name):
                verdict = item.get("verdict")
                if not verdict or verdict.get("author") != "owner":
                    continue
                if item["status"] == Status.REJECTED and verdict["id"] in shown_to_any:
                    continue
                if item["status"] not in (Status.ACCEPTED, Status.REJECTED):
                    continue
                found.append(
                    {
                        "kind": str(item["status"]),
                        "key": verdict["id"],
                        "ref": item["ref"],
                        "title": item["title"],
                        "text": item["takes"] if item["status"] == Status.ACCEPTED else "",
                        "moment": verdict["moment"],
                        "yours": mine,
                    }
                )
            for done in topic["reviewed"]:
                entry = next(
                    (
                        e
                        for e in topic["thread"]
                        if e["kind"] == "reviewed" and e["moment"] == done["moment"]
                    ),
                    None,
                )
                if entry is None or entry["id"] in shown_to_any:
                    continue
                found.append(
                    {
                        "kind": "reviewed",
                        "key": entry["id"],
                        "ref": name,
                        "title": f"review v{done['version']}",
                        "text": "the owner is done with the review",
                        "moment": done["moment"],
                        "yours": mine,
                    }
                )
        if not every:
            found = [entry for entry in found if entry["key"] not in shown_to_me]
        found.sort(
            key=lambda entry: (KINDS.index(entry["kind"]), not entry["yours"], entry["moment"])
        )
        return found

    def wrote_in(self, topic: str) -> bool:
        return bool(
            self.project.store.rows(
                "SELECT 1 FROM wrote WHERE topic = ? AND (session = ? OR parent = ?) LIMIT 1",
                (topic, self.reader, self.reader),
            )
        )

    def shown(self, reader: str | None) -> set[str]:
        if reader is None:
            rows = self.project.store.rows("SELECT entry FROM inbox_shown")
        else:
            rows = self.project.store.rows(
                "SELECT entry FROM inbox_shown WHERE reader = ?", (reader,)
            )
        return {row["entry"] for row in rows}

    def mark_shown(self, entries: list[dict[str, Any]]) -> None:
        for entry in entries:
            self.project.store.insert("inbox_shown", {"reader": self.reader, "entry": entry["key"]})

    def wait(
        self,
        deadline: float,
        settle: float,
        now: Callable[[], float] = time.time,
        pause: Callable[[float], None] = time.sleep,
    ) -> list[dict[str, Any]]:
        """Block until there is something new: a message at once, the rest
        once the owner has said nothing for `settle` seconds;
        nothing once `deadline` seconds have passed."""
        until = now() + deadline
        self.listen(until)
        try:
            while True:
                found = self.entries()
                urgent = [entry for entry in found if entry["kind"] in ("now", "message")]
                if urgent:
                    return found
                if found:
                    moments = [parse_moment(entry["moment"]) for entry in found]
                    last = (
                        max(moment.timestamp() for moment in moments if moment)
                        if any(moments)
                        else 0
                    )
                    if now() - last >= settle:
                        return found
                if now() >= until:
                    return []
                pause(min(2.0, max(0.1, until - now())))
        finally:
            self.listen(None)

    def listen(self, until: float | None) -> None:
        """Say who is listening, until when (none: no longer), for the studio."""
        path = self.project.local / LISTENING
        try:
            listening = read_json(path) if path.is_file() else {}
        except Exception:
            listening = {}
        if until is None:
            listening.pop(self.reader, None)
        else:
            listening[self.reader] = until
        write_json(path, listening)


def urge(project: Project, message: str) -> None:
    """A message the owner sent for an answer now, while an agent listens: first in the inbox."""
    path = project.local / URGED
    try:
        urged = read_json(path) if path.is_file() else []
    except Exception:
        urged = []
    if message not in urged:
        write_json(path, [*urged, message])


def listeners(project: Project, now: float | None = None) -> list[str]:
    """Who is waiting on the inbox now."""
    path = project.local / LISTENING
    try:
        listening = read_json(path) if path.is_file() else {}
    except Exception:
        return []
    moment = time.time() if now is None else now
    return sorted(reader for reader, until in listening.items() if until > moment)
