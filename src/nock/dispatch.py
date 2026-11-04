"""The dispatcher: a fresh headless agent session launched with a brief, under
supervision, and read into telemetry when it ends. Each seat may do exactly
what its brief needs (`SEATS`); Claude Code refuses anything else, and the
refusals come back with the session."""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from nock.errors import PolicyError
from nock.processes import Supervisor
from nock.project import ROLE_VARIABLE, SESSION_VARIABLE
from nock.sessions import Sessions, find_transcript
from nock.telemetry import UNRECORDED_VARIABLE

if TYPE_CHECKING:
    from nock.project import Project

# The longest brief a command line carries whole; a longer one waits in a file.
ARGUMENT_LIMIT = 100_000
# The variables of the parent Claude Code session a child must not inherit.
PARENT_SESSION_VARIABLES = (
    "CLAUDECODE",
    "CLAUDE_CODE_ENTRYPOINT",
    "CLAUDE_CODE_SESSION_ID",
    "CLAUDE_CODE_CHILD_SESSION",
    "CLAUDE_CODE_SESSION_ATTENDED",
    "CLAUDE_CODE_MESSAGING_SOCKET",
    "CLAUDE_CODE_MESSAGING_TOKEN",
    "CLAUDE_PID",
)

# The flags that would lift Claude Code's permission checks: nock never passes
# them, and refuses an `agent.command` that does.
BYPASS = (
    "--dangerously-skip-permissions",
    "--allow-dangerously-skip-permissions",
    "bypassPermissions",
)
# The flags nock sets on every dispatch, which `agent.command` must not override.
PERMISSION_FLAGS = (
    "--permission-mode",
    "--allowedTools",
    "--allowed-tools",
    "--disallowedTools",
    "--disallowed-tools",
    "--tools",
    "--setting-sources",
)


def nock(path: str) -> str:
    """The rule letting a seat run one nock command, with any arguments."""
    return f"Bash(.nock/nock {path}:*)"


@dataclass(frozen=True)
class Seat:
    """What a dispatched agent may do. `tools` are the Claude Code tools it
    has at all; `allowed` the rules it runs unasked. Reading files in the
    directory it runs in needs no rule; everything else — editing a file,
    any other command, the network, a file outside — is refused."""

    tools: tuple[str, ...]
    allowed: tuple[str, ...]
    denied: tuple[str, ...] = ()
    """Rules refused even where `allowed` would let them through."""


READING = ("Read", "Grep", "Glob", "Bash")
# `git log` and `git show` read, but `--output` (or any abbreviation git
# accepts, down to `--ou`) writes their output to a file anywhere.
GIT_READING = ("Bash(git log:*)", "Bash(git show:*)")
GIT_WRITING = ("Bash(git * --ou*)",)
SEATS = {
    # Reads the decisions and advises through `nock advise`; changes nothing.
    "consultant": Seat(
        READING,
        (nock("decisions list"), nock("decisions show"), nock("docs"), nock("advise")),
    ),
    # Reads the code, its history and the decisions; edits the one decision.
    "elaborator": Seat(
        READING,
        (
            nock("decisions list"),
            nock("decisions show"),
            nock("docs"),
            nock("decisions edit"),
            *GIT_READING,
        ),
        GIT_WRITING,
    ),
    # Makes an asset's next version in its work directory and registers it;
    # each regeneration adds that directory, and the recipe's command (`assets.Assets.seat`).
    "regenerator": Seat(
        (*READING, "Edit", "Write"),
        (nock("assets show"), nock("assets add"), nock("docs"), *GIT_READING),
        GIT_WRITING,
    ),
    # Reads what identifies the project and answers in its last message.
    "sharer": Seat(READING, (GIT_READING[0],), GIT_WRITING),
}


@dataclass
class Session:
    """A finished dispatched session: its id, its run, how it ended and its
    final message."""

    id: str
    run: int | None
    exit_code: int
    result: str | None
    log: Path
    denied: list[str]
    """What Claude Code refused the session: each tool and what it was asked."""


