"""The studio's chat: the owner's conversations with a headless Claude Code
session in the project, from the button beside the studio's settings. A chat
is one session (`dispatch.Dispatcher`, seat `chatter`: it reads, as the Ask
does, and changes nothing), its words streamed to the page as the agent
writes them (`--include-partial-messages`), continued turn by turn with
`--resume`; a chat whose session is gone continues in a new one, briefed
with the chat's transcript. Starting a new chat names the one before it: a
fresh agent (`namer`) gives it a title and a summary.

Tidy up is a chat too: an agent (`tidier`) reorganizes the topics through
nock's commands, which leave its writes uncommitted (`topics.TIDIER`); when
it ends they land as one commit, which Undo reverts. So is Address my
comments: an agent (`addresser`) answers each comment the owner left
waiting in a thread, making new versions and changing the code where one
asks for it; Address now does the same for one thread.

Chats are the owner's conversations, not the project's records: they are
kept on this machine, in `.nock/local/chats/ID.json`, never committed."""

from __future__ import annotations

import json
import re
import shutil
import threading
import uuid
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Any

from nock.asking import listing
from nock.dispatch import Dispatcher, Session
from nock.errors import ConflictError, Error, NotFoundError, UsageError
from nock.git import GitError
from nock.sessions import find_transcript
from nock.templates import Library
from nock.topics import ADDRESSER, TIDIER, Topics, attachment_name, committed, kind_of
from nock.utils import now, read_json, write_json

if TYPE_CHECKING:
    from nock.project import Project

BRIEFS = Path(__file__).resolve().parent / "briefs"
CHATTER = "chatter"
NAMER = "namer"
# The topics, as the main checkout keeps them: what Tidy up commits.
TOPICS = ".nock/topics"
# What the owner's first message in a Tidy up chat says.
TIDY_REQUEST = "Tidy up the topics: regroup the items, set the topics' states, drop what is stale, and put the topics in order."
# How much of one comment the request to address them quotes; the agent reads the rest.
QUOTED = 1_000
# The longest naming may take, in seconds.
NAMING_DEADLINE = 180
# How much of a chat a namer or a new session reads, in characters: its end.
TRANSCRIPT_LIMIT = 60_000
# How much of a command a line of activity shows.
SHOWN = 160


class Kind(StrEnum):
    CHAT = "chat"
    TIDY = "tidy"
    ADDRESS = "address"


# Who answers in each kind of chat.
ROLES = {Kind.CHAT: CHATTER, Kind.TIDY: TIDIER, Kind.ADDRESS: ADDRESSER}


def address_request(comments: list[dict[str, Any]]) -> str:
    """The owner's message starting Address my comments: each comment with
    its thread's ref, quoted."""
    count = len(comments)
    lines = [
        f"Address my {count} comments:" if count > 1 else "Address my comment:",
        "",
    ]
    for comment in comments:
        text = " ".join(comment["text"].split()) or "(files only)"
        if len(text) > QUOTED:
            text = text[: QUOTED - 1] + "…"
        about = f" ({comment['title']})" if comment["title"] else ""
        lines.append(f"- [{comment['ref']}]{about}: {text}")
        for path in comment["files"]:
            lines.append(f"  - attached: {path}")
    return "\n".join(lines)


@dataclass
class Turn:
    """An agent's answer under way: what it has written so far (whole blocks,
    and the block it is writing), what it ran, and the way to stop it."""

    started: str
    blocks: list[str] = field(default_factory=list)
    partial: str = ""
    activity: list[str] = field(default_factory=list)
    doing: str = ""
    """The tool it runs now; empty while it writes."""
    result: str | None = None
    stop: threading.Event = field(default_factory=threading.Event)
    buffer: bytes = b""

    @property
    def text(self) -> str:
        return "\n\n".join(part for part in [*self.blocks, self.partial] if part.strip())

    def hear(self, chunk: bytes) -> None:
        """A chunk of Claude Code's stream-json, read a line at a time."""
        self.buffer += chunk
        *lines, self.buffer = self.buffer.split(b"\n")
        for line in lines:
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(record, dict):
                self.record(record)

    def record(self, record: dict[str, Any]) -> None:
        kind = record.get("type")
        if kind == "stream_event":
            event = record.get("event") or {}
            delta = event.get("delta") or {}
            if event.get("type") == "content_block_delta" and delta.get("type") == "text_delta":
                self.partial += str(delta.get("text") or "")
                self.doing = ""
        elif kind == "assistant":
            for block in (record.get("message") or {}).get("content") or []:
                if block.get("type") == "text" and str(block.get("text") or "").strip():
                    self.blocks.append(str(block["text"]).strip())
                    self.doing = ""
                elif block.get("type") == "tool_use":
                    self.activity.append(activity(block))
                    self.doing = self.activity[-1]
            self.partial = ""
        elif kind == "result" and isinstance(record.get("result"), str):
            self.result = record["result"]

    def reset(self) -> None:
        self.blocks, self.partial, self.activity, self.doing = [], "", [], ""
        self.result, self.buffer = None, b""


