"""The usage report nock shares with its makers, to improve nock: counts and
categories, and a random id for the project so they can count projects
without knowing which, never the project's code, paths, names or text. Only
with the owner's yes: `share` unset is unanswered, and nothing is sent. nock
asks once per machine, the first time the owner engages with it (a
reflection round, the page, their verdict on an item), and their answer is
written to `share` in the config, with when they gave it and which question
they answered kept in the machine's state."""

from __future__ import annotations

import json
import re
import sys
import tomllib
import urllib.error
import urllib.request
import uuid
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Any

from nock.checks import Checks
from nock.errors import PreconditionError
from nock.git import Git, GitError
from nock.logika import LEDGER
from nock.reflect import Reflection, Window, tool_rows
from nock.releases import VERSION
from nock.rounds import protocols
from nock.sessions import Sessions
from nock.shared import SETTINGS, Shared, by_for
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
    """When the owner engages with nock enough to be asked whether it shares."""

    ROUND = "round"
    STUDIO = "studio"
    REVIEW = "review"


class Answer(StrEnum):
    """The owner's answer to whether nock shares its usage report."""

    UNANSWERED = "unanswered"
    YES = "yes"
    NO = "no"


# The words the owner is asked; a new version is a new number, and an answer
# records the version it answered.
QUESTION_VERSION = 1
QUESTION = (
    "May nock share a weekly usage report with its makers, to improve nock? It holds counts"
    " and categories only (sessions, calls to nock's own commands and how they ended, how many"
    " tools, checks and topics there are, the versions of nock and Python) and a random id"
    " for this project, made when the first report is sent and committed in .nock/project.json"
    " so its clones share it; never code, paths, names, prompts, arguments or what items"
    " say. Nothing is sent unless you say yes; the first report would go a week after, then at"
    " most weekly, and `.nock/nock config share` shows exactly what it would carry. You can change your"
    " answer at any time with `share` in .nock/config.toml."
)
# How the agent who asked records the answer.
RECORD = (
    "Ask the owner this in its words, and record exactly what they answer with"
    " `.nock/nock config share true` or `.nock/nock config share false`; without an answer nothing"
    " is sent."
)


def sharing(project: Project) -> Answer:
    """The owner's answer: `share` in the config, or, unset, the answer this
    machine recorded, if any; else unanswered."""
    value = project.configuration.get("share")
    if value is None:
        answered = Usage(project).state().get("answered")
        if isinstance(answered, dict) and isinstance(answered.get("share"), bool):
            return Answer.YES if answered["share"] else Answer.NO
        return Answer.UNANSWERED
    if not isinstance(value, bool):
        raise PreconditionError(f"`share` is {value!r}: it is true or false")
    return Answer.YES if value else Answer.NO


def shares(project: Project) -> bool:
    return sharing(project) is Answer.YES


def with_setting(text: str, key: str, value: bool) -> str:
    """A TOML file's text with a top-level `key = value`: its line replaced,
    or a commented `# key = …` line taken over, or one added before the
    first table."""
    lines = text.splitlines(keepends=True)
    tables = [index for index, line in enumerate(lines) if line.lstrip().startswith("[")]
    top = tables[0] if tables else len(lines)
    setting = f"{key} = {str(value).lower()}\n"
    for pattern in (rf"^{key}\s*=", rf"^#\s*{key}\s*="):
        for index in range(top):
            if re.match(pattern, lines[index]):
                lines[index] = setting
                return "".join(lines)
    if top and lines[top - 1].strip():
        setting = "\n" + setting
    lines.insert(top, setting + ("\n" if tables else ""))
    return "".join(lines)


