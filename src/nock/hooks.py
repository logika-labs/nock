"""Claude Code's hook events, handled: `nock hook EVENT` reads the payload on
stdin and answers in Claude Code's hook format. nock's own: a session starts
knowing the toolbox and — when the human started it — where things stand
(a reflection round due, decisions waiting on review or rework); a prompt
brings the owner's reviews of the decisions the session recorded; an edit to
a file shows the decisions that govern it; and the transcript is read into
telemetry when the session ends. What calls for the owner is also said to
the human. The project's `@nock.hook`s run after. Every handler fails open —
a nock that cannot load must never block the tool call that would fix it."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from nock.decisions import Decisions
from nock.fixtures import Call, Scope
from nock.project import Project
from nock.sessions import Sessions
from nock.status import Standing
from nock.tools import NATIVE_EVENTS, Event

EVENTS = {native: event for event, native in NATIVE_EVENTS.items()}
# The events nock itself always listens to.
BUILT_IN_EVENTS = (Event.SESSION_START, Event.PROMPT, Event.AFTER_TOOL, Event.SESSION_END)
# The tools whose use is an edit, as a Claude Code matcher: the after-tool handler's.
EDIT_TOOLS = "Edit|MultiEdit|Write|NotebookEdit"
# What the standing a session starts with is, and what to do with it.
STANDING_PREFACE = (
    "Where the project stands with nock, as this session starts. It is not your task: work"
    " on what the human asks. Take into account what bears on it, and mention the rest to"
    " the human only when it is relevant to the request, or once your work is done."
)


class Block(Exception):
    """Raised by a `stop` hook to refuse the end of a turn, with the reason."""


class HookRunner:
    def __init__(self, project: Project, payload: dict[str, Any]) -> None:
        self.project = project
        self.payload = payload
        # What the human should see, beside what the agent reads.
        self.notices: list[str] = []

    def handle(self, native: str) -> dict[str, Any] | None:
        event = EVENTS[native]
        messages: list[str] = []
        if event is Event.SESSION_START:
            messages.append(self.session_start())
        elif event is Event.PROMPT:
            messages.append(self.reviews())
        elif event is Event.AFTER_TOOL:
            messages.append(self.decisions())
        elif event is Event.SESSION_END:
            self.session_end()
        blocks: list[str] = []
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
            lines.append("This project's nock tools (`.nock/nock NAME --help` for usage):")
            lines += [f"- {tool.command.usage()}: {tool.command.summary}" for tool in own]
        if registry.failures:
            lines += [f"nock: a tool did not load — {failure}" for failure in registry.failures]
        if self.project.current_role() is None:
            standing = Standing(self.project)
            collected = standing.collect()
            unshared = collected["unshared"]
            if unshared and self.project.store.rows(
                "SELECT round FROM nudged WHERE round = ?", (unshared,)
            ):
                collected["unshared"] = None
            elif unshared:
                self.project.store.insert("nudged", {"round": unshared})
            said = standing.lines(collected)
            if said:
                lines += [STANDING_PREFACE, *said]
            # The human hears what calls for them; the backlog and their own notes, they know.
            self.notices += [
                line for line in said if line.startswith("nock:") and "the owner" not in line
            ]
        return "\n".join(lines)

    def decisions(self) -> str:
        """The standing decisions that govern the file just edited, the first
        time this session edits it."""
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
        found = Decisions(self.project).reminders_for(session, relative)
        if not found:
            return ""
        lines = [f"nock: decisions govern {relative} — keep to them, or record why not:"]
        for decision in found:
            note = f" The owner: {decision['note']}" if decision["note"] else ""
            lines.append(
                f"- [D{decision['number']}] ({decision['status']}, {decision['review']}) "
                f"{decision['title']}.{note}"
            )
        lines.append("`.nock/nock decisions show N` has the reasoning.")
        return "\n".join(lines)

    def reviews(self) -> str:
        """The owner's reviews and notes on this session's decisions, the first time it sees them."""
        session = self.payload.get("session_id")
        if not isinstance(session, str):
            return ""
        lines = []
        for decision in Decisions(self.project).news_for(session):
            note = f": {decision['note']}" if decision["note"] else ""
            lines.append(
                f"- [D{decision['number']}] {decision['title']} — {decision['review']}{note}"
            )
        if not lines:
            return ""
        return "\n".join(
            [
                "nock: the owner reviewed decision(s) you recorded:",
                *lines,
                "Rework what was rejected, act on what they answered, and edit the decision to say what you did: "
                "`.nock/nock decisions edit '{\"number\": N, …}'`.",
            ]
        )

    def session_end(self) -> None:
        transcript = self.payload.get("transcript_path")
        if isinstance(transcript, str) and Path(transcript).is_file():
            Sessions(self.project).ingest(Path(transcript))


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