def activity(block: dict[str, Any]) -> str:
    """A tool the agent ran, in a line: the command, the file or the pattern."""
    given = block.get("input") or {}
    said = given.get("command") or given.get("file_path") or given.get("pattern") or ""
    line = f"{block.get('name')}: {' '.join(str(said).split())}" if said else str(block.get("name"))
    return line if len(line) <= SHOWN else line[: SHOWN - 1] + "…"


def transcript(messages: list[dict[str, Any]]) -> str:
    """A chat's messages as a new session or a namer reads them: its end, when long."""
    said = "\n\n".join(
        f"**{'Owner' if entry['author'] == 'owner' else 'Agent'}:** {entry.get('text') or '(no answer)'}"
        for entry in messages
    )
    return said if len(said) <= TRANSCRIPT_LIMIT else "…" + said[-TRANSCRIPT_LIMIT:]


def named(text: str) -> tuple[str, str] | None:
    """The namer's title and summary, from the JSON in its last message."""
    found = re.search(r"\{.*\}", text or "", re.DOTALL)
    if not found:
        return None
    try:
        value = json.loads(found.group(0))
    except json.JSONDecodeError:
        return None
    if not isinstance(value, dict) or not str(value.get("title") or "").strip():
        return None
    return " ".join(str(value["title"]).split())[:80], " ".join(
        str(value.get("summary") or "").split()
    )[:300]


