"""Claude Code's hook events, handled: `nock hook EVENT` reads the payload on
stdin and answers in Claude Code's hook format. nock's own: a session starts
knowing the toolbox, upgraded to a newer nock when the merge is clean
(`upgrade.auto`), and — when the human started it, once a day or when
something new calls — where things stand, in a few lines (a reflection round
due, what is new in Topics and what waits on an agent there, another kind of round worth
offering); a
prompt brings the owner's verdicts and messages on the items the session
submitted; a `.nock/nock` command about to run is noted with the subagent
running it, if any (`callers.py`), so what it writes names its parent session;
an edit to a file shows the items about it; and when the session ends
its transcript is read into telemetry and, when due, the usage statistics
are shared. A turn that would end with a round this session started still
open is refused once, saying what the round still needs — unless it ends only
to wait on the background agents it launched, the round's parts — and so, once a
session, is one that wrote to a topic without ever setting where it stands
(its state or status). What calls for the owner is also said to the human. With
`reminders = false` nock says nothing unasked, and still records. The
project's `@nock.hook`s run after. Every handler fails open — a nock that
cannot load must never block the tool call that would fix it."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from nock.callers import Callers
from nock.fixtures import Call, Scope
from nock.kinds import kinds
from nock.primer import refresh
from nock.project import NOCK_DIRECTORY, Project
from nock.releases import Updates
from nock.sessions import Sessions, background_agents, find_transcript
from nock.status import Standing
from nock.tools import CONFIRM_NOTES, NATIVE_EVENTS, Event
from nock.topics import Author, Topics
from nock.usage import Usage

EVENTS = {native: event for event, native in NATIVE_EVENTS.items()}
# The events nock itself always listens to.
BUILT_IN_EVENTS = (
    Event.SESSION_START,
    Event.PROMPT,
    Event.BEFORE_TOOL,
    Event.AFTER_TOOL,
    Event.STOP,
    Event.SESSION_END,
)
# The tools whose use is an edit, as a Claude Code matcher: the after-tool handler's.
EDIT_TOOLS = "Edit|MultiEdit|Write|NotebookEdit"
# The before-tool handler's: only Bash commands running nock, as Claude Code's hook `if` rule.
NOCK_COMMANDS = "Bash(*.nock/nock *)"
# The longest a session start waits on an upgrade, in seconds: two wheels downloaded, a merge.
UPGRADE_DEADLINE = 120
# What the standing a session starts with is, and what to do with it.
STANDING_PREFACE = (
    "Where the project stands with nock (not your task: take into account what bears on the"
    " request, and mention the rest to the human only when relevant, or once you are done):"
)


class Block(Exception):
    """Raised by a `stop` hook to refuse the end of a turn, with the reason."""


class HookRunner:
    def __init__(self, project: Project, payload: dict[str, Any]) -> None:
        self.project = project
        self.payload = payload
        # What the human should see, beside what the agent reads.
        self.notices: list[str] = []

    @property
    def reminding(self) -> bool:
        """Whether nock may speak up unasked (`reminders`)."""
        return self.project.configuration.get("reminders") is not False

    def handle(self, native: str) -> dict[str, Any] | None:
        event = EVENTS[native]
        messages: list[str] = []
        if event is Event.SESSION_START:
            refresh(self.project.here / NOCK_DIRECTORY)
            if self.project.current_role() is None:
                upgraded = self.upgrade_itself()
                messages.append(upgraded)
                self.notices += [upgraded] if upgraded else []
            if self.reminding:
                messages.append(self.session_start())
        elif event is Event.PROMPT and self.reminding:
            messages.append(self.reviews())
        elif event is Event.BEFORE_TOOL:
            Callers(self.project.store).note(self.payload)
        elif event is Event.AFTER_TOOL and self.reminding:
            messages.append(self.items_about())
        elif event is Event.SESSION_END:
            self.session_end()
        blocks: list[str] = []
        if event is Event.STOP and not self.waiting():
            blocks += self.rounds_left_open()
            if self.reminding:
                blocks += self.topics_unstated()
        for entry in self.project.registry.hooks_for(event):
            values = {
                "project": self.project,
                "payload": self.payload,
                "call": Call(None, f"hook {entry.name}"),
            }
            try:
                with Scope(self.project.registry, values) as scope:
                    result = scope.call(entry.function)
            except Block as block:
                blocks.append(str(block))
                continue
            except Exception as error:
                print(
                    f"nock: hook {entry.name} ({entry.source}) failed: {error!r}", file=sys.stderr
                )
                continue
            if isinstance(result, str) and result.strip():
                messages.append(result.strip())
        if blocks and event is Event.STOP and self.payload.get("stop_hook_active") is not True:
            return {"decision": "block", "reason": "\n".join(blocks)}
        text = "\n\n".join(message for message in messages if message)
        output: dict[str, Any] = {}
        if self.notices:
            output["systemMessage"] = "\n".join(self.notices)
        if text and event not in (Event.STOP, Event.SESSION_END):
            output["hookSpecificOutput"] = {"hookEventName": native, "additionalContext": text}
        return output or None

    def session_start(self) -> str:
        """The toolbox, so the session reaches for a tool before scripting one,
        and — for a session the human started — where things stand."""
        registry = self.project.registry
        lines = []
        own = registry.project_tools()
        if own:
            note = CONFIRM_NOTES[self.project.configuration.confirm()]
            lines.append("This project's nock tools (`.nock/nock NAME --help` for usage):")
            lines += [
                f"- {tool.command.usage()}: {tool.command.summary}" + (note if tool.confirm else "")
                for tool in own
            ]
        if registry.failures:
            lines += [f"nock: a tool did not load — {failure}" for failure in registry.failures]
        if self.project.current_role() is None:
            said = self.standing()
            if said:
                lines += [STANDING_PREFACE, *said]
            # The human hears what calls for them; the backlog and their own notes, they know.
            self.notices += [
                line for line in said if line.startswith("nock:") and "the owner" not in line
            ]
        return "\n".join(lines)

    def upgrade_itself(self) -> str:
        """A newer release merged into the core by itself, when the merge is
        clean, said in a line; on a conflict nothing changes, and the standing
        says the release is out, as it does with `upgrade.auto` off. The owner
        made it the default, so it runs without the ask `nock upgrade` has."""
        updates = Updates(self.project)
        latest = updates.automatic()
        if latest is None:
            return ""
        before = updates.installed()
        try:
            done = subprocess.run(
                [str(self.project.here / NOCK_DIRECTORY / "nock"), "upgrade", "--only-clean"],
                cwd=self.project.here,
                capture_output=True,
                text=True,
                timeout=UPGRADE_DEADLINE,
            )
        except (OSError, subprocess.TimeoutExpired):
            return ""
        if done.returncode != 0:
            return ""
        return (
            f"nock: upgraded itself to {updates.installed()} (from {before}), a clean merge; "
            "`.nock/` and `.claude/` changed, to commit (`upgrade.auto = false` turns this off)."
        )

    def standing(self) -> list[str]:
        """Where things stand, said once a day — sooner when something new
        calls: a round falls due, the owner rejects something."""
        store = self.project.store

        def seen(key: str) -> bool:
            if store.rows("SELECT round FROM nudged WHERE round = ?", (key,)):
                return True
            store.insert("nudged", {"round": key})
            return False

        standing = Standing(self.project)
        collected = standing.collect()
        offers = sorted(kind for kind, offer in collected["rounds"].items() if offer.get("due"))
        news = [
            bool(collected["reflection"]["due"]),
            collected["topics"]["awaiting_you"],
            collected["unshared"],
            collected["newer_nock"],
            offers,
        ]
        if not standing.lines(collected):
            return []
        digest = hashlib.sha256(json.dumps(news).encode()).hexdigest()[:16]
        if seen(f"standing:{datetime.now(UTC).date().isoformat()}:{digest}"):
            return []
        # An unshared summary is mentioned once per round.
        if collected["unshared"] and seen(collected["unshared"]):
            collected["unshared"] = None
        # Another kind of round is offered gently: at most once a week while it is due.
        year, week, _ = datetime.now(UTC).isocalendar()
        for kind in offers:
            offer = collected["rounds"][kind]
            if seen(f"{kind}:{offer['last'] or 'never'}:{year}-{week}"):
                del collected["rounds"][kind]
        return standing.lines(collected)

    def items_about(self) -> str:
        """The items about the file just edited (holding it, or derived from
        it), the first time this session edits it."""
        session = self.payload.get("session_id")
        tool_input = self.payload.get("tool_input")
        if not isinstance(session, str) or not isinstance(tool_input, dict):
            return ""
        target = tool_input.get("file_path") or tool_input.get("notebook_path")
        if not isinstance(target, str):
            return ""
        path = Path(target)
        path = path if path.is_absolute() else self.project.here / path
        if not path.resolve().is_relative_to(self.project.here.resolve()):
            return ""
        relative = str(path.resolve().relative_to(self.project.here.resolve()))
        found = Topics(self.project).governing(session, relative)
        if not found:
            return ""
        lines = [f"nock: items in Topics are about {relative} — keep to them, or say why not:"]
        lines += [f"- [{item['ref']}] ({item['verdict']}) {item['title']}" for item in found]
        lines.append("`.nock/nock items show REF` has each in full.")
        return "\n".join(lines)

    def reviews(self) -> str:
        """The owner's verdicts and messages on the items this session
        submitted, the first time it sees them: never what it recorded
        itself, nor anything on a dropped item."""
        session = self.payload.get("session_id")
        if not isinstance(session, str):
            return ""
        lines = []
        topics = Topics(self.project)
        for item in topics.news_for(session):
            said = [entry for entry in item["thread"] if entry["author"] == Author.OWNER]
            note = f": {said[-1]['text']}" if said and said[-1]["text"] else ""
            lines.append(f"- [{item['ref']}] {item['title']} — {item['verdict']}{note}")
            files = topics.attached(said[-1], item["topic"], item["slug"]) if said else []
            if files:
                lines.append(f"  attached (Read them): {', '.join(files)}")
        if not lines:
            return ""
        return "\n".join(
            [
                "nock: the owner said something on item(s) you submitted:",
                *lines,
                "Rework what was rejected as a new version (`.nock/nock items update REF --version '{…}'`);"
                " answer a question in the thread (`--reply`), briefly, when the owner is away.",
            ]
        )

    def waiting(self) -> bool:
        """Whether the turn ends only to wait on background agents it launched
        (a round's parts), which give the session another turn as they end:
        nock asks for nothing then, and asks at the turn after the last."""
        session = self.payload.get("session_id")
        transcript = self.payload.get("transcript_path")
        path = (
            Path(transcript)
            if isinstance(transcript, str)
            else find_transcript(self.project.root, session)
            if isinstance(session, str)
            else None
        )
        return path is not None and path.is_file() and bool(background_agents(path))

    def rounds_left_open(self) -> list[str]:
        """Every round this session started and has not finished, with what it still needs."""
        session = self.payload.get("session_id")
        if not isinstance(session, str) or self.payload.get("stop_hook_active") is True:
            return []
        return [said for kind in kinds(self.project) if (said := kind.left_open(session))]

    def topics_unstated(self) -> list[str]:
        """Once a session: the topics it wrote to (itself or through its
        subagents) and never said where they stand."""
        session = self.payload.get("session_id")
        if not isinstance(session, str) or self.payload.get("stop_hook_active") is True:
            return []
        store = self.project.store
        if store.rows("SELECT session FROM stated WHERE session = ?", (session,)):
            return []
        names = Topics(self.project).unstated(session)
        if not names:
            return []
        store.insert("stated", {"session": session})
        listed = ", ".join(names)
        return [
            f"nock: you worked in topic(s) {listed} and never set where they stand. Before you"
            f' stop: `.nock/nock topics update {names[0]} \'{{"status": "…"}}\'` — or'
            ' `{"state": "review"}` when it is built and only the owner\'s verdicts remain,'
            ' `{"state": "done"}` (or "abandoned") when the work is finished.'
        ]

    def session_end(self) -> None:
        transcript = self.payload.get("transcript_path")
        if isinstance(transcript, str) and Path(transcript).is_file():
            Sessions(self.project).ingest(Path(transcript))
        if self.project.current_role() is None:
            Usage(self.project).send()


def run(native: str, stdin_text: str) -> int:
    """The hook entry point; always exits 0 — a block is said in the output."""
    if native not in EVENTS:
        print(f"nock: unknown hook event {native!r}; known: {', '.join(EVENTS)}", file=sys.stderr)
        return 0
    try:
        payload = json.loads(stdin_text) if stdin_text.strip() else {}
        payload = payload if isinstance(payload, dict) else {}
        project = Project.discover(Path(payload.get("cwd") or "."))
        output = HookRunner(project, payload).handle(native)
    except Exception as error:  # fail open: nock must never wedge the session
        print(f"nock: the {native} hook failed and was skipped: {error!r}", file=sys.stderr)
        return 0
    if output is not None:
        print(json.dumps(output))
    return 0
