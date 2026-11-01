"""The usage report nock shares with its makers, to improve nock: counts and
categories, and a random id for the project so they can count projects
without knowing which, never the project's code, paths, names or text. The
owner is told what is shared, once per machine, the first time they engage
with nock (a reflection round, the page, their word on a decision); nothing
is sent before that, nor at all when `share` is false."""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
import uuid
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from nock.checks import Checks
from nock.errors import PreconditionError
from nock.git import Git, GitError
from nock.kinds import kinds
from nock.logika import LEDGER
from nock.reflect import Reflection, Window, tool_rows
from nock.releases import VERSION
from nock.sessions import Sessions
from nock.tools import BUILT_IN_SOURCE
from nock.utils import now, parse_moment, read_json, write_json

if TYPE_CHECKING:
    from nock.project import Project

# The shape of a report, so a reader can tell versions apart.
SCHEMA = 3
# Days between reports, and between attempts after one failed.
INTERVAL = 7
RETRY = 1
# Seconds a send may take: it runs as a session ends.
TIMEOUT = 3
STATE = "usage.json"
# The project's anonymous id, committed so that every clone shares it.
IDENTITY = "project.json"
# What a report shown before the first send says in place of the id, which is
# made only then, after the owner was told.
UNMADE = "(created when the first report is sent)"


class Moment(StrEnum):
    """When the owner engages with nock enough to be told what it shares."""

    ROUND = "round"
    STUDIO = "studio"
    REVIEW = "review"


DISCLOSURE = (
    "nock shares an anonymous usage report with its makers, to improve nock: counts and"
    " categories only (sessions, calls to nock's own commands and how they ended, how many"
    " tools, checks and decisions there are, the versions of nock and Python) and a random id"
    " for this project, committed in .nock/project.json so its clones share it, which lets"
    " nock's makers count projects without knowing which; never code, paths, names, prompts,"
    " arguments or what decisions say. Nothing has been sent yet: the first report goes in a"
    " week, then at most weekly. `.nock/nock usage` shows exactly what would be sent. To send"
    " nothing at all, set `share = false` in .nock/config.toml (or .nock/local/config.toml,"
    " for this machine only)."
)


def sharing(project: Project) -> tuple[bool, str | None]:
    """Whether nock shares, and a note when the setting is an earlier nock's
    `[share]` table: `level = "none"` reads as false, anything else as true,
    which now shares only the anonymous report."""
    value = project.configuration.get("share")
    if isinstance(value, bool):
        return value, None
    if not isinstance(value, dict):
        raise PreconditionError(f"`share` is {value!r}: it is true or false")
    shared = value.get("level") != "none"
    said = f"`share.level = {json.dumps(value['level'])}`" if "level" in value else "`[share]`"
    return shared, (
        f"{said} is an earlier nock's setting and reads as `share = {str(shared).lower()}`;"
        " write `share = true` or `share = false` at the top of .nock/config.toml instead"
        " (the endpoints are now under [endpoints])."
    )


def shares(project: Project) -> bool:
    return sharing(project)[0]