class Chats:
    """The chats kept on this machine, and the answers under way (one per
    chat; one Tidy up at a time)."""

    def __init__(self, project: Project) -> None:
        self.project = project
        self.directory = project.local / "chats"
        self.turns: dict[str, Turn] = {}
        self.naming: set[str] = set()
        self.lock = threading.RLock()

    # --- the store ------------------------------------------------------------

    def path(self, identifier: str) -> Path:
        if not re.fullmatch(r"[0-9a-f-]{8,64}", identifier):
            raise NotFoundError(f"no chat {identifier}")
        return self.directory / f"{identifier}.json"

    def load(self, identifier: str) -> dict[str, Any]:
        path = self.path(identifier)
        if not path.is_file():
            raise NotFoundError(f"no chat {identifier}")
        return read_json(path)

    def save(self, chat: dict[str, Any], said: bool = True) -> None:
        """`said`: something was said in it, which makes it the latest."""
        if said:
            chat["updated"] = now()
        write_json(self.path(chat["id"]), chat)

    def listing(self) -> list[dict[str, Any]]:
        """Every chat in a line, the latest first: its title (its first words
        until it is named), its summary, when it was last written in."""
        rows: list[tuple[int, dict[str, Any]]] = []
        for path in self.directory.glob("*.json") if self.directory.is_dir() else []:
            try:
                chat = read_json(path)
                written = path.stat().st_mtime_ns
            except (OSError, Error):
                continue
            first = next((entry["text"] for entry in chat["messages"] if entry.get("text")), "")
            rows.append(
                (
                    written,
                    {
                        "id": chat["id"],
                        "kind": chat["kind"],
                        "title": chat.get("title") or " ".join(first.split())[:60] or "New chat",
                        "summary": chat.get("summary") or "",
                        "created": chat["created"],
                        "updated": chat["updated"],
                        "messages": len(chat["messages"]),
                        "running": chat["id"] in self.turns,
                        **({"refs": chat["refs"]} if chat.get("refs") else {}),
                        "naming": chat["id"] in self.naming,
                    },
                )
            )
        # Written within the same second, the file's own time tells them apart.
        rows.sort(key=lambda row: (row[1]["updated"], row[0]), reverse=True)
        return [row for _, row in rows]

    def search(self, query: str) -> list[str]:
        """The chats holding every word searched for, in their title, summary
        or messages, as the list orders them: what the Chats list's search
        keeps."""
        wanted = query.lower().split()
        if not wanted:
            return []
        found = []
        for row in self.listing():
            try:
                messages = self.load(row["id"])["messages"]
            except Error:
                continue
            said = " ".join(
                [row["title"], row["summary"], *(entry.get("text") or "" for entry in messages)]
            ).lower()
            if all(word in said for word in wanted):
                found.append(row["id"])
        return found

    def shown(self, identifier: str) -> dict[str, Any]:
        """A chat as the page shows it: its messages, and the answer being written."""
        with self.lock:
            chat = self.load(identifier)
            turn = self.turns.get(identifier)
        live = (
            {
                "started": turn.started,
                "text": turn.text,
                "activity": turn.activity,
                "doing": turn.doing,
            }
            if turn is not None
            else None
        )
        return {**chat, "running": turn is not None, "live": live}

    # --- talking ----------------------------------------------------------------

    def send(
        self, identifier: str | None, text: str, files: list[Path] | None = None
    ) -> dict[str, Any]:
        """The owner's message, with the files it carries (moved beside the
        chat): in a new chat without `identifier`; the agent's answer starts
        at once, in the background."""
        files = files or []
        if not text.strip() and not files:
            raise UsageError("the message is empty")
        with self.lock:
            if identifier is None:
                chat = self.create(Kind.CHAT)
            else:
                chat = self.load(identifier)
                if chat["kind"] == Kind.TIDY:
                    raise UsageError("a Tidy up chat takes no messages: start a new chat")
                if identifier in self.turns:
                    raise ConflictError("the agent is still answering: wait for it, or stop it")
            said: dict[str, Any] = {"author": "owner", "text": text.strip(), "moment": now()}
            if files:
                said["attachments"] = self.attach(chat["id"], files, said["moment"])
            chat["messages"].append(said)
            self.save(chat)
            self.start(chat)
        return self.shown(chat["id"])

    def attach(self, identifier: str, files: list[Path], stamp: str) -> list[dict[str, Any]]:
        """Files moved beside the chat, in a folder of their message's own."""
        label = stamp.replace("-", "").replace(":", "")
        folder, number = self.directory / identifier / label, 2
        while folder.exists():
            folder, number = self.directory / identifier / f"{label}-{number}", number + 1
        folder.mkdir(parents=True)
        kept = []
        for source in files:
            name = attachment_name(source.name)
            target = folder / name
            while target.exists():
                target = folder / f"{target.stem}-2{target.suffix}"
            shutil.move(source, target)
            with target.open("rb") as handle:
                kind = kind_of(target.name, handle.read(65536))
            kept.append(
                {
                    "name": target.name,
                    "type": kind,
                    "bytes": target.stat().st_size,
                    "path": str(target.relative_to(self.directory / identifier)),
                }
            )
        return kept

    def attachment(self, identifier: str, path: str) -> Path:
        """One of the files a chat's messages carry; only those."""
        for said in self.load(identifier)["messages"]:
            for file in said.get("attachments") or []:
                if file["path"] == path:
                    return self.directory / identifier / path
        raise NotFoundError(f"chat {identifier} has no file {path}")

    def tidy(self) -> dict[str, Any]:
        """Tidy up: a new chat whose agent reorganizes the topics."""
        with self.lock:
            running = [key for key in self.turns if self.load(key)["kind"] == Kind.TIDY]
            if running:
                raise ConflictError("Tidy up is already under way")
            chat = self.create(Kind.TIDY)
            chat["title"] = "Tidy up"
            chat["messages"].append({"author": "owner", "text": TIDY_REQUEST, "moment": now()})
            self.save(chat)
            self.start(chat)
        return self.shown(chat["id"])

    def address(self, ref: str | None = None) -> dict[str, Any]:
        """Address my comments: a new chat whose agent answers every comment
        the owner left waiting in a thread; with REF (a topic's name or an
        item's ref), Address now, the comment in that one thread. One such
        chat at a time for each thread."""
        with self.lock:
            comments = Topics(self.project).comments()
            if ref is not None:
                comments = [comment for comment in comments if comment["ref"] == ref]
                if not comments:
                    raise UsageError(f"no comment of yours waits for an answer in {ref}")
            elif not comments:
                raise UsageError("no comment of yours waits for an answer")
            busy = self.addressing()
            if any(comment["ref"] in busy for comment in comments):
                raise ConflictError("your comments are being addressed already")
            chat = self.create(Kind.ADDRESS)
            chat["title"] = "Address now" if ref is not None else "Address my comments"
            chat["refs"] = [comment["ref"] for comment in comments]
            said = address_request(comments)
            chat["messages"].append({"author": "owner", "text": said, "moment": now()})
            self.save(chat)
            self.start(chat)
        return self.shown(chat["id"])

    def addressing(self) -> set[str]:
        """The threads whose comments an agent is answering now."""
        refs: set[str] = set()
        with self.lock:
            for key in list(self.turns):
                try:
                    chat = self.load(key)
                except Error:
                    continue
                if chat["kind"] == Kind.ADDRESS:
                    refs.update(chat.get("refs") or [])
        return refs

    def create(self, kind: str) -> dict[str, Any]:
        moment = now()
        return {
            "id": str(uuid.uuid4()),
            "kind": kind,
            "session": None,
            "title": "",
            "summary": "",
            "named": 0,
            "created": moment,
            "updated": moment,
            "messages": [],
        }

    def start(self, chat: dict[str, Any]) -> None:
        turn = Turn(started=now())
        self.turns[chat["id"]] = turn
        threading.Thread(target=self.answer, args=(chat["id"], turn), daemon=True).start()

    def stop(self, identifier: str) -> dict[str, Any]:
        turn = self.turns.get(identifier)
        if turn is not None:
            turn.stop.set()
        return self.shown(identifier)

    def answer(self, identifier: str, turn: Turn) -> None:
        """One turn: the agent's answer to the owner's last message, kept with
        what it ran; for Tidy up, its writes then committed together."""
        try:
            self.answered(identifier, turn)
        finally:
            with self.lock:
                self.turns.pop(identifier, None)

    def answered(self, identifier: str, turn: Turn) -> None:
        chat = self.load(identifier)
        reply: dict[str, Any] = {"author": "agent", "moment": now()}
        session: Session | None = None
        try:
            session = self.converse(chat, turn)
        except Error as error:
            reply["problem"] = str(error)
        reply["text"] = turn.text or (turn.result or "").strip()
        reply["activity"] = turn.activity
        if session is not None and session.exit_code != 0:
            reply["problem"] = (
                "stopped"
                if turn.stop.is_set()
                else f"the agent stopped (exit {session.exit_code}; log: {session.log})"
            )
            if session.denied:
                reply["problem"] += "; refused: " + "; ".join(session.denied)
        reply["moment"] = now()
        with self.lock:
            chat = self.load(identifier)
            if session is not None:
                chat["session"] = session.id
            chat["messages"].append(reply)
            if chat["kind"] == Kind.TIDY:
                # Its last message is the summary: what it said along the way is not.
                summary = (turn.result or reply["text"] or "").strip()
                chat["tidy"] = self.gather(summary)
                chat["summary"] = " ".join(summary.split())[:300]
            elif chat["kind"] == Kind.ADDRESS and not chat["summary"]:
                summary = (turn.result or reply["text"] or "").strip()
                chat["summary"] = " ".join(summary.split())[:300]
            self.save(chat)

    def converse(self, chat: dict[str, Any], turn: Turn) -> Session:
        """Continue the chat's session when Claude Code still has it; else, or
        when resuming fails before a word, a new one briefed with what was said."""
        role = ROLES[Kind(chat["kind"])]
        said = self.heard(chat, chat["messages"][-1])
        earlier = chat["messages"][:-1]
        previous = chat.get("session")
        if previous and find_transcript(self.project.root, previous) is not None:
            session = self.launch(role, said, turn, resume=previous)
            if session.exit_code == 0 or turn.text or turn.stop.is_set():
                return session
            turn.reset()
        return self.launch(role, self.brief(chat, said, earlier), turn)

    def heard(self, chat: dict[str, Any], said: dict[str, Any]) -> str:
        """The owner's message as the agent reads it: the files it carries named
        by where they are, to read."""
        files = said.get("attachments") or []
        if not files:
            return said["text"]
        listed = "\n".join(
            f"- {self.directory / chat['id'] / file['path']} ({file['type']})" for file in files
        )
        return f"{said['text']}\n\nThe owner attached these files (read them):\n{listed}".strip()

    def launch(self, role: str, prompt: str, turn: Turn, resume: str | None = None) -> Session:
        return Dispatcher(self.project).launch(
            role,
            prompt,
            self.project.here,
            resume=resume,
            arguments=("--include-partial-messages",),
            listener=turn.hear,
            stop=turn.stop,
        )

    def brief(self, chat: dict[str, Any], said: str, earlier: list[dict[str, Any]]) -> str:
        library = Library(self.project.code_path("briefs"), BRIEFS)
        topics = listing(Topics(self.project))
        if chat["kind"] == Kind.TIDY:
            return library.render("tidy.md", topics=topics)
        if chat["kind"] == Kind.ADDRESS:
            return library.render(
                "address.md",
                message=said,
                transcript=transcript(earlier) if earlier else "",
            )
        context = self.project.code_path("context.md")
        return library.render(
            "chat.md",
            message=said,
            topics=topics,
            context=context.read_text().strip() if context.is_file() else "",
            transcript=transcript(earlier) if earlier else "",
        )

    # --- naming -----------------------------------------------------------------

    def leave(self, identifier: str) -> dict[str, Any]:
        """The owner starts a new chat: the one they leave is named, in the
        background, when something was said since it last was."""
        with self.lock:
            chat = self.load(identifier)
            fresh = chat["kind"] == Kind.CHAT and chat.get("named", 0) < len(chat["messages"])
            if fresh and identifier not in self.turns and identifier not in self.naming:
                self.naming.add(identifier)
                threading.Thread(target=self.name, args=(identifier,), daemon=True).start()
        return {"naming": identifier in self.naming}

    def name(self, identifier: str) -> None:
        try:
            chat = self.load(identifier)
            count = len(chat["messages"])
            brief = Library(self.project.code_path("briefs"), BRIEFS).render(
                "name.md", transcript=transcript(chat["messages"])
            )
            session = Dispatcher(self.project).launch(
                NAMER, brief, self.project.here, deadline=NAMING_DEADLINE
            )
            found = named(session.result or "")
            with self.lock:
                chat = self.load(identifier)
                if found:
                    chat["title"], chat["summary"] = found
                elif not chat.get("title"):
                    first = chat["messages"][0]["text"] if chat["messages"] else ""
                    chat["title"] = " ".join(first.split())[:60]
                chat["named"] = count
                self.save(chat, said=False)
        except Error:
            pass
        finally:
            self.naming.discard(identifier)

    # --- Tidy up's one commit ---------------------------------------------------

    def gather(self, summary: str) -> dict[str, Any]:
        """Tidy up's writes to the topics, committed as one, its summary the
        message; nothing changed, nothing committed."""
        git = self.project.git
        if not git("status", "--porcelain", "--", TOPICS):
            return {"commit": None}
        first = next(
            (line.strip("#*- ").strip() for line in summary.splitlines() if line.strip()), ""
        )
        subject = f"Topics tidied up: {first}" if first else "Topics tidied up by Tidy up"
        if len(subject) > 100:
            subject = subject[:99] + "…"
        body = f"{subject}\n\n{summary}\n" if summary else subject
        try:
            problem = committed(self.project, [TOPICS], body)
        except GitError as error:
            return {"commit": None, "problem": str(error)}
        if problem:
            return {"commit": None, "problem": problem}
        return {"commit": git("rev-parse", "HEAD"), "subject": subject}

    def undo(self, identifier: str) -> dict[str, Any]:
        """Revert Tidy up's commit (`git revert`), when nothing since conflicts with it."""
        with self.lock:
            chat = self.load(identifier)
            done = chat.get("tidy") or {}
            if not done.get("commit"):
                raise UsageError("this chat committed nothing to undo")
            if done.get("reverted"):
                raise ConflictError("Tidy up was undone already")
            git = self.project.git
            try:
                git("revert", "--no-edit", done["commit"])
            except GitError as error:
                git("revert", "--abort", check=False)
                raise ConflictError(
                    "Tidy up cannot be undone cleanly: what changed since touches the same topics"
                    f" — revert {done['commit'][:12]} by hand ({error.output.strip()[:200]})"
                ) from error
            done["reverted"] = git("rev-parse", "HEAD")
            chat["tidy"] = done
            self.save(chat)
        return self.shown(identifier)
