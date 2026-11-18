"""Runs: the headless Claude Code sessions the studio starts on the owner's
click, in the background, each watched while it runs (running, done, failed,
with its log and what it says as it goes). Two kinds:

- **answer**: the owner sent a message in a task's chat for an answer now.
  An agent waiting on `nock inbox --wait` gets it first (`inbox.urge`);
  otherwise nock dispatches the `answerer`, who reads the message and the
  notes it carries, does what they ask (a reply, an item revised, a new
  version of an asset or of the review, a change to the code checked with the
  project's gate, never committed) and answers in the chat.
- **round**: a reflection round (`nock reflect NAME`), run whole by a lead
  that dispatches the round's own subagents; its result is a task to review.

At most one run per task or round at a time. A run is kept on this machine,
`.nock/local/runs/ID.json`; one left running by a studio that stopped is
marked stopped."""

from __future__ import annotations

import json
import re
import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from nock.dispatch import Dispatcher, Session
from nock.errors import ConflictError, Error, NotFoundError, UsageError
from nock.inbox import listeners, urge
from nock.shared import Shared, by_for
from nock.templates import Library
from nock.topics import ANSWERER, Topics, pending
from nock.utils import now, read_json, write_json

if TYPE_CHECKING:
    from nock.project import Project

BRIEFS = Path(__file__).resolve().parent / "briefs"
RUNS = "runs"
# The headless lead of a round the owner started from the studio.
REFLECTOR = "reflector"
# How long a tool call's line is, in characters.
SHOWN = 160
# Each task's chat session, by task: its next answer resumes it.
SESSIONS = "runs-sessions.json"


def clipped(text: str) -> str:
    line = " ".join(text.split())
    return line if len(line) <= SHOWN else line[: SHOWN - 1] + "…"


@dataclass
class Progress:
    """A run's turn as it streams, from Claude Code's stream-json, a line at
    a time: each record kept in the turn's stream file beside the run, and
    what the page shows of it — the agent's reasoning, its words, each tool
    call with its input and then its result."""

    stream: Path
    events: list[dict[str, Any]] = field(default_factory=list)
    buffer: bytes = b""
    stop: threading.Event = field(default_factory=threading.Event)

    @property
    def lines(self) -> list[dict[str, Any]]:
        return self.events

    def hear(self, chunk: bytes) -> None:
        self.buffer += chunk
        *lines, self.buffer = self.buffer.split(b"\n")
        with self.stream.open("ab") as kept:
            for line in lines:
                if line.strip():
                    kept.write(line + b"\n")
        for line in lines:
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(record, dict):
                self.events += shown_events(record)


def shown_events(record: dict[str, Any]) -> list[dict[str, Any]]:
    """What the page shows of one stream-json record."""
    kind = record.get("type")
    found: list[dict[str, Any]] = []
    if kind in ("assistant", "user"):
        for block in (record.get("message") or {}).get("content") or []:
            if not isinstance(block, dict):
                continue
            part = block.get("type")
            if part == "thinking" and block.get("thinking"):
                found.append({"kind": "thinking", "text": str(block["thinking"])[:4000]})
            elif part == "text" and str(block.get("text") or "").strip():
                found.append({"kind": "text", "text": str(block["text"])[:8000]})
            elif part == "tool_use":
                given = block.get("input") or {}
                said = (
                    given.get("command")
                    or given.get("file_path")
                    or given.get("description")
                    or given.get("pattern")
                    or ""
                )
                found.append(
                    {
                        "kind": "tool",
                        "id": block.get("id"),
                        "name": block.get("name"),
                        "summary": clipped(str(said)),
                        "input": json.dumps(given, indent=2)[:6000],
                    }
                )
            elif part == "tool_result":
                content = block.get("content")
                if isinstance(content, list):
                    content = "\n".join(
                        str(piece.get("text") or "") for piece in content if isinstance(piece, dict)
                    )
                found.append(
                    {
                        "kind": "result",
                        "id": block.get("tool_use_id"),
                        "error": bool(block.get("is_error")),
                        "text": str(content or "")[:6000],
                    }
                )
    elif kind == "system" and record.get("subtype") == "init":
        found.append({"kind": "event", "text": f"session {record.get('session_id', '')} started"})
    elif kind == "result":
        found.append(
            {
                "kind": "event",
                "text": f"finished: {record.get('subtype', '')}"
                + (f", {record['num_turns']} turns" if record.get("num_turns") else ""),
            }
        )
    return found