class Usage:
    def __init__(self, project: Project) -> None:
        self.project = project
        self.path = project.local / STATE
        # In the main checkout, like the decisions, so a worktree never makes a second id.
        self.identity_path = project.root / ".nock" / IDENTITY

    def state(self) -> dict[str, Any]:
        try:
            return read_json(self.path) if self.path.is_file() else {}
        except PreconditionError:
            return {}

    def disclose(self, moment: Moment) -> str | None:
        """What to tell the owner, the first time on this machine they engage
        with nock while it shares; nothing after that, or when it does not."""
        state = self.state()
        if not shares(self.project) or state.get("disclosed"):
            return None
        state["disclosed"] = {"moment": str(moment), "at": now()}
        write_json(self.path, state)
        return DISCLOSURE

    def identity(self) -> str:
        """The project's anonymous id: random, made as the first report is sent
        (after the owner was told) and committed in the main checkout, so every
        clone shares it."""
        with self.project.lock("identity"):
            known = self.known_identity()
            if known:
                return known
            made = str(uuid.uuid4())
            write_json(self.identity_path, {"id": made})
        relative = f".nock/{IDENTITY}"
        try:
            git = Git(self.project.root)
            git("add", "--", relative)
            git(
                "commit", "--quiet", "--no-verify", "--only", "-m",
                "nock: the project's anonymous id, for its usage reports", "--", relative,
            )  # fmt: skip
        except GitError:
            pass  # left for the owner to commit with the rest; the id is kept either way
        return made

    def known_identity(self) -> str | None:
        try:
            value = read_json(self.identity_path).get("id")
        except (FileNotFoundError, PreconditionError, AttributeError):
            return None
        try:
            return str(uuid.UUID(value, version=4)) if isinstance(value, str) else None
        except ValueError:
            return None

    def since(self) -> str | None:
        """Where the next report starts: the last one's end, else the
        disclosure — nothing from before the owner was told is counted."""
        state = self.state()
        sent = state.get("sent") or []
        if sent:
            return sent[-1]["until"]
        disclosed = state.get("disclosed")
        return disclosed["at"] if disclosed else None

    def report(self, sending: bool = False) -> dict[str, Any]:
        """Exactly what the next send carries. Only a send makes the project's
        id; until then a report shows `UNMADE` in its place."""
        project = self.project
        since = self.since()
        if since is None:
            moment = datetime.now(UTC) - timedelta(days=INTERVAL)
            since = moment.replace(microsecond=0).isoformat().replace("+00:00", "Z")
        sessions = Sessions(project)
        sessions.catch_up()
        window = Window(since, sessions.since(since))
        registry = project.registry
        commands = {
            row["tool"]: {"calls": row["calls"], "failures": row["failures"]}
            for row in tool_rows(project, since)
            if row["source"] == BUILT_IN_SOURCE and row["calls"]
        }
        own_checks = [
            name for name, entry in registry.checks.items() if entry.source != BUILT_IN_SOURCE
        ]
        command_checks = [
            name for name in Checks(project).available() if name not in registry.checks
        ]
        return {
            "schema": SCHEMA,
            "project": self.identity() if sending else self.known_identity() or UNMADE,
            "nock": VERSION,
            "python": f"{sys.version_info.major}.{sys.version_info.minor}",
            "platform": sys.platform,
            "settings": {
                "reminders": project.configuration.get("reminders") is not False,
                "consult": project.configuration.get("consult.enabled") is not False,
                "logika": (project.here / LEDGER).is_file(),
            },
            "metrics": Reflection(project).metrics(window),
            "commands": commands,
            "toolbox": {
                "tools": len(registry.project_tools()),
                "checks": len(own_checks) + len(command_checks),
                "hooks": sum(1 for entry in registry.hooks if entry.source != BUILT_IN_SOURCE),
                "generators": sum(
                    1 for entry in registry.generators if entry.source != BUILT_IN_SOURCE
                ),
                "load_failures": len(registry.failures),
            },
            "rounds": {kind.kind: len(kind.rounds.all()) for kind in kinds(project)},
        }

    def due(self) -> bool:
        """Shared, told, and a week since the last report (a day since a failed try)."""
        if not shares(self.project):
            return False
        state = self.state()
        start = parse_moment(self.since())
        if not state.get("disclosed") or start is None:
            return False
        moment = datetime.now(UTC)
        tried = parse_moment(state.get("tried"))
        if tried and moment - tried < timedelta(days=RETRY):
            return False
        return moment - start >= timedelta(days=INTERVAL)

    def send(self) -> bool:
        """Send the report when one is due; whether it went. Silent on any failure."""
        if not self.due():
            return False
        report = self.report(sending=True)
        endpoint = str(self.project.configuration.get("endpoints.usage"))
        state = self.state()
        state["tried"] = now()
        post = urllib.request.Request(
            endpoint,
            data=json.dumps(report).encode(),
            headers={"Content-Type": "application/json", "User-Agent": f"nock/{VERSION}"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(post, timeout=TIMEOUT):
                pass
        except (urllib.error.URLError, TimeoutError, ValueError, OSError):
            write_json(self.path, state)
            return False
        sent = [
            *(state.get("sent") or []),
            {"at": now(), "since": self.since(), "until": state["tried"]},
        ]
        state["sent"] = sent[-20:]
        write_json(self.path, state)
        return True

    def standing(self) -> dict[str, Any]:
        """Whether nock shares, whether this machine has told the owner, when
        reports went and when the next goes, and the next one exactly."""
        shared, note = sharing(self.project)
        state = self.state()
        start = parse_moment(self.since())
        due = (
            (start + timedelta(days=INTERVAL))
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z")
            if start and shared and state.get("disclosed")
            else None
        )
        standing: dict[str, Any] = {
            "share": shared,
            "disclosed": state.get("disclosed"),
            "sent": state.get("sent") or [],
            "next": due,
            "to": str(self.project.configuration.get("endpoints.usage")) if shared else None,
            "would_send": self.report() if shared else None,
        }
        if note:
            standing["note"] = note
        return standing
