"""Claude Code's hook events, handled: `nock hook EVENT` reads the payload on
stdin and answers in Claude Code's hook format. nock's own: a session starts
upgraded to a newer nock when the merge is clean (`upgrade.auto`), and — when
the human started it, once a day or when what is due changes — told in one
line which rounds are due; a `.nock/nock` command about to run is noted with
the subagent running it, if any (`callers.py`), so its call names its parent
session; and when the session ends its transcript is read into telemetry
and, when due, the usage statistics are shared. A turn that would end with a
subround run this session started still open is refused once, saying what
the run still needs — unless it ends only to wait on the background agents
it launched. What is due is also said to the human. With `reminders = false`
nock says nothing unasked, and still records. The project's `@nock.hook`s
run after. Every handler fails open — a nock that cannot load must never
block the tool call that would fix it."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from nock.callers import Callers
from nock.environment import enter
from nock.harnesses import NATIVE_EVENTS, Event, Harness
from nock.project import NOCK_DIRECTORY, Project

if TYPE_CHECKING:
    from nock.tools import Hook

EVENTS = {native: event for event, native in NATIVE_EVENTS.items()}
# The before-tool handler's: only Bash commands running nock, as Claude Code's hook `if` rule.
NOCK_COMMANDS = "Bash(*.nock/nock *)"
# The longest a session start waits on an upgrade, in seconds: two wheels downloaded, a merge.
UPGRADE_DEADLINE = 120


class Block(Exception):
    """Raised by a `stop` hook to refuse the end of a turn, with the reason."""


class HookRunner:
    def __init__(
        self, project: Project, payload: dict[str, Any], harness: Harness = Harness.CLAUDE_CODE
    ) -> None:
        self.project = project
        self.harness = harness
        self.payload = normalized(payload, harness)
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
            from nock.primer import refresh

            refresh(self.project.here / NOCK_DIRECTORY)
            if self.project.current_role() is None:
                upgraded = self.upgrade_itself()
                self.notices += [upgraded] if upgraded else []
                if self.reminding:
                    due = self.standing()
                    messages.append(due)
                    self.notices += [due] if due else []
        elif event is Event.BEFORE_TOOL:
            Callers(self.project.store).note(self.payload)
        elif event is Event.SESSION_END:
            self.session_end()
        blocks: list[str] = []
        if event is Event.STOP and not self.waiting():
            blocks += self.rounds_left_open()
        for entry in self.own_hooks(event):
            from nock.fixtures import Call, Scope

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
            reason = "\n".join(blocks)
            if self.harness is Harness.CURSOR:
                return {"followup_message": reason}
            return {"decision": "block", "reason": reason}
        text = "\n\n".join(message for message in messages if message)
        if self.harness is Harness.CURSOR:
            # Cursor shows the human nothing a hook says; the agent reads it.
            told = "\n\n".join(part for part in (text, *self.notices) if part)
            return {"additional_context": told} if told and event is Event.SESSION_START else None
        output: dict[str, Any] = {}
        if self.notices:
            output["systemMessage"] = "\n".join(self.notices)
        if text and event not in (Event.STOP, Event.SESSION_END):
            output["hookSpecificOutput"] = {"hookEventName": native, "additionalContext": text}
        return output or None

    def own_hooks(self, event: Event) -> list[Hook]:
        """The project's hooks for the event; none at Cursor, whose payloads
        they are not written for. The toolbox is loaded only when it may hold one."""
        if self.harness is Harness.CURSOR:
            return []
        known = self.project.hook_events()
        if known is not None and event not in known:
            return []
        return self.project.registry.hooks_for(event)

    def upgrade_itself(self) -> str:
        """A newer release merged into the core by itself, when the merge is
        clean, said in a line; on a conflict nothing changes, and the standing
        says the release is out, as it does with `upgrade.auto` off. The owner
        made it the default, so it runs without the ask `nock upgrade` has."""
        from nock.releases import Updates

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

    def standing(self) -> str:
        """The rounds due, in one line, said once a day, and at once when what
        is due changes."""
        from nock.status import Standing

        standing = Standing(self.project)
        due = standing.due()
        line = standing.line(due)
        if not line:
            return ""
        digest = hashlib.sha256(json.dumps(sorted(due)).encode()).hexdigest()[:16]
        key = f"due:{datetime.now(UTC).date().isoformat()}:{digest}"
        store = self.project.store
        if store.rows("SELECT round FROM nudged WHERE round = ?", (key,)):
            return ""
        store.insert("nudged", {"round": key})
        return line

    def waiting(self) -> bool:
        """Whether the turn ends only to wait on background agents it launched
        (a round's parts), which give the session another turn as they end:
        nock asks for nothing then, and asks at the turn after the last."""
        if self.harness is not Harness.CLAUDE_CODE:
            return False
        from nock.sessions import background_agents, find_transcript

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
        """Every subround run this session started and has not finished, with what it still needs."""
        session = self.payload.get("session_id")
        if not isinstance(session, str) or self.payload.get("stop_hook_active") is True:
            return []
        from nock.rounds import subrounds

        return [
            said for subround in subrounds(self.project) if (said := subround.left_open(session))
        ]

    def session_end(self) -> None:
        from nock.sessions import Sessions
        from nock.usage import Usage

        transcript = self.payload.get("transcript_path")
        if isinstance(transcript, str) and Path(transcript).is_file():
            Sessions(self.project).ingest(Path(transcript))
        if self.project.current_role() is None:
            Usage(self.project).send()


def normalized(payload: dict[str, Any], harness: Harness) -> dict[str, Any]:
    """Cursor's payload in Claude Code's words: its conversation is the
    session, its first workspace root the directory, and a stop it already
    continued after (`loop_count`) a stop hook's."""
    if harness is not Harness.CURSOR:
        return payload
    roots = payload.get("workspace_roots")
    count = payload.get("loop_count")
    return {
        **payload,
        "session_id": payload.get("session_id") or payload.get("conversation_id"),
        "cwd": payload.get("cwd") or (roots[0] if isinstance(roots, list) and roots else None),
        "stop_hook_active": isinstance(count, int) and count > 0,
    }


def main() -> None:
    """`nock hook EVENT [HARNESS]`, from `python -m nock` without the rest of
    the CLI: on the project's interpreter, then `run`."""
    arguments = sys.argv[1:]
    enter(arguments)
    native, word = (*arguments[1:3], "", "")[:2]
    sys.exit(run(native, sys.stdin.read(), word or "claude"))


def run(native: str, stdin_text: str, word: str = Harness.CLAUDE_CODE) -> int:
    """The hook entry point, `nock hook EVENT [HARNESS]`: EVENT by Claude
    Code's name, HARNESS `claude` (the default), `codex` or `cursor`; always
    exits 0 — a block is said in the output."""
    if native not in EVENTS:
        print(f"nock: unknown hook event {native!r}; known: {', '.join(EVENTS)}", file=sys.stderr)
        return 0
    if word not in {harness.value for harness in Harness}:
        known = ", ".join(harness.value for harness in Harness)
        print(f"nock: unknown harness {word!r}; known: {known}", file=sys.stderr)
        return 0
    harness = Harness(word)
    try:
        payload = json.loads(stdin_text) if stdin_text.strip() else {}
        payload = normalized(payload if isinstance(payload, dict) else {}, harness)
        project = Project.discover(Path(payload.get("cwd") or "."))
        output = HookRunner(project, payload, harness).handle(native)
    except Exception as error:  # fail open: nock must never wedge the session
        print(f"nock: the {native} hook failed and was skipped: {error!r}", file=sys.stderr)
        return 0
    if output is not None:
        print(json.dumps(output))
    return 0
