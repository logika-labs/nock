"""The usage statistics nock shares with its makers, to improve nock: counts
and categories only, never the project's code, paths, names or text. The
owner is told what is shared, once per machine, the first time they engage
with nock (a reflection round, the page, their word on a decision); nothing
is sent before that, nor at all when `share.level` is `none`."""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from nock.checks import Checks
from nock.errors import PreconditionError
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
SCHEMA = 1
# Days between reports, and between attempts after one failed.
INTERVAL = 7
RETRY = 1
# Seconds a send may take: it runs as a session ends.
TIMEOUT = 3
STATE = "usage.json"


class Level(StrEnum):
    NONE = "none"
    """Nothing is ever sent: no statistics, no summaries."""
    ANONYMOUS = "anonymous"
    """Counts and categories, kept by nock's makers."""
    PUBLIC = "public"
    """The anonymous statistics and the toolbox's tool names with their
    counts, published on nock.dev."""


class Moment(StrEnum):
    """When the owner engages with nock enough to be told what it shares."""

    ROUND = "round"
    STUDIO = "studio"
    REVIEW = "review"


ANONYMOUS_DISCLOSURE = (
    "nock shares anonymous usage statistics with its makers, to improve nock: counts and"
    " categories only (sessions, calls to nock's own commands and how they ended, how many"
    " tools, checks and decisions there are, the versions of nock and Python), never code,"
    " paths, names, prompts, arguments or what decisions say. Nothing has been sent yet: the"
    " first report goes in a week, then at most weekly. `.nock/nock usage` shows exactly what"
    " would be sent. To change it, set `share.level` in .nock/config.toml (or"
    ' .nock/local/config.toml, for this machine only): "none" sends nothing at all, "public"'
    " adds this project's tool names with their counts and publishes the statistics on nock.dev."
)
PUBLIC_DISCLOSURE = (
    "nock shares usage statistics publicly, on nock.dev, to improve nock: counts and"
    " categories (sessions, calls to nock's own commands and how they ended, how many tools,"
    " checks and decisions there are, the versions of nock and Python) and this project's tool"
    " names with their counts, never code, paths, prompts, arguments or what decisions say."
    " Nothing has been sent yet: the first report goes in a week, then at most weekly."
    " `.nock/nock usage` shows exactly what would be sent. To change it, set `share.level` in"
    ' .nock/config.toml (or .nock/local/config.toml, for this machine only): "anonymous" sends'
    ' no names and publishes nothing, "none" sends nothing at all.'
)


def level_of(project: Project) -> Level:
    value = project.configuration.get("share.level")
    try:
        return Level(value)
    except ValueError as error:
        choices = ", ".join(f'"{level}"' for level in Level)
        raise PreconditionError(f"`share.level` is {value!r}: it is one of {choices}") from error


class Usage:
    def __init__(self, project: Project) -> None:
        self.project = project
        self.path = project.local / STATE

    def state(self) -> dict[str, Any]:
        try:
            return read_json(self.path) if self.path.is_file() else {}
        except PreconditionError:
            return {}

    def disclose(self, moment: Moment) -> str | None:
        """What to tell the owner, the first time on this machine they engage
        with nock while something is shared; nothing after that, or at `none`."""
        level = level_of(self.project)
        state = self.state()
        if level is Level.NONE or state.get("disclosed"):
            return None
        state["disclosed"] = {"moment": str(moment), "at": now(), "level": str(level)}
        write_json(self.path, state)
        return PUBLIC_DISCLOSURE if level is Level.PUBLIC else ANONYMOUS_DISCLOSURE

    def since(self) -> str | None:
        """Where the next report starts: the last one's end, else the
        disclosure — nothing from before the owner was told is counted."""
        state = self.state()
        sent = state.get("sent") or []
        if sent:
            return sent[-1]["until"]
        disclosed = state.get("disclosed")
        return disclosed["at"] if disclosed else None

    def report(self) -> dict[str, Any]:
        """Exactly what the next send carries."""
        project = self.project
        level = level_of(project)
        since = self.since()
        if since is None:
            moment = datetime.now(UTC) - timedelta(days=INTERVAL)
            since = moment.replace(microsecond=0).isoformat().replace("+00:00", "Z")
        window = Window(since, Sessions(project).since(since))
        registry = project.registry
        rows = tool_rows(project, since)
        commands = {
            row["tool"]: {"calls": row["calls"], "failures": row["failures"]}
            for row in rows
            if row["source"] == BUILT_IN_SOURCE and row["calls"]
        }
        own_checks = [
            name for name, entry in registry.checks.items() if entry.source != BUILT_IN_SOURCE
        ]
        command_checks = [
            name for name in Checks(project).available() if name not in registry.checks
        ]
        report: dict[str, Any] = {
            "schema": SCHEMA,
            "level": str(level),
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
        if level is Level.PUBLIC:
            report["tools"] = [
                {"tool": row["tool"], "calls": row["calls"], "failures": row["failures"]}
                for row in rows
                if row["source"] != BUILT_IN_SOURCE
            ]
        return report

    def due(self) -> bool:
        """Shared, told, and a week since the last report (a day since a failed try)."""
        if level_of(self.project) is Level.NONE:
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
        report = self.report()
        endpoint = str(self.project.configuration.get("share.usage_endpoint"))
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
            {"at": now(), "since": self.since(), "until": state["tried"], "level": report["level"]},
        ]
        state["sent"] = sent[-20:]
        write_json(self.path, state)
        return True

    def standing(self) -> dict[str, Any]:
        """The level, whether this machine has told the owner, when reports
        went and when the next goes, and the next one exactly."""
        level = level_of(self.project)
        state = self.state()
        start = parse_moment(self.since())
        due = (
            (start + timedelta(days=INTERVAL))
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z")
            if start and level is not Level.NONE and state.get("disclosed")
            else None
        )
        return {
            "level": str(level),
            "disclosed": state.get("disclosed"),
            "sent": state.get("sent") or [],
            "next": due,
            "to": str(self.project.configuration.get("share.usage_endpoint"))
            if level is not Level.NONE
            else None,
            "would_send": self.report() if level is not Level.NONE else None,
        }
