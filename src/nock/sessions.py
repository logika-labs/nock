"""Claude Code sessions, read from their transcripts into the telemetry store:
what the human asked, every tool call the agent made — with its input, how
long it took, whether it failed and how much it printed — its tokens and what
they would cost at API prices. A transcript is read on from where the last
read stopped, so a session that runs for days is counted as it goes, never
twice. Best effort over an internal format: a record that fits no shape is
skipped, never a crash. Transcripts stay on the machine that wrote them."""

from __future__ import annotations

import json
import os
import re
import sqlite3
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from nock.prices import KINDS, Prices
from nock.utils import now, parse_moment, read_json

if TYPE_CHECKING:
    from nock.project import Project

INTERRUPTED = "[Request interrupted by user"
# A session someone works in, and one run without a person: `claude -p` or the
# Agent SDK, whose transcripts say `"entrypoint": "sdk-…"`. A session nock
# dispatched carries the role it was dispatched as instead.
INTERACTIVE = "interactive"
HEADLESS = "headless"
PROMPT_LIMIT = 600
INPUT_LIMIT = 400
# The field of each tool's input that says what it was used on.
INPUT_FIELDS = {
    "Bash": "command",
    "Read": "file_path",
    "Edit": "file_path",
    "Write": "file_path",
    "MultiEdit": "file_path",
    "NotebookEdit": "notebook_path",
    "Glob": "pattern",
    "Grep": "pattern",
    "WebFetch": "url",
    "WebSearch": "query",
    "Agent": "description",
    "Task": "description",
    "Skill": "skill",
}


def headless(entrypoint: str | None) -> bool:
    """Whether a Claude Code entrypoint (`CLAUDE_CODE_ENTRYPOINT`, a
    transcript's `entrypoint`) runs without a person: `sdk-cli`, `sdk-py`,
    `sdk-ts`. Everything else — `cli`, an IDE, the desktop app — has one."""
    return bool(entrypoint) and str(entrypoint).startswith("sdk")


def configuration_directory() -> Path:
    return Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")


def encoded(path: Path) -> str:
    """How Claude Code names a project's transcript directory."""
    return re.sub(r"[^A-Za-z0-9]", "-", str(path))


def transcript_directories(root: Path) -> list[Path]:
    """The transcript directories of the checkout at `root` and of the
    worktrees beside it."""
    projects = configuration_directory() / "projects"
    if not projects.is_dir():
        return []
    prefix = encoded(root)
    return sorted(
        directory
        for directory in projects.iterdir()
        if directory.is_dir()
        and (directory.name == prefix or directory.name.startswith(prefix + "-"))
    )


def find_transcript(root: Path, session: str) -> Path | None:
    for directory in transcript_directories(root):
        candidate = directory / f"{session}.jsonl"
        if candidate.is_file():
            return candidate
    return None


@dataclass
class Event:
    moment: str | None
    tool: str
    input: str
    failed: bool = False
    output_bytes: int = 0
    duration: float | None = None
    # Its row in `events`, once written; a later read fills in its result.
    row: int | None = None