def events_of(stream: Path) -> list[dict[str, Any]]:
    """A finished turn's events, read back from its stream file."""
    found: list[dict[str, Any]] = []
    try:
        lines = stream.read_text(errors="replace").splitlines()
    except OSError:
        return found
    for line in lines:
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(record, dict):
            found += shown_events(record)
    return found


class Runs:
    """The studio's runs: started, watched, listed."""

    def __init__(self, project: Project, instance: str = "") -> None:
        self.project = project
        self.instance = instance
        self.lock = threading.RLock()
        self.progress: dict[str, Progress] = {}

    @property
    def directory(self) -> Path:
        return self.project.local / RUNS

    def path(self, identifier: str) -> Path:
        return self.directory / f"{identifier}.json"

    def load(self, identifier: str) -> dict[str, Any]:
        record = read_json(self.path(identifier))
        orphaned = identifier not in self.progress and record.get("instance") != self.instance
        if record.get("status") == "running" and orphaned:
            record["status"] = "stopped"
        return record

    def stream_of(self, identifier: str) -> Path:
        return self.directory / f"{identifier}.jsonl"

    def turn(self, identifier: str) -> dict[str, Any]:
        """A run with its turn's events, live while it runs."""
        if not re.fullmatch(r"[0-9a-f]{12}", identifier) or not self.path(identifier).is_file():
            raise NotFoundError(f"no run {identifier}")
        record = self.load(identifier)
        progress = self.progress.get(identifier)
        events = (
            list(progress.events) if progress is not None else events_of(self.stream_of(identifier))
        )
        return {**record, "events": events}

    def sessions(self) -> dict[str, str]:
        """Each task's chat session, which its next answer resumes."""
        path = self.project.local / SESSIONS
        try:
            found = read_json(path) if path.is_file() else {}
        except Error:
            found = {}
        return found if isinstance(found, dict) else {}

    def save(self, record: dict[str, Any]) -> None:
        write_json(self.path(record["id"]), {k: v for k, v in record.items() if k != "events"})

    def listing(self, limit: int = 30) -> list[dict[str, Any]]:
        """The runs, newest first."""
        if not self.directory.is_dir():
            return []
        found = []
        for path in self.directory.glob("*.json"):
            try:
                found.append(self.load(path.stem))
            except Error:
                continue
        found.sort(key=lambda run: run.get("started") or "", reverse=True)
        return found[:limit]

    def running(self, kind: str, subject: str) -> dict[str, Any] | None:
        for run in self.listing(limit=200):
            if run["kind"] == kind and run["subject"] == subject and run["status"] == "running":
                return run
        return None

    def start(
        self,
        kind: str,
        subject: str,
        role: str,
        prompt: str,
        title: str,
        topic: str,
        allowed: tuple[str, ...] = (),
        resume: str | None = None,
    ) -> dict[str, Any]:
        """A run in the background; refused while one for the same task or round runs."""
        with self.lock:
            busy = self.running(kind, subject)
            if busy is not None:
                raise ConflictError(f"{title} is running already (started {busy['started']})")
            record = {
                "id": uuid.uuid4().hex[:12],
                "kind": kind,
                "subject": subject,
                "title": title,
                "topic": topic,
                "role": role,
                "status": "running",
                "started": now(),
                "finished": None,
                "instance": self.instance,
                "log": None,
                "session": None,
                "problem": None,
                "said": "",
                "message": None,
            }
            self.save(record)
            progress = Progress(self.stream_of(record["id"]))
            self.progress[record["id"]] = progress
        threading.Thread(
            target=self.run,
            args=(record["id"], role, prompt, allowed, progress, resume),
            daemon=True,
        ).start()
        return self.load(record["id"])

    def run(
        self,
        identifier: str,
        role: str,
        prompt: str,
        allowed: tuple[str, ...],
        progress: Progress,
        resume: str | None,
    ) -> None:
        session: Session | None = None
        problem = None
        try:
            session = Dispatcher(self.project).launch(
                role,
                prompt,
                self.project.here,
                stop=progress.stop,
                allowed=allowed,
                resume=resume,
                listener=progress.hear,
            )
            if session.exit_code != 0 and resume and not progress.events:
                # The session to resume is gone: a new one, briefed afresh.
                session = Dispatcher(self.project).launch(
                    role, prompt, self.project.here, stop=progress.stop, allowed=allowed,
                    listener=progress.hear,
                )  # fmt: skip
        except Error as error:
            problem = str(error)
        with self.lock:
            record = read_json(self.path(identifier))
            record["finished"] = now()
            if session is not None:
                record["session"] = session.id
                record["log"] = str(session.log)
                record["said"] = (session.result or "").strip()
                if session.exit_code != 0:
                    problem = (
                        "stopped"
                        if progress.stop.is_set()
                        else f"the agent stopped (exit {session.exit_code})"
                    )
                    if session.denied:
                        problem += "; refused: " + "; ".join(session.denied)
            settled, message = self.settled(role, session)
            if settled:
                problem = (problem + "; " if problem else "") + settled
            record["problem"] = problem
            record["message"] = message
            record["status"] = "failed" if problem else "done"
            if record["kind"] == "answer" and session is not None:
                sessions = self.sessions()
                sessions[record["subject"]] = session.id
                write_json(self.project.local / SESSIONS, sessions)
            self.save(record)
            self.progress.pop(identifier, None)

    def settled(self, role: str, session: Session | None) -> tuple[str, str | None]:
        """What the agent wrote in the store, settled as its own: the problems,
        said, and the id of its reply in the chat, if it wrote one."""
        writer = {
            "session": session.id if session is not None else None,
            "role": role,
            "parent": self.project.writer().get("session"),
        }
        result = Shared(self.project).settle_changes(lambda: by_for(self.project, writer=writer))
        Topics(self.project).heard(result)
        replies = [
            event["id"]
            for event in result.events
            if event.get("kind") == "message" and not event.get("item") and not event.get("asset")
        ]
        message = replies[-1] if replies else None
        if result.problems:
            return "what it wrote in .nock/shared/ does not hold: " + "; ".join(
                result.problems
            ), message
        return "", message

    def stop(self, identifier: str) -> dict[str, Any]:
        progress = self.progress.get(identifier)
        if progress is not None:
            progress.stop.set()
        return self.load(identifier)

    # --- the two kinds ------------------------------------------------------------

    def answer(self, topic: str) -> dict[str, Any]:
        """The owner's message in TOPIC's chat answered now: by an agent
        waiting on its inbox when one is, else by the answerer."""
        topics = Topics(self.project)
        said = pending(topics.topic(topic)["thread"])
        if said is None:
            raise UsageError(f"no message of yours waits for an answer in {topic}")
        if listeners(self.project):
            urge(self.project, said["id"])
            return {"listening": True, "topic": topic}
        comment = next(c for c in topics.comments() if c["ref"] == topic)
        prompt = Library(self.project.code_path("briefs"), BRIEFS).render(
            "answer.md",
            topic=topic,
            view=str(self.project.local / "views" / f"{topic}.md"),
            message=comment["text"] or "(no text: their notes are the message)",
            notes="\n".join(f"- on {note['target']}: {note['text']}" for note in comment["notes"]),
            files="\n".join(f"- {path}" for path in comment["files"]),
        )
        recipes = tuple(f"Bash({command})" for command in topics.recipes(topic))
        resume = self.sessions().get(topic)
        return self.start(
            "answer", topic, ANSWERER, prompt, f"Answering in {topic}", topic, recipes, resume
        )

    def round(self, name: str) -> dict[str, Any]:
        """A reflection round run whole, its result a task to review."""
        # A genuine cycle: the rounds read the topics.
        from nock.rounds import named, task_of

        found = named(self.project, name)
        if len(found) != 1:
            raise UsageError(f"name one round, not {name!r}")
        protocol = found[0]
        problem = protocol.unavailable()
        if problem:
            raise UsageError(f"{protocol.name} cannot run here: {problem}")
        topic = task_of(protocol)
        prompt = Library(self.project.code_path("briefs"), BRIEFS).render(
            "round.md", protocol=protocol.name, title=protocol.title, topic=topic
        )
        return self.start("round", protocol.name, REFLECTOR, prompt, protocol.title, topic)
