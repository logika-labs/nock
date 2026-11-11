"""The hook events nock knows, by its names and Claude Code's, and the
coding-agent harnesses nock wires itself into — Claude Code always,
Codex and Cursor where the repository or `PATH` has them — and, for each,
where its skills, hooks and instructions go and which of nock's hook events
it can send."""

from __future__ import annotations

import shutil
from enum import StrEnum
from pathlib import Path


class Event(StrEnum):
    """What a `@nock.hook` reacts to: Claude Code's hook events, by nock's names."""

    SESSION_START = "session-start"
    PROMPT = "prompt"
    BEFORE_TOOL = "before-tool"
    AFTER_TOOL = "after-tool"
    TOOL_FAILED = "tool-failed"
    STOP = "stop"
    SESSION_END = "session-end"


# Claude Code's name for each event.
NATIVE_EVENTS = {
    Event.SESSION_START: "SessionStart",
    Event.PROMPT: "UserPromptSubmit",
    Event.BEFORE_TOOL: "PreToolUse",
    Event.AFTER_TOOL: "PostToolUse",
    Event.TOOL_FAILED: "PostToolUseFailure",
    Event.STOP: "Stop",
    Event.SESSION_END: "SessionEnd",
}

# The events nock itself listens to in Claude Code.
BUILT_IN_EVENTS = (
    Event.SESSION_START,
    Event.PROMPT,
    Event.BEFORE_TOOL,
    Event.AFTER_TOOL,
    Event.STOP,
    Event.SESSION_END,
)


class Harness(StrEnum):
    """By the word its hook commands carry (`.nock/nock hook EVENT WORD`)."""

    CLAUDE_CODE = "claude"
    CODEX = "codex"
    CURSOR = "cursor"

    @property
    def label(self) -> str:
        return {
            Harness.CLAUDE_CODE: "Claude Code",
            Harness.CODEX: "Codex",
            Harness.CURSOR: "Cursor",
        }[self]

    def found(self, root: Path) -> bool:
        """Claude Code always; Codex and Cursor when the repository has their
        directory or their command is on `PATH`."""
        if self is Harness.CLAUDE_CODE:
            return True
        directory, commands = {
            Harness.CODEX: (".codex", ("codex",)),
            Harness.CURSOR: (".cursor", ("cursor", "cursor-agent")),
        }[self]
        return (root / directory).is_dir() or any(shutil.which(name) for name in commands)

    @property
    def skills_directory(self) -> str:
        return {
            Harness.CLAUDE_CODE: ".claude/skills",
            Harness.CODEX: ".agents/skills",
            Harness.CURSOR: ".cursor/skills",
        }[self]

    @property
    def skills_read(self) -> tuple[str, ...]:
        """Every project skills directory it reads: Cursor reads Claude Code's
        and Codex's too, so a copy of its own would list each skill twice."""
        if self is Harness.CURSOR:
            return (".cursor/skills", ".agents/skills", ".claude/skills", ".codex/skills")
        return (self.skills_directory,)

    @property
    def hooks_file(self) -> str:
        return {
            Harness.CLAUDE_CODE: ".claude/settings.json",
            Harness.CODEX: ".codex/hooks.json",
            Harness.CURSOR: ".cursor/hooks.json",
        }[self]

    @property
    def events(self) -> dict[Event, str]:
        """The events it sends that nock handles, by its own name for each.
        Codex's payloads and answers are Claude Code's, without a session end
        or a failed tool; Cursor can be told something only at a session's
        start and its stop, and its payloads are its own, so a project's
        `@nock.hook`s, written for Claude Code's, are not wired there."""
        if self is Harness.CURSOR:
            return {Event.SESSION_START: "sessionStart", Event.STOP: "stop"}
        if self is Harness.CODEX:
            return {
                event: native
                for event, native in NATIVE_EVENTS.items()
                if event not in (Event.TOOL_FAILED, Event.SESSION_END)
            }
        return dict(NATIVE_EVENTS)

    @property
    def own_events(self) -> tuple[Event, ...]:
        """The events nock itself listens to there. Elsewhere than Claude
        Code, a tool call names no subagent and an edit no file, and a
        session's end has no transcript nock reads; after a tool, nock looks
        only for what it wrote in `.nock/shared/`."""
        if self is Harness.CLAUDE_CODE:
            return BUILT_IN_EVENTS
        return tuple(
            event
            for event in (Event.SESSION_START, Event.PROMPT, Event.AFTER_TOOL, Event.STOP)
            if event in self.events
        )


def found(root: Path) -> list[Harness]:
    return [harness for harness in Harness if harness.found(root)]


def skill_installs(harnesses: list[Harness]) -> list[Harness]:
    """The harnesses whose skills directory gets the portable skills, in
    order: each only when no directory written before it is one it reads."""
    installs: list[Harness] = []
    for harness in harnesses:
        if not any(done.skills_directory in harness.skills_read for done in installs):
            installs.append(harness)
    return installs