class Dispatcher:
    def __init__(self, project: Project) -> None:
        self.project = project

    def launch(
        self,
        role: str,
        brief: str,
        directory: Path,
        variables: dict[str, str] | None = None,
        deadline: float | None = None,
        seat: Seat | None = None,
    ) -> Session:
        """`seat` is the role's own when not given; an evaluation step gives
        its agent's, since what it may do is the scenario's to say."""
        session = str(uuid.uuid4())
        settings = self.project.configuration
        prompt, allowed = self.carried(session, brief)
        command = [*self.command(role, allowed, seat)]
        command += ["--session-id", session]
        model = str(settings.get("agent.model") or "")
        if model:
            command += ["--model", model]
        command += ["--", prompt]
        Sessions(self.project).note_dispatch(session, role)
        output = Supervisor(
            self.project,
            command,
            directory=directory,
            deadline=deadline or float(settings.get("agent.deadline")),
            silence=float(settings.get("agent.silence")),
            environment={**self.environment(session, role), **(variables or {})},
            session=session,
        ).run()
        transcript = find_transcript(self.project.root, session)
        if transcript is not None:
            Sessions(self.project).ingest(transcript)
        denied = denials(output.raw)
        if denied:
            with output.log.open("a") as log:
                log.write("".join(f"nock: Claude Code refused {line}\n" for line in denied))
        return Session(
            session, output.run, output.code, final_result(output.raw), output.log, denied
        )

    def command(
        self, role: str, allowed: tuple[str, ...] = (), seat: Seat | None = None
    ) -> list[str]:
        """The agent's command line for a seat, up to its session and brief:
        headless, its tools and allow rules only, refusing the rest
        (`dontAsk`: nobody is there to answer a prompt). The project's and
        this checkout's Claude Code settings are not loaded, so the
        project's own allow rules never widen a seat; the user's are theirs."""
        seat = seat or SEATS.get(role)
        if seat is None:
            raise PolicyError(f"nock dispatches no agent as {role!r}: seats are {', '.join(SEATS)}")
        base = [str(part) for part in self.project.configuration.get("agent.command")]
        lifted = [part for part in base if part in BYPASS or part.split("=")[0] in PERMISSION_FLAGS]
        if lifted:
            raise PolicyError(
                f"`agent.command` sets {', '.join(lifted)}: nock sets each seat's permissions"
                " itself and never bypasses them — take it out of .nock/config.toml"
            )
        return [
            *base,
            "-p",
            "--output-format",
            "stream-json",
            "--verbose",
            "--permission-mode",
            "dontAsk",
            "--setting-sources",
            "user",
            "--strict-mcp-config",
            "--tools",
            ",".join(seat.tools),
            "--allowedTools",
            *seat.allowed,
            *allowed,
            *(["--disallowedTools", *seat.denied] if seat.denied else []),
        ]

    def environment(self, session: str, role: str) -> dict[str, str]:
        environment = {
            key: value
            for key, value in os.environ.items()
            if key not in (*PARENT_SESSION_VARIABLES, UNRECORDED_VARIABLE)
        }
        environment[ROLE_VARIABLE] = role
        environment[SESSION_VARIABLE] = session
        return environment

    def carried(self, session: str, brief: str) -> tuple[str, tuple[str, ...]]:
        """The prompt, and the rule to read the file a long brief waits in
        (in the main checkout, maybe outside the directory the seat runs in)."""
        if len(brief.encode()) <= ARGUMENT_LIMIT:
            return brief, ()
        path = self.project.local / "briefs" / f"{session}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(brief)
        return (
            f"Your brief is {len(brief.encode())} bytes, too long for a command line: read {path} in full before anything else.",
            (f"Read(/{path.resolve()})",),
        )


def final_result(stream: str) -> str | None:
    """The session's last word: the `result` line of a stream-json transcript."""
    for line in reversed(stream.splitlines()):
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(record, dict) and record.get("type") == "result":
            result = record.get("result")
            return result if isinstance(result, str) else None
    return None


def denials(stream: str) -> list[str]:
    """What Claude Code refused, from the `permission_denials` of a
    stream-json transcript's `result` line: each tool and what it was asked."""
    for line in reversed(stream.splitlines()):
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(record, dict) and record.get("type") == "result":
            found = record.get("permission_denials") or []
            return [denied(item) for item in found if isinstance(item, dict)]
    return []


def denied(item: dict[str, object]) -> str:
    asked = item.get("tool_input")
    if isinstance(asked, dict):
        asked = asked.get("command") or asked.get("file_path") or asked.get("pattern") or asked
    shown = asked if isinstance(asked, str) else json.dumps(asked)
    return f"{item.get('tool_name')}: {shown}"
