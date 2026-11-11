"""The project: the hub every call starts from — where the repository is, what
it is configured to do, its toolbox and its telemetry."""

from __future__ import annotations

import contextlib
import fcntl
import json
import os
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from functools import cached_property
from pathlib import Path
from typing import TYPE_CHECKING

from nock.callers import Callers
from nock.configuration import Configuration
from nock.errors import PreconditionError
from nock.git import Git, GitError
from nock.store import Store
from nock.utils import write_json

if TYPE_CHECKING:
    from nock.tools import Registry

NOCK_DIRECTORY = ".nock"
# Set by nock on the sessions it dispatches; Claude Code sets the session's id.
ROLE_VARIABLE = "NOCK_ROLE"
SESSION_VARIABLE = "CLAUDE_CODE_SESSION_ID"
# Set by nock on the sessions it dispatches: the session that dispatched it.
PARENT_VARIABLE = "NOCK_PARENT_SESSION"
# Claude Code's: `cli` for a session someone works in, `sdk-…` for `claude -p`.
ENTRYPOINT_VARIABLE = "CLAUDE_CODE_ENTRYPOINT"
# Which events each working tree's `@nock.hook`s listen to, in `local/`.
HOOK_EVENTS_FILE = "hook-events.json"
# The role of a `claude -p` run nock did not start.
HEADLESS = "headless"


def headless(entrypoint: str | None) -> bool:
    """Whether a Claude Code entrypoint (`CLAUDE_CODE_ENTRYPOINT`, a
    transcript's `entrypoint`) runs without a person: `sdk-cli`, `sdk-py`,
    `sdk-ts`. Everything else — `cli`, an IDE, the desktop app — has one."""
    return bool(entrypoint) and str(entrypoint).startswith("sdk")


class Project:
    """One repository under nock. `root` is the main checkout — telemetry lives
    there whichever worktree a call runs in — and `here` is the working tree
    the call runs in, whose `.nock/` code (tools, settings, briefs) it uses."""

    def __init__(self, root: Path, here: Path | None = None) -> None:
        self.root = root
        self.here = here or root
        # The session's note of this command, once claimed: one claim per process.
        self.caller: tuple[str, dict[str, str | None] | None] | None = None

    @classmethod
    def discover(cls, directory: Path | None = None) -> Project:
        directory = (directory or Path.cwd()).resolve()
        try:
            here, root = Git(directory).location()
        except GitError as error:
            raise PreconditionError(f"{directory} is not inside a git repository") from error
        project = cls(root, here)
        if not (here / NOCK_DIRECTORY).is_dir():
            raise PreconditionError(f"{here} has no {NOCK_DIRECTORY}/ — run `nock init` first")
        return project

    # --- places ------------------------------------------------------------------

    @property
    def local(self) -> Path:
        """Machine state, never committed: telemetry, logs, caches."""
        path = self.root / NOCK_DIRECTORY / "local"
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def logs(self) -> Path:
        path = self.local / "logs"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def code_path(self, *parts: str) -> Path:
        """A place in the project's nock code — settings, tools, briefs,
        generators, reflections — in the working tree the call runs in."""
        return (self.here / NOCK_DIRECTORY).joinpath(*parts)

    # --- settings, tools and telemetry --------------------------------------------

    @cached_property
    def configuration(self) -> Configuration:
        return Configuration(
            [
                self.code_path("config.toml"),
                self.root / NOCK_DIRECTORY / "shared" / "settings.toml",
                self.local / "config.toml",
            ]
        )

    @cached_property
    def git(self) -> Git:
        """The main checkout's git."""
        return Git(self.root)

    @property
    def branch(self) -> str:
        return str(self.configuration.get("branch", "main"))

    @cached_property
    def registry(self) -> Registry:
        """Built-ins and the project's `.nock/tools/`, loaded once."""
        # Imported here, not at the top: a hook that needs no tools never loads them.
        from nock.tools import Registry

        return Registry.load(self)

    def tools_stamp(self) -> list[list[str | int]]:
        """What the toolbox loads, as it stands: each module of `.nock/tools/`
        by name, modification time and size."""
        stamp: list[list[str | int]] = []
        for path in sorted(self.code_path("tools").glob("*.py")):
            status = path.stat()
            stamp.append([path.name, status.st_mtime_ns, status.st_size])
        return stamp

    def hook_events(self) -> set[str] | None:
        """The events the project's `@nock.hook`s listen to, as the last full
        load of this working tree's toolbox found them, while its modules are
        unchanged since; None when that is not known. A hook skips loading the
        toolbox when the event has none."""
        try:
            recorded = json.loads((self.local / HOOK_EVENTS_FILE).read_text()).get(str(self.here))
            if recorded is None or recorded["stamp"] != self.tools_stamp():
                return None
            return set(recorded["events"])
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            return None

    def record_hook_events(self, stamp: list[list[str | int]], events: set[str]) -> None:
        path = self.local / HOOK_EVENTS_FILE
        try:
            recorded = json.loads(path.read_text())
        except (OSError, ValueError):
            recorded = {}
        entry = {"stamp": stamp, "events": sorted(events)}
        if not isinstance(recorded, dict):
            recorded = {}
        if recorded.get(str(self.here)) != entry:
            with contextlib.suppress(OSError):
                write_json(path, {**recorded, str(self.here): entry})

    @cached_property
    def store(self) -> Store:
        return Store(self.local / "nock.db")

    def current_session(self) -> str | None:
        return os.environ.get(SESSION_VARIABLE) or None

    def current_role(self) -> str | None:
        """The role nock dispatched this session as, `headless` for a
        `claude -p` run nock did not start, and None for a person's session."""
        if os.environ.get(ROLE_VARIABLE):
            return os.environ[ROLE_VARIABLE]
        return HEADLESS if headless(os.environ.get(ENTRYPOINT_VARIABLE)) else None

    def writer(self) -> dict[str, str | None]:
        """Who writes, as every record in Topics keeps it: `session`, `role`,
        and `parent`, the session that dispatched it, for a subagent (its
        session the subagent's id, its role the subagent's type) or a
        session nock dispatched."""
        session = self.current_session()
        role = self.current_role() or "interactive"
        parent = os.environ.get(PARENT_VARIABLE) or None
        if session and not parent:
            if self.caller is None or self.caller[0] != session:
                self.caller = (session, Callers(self.store).claim(session, sys.argv[1:]))
            noted = self.caller[1]
            if noted and noted["agent"]:
                session, parent, role = noted["agent"], session, noted["type"] or "subagent"
        return {"session": session, **({"parent": parent} if parent else {}), "role": role}

    @contextmanager
    def lock(self, name: str) -> Iterator[None]:
        """An exclusive, cross-process lock named `name`."""
        path = self.local / "locks" / f"{name}.lock"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)