@dataclass
class Transcript:
    """What one transcript says, reduced to what telemetry keeps: totals over
    everything read so far, and the prompts and tool calls this read found."""

    session: str
    entrypoint: str | None = None
    directory: str | None = None
    title: str | None = None
    first_prompt: str | None = None
    started: str | None = None
    ended: str | None = None
    prompt_count: int = 0
    interrupts: int = 0
    compactions: int = 0
    # Tokens by model, then by kind (`prices.KINDS`).
    usage: dict[str, Counter[str]] = field(default_factory=dict)
    # What a `cost-state` record said the session cost, when one did.
    reported_cost: float | None = None
    seen: set[str] = field(default_factory=set)
    pending: dict[str, Event] = field(default_factory=dict)
    prompts: list[tuple[str | None, str]] = field(default_factory=list)
    events: list[Event] = field(default_factory=list)
    resolved: list[Event] = field(default_factory=list)

    @classmethod
    def resume(cls, session: str, state: dict[str, Any]) -> Transcript:
        """A transcript read up to where `state` (from `state()`) left off."""
        return cls(
            session=session,
            entrypoint=state.get("entrypoint"),
            directory=state.get("directory"),
            title=state.get("title"),
            first_prompt=state.get("first_prompt"),
            started=state.get("started"),
            ended=state.get("ended"),
            prompt_count=int(state.get("prompts") or 0),
            interrupts=int(state.get("interrupts") or 0),
            compactions=int(state.get("compactions") or 0),
            usage={model: Counter(tokens) for model, tokens in (state.get("usage") or {}).items()},
            reported_cost=state.get("reported_cost"),
            seen=set(state.get("seen") or []),
            pending={
                identity: Event(moment, "", "", row=row)
                for identity, (row, moment) in (state.get("pending") or {}).items()
            },
        )

    def state(self) -> dict[str, Any]:
        """What reading on from here needs."""
        return {
            "entrypoint": self.entrypoint,
            "directory": self.directory,
            "title": self.title,
            "first_prompt": self.first_prompt,
            "started": self.started,
            "ended": self.ended,
            "prompts": self.prompt_count,
            "interrupts": self.interrupts,
            "compactions": self.compactions,
            "usage": {model: dict(tokens) for model, tokens in self.usage.items()},
            "reported_cost": self.reported_cost,
            "seen": sorted(self.seen),
            "pending": {
                identity: [event.row, event.moment] for identity, event in self.pending.items()
            },
        }

    @property
    def tokens(self) -> Counter[str]:
        total: Counter[str] = Counter({kind: 0 for kind in KINDS})
        for tokens in self.usage.values():
            total.update(tokens)
        return total

    @property
    def model(self) -> str | None:
        """The model that did most of the work, by output tokens."""
        if not self.usage:
            return None
        return max(self.usage, key=lambda model: self.usage[model]["output"])

    def read(self, path: Path, offset: int = 0) -> int:
        """Fold in the whole lines from byte `offset` on; returns where the
        next read starts. A last line still being written waits for it."""
        with path.open("rb") as handle:
            handle.seek(offset)
            data = handle.read()
        end = data.rfind(b"\n") + 1
        lines = data[:end].split(b"\n")
        tail = data[end:]
        if tail.strip() and self.whole(tail):
            lines.append(tail)
            end = len(data)
        for line in lines:
            try:
                record = json.loads(line.decode(errors="replace"))
            except json.JSONDecodeError:
                continue
            if isinstance(record, dict):
                self.fold(record)
        return offset + end

    def whole(self, line: bytes) -> bool:
        try:
            return isinstance(json.loads(line.decode(errors="replace")), dict)
        except json.JSONDecodeError:
            return False

    def fold(self, record: dict[str, Any]) -> None:
        kind = record.get("type")
        moment = record.get("timestamp")
        if isinstance(moment, str) and parse_moment(moment):
            self.started = self.started or moment
            self.ended = moment
        else:
            moment = None
        if self.entrypoint is None and isinstance(record.get("entrypoint"), str):
            self.entrypoint = record["entrypoint"]
        if kind == "ai-title":
            self.title = record.get("aiTitle") or self.title
        elif kind == "cost-state":
            cost = record.get("totalCostUSD")
            if isinstance(cost, int | float) and not isinstance(cost, bool):
                self.reported_cost = float(cost)
        if record.get("isSidechain") or record.get("parent_tool_use_id"):
            return
        if self.directory is None and isinstance(record.get("cwd"), str):
            self.directory = record["cwd"]
        message = record.get("message")
        if not isinstance(message, dict):
            return
        if kind == "assistant":
            self.fold_assistant(message, moment)
        elif kind == "user":
            self.fold_user(record, message, moment)

    def fold_assistant(self, message: dict[str, Any], moment: str | None) -> None:
        identity = str(message.get("id") or "")
        usage = message.get("usage")
        model = str(message.get("model") or "unknown")
        if identity and identity not in self.seen and isinstance(usage, dict):
            self.seen.add(identity)
            if model != "<synthetic>":
                tokens = self.usage.setdefault(model, Counter())
                tokens["input"] += int(usage.get("input_tokens") or 0)
                tokens["output"] += int(usage.get("output_tokens") or 0)
                tokens["cache_read"] += int(usage.get("cache_read_input_tokens") or 0)
                tokens["cache_write"] += int(usage.get("cache_creation_input_tokens") or 0)
        for block in message.get("content") or []:
            if not isinstance(block, dict) or block.get("type") != "tool_use":
                continue
            name = str(block.get("name") or "")
            event = Event(moment, name, self.summarize(name, block.get("input")))
            self.events.append(event)
            self.pending[str(block.get("id"))] = event

    def summarize(self, name: str, raw: object) -> str:
        values: dict[str, Any] = raw if isinstance(raw, dict) else {}
        key = INPUT_FIELDS.get(name)
        value = values.get(key) if key else None
        text = str(value) if value is not None else json.dumps(values, ensure_ascii=False)
        if self.directory:
            text = text.replace(f"{self.directory}/", "")
        if name == "Grep" and values.get("path"):
            text += f" in {values['path']}"
        return text[:INPUT_LIMIT]

    def prompt(self, moment: str | None, text: str) -> None:
        self.prompts.append((moment, text[:PROMPT_LIMIT]))
        self.prompt_count += 1
        self.first_prompt = self.first_prompt or text[:PROMPT_LIMIT]

    def fold_user(
        self, record: dict[str, Any], message: dict[str, Any], moment: str | None
    ) -> None:
        if record.get("isCompactSummary"):
            self.compactions += 1
            return
        content = message.get("content")
        if isinstance(content, str):
            if record.get("isMeta") or content.startswith("<"):
                return
            if content.startswith(INTERRUPTED):
                self.interrupts += 1
                return
            self.prompt(moment, content)
            return
        if not isinstance(content, list):
            return
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "text":
                text = str(block.get("text") or "")
                if text.startswith(INTERRUPTED):
                    self.interrupts += 1
                elif not record.get("isMeta") and text and not text.startswith("<"):
                    self.prompt(moment, text)
            if block.get("type") != "tool_result":
                continue
            event = self.pending.pop(str(block.get("tool_use_id")), None)
            if event is None:
                continue
            event.failed = bool(block.get("is_error"))
            event.output_bytes = len(result_text(block.get("content")).encode())
            start, end = parse_moment(event.moment), parse_moment(moment)
            if start and end:
                event.duration = round((end - start).total_seconds(), 3)
            if event.row is not None:
                self.resolved.append(event)


