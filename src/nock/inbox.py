"""The inbox: what the owner said that an agent should act on — a message
sent with Address now, a message in the studio's global chat, a comment
waiting in a thread, a verdict — and that no agent has addressed yet.
Addressed is the store's, the same for every reader (an agent's answer, a
new version, a later verdict); shown is each reader's own (`inbox_shown`),
so a reader is not shown the same entry twice while another still is.
`nock inbox --wait` blocks until something is there, returning a message at
once and verdicts and comments once the owner has been quiet a while, so a
triage lands as one batch."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from nock.topics import Author, Topics, by, every_version, pending, talk
from nock.utils import parse_moment, read_json, write_json

if TYPE_CHECKING:
    from nock.project import Project

# The entries by priority, the first first.
KINDS = ("now", "chat", "comment", "verdict")
# Verdicts whose word asks nothing more of an agent once one has heard it.
SETTLED = ("accepted", "dropped")
LISTENING = "inbox-listening.json"
# The owner's comments sent with Address now while an agent listened, by id.
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
        """What waits on an agent, by priority, the reader's own first in each;
        without `every`, only what this reader has not been shown."""
        shown_to_me = self.shown(self.reader)
        shown_to_any = self.shown(None)
        found = []
        for name in self.topics.names():
            topic = self.topics.topic(name)
            mine = self.wrote_in(name)
            if pending(topic["thread"]):
                found.append(self.said(talk(topic["thread"])[-1], name, "", mine))
            for item in self.topics.items(name):
                yours = mine or self.made(item)
                if pending(item["thread"], item.get("decided")):
                    found.append(
                        self.said(talk(item["thread"])[-1], item["ref"], item["title"], yours)
                    )
                decided = item.get("decided") or {}
                if decided.get("author") == Author.OWNER and decided.get("id"):
                    if item["verdict"] in SETTLED and decided["id"] in shown_to_any:
                        continue
                    found.append(
                        {
                            "kind": "verdict",
                            "key": decided["id"],
                            "ref": item["ref"],
                            "title": item["title"],
                            "verdict": item["verdict"],
                            "text": self.comment(item),
                            "moment": decided.get("moment") or "",
                            "yours": yours,
                        }
                    )
        found += self.chats()
        if not every:
            found = [entry for entry in found if entry["key"] not in shown_to_me]
        found.sort(
            key=lambda entry: (KINDS.index(entry["kind"]), not entry["yours"], entry["moment"])
        )
        return found

    def said(self, entry: dict[str, Any], ref: str, title: str, yours: bool) -> dict[str, Any]:
        urged = entry.get("now") or entry.get("id") in self.urged
        return {
            "kind": "now" if urged else "comment",
            "key": entry.get("id") or f"{ref}:{entry['moment']}",
            "ref": ref,
            "title": title,
            "text": entry.get("text") or "",
            "moment": entry["moment"],
            "yours": yours,
            **(
                {"attachments": [str(self.topics.where(file, "")) for file in entry["attachments"]]}
                if entry.get("attachments")
                else {}
            ),
        }

    def comment(self, item: dict[str, Any]) -> str:
        said = [entry for entry in item["thread"] if entry.get("verdict")]
        return said[-1]["text"] if said else ""

    def chats(self) -> list[dict[str, Any]]:
        """The owner's messages in the studio's global chats still unanswered."""
        directory = self.project.local / "chats"
        found = []
        for path in sorted(directory.glob("*.json")) if directory.is_dir() else []:
            try:
                chat = read_json(path)
            except Exception:
                continue
            if chat.get("kind", "chat") != "chat" or not chat.get("messages"):
                continue
            last = chat["messages"][-1]
            if last.get("author") == "owner":
                found.append(
                    {
                        "kind": "chat",
                        "key": f"chat:{chat['id']}:{last['moment']}",
                        "ref": f"chat:{chat['id']}",
                        "title": chat.get("title") or "",
                        "text": last.get("text") or "",
                        "moment": last["moment"],
                        "yours": False,
                    }
                )
        return found

    def made(self, item: dict[str, Any]) -> bool:
        return any(by(version, {self.reader}) for version in every_version(item))

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
        """Block until there is something new: a message at once, verdicts
        and comments once the owner has said nothing for `settle` seconds;
        nothing once `deadline` seconds have passed."""
        until = now() + deadline
        self.listen(until)
        try:
            while True:
                found = self.entries()
                urgent = [entry for entry in found if entry["kind"] in ("now", "chat")]
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
    """A comment the owner sent with Address now: first in the inbox."""
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