class Usage:
    def __init__(self, project: Project) -> None:
        self.project = project
        self.path = project.local / STATE
        # In the main checkout, like the topics, so a worktree never makes a second id.
        self.identity_path = project.root / ".nock" / IDENTITY

    def state(self) -> dict[str, Any]:
        try:
            return read_json(self.path) if self.path.is_file() else {}
        except PreconditionError:
            return {}

    def ask(self, moment: Moment) -> str | None:
        """What to ask the owner, the first time on this machine they engage
        with nock while nobody has answered; nothing after that."""
        state = self.state()
        if sharing(self.project) is not Answer.UNANSWERED or state.get("asked"):
            return None
        state["asked"] = {"moment": str(moment), "at": now(), "prompt": QUESTION_VERSION}
        write_json(self.path, state)
        return f"{QUESTION}\n\n{RECORD}"

    def answer(self, share: bool, via: str) -> dict[str, Any]:
        """The owner's answer, written to `share` in the team's settings
        (`.nock/shared/settings.toml`, committed with the topics) or, where the
        machine's own config already sets it, in that; when and how it was
        given, and to which question, kept in this machine's state."""
        local = self.project.local / "config.toml"
        team = self.project.root / ".nock" / "shared" / SETTINGS
        setting = local if sets(local, "share") else team
        setting.parent.mkdir(parents=True, exist_ok=True)
        text = setting.read_text() if setting.is_file() else ""
        setting.write_text(with_setting(text, "share", share))
        self.project.__dict__.pop("configuration", None)
        state = self.state()
        state["answered"] = {"share": share, "at": now(), "via": via, "prompt": QUESTION_VERSION}
        write_json(self.path, state)
        if setting == team:
            store = Shared(self.project)
            by = by_for(self.project)
            settled = store.settle(by, only=[team], commit=False)
            store.commit(
                settled.written,
                by,
                settled,
                subject=f"nock: the owner's answer on sharing nock's usage report, share = {str(share).lower()}",
            )
        return self.standing()

    def counting(self) -> None:
        """Where counting starts for a yes this machine has not recorded (a
        `share = true` already in the config): now, the first time it is seen."""
        state = self.state()
        if shares(self.project) and self.since() is None:
            state["answered"] = {"share": True, "at": now(), "via": "config", "prompt": None}
            write_json(self.path, state)

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
        """Where the next report starts: the last one's end, else the owner's
        answer — nothing from before is counted."""
        state = self.state()
        sent = state.get("sent") or []
        if sent:
            return sent[-1]["until"]
        answered = state.get("answered")
        return answered["at"] if isinstance(answered, dict) and answered.get("at") else None

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
            "rounds": {
                protocol.name: len(protocol.rounds.all()) for protocol in protocols(project)
            },
        }

    def due(self) -> bool:
        """A yes, and a week since it or the last report (a day since a failed try)."""
        if not shares(self.project):
            return False
        state = self.state()
        start = parse_moment(self.since())
        if start is None:
            return False
        moment = datetime.now(UTC)
        tried = parse_moment(state.get("tried"))
        if tried and moment - tried < timedelta(days=RETRY):
            return False
        return moment - start >= timedelta(days=INTERVAL)

    def send(self) -> bool:
        """Send the report when one is due; whether it went. Silent on any failure."""
        self.counting()
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
        """The owner's answer (unanswered, yes or no) and when this machine
        asked and recorded it, the reports sent, when the next goes, and the
        next one exactly."""
        answer = sharing(self.project)
        shared = answer is Answer.YES
        offered = answer is not Answer.NO
        state = self.state()
        start = parse_moment(self.since())
        due = (
            (start + timedelta(days=INTERVAL))
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z")
            if start and shared
            else None
        )
        standing: dict[str, Any] = {
            "share": str(answer),
            "asked": state.get("asked"),
            "answered": state.get("answered"),
            "sent": state.get("sent") or [],
            "next": due,
            # Shown while unanswered too, so the owner sees what they are asked about.
            "to": str(self.project.configuration.get("endpoints.usage")) if offered else None,
            "would_send": self.report() if offered else None,
        }
        if answer is Answer.UNANSWERED:
            standing["question"] = QUESTION
            standing["record"] = RECORD
        return standing


def sets(path: Path, key: str) -> bool:
    """Whether the TOML file at `path` sets `key` at its top level."""
    try:
        return key in tomllib.loads(path.read_text())
    except (tomllib.TOMLDecodeError, OSError):
        return False