def result_text(content: object) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            str(block.get("text") or "")
            for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        )
    return ""


# A background agent launched (its Agent tool result), and its end said back
# (the notification Claude Code queues for the session when it stops).
LAUNCHED = re.compile(r"Async agent launched.*?agentId: ([\w-]+)", re.DOTALL)
NOTIFIED = re.compile(
    r"<task-notification>\s*<task-id>([\w-]+)</task-id>.*?<status>(\w+)</status>", re.DOTALL
)


def background_agents(path: Path) -> set[str]:
    """The background agents the session of the transcript at `path` launched
    and has not heard back from: while there are any, a turn ending is the
    session waiting on them, and it gets another turn when each ends."""
    running: set[str] = set()
    with path.open("rb") as handle:
        for line in handle:
            try:
                record = json.loads(line.decode(errors="replace"))
            except json.JSONDecodeError:
                continue
            if not isinstance(record, dict) or record.get("isSidechain"):
                continue
            message = record.get("message")
            content = message.get("content") if isinstance(message, dict) else None
            said = [record.get("content")] if record.get("type") == "queue-operation" else []
            if record.get("type") == "user" and isinstance(content, str):
                said.append(content)
            for block in content if isinstance(content, list) else []:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "tool_result":
                    running.update(LAUNCHED.findall(result_text(block.get("content"))))
                elif block.get("type") == "text":
                    said.append(block.get("text"))
            for text in said:
                for agent, status in NOTIFIED.findall(text if isinstance(text, str) else ""):
                    if status != "running":
                        running.discard(agent)
    return running


class Sessions:
    def __init__(self, project: Project) -> None:
        self.project = project
        self.prices = Prices(project)

    def note_dispatch(self, session: str, role: str) -> None:
        path = self.project.local / "dispatched" / f"{session}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"role": role}))

    def role(self, session: str, entrypoint: str | None) -> str:
        """The role nock dispatched it as, else headless or interactive."""
        path = self.project.local / "dispatched" / f"{session}.json"
        if path.is_file():
            try:
                dispatched = read_json(path).get("role")
                if dispatched:
                    return str(dispatched)
            except Exception:
                pass
        return HEADLESS if headless(entrypoint) else INTERACTIVE

    def ingest(self, path: Path) -> Transcript:
        """Read what is new in one transcript into the store: from where the
        last read stopped, or — the first time, or when the file is not the
        one read before — from the start, replacing what an earlier read left."""
        session = path.stem
        with self.project.lock("transcripts"):
            known = self.project.store.rows(
                "SELECT path, offset, state FROM transcripts WHERE session = ?", (session,)
            )
            size = path.stat().st_size
            if known and known[0]["path"] == str(path) and known[0]["offset"] <= size:
                transcript = Transcript.resume(session, json.loads(known[0]["state"]))
                offset = known[0]["offset"]
            else:
                transcript, offset = Transcript(session), 0
            if known and offset == known[0]["offset"] == size:
                return transcript
            fresh = offset == 0
            offset = transcript.read(path, offset)
            cost = self.cost(transcript)
            with self.project.store.connection() as connection:
                if fresh:
                    for table, column in (
                        ("sessions", "id"),
                        ("prompts", "session"),
                        ("events", "session"),
                    ):
                        connection.execute(f"DELETE FROM {table} WHERE {column} = ?", (session,))
                self.write(connection, transcript, path, cost)
                for event in transcript.events:
                    event.row = connection.execute(
                        "INSERT INTO events (session, moment, tool, input, failed, output_bytes,"
                        " duration) VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (
                            session,
                            event.moment,
                            event.tool,
                            event.input,
                            int(event.failed),
                            event.output_bytes,
                            event.duration,
                        ),
                    ).lastrowid
                connection.executemany(
                    "UPDATE events SET failed = ?, output_bytes = ?, duration = ? WHERE rowid = ?",
                    [
                        (int(event.failed), event.output_bytes, event.duration, event.row)
                        for event in transcript.resolved
                    ],
                )
                connection.executemany(
                    "INSERT INTO prompts (session, moment, text) VALUES (?, ?, ?)",
                    [(session, moment, text) for moment, text in transcript.prompts],
                )
                connection.execute(
                    "INSERT OR REPLACE INTO transcripts (session, path, offset, state)"
                    " VALUES (?, ?, ?, ?)",
                    (session, str(path), offset, json.dumps(transcript.state())),
                )
        return transcript

    def write(
        self, connection: sqlite3.Connection, transcript: Transcript, path: Path, cost: float | None
    ) -> None:
        tokens = transcript.tokens
        title = transcript.title or (
            transcript.first_prompt[:120] if transcript.first_prompt else None
        )
        connection.execute(
            "INSERT OR REPLACE INTO sessions (id, role, title, started, ended, model, prompts,"
            " interrupts, compactions, input_tokens, output_tokens, cache_read_tokens,"
            " cache_write_tokens, cost, transcript, ingested)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                transcript.session,
                self.role(transcript.session, transcript.entrypoint),
                title,
                transcript.started,
                transcript.ended,
                transcript.model,
                transcript.prompt_count,
                transcript.interrupts,
                transcript.compactions,
                tokens["input"],
                tokens["output"],
                tokens["cache_read"],
                tokens["cache_write"],
                cost,
                str(path),
                now(),
            ),
        )

    def cost(self, transcript: Transcript) -> float | None:
        """What the session reported it cost, else its tokens at API prices;
        None when a model it used is unpriced."""
        if transcript.reported_cost is not None:
            return transcript.reported_cost
        return self.prices.cost(transcript.usage)

    def catch_up(self) -> int:
        """Read on in every transcript of this project that grew since it was
        last read — cheap when none did, one `stat` each — and cost the
        sessions left unpriced if prices can be had now; returns how many
        transcripts were read."""
        known = {
            row["session"]: (row["path"], row["offset"])
            for row in self.project.store.rows("SELECT session, path, offset FROM transcripts")
        }
        count = 0
        for directory in transcript_directories(self.project.root):
            for path in sorted(directory.glob("*.jsonl")):
                try:
                    size = path.stat().st_size
                except OSError:
                    continue
                if known.get(path.stem) == (str(path), size):
                    continue
                self.ingest(path)
                count += 1
        self.price_unpriced()
        return count

    def price_unpriced(self) -> None:
        rows = self.project.store.rows(
            "SELECT sessions.id, transcripts.state FROM sessions JOIN transcripts"
            " ON transcripts.session = sessions.id WHERE sessions.cost IS NULL"
            " AND sessions.model IS NOT NULL"
        )
        priced = []
        for row in rows:
            cost = self.cost(Transcript.resume(row["id"], json.loads(row["state"])))
            if cost is not None:
                priced.append((cost, row["id"]))
        if priced:
            with self.project.store.connection() as connection:
                connection.executemany("UPDATE sessions SET cost = ? WHERE id = ?", priced)

    def since(self, moment: str | None, role: str = INTERACTIVE) -> list[dict[str, Any]]:
        """Sessions of `role` (interactive: the ones a person worked in) that
        ended after `moment` (all of them when None), oldest first."""
        rows = self.project.store.rows(
            "SELECT * FROM sessions WHERE role = ? ORDER BY started", (role,)
        )
        start = parse_moment(moment)
        if start is None:
            return rows
        return [row for row in rows if (parse_moment(row["ended"]) or start) > start]
