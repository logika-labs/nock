"""Reflection rounds, and nock's own kind of them. A round is of a kind
(`kinds.KINDS`): each kind is a `Round` — its name, its skill, when it can
run and is due, what it reads, the files its lead writes and the checks its
end must pass, where its rounds are kept. `nock reflect [KIND]` starts one
and `nock reflect [KIND] finish JSON` checks it and commits it.

nock's own kind, `Reflection`, the default: an agent following the
`/nock-reflect` skill has three subagents look at what the work has been
since the last round — one improves the toolbox (`.nock/tools/`), one keeps
the map of topics (`.nock/topics/map.md`), one weighs how well nock
itself is serving the project — and writes the owner a report, and a summary
abstract enough to share. Each round keeps its numbers, so the next holds its
changes to them, and the first is the baseline."""

from __future__ import annotations

import json
import math
import os
import re
import shlex
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, NotRequired, TypedDict

from nock.checks import Checks
from nock.commands import schema_of
from nock.errors import Failed, PreconditionError
from nock.git import Git, GitError
from nock.project import HEADLESS
from nock.schema import validate
from nock.sessions import Sessions
from nock.topics import CITATION, Topics
from nock.topics import Verdict as ItemVerdict
from nock.utils import format_duration, now, parse_moment, read_json, write_json

if TYPE_CHECKING:
    from nock.project import Project

# Programs whose second word says what they do: `git status`, `uv run`.
TWO_WORDS = {
    "git", "uv", "npm", "npx", "pnpm", "yarn", "poetry", "cargo", "go", "make", "docker",
    "kubectl", "gh", "pip", "bundle", "rails", "dotnet", "mvn", "gradle", "terraform", "brew",
}  # fmt: skip
# Where an agent cut a command's output down by hand.
TRIMMERS = re.compile(r"\|\s*(head|tail|grep|sed -n|awk|cut|wc)\b")
SECTION_ROWS = 25
# A round is due after this many sessions since the last one, or this many days, whichever
# comes first, given a session to look at.
SESSIONS = 15
DAYS = 7
# What the round's lead writes beside its record.
REPORT = "report.md"
SHARE = "share.md"
# The checks nock's round must pass before it counts: nock's own.
ROUND_CHECKS = ("nock-tools", "nock-generators", "nock-map", "nock-share")
# Those quick enough for the end of a turn, when a round is left open.
QUICK_CHECKS = ("nock-map", "nock-share")
ROUND_FILE = "round.json"
RECORD_FILE = "record.json"
# The window's calls, each marked `wrapped` when its exit code is the one a
# command it supervised (`nock run -- pytest`, a tool's `sh`) exited with — not
# one nock gave it for a run it could not start or killed, which has a note.
CALLS = """
SELECT calls.*, EXISTS (
    SELECT 1 FROM runs WHERE runs.call = calls.id AND runs.exit_code = calls.exit_code
    AND NOT (runs.exit_code BETWEEN 40 AND 59 AND runs.note IS NOT NULL)
) AS wrapped FROM calls WHERE started > ? ORDER BY id
"""


class Ending(StrEnum):
    """How a nock call ended, by the exit-code taxonomy: the tool ran and its
    answer was no (exit 1, or a supervised command's own failing code) is not
    nock refusing the call (40s: called wrong, a precondition, policy), nor
    nock breaking (50s)."""

    SUCCEEDED = "succeeded"
    FAILED = "failed"
    REFUSED = "refused"
    BROKE = "broke"

    @classmethod
    def of(cls, call: dict[str, Any]) -> Ending:
        code = call["exit_code"] or 0
        if code == 0:
            return cls.SUCCEEDED
        if call.get("wrapped") or not 40 <= code < 126:
            return cls.FAILED
        return cls.REFUSED if code < 50 else cls.BROKE


class Change(TypedDict):
    kind: Literal[
        "add", "change", "retire", "check", "generator",
        "validate", "path", "timeout", "rule", "invariant", "error", "risk",
        "instrumentation", "identity", "dimension", "funnel", "milestone", "view", "other",
    ]  # fmt: skip
    """add, change, retire, check, generator — the toolbox; validate, path,
    timeout, rule, invariant, error — a logika round's rules; risk — a risk
    it declared on an event, or ruled out with its reason; instrumentation
    — the fields it added to the code for them; identity, dimension, funnel,
    milestone, view — its analytics; other."""
    target: str
    """The tool, check or file: `failures`, `.nock/tools/db.py`; in a logika
    round, the event or rule: `checkout`, `receipt_continuity`."""
    why: str
    """The evidence: what in the material called for it."""
    expect: str
    """What should be measurably different by the next round, and how to tell."""
    tested: NotRequired[str]
    """A logika round's, optional: what showed the change, such as the noise
    check a rule stayed quiet in, or the captures that showed the events and
    params it names."""


class Verdict(TypedDict):
    expectation: str
    held: bool | None
    evidence: str


class Record(TypedDict):
    summary: str
    """The round in a sentence or two."""
    changes: list[Change]
    """What it changed in the toolbox."""
    verdicts: NotRequired[list[Verdict]]
    """On each expectation the last round left."""
    notes: NotRequired[str]
    """What the next round should look at."""


def shape(command: str) -> str:
    """What a shell command is, in a word or three: `pytest`, `git log`,
    `python -m pytest`."""
    first = command.strip().split("\n")[0]
    segments = [segment.strip() for segment in re.split(r"&&|;|\|\|", first)]
    segment = next((part for part in segments if part and not part.startswith("cd ")), first)
    segment = segment.split("|")[0]
    try:
        words = shlex.split(segment)
    except ValueError:
        words = segment.split()
    words = [word for word in words if not re.match(r"^[A-Z_][A-Z0-9_]*=", word)]
    if not words:
        return first[:40]
    program = os.path.basename(words[0])
    if program.startswith("python") and len(words) > 2 and words[1] == "-m":
        return f"{program} -m {words[2]}"
    if program in TWO_WORDS and len(words) > 1 and not words[1].startswith("-"):
        return f"{program} {words[1]}"
    return program


def is_nock(command: str) -> bool:
    return ".nock/nock" in command


def kilobytes(count: float | None) -> str:
    if count is None:
        return "-"
    return f"{count / 1000:.1f}k" if count >= 1000 else str(int(count))


def seconds(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value:.1f}s" if value < 60 else format_duration(value)


@dataclass
class Window:
    since: str | None
    sessions: list[dict[str, Any]]

    def rows(self, project: Project, table: str, order: str) -> list[dict[str, Any]]:
        """The window's sessions' prompts or events from inside the window: a
        session that ran for days brings only what it did since `since`."""
        identities = [row["id"] for row in self.sessions]
        marks = ",".join("?" for _ in identities) or "''"
        rows = project.store.rows(
            f"SELECT * FROM {table} WHERE session IN ({marks}) ORDER BY {order}",
            tuple(identities),
        )
        start = parse_moment(self.since)
        if start is None:
            return rows
        return [row for row in rows if (parse_moment(row["moment"]) or start) >= start]

    def spend(self) -> tuple[float | None, int]:
        """The sessions' API-equivalent cost over those priced, and how many
        are unpriced; the cost is None when none is priced but some ran."""
        priced = [row["cost"] for row in self.sessions if row["cost"] is not None]
        unpriced = len(self.sessions) - len(priced)
        if unpriced and not priced:
            return None, unpriced
        return round(sum(priced), 4), unpriced

    def tokens(self, kind: str | None = None) -> int:
        kinds = [kind] if kind else list(TOKEN_COLUMNS)
        return sum(row[TOKEN_COLUMNS[name]] or 0 for row in self.sessions for name in kinds)


# The sessions table's column of each token kind.
TOKEN_COLUMNS = {
    "input": "input_tokens",
    "output": "output_tokens",
    "cache_read": "cache_read_tokens",
    "cache_write": "cache_write_tokens",
}


def said_spend(cost: float | None, unpriced: int) -> str:
    """The cost as a reader should take it: API-equivalent, with what it leaves out."""
    if cost is None:
        return "cost unknown (no session priced)"
    left_out = f", {unpriced} session(s) unpriced" if unpriced else ""
    return f"${cost:.2f} at API prices{left_out}"


class Rounds:
    """Every round: `.nock/reflections/DATE/` — its record, report and shareable
    summary, committed — and, while it runs, what it reads, in
    `.nock/local/reflections/DATE/`."""

    def __init__(self, project: Project, place: str = "") -> None:
        self.project = project
        # A kind's rounds are a directory of their own, so they never move nock's window.
        self.place = [place] if place else []

    @property
    def directory(self) -> Path:
        return self.project.code_path("reflections", *self.place)

    @property
    def scratch(self) -> Path:
        return self.project.local.joinpath("reflections", *self.place)

    def all(self) -> list[dict[str, Any]]:
        """Every finished round, oldest first."""
        if not self.directory.is_dir():
            return []
        records = []
        for path in self.directory.glob(f"*/{RECORD_FILE}"):
            try:
                record = read_json(path)
            except PreconditionError:
                continue
            record.setdefault("round", path.parent.name)
            records.append(record)
        return sorted(records, key=lambda record: record.get("finished") or record["round"])

    def last(self) -> dict[str, Any] | None:
        records = self.all()
        return records[-1] if records else None

    def current(self) -> str | None:
        """The round started and not finished, if there is one."""
        if not self.scratch.is_dir():
            return None
        started = sorted(
            path.parent.name
            for path in self.scratch.glob(f"*/{ROUND_FILE}")
            if not (self.directory / path.parent.name / RECORD_FILE).is_file()
        )
        return started[-1] if started else None

    def new_name(self) -> str:
        """Today's date, with `-2`, `-3`… for another round the same day."""
        today = datetime.now(UTC).strftime("%Y-%m-%d")
        name, count = today, 1
        while (self.directory / name).exists() or (self.scratch / name).exists():
            count += 1
            name = f"{today}-{count}"
        return name


def schema() -> dict[str, Any]:
    return schema_of(Record)


def commit(project: Project, message: str, also: tuple[str, ...] = ()) -> None:
    """Commit a round: `.nock/` (and `also`) in the working tree, and the main
    checkout's topics when the round ran in a worktree; nothing else in either."""
    places = [(project.here, [".nock", *also])]
    if project.root != project.here:
        places.append((project.root, [".nock/topics"]))
    for root, paths in places:
        git = Git(root)
        git("add", "--all", "--", *paths)
        if git("diff", "--cached", "--name-only", "--", *paths):
            git("commit", "--quiet", "--no-verify", "--only", "-m", message, "--", *paths)


class Round:
    """A kind of reflection round: what `kinds.KINDS` holds. A kind says its
    name (the word after `nock reflect`), its skill, where it can run and
    when it is due, what its lead reads (`begin`), the files the lead writes,
    the checks its end must pass, and what its record keeps (`kept`)."""

    kind = ""
    # The kind run by `nock reflect` alone; its rounds are `.nock/reflections/DATE/`.
    default = False
    title = ""
    skill = ""
    # What the round's lead writes beside its record.
    files: tuple[str, ...] = (REPORT,)
    # nock checks its end must pass; the quick ones also judge a round left open.
    checks: tuple[str, ...] = ()
    quick: tuple[str, ...] = ()
    # Committed with `.nock/` when it finishes.
    also: tuple[str, ...] = ()

    def __init__(self, project: Project) -> None:
        self.project = project
        self.rounds = Rounds(project, "" if self.default else self.kind)

    @classmethod
    def wanted(cls, root: Path) -> bool:
        """Whether `nock init` installs its skill in the repository at `root`."""
        return True

    @property
    def command(self) -> str:
        return "reflect" if self.default else f"reflect {self.kind}"

    def unavailable(self) -> str:
        """Why a round of this kind cannot run here, or nothing when it can."""
        return ""

    def due(self) -> str:
        return ""

    def standing(self) -> dict[str, Any] | None:
        """For `nock status` and the session start, of a kind that is offered
        rather than due: nothing where it cannot run."""
        if self.unavailable():
            return None
        last = self.rounds.last()
        return {
            "due": self.due() or None,
            "last": last.get("finished") if last else None,
            "skill": (self.project.here / ".claude" / "skills" / self.skill / "SKILL.md").is_file(),
        }

    def begin(self, name: str, scratch: Path) -> dict[str, Any]:
        """Write what the round reads into `scratch`: `since`, `material`
        (part → file) and what `round.json` keeps for the record."""
        raise NotImplementedError

    def problems(self, record: Record | None) -> list[str]:
        """What its end-of-round checks find: `checks` (only `quick` with no
        record, for a round left open), and the record's own."""
        names = list(self.checks if record is not None else self.quick)
        return Checks(self.project).run(names).problems() if names else []

    def kept(self, name: str, started: dict[str, Any]) -> dict[str, Any]:
        """What the record keeps beside the lead's: the numbers it started from."""
        return {}

    def start(self) -> dict[str, Any]:
        """Start a round — or pick up the one started and not finished, its
        material and start left as they were written, so a second start
        overwrites nothing; another round the same day is `DATE-2`."""
        problem = self.unavailable()
        if problem:
            raise PreconditionError(problem)
        name = self.rounds.current()
        scratch = self.rounds.scratch / (name or self.rounds.new_name())
        kept = scratch / ROUND_FILE
        session = self.project.current_session()
        if name is not None and kept.is_file():
            started = read_json(kept)
            if session and session not in started.get("sessions", []):
                write_json(kept, {**started, "sessions": [*started.get("sessions", []), session]})
            material = started.get("material") or {
                path.stem: str(path) for path in sorted(scratch.glob("*.md"))
            }
            return {
                **self.started(scratch.name, started["since"], material),
                "picked_up": f"the round {scratch.name}, started {started['started']} and not "
                "finished; its material stands as written then",
            }
        name = scratch.name
        scratch.mkdir(parents=True, exist_ok=True)
        begun = self.begin(name, scratch)
        write_json(
            kept,
            {
                "round": name,
                "since": begun["since"],
                "started": now(),
                "sessions": [session] if session else [],
                "material": begun["material"],
                **begun["kept"],
            },
        )
        (self.rounds.directory / name).mkdir(parents=True, exist_ok=True)
        return self.started(name, begun["since"], begun["material"])

    def started(self, name: str, since: str | None, material: dict[str, str]) -> dict[str, Any]:
        """What `nock reflect` answers of a round under way."""
        return {
            "round": name,
            "since": since,
            # On the main checkout, wherever the round runs.
            "material": material,
            "write": [
                str((self.rounds.directory / name / file).relative_to(self.project.here))
                for file in self.files
            ],
            "finish": f".nock/nock {self.command} finish JSON",
        }

    def unwritten(self, name: str) -> list[str]:
        directory = self.rounds.directory / name
        return [
            file
            for file in self.files
            if not (directory / file).is_file() or not (directory / file).read_text().strip()
        ]

    def finish(self, record: Record) -> dict[str, Any]:
        """Check the round and commit it: its files written, its checks
        passing, the record kept with what it started from."""
        name = self.rounds.current()
        if name is None:
            raise PreconditionError(
                f"no {self.title} is under way — `.nock/nock {self.command}` starts one"
            )
        validate(record, schema())
        directory = self.rounds.directory / name
        missing = self.unwritten(name)
        if missing:
            raise PreconditionError(f"write {' and '.join(missing)} in {directory} first")
        problems = self.problems(record)
        if problems:
            raise Failed(f"the {self.title} does not pass its checks yet", problems)
        started = read_json(self.rounds.scratch / name / ROUND_FILE)
        write_json(
            directory / RECORD_FILE,
            {
                **record,
                "round": name,
                "since": started["since"],
                "started": started["started"],
                "finished": now(),
                **self.kept(name, started),
            },
        )
        commit(self.project, f"{self.title.capitalize()} {name}: {record['summary']}", self.also)
        return {
            "round": name,
            "wrote": [
                str((directory / file).relative_to(self.project.here)) for file in self.files
            ],
        }

    def left_open(self, session: str) -> str | None:
        """What a session that started this kind's round, still under way,
        has left to do before it may end; nothing otherwise."""
        name = self.rounds.current()
        if name is None:
            return None
        started = read_json(self.rounds.scratch / name / ROUND_FILE)
        if session not in started.get("sessions", []):
            return None
        directory = self.rounds.directory / name
        owed = [
            f"write {file} in {directory.relative_to(self.project.here)}"
            for file in self.unwritten(name)
        ]
        if not owed:
            owed += [f"fix what its checks find: {problem}" for problem in self.problems(None)]
        owed.append(f"then `.nock/nock {self.command} finish JSON` records it")
        return (
            f"nock: the {self.title} {name} is under way and not finished — "
            + "; ".join(owed)
            + ". Finish it, or tell the owner why it stays open."
        )


class Reflection(Round):
    """nock's own round: the toolbox, the map and nock itself."""

    kind = "nock"
    default = True
    title = "reflection round"
    skill = "nock-reflect"
    files = (REPORT, SHARE)
    checks = ROUND_CHECKS
    quick = QUICK_CHECKS

    # --- when -----------------------------------------------------------------

    def window(self) -> Window:
        """The sessions since the last round, the transcripts read up to now first."""
        last = self.rounds.last()
        since = last.get("finished") if last else None
        sessions = Sessions(self.project)
        sessions.catch_up()
        return Window(since, sessions.since(since))

    def due(self) -> str:
        """Why a round is due, or nothing when it is not: enough sessions or
        enough days since the last one, and at least one session to look at."""
        window = self.window()
        count = len(window.sessions)
        if not count:
            return ""
        if count >= SESSIONS:
            return f"a reflection round is due ({count} sessions since the last)"
        days = self.days(window)
        if days >= DAYS:
            return f"a reflection round is due ({count} sessions over {days:.0f} days)"
        return ""

    def days(self, window: Window) -> float:
        since = parse_moment(window.since) or (
            parse_moment(window.sessions[0]["started"]) if window.sessions else None
        )
        return (datetime.now(UTC) - since).total_seconds() / 86400 if since else 0

    # --- a round ----------------------------------------------------------------

    def begin(self, name: str, scratch: Path) -> dict[str, Any]:
        """What its three parts read: the toolbox's, the map's and nock's."""
        window = self.window()
        last = self.rounds.last()
        metrics = self.metrics(window)
        material = {
            "process": Material(self.project, window, last).render(),
            "knowledge": Knowledge(self.project, window).render(),
            "nock": Evidence(
                self.project, metrics, self.rounds.all(), feedback(self.project, window.since)
            ).render(),
        }
        for part, text in material.items():
            (scratch / f"{part}.md").write_text(text)
        return {
            "since": window.since,
            "material": {part: str(scratch / f"{part}.md") for part in material},
            "kept": {"metrics": metrics},
        }

    def kept(self, name: str, started: dict[str, Any]) -> dict[str, Any]:
        return {
            "metrics": started["metrics"],
            "snapshot": self.snapshot(started["since"]),
            "shared": None,
        }

    def record_shared(self, name: str, shared: dict[str, Any]) -> None:
        path = self.rounds.directory / name / RECORD_FILE
        write_json(path, {**read_json(path), "shared": shared})

    # --- the numbers --------------------------------------------------------------

    def snapshot(self, since: str | None) -> dict[str, Any]:
        """Each tool's numbers over the window, kept in the round's record so
        the next round can compare."""
        return {
            row["tool"]: {
                key: row[key]
                for key in ("calls", "failures", "sessions", "median_seconds", "mean_bytes")
            }
            for row in tool_rows(self.project, since)
        }

    def metrics(self, window: Window) -> dict[str, Any]:
        """The window in numbers, computed the same way every round: the work,
        nock's use, the decisions and how the owner met them, the toolbox and
        the map. The first round's are the baseline."""
        since = window.since or ""
        events = window.rows(self.project, "events", "rowid")
        prompts = window.rows(self.project, "prompts", "rowid")
        cost, unpriced = window.spend()
        calls = self.project.store.rows(CALLS, (since,))
        endings = Counter(Ending.of(row) for row in calls)
        topics = Topics(self.project)
        every = topics.every()
        submitted = [item for item in every if item["created"]["moment"] > since]
        decided = [item for item in every if item["decided"] and item["decided"]["moment"] > since]
        tools = [row for row in tool_rows(self.project, since) if row["source"] != "nock"]
        try:
            commits = int(
                self.project.git("rev-list", "--count", f"--since={since or '1970-01-01'}", "HEAD")
            )
        except GitError:
            commits = 0
        cited = (
            len({match.group(0) for match in CITATION.finditer(topics.map.read_text())})
            if topics.map.is_file()
            else 0
        )
        return {
            "days": round(self.days(window), 1),
            "sessions": len(window.sessions),
            "headless_sessions": len(Sessions(self.project).since(window.since, HEADLESS)),
            "requests": len(prompts),
            "interrupts": sum(row["interrupts"] or 0 for row in window.sessions),
            "compactions": sum(row["compactions"] or 0 for row in window.sessions),
            "tool_calls": len(events),
            "failed_tool_calls": sum(row["failed"] or 0 for row in events),
            "tokens": window.tokens(),
            **{f"{kind}_tokens": window.tokens(kind) for kind in TOKEN_COLUMNS},
            "api_cost": cost,
            "unpriced_sessions": unpriced,
            "commits": commits,
            "nock_calls": len(calls),
            "nock_failed": endings[Ending.FAILED],
            "nock_refused": endings[Ending.REFUSED],
            "nock_broke": endings[Ending.BROKE],
            "consultations": sum(
                1
                for row in self.project.store.rows(
                    "SELECT exit_code FROM calls WHERE tool = 'consult' AND started > ?", (since,)
                )
                if row["exit_code"] == 0
            ),
            "topics": len(topics.names()),
            "items_submitted": len(submitted),
            "items_decisions": sum(
                1
                for item in submitted
                if any(entry["kind"] == "decision" for entry in item["versions"][-1]["files"])
            ),
            "items_decided": len(decided),
            "items_accepted": sum(1 for item in decided if item["verdict"] == ItemVerdict.ACCEPTED),
            "items_rejected": sum(
                1
                for item in decided
                if item["verdict"] in (ItemVerdict.REJECTED, ItemVerdict.DROPPED)
            ),
            "items_open": sum(1 for item in every if item["verdict"] == ItemVerdict.OPEN),
            "tools": len(tools),
            "tools_used": sum(1 for row in tools if row["calls"]),
            "tool_calls_to_project_tools": sum(row["calls"] for row in tools),
            "map_lines": len(topics.map.read_text().splitlines()) if topics.map.is_file() else 0,
            "map_citations": cited,
        }


def feedback(project: Project, since: str | None) -> list[str]:
    """What consultants said nock lacked, in the window."""
    found = []
    for path in sorted((project.local / "consultations").glob("*.json")):
        try:
            record = read_json(path)
        except PreconditionError:
            continue
        said = str((record.get("submitted") or {}).get("feedback") or "").strip()
        if said and str(record.get("moment") or "") > (since or ""):
            found.append(said)
    return found


def tool_rows(project: Project, since: str | None) -> list[dict[str, Any]]:
    """Per command over the window: calls, failures by kind, sessions, duration,
    how much it printed, how often it was capped or cached."""
    rows = project.store.rows(CALLS, (since or "",))
    known = {tool.command.path: tool for tool in project.registry.tools}
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if row["tool"] in known:
            grouped[row["tool"]].append(row)
    result = []
    for path, tool in known.items():
        calls = grouped.get(path, [])
        durations = [row["duration"] for row in calls if row["duration"] is not None]
        printed = [row["output_bytes"] or 0 for row in calls]
        codes = Counter(row["exit_code"] for row in calls)
        endings = Counter(Ending.of(row) for row in calls)
        result.append(
            {
                "tool": path,
                "source": tool.source,
                "pinned": tool.pinned,
                "calls": len(calls),
                "sessions": len({row["session"] for row in calls if row["session"]}),
                "failures": sum(count for code, count in codes.items() if code not in (0, None)),
                "failed": endings[Ending.FAILED],
                "refused": endings[Ending.REFUSED],
                "broke": endings[Ending.BROKE],
                "median_seconds": round(statistics.median(durations), 2) if durations else None,
                "max_seconds": round(max(durations), 2) if durations else None,
                "mean_bytes": round(sum(printed) / len(printed)) if printed else None,
                "capped": sum(
                    1 for row in calls if (row["full_bytes"] or 0) > (row["output_bytes"] or 0)
                ),
                "cached": sum(row["cached"] or 0 for row in calls),
                "last_used": calls[-1]["started"] if calls else None,
            }
        )
    return result


class Material:
    """What the round's toolbox part reads, computed: the big picture first,
    then the numbers."""

    def __init__(self, project: Project, window: Window, last: dict[str, Any] | None) -> None:
        self.project = project
        self.window = window
        self.last = last
        self.since = window.since or ""
        self.events = window.rows(project, "events", "session, moment")
        self.prompts = window.rows(project, "prompts", "moment")
        self.calls = project.store.rows(CALLS, (self.since,))

    def render(self) -> str:
        sections = [
            self.overview(),
            self.requests(),
            self.direction(),
            self.expectations(),
            self.toolbox(),
            self.mistakes(),
            self.raw_work(),
            self.reading(),
            self.sessions_table(),
            QUERY_HELP,
        ]
        return "\n\n".join(section for section in sections if section)

    def overview(self) -> str:
        sessions = self.window.sessions
        tokens = self.window.tokens()
        since = (
            f"since the last round ({self.since})"
            if self.window.since
            else "since nock was installed"
        )
        return (
            f"# Overview\n\n{len(sessions)} sessions {since}: {len(self.prompts)} requests from the human, "
            f"{len(self.events)} tool calls, {len(self.calls)} calls to nock, "
            f"{tokens / 1e6:.1f}M tokens, {said_spend(*self.window.spend())}."
        )

    def requests(self) -> str:
        """What the human asked for, in their words — the work the toolbox serves."""
        if not self.prompts:
            return ""
        titles = {row["id"]: row["title"] for row in self.window.sessions}
        lines = [
            "# What the human asked for",
            "",
            "In their words, oldest first; a correction or a repeat is a signal.",
        ]
        shown = self.prompts[-80:]
        if len(self.prompts) > len(shown):
            lines.append(f"(the {len(self.prompts) - len(shown)} oldest are left out)")
        current = None
        for prompt in shown:
            if prompt["session"] != current:
                current = prompt["session"]
                lines.append(f"\n## {(titles.get(current) or current)[:80]} ({current[:8]})")
            text = " ".join(prompt["text"].split())
            lines.append(f"- {text[:300]}{'…' if len(text) > 300 else ''}")
        return "\n".join(lines)

    def direction(self) -> str:
        """Where the code is going: commits and the areas they touch."""
        try:
            commits = self.project.git.commits(
                "HEAD",
                f"--since={self.window.since}" if self.window.since else "--max-count=60",
                limit=60,
            )
        except GitError:
            return ""
        if not commits:
            return ""
        areas: Counter[str] = Counter()
        churn: Counter[str] = Counter()
        for commit in commits:
            for path in commit.files:
                parts = path.split("/")
                area = "/".join(parts[:2]) if len(parts) > 2 else parts[0]
                areas[area] += 1
            churn["insertions"] += commit.insertions
            churn["deletions"] += commit.deletions
        lines = [
            "# Where the code is going",
            "",
            f"{len(commits)} commits, +{churn['insertions']} −{churn['deletions']} lines. Most touched: "
            + ", ".join(f"{area} ({count})" for area, count in areas.most_common(10)),
            "",
        ]
        lines += [f"- {commit.moment[:10]} {commit.subject[:100]}" for commit in commits[:40]]
        return "\n".join(lines)

    def expectations(self) -> str:
        if not self.last:
            return "# The last round\n\nThis is the first round."
        lines = [
            f"# The last round ({self.last['round']})",
            "",
            str(self.last.get("summary", "")),
            "",
        ]
        before = self.last.get("snapshot") or {}
        now_rows = {row["tool"]: row for row in tool_rows(self.project, self.since)}
        for change in self.last.get("changes", []):
            lines.append(
                f"- {change.get('kind')} {change.get('target')}: expected {change.get('expect')}"
            )
            target = str(change.get("target", ""))
            for tool, row in now_rows.items():
                if tool == target or target.endswith(f"/{tool}") or f"`{tool}`" in target:
                    earlier = before.get(tool) or {}
                    lines.append(
                        f"  now: {row['calls']} calls in {row['sessions']} sessions, {row['failures']} failed"
                        + (
                            f" (the round before: {earlier.get('calls', 0)} calls, {earlier.get('failures', 0)} failed)"
                            if earlier
                            else ""
                        )
                    )
        if self.last.get("notes"):
            lines += ["", f"Notes it left: {self.last['notes']}"]
        return "\n".join(lines)

    def toolbox(self) -> str:
        rows = tool_rows(self.project, self.since)
        total = sum(row["calls"] for row in rows)
        threshold = 0.5 * math.log10(total) if total > 1 else 0
        lines = [
            "# The toolbox",
            "",
            "Per command over the window (nock's own only when used). failed: it ran and its "
            "answer was no (exit 1, or the code of a command it ran, as `run -- pytest` passes "
            "pytest's on), never nock refusing; refused: nock refused the call (40s: called wrong, "
            "a precondition, policy); broke: 50s; capped is how often it printed less than it had.",
            "",
            "tool,source,calls,sessions,failed,refused,broke,median_seconds,max_seconds,mean_bytes,capped,cached,last_used",
        ]
        shown = [row for row in rows if row["calls"] or row["source"] != "nock"]
        for row in sorted(shown, key=lambda row: (row["source"] == "nock", -row["calls"])):
            lines.append(
                ",".join(
                    str(value if value is not None else "-")
                    for value in (
                        row["tool"],
                        row["source"],
                        row["calls"],
                        row["sessions"],
                        row["failed"],
                        row["refused"],
                        row["broke"],
                        row["median_seconds"],
                        row["max_seconds"],
                        row["mean_bytes"],
                        row["capped"],
                        row["cached"],
                        (row["last_used"] or "-")[:10],
                    )
                )
            )
        rare = [
            row["tool"]
            for row in rows
            if row["source"] != "nock" and not row["pinned"] and row["calls"] < threshold
        ]
        if rare:
            lines += [
                "",
                f"Used fewer than {threshold:.1f} times (½·log₁₀ of all calls) — candidates to retire or merge: {', '.join(rare)}",
            ]
        pinned = [row["tool"] for row in rows if row["pinned"]]
        if pinned:
            lines.append(f"Pinned (keep however rarely used): {', '.join(pinned)}")
        failures = self.project.registry.failures
        if failures:
            lines += ["", "Tools that do not load:"] + [f"- {failure}" for failure in failures]
        return "\n".join(lines)

    def mistakes(self) -> str:
        """Calls nock refused or that broke: what agents expected to exist, or got wrong."""
        known = {tool.command.path for tool in self.project.registry.tools}
        unknown: Counter[str] = Counter()
        wrong: Counter[tuple[str, str]] = Counter()
        crashed: Counter[tuple[str, str]] = Counter()
        for row in self.calls:
            ending = Ending.of(row)
            if row["tool"] not in known:
                unknown[row["tool"]] += 1
            elif ending == Ending.REFUSED and row["error"]:
                wrong[(row["tool"], row["error"][:160])] += 1
            elif ending == Ending.BROKE and row["error"]:
                crashed[(row["tool"], row["error"][:160])] += 1
        if not (unknown or wrong or crashed):
            return ""
        lines = ["# Mistakes", ""]
        if unknown:
            lines.append(
                "Commands agents tried that do not exist (what they expected to find): "
                + ", ".join(f"`{name}` ×{count}" for name, count in unknown.most_common(15))
            )
        for (tool, error), count in wrong.most_common(10):
            lines.append(f"- `{tool}` called wrong ×{count}: {error}")
        for (tool, error), count in crashed.most_common(10):
            lines.append(f"- `{tool}` broke ×{count}: {error}")
        return "\n".join(lines)

    def raw_work(self) -> str:
        """Shell work done around nock: what repeats, what fails, what prints most."""
        bash = [
            event
            for event in self.events
            if event["tool"] == "Bash" and not is_nock(event["input"] or "")
        ]
        if not bash:
            return ""
        by_shape: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for event in bash:
            by_shape[shape(event["input"] or "")].append(event)
        lines = [
            "# Raw shell work",
            "",
            "Commands run without nock, by what they are. trimmed = piped into head/tail/grep by hand.",
            "",
            "command,runs,sessions,failed,trimmed,median_seconds,total_output,example",
        ]
        ranked = sorted(by_shape.items(), key=lambda item: -len(item[1]))[:SECTION_ROWS]
        for name, events in ranked:
            durations = [event["duration"] for event in events if event["duration"] is not None]
            example = max(events, key=lambda event: len(event["input"] or ""))["input"].split("\n")[
                0
            ][:120]
            lines.append(
                ",".join(
                    [
                        name,
                        str(len(events)),
                        str(len({event["session"] for event in events})),
                        str(sum(event["failed"] or 0 for event in events)),
                        str(sum(1 for event in events if TRIMMERS.search(event["input"] or ""))),
                        seconds(statistics.median(durations) if durations else None),
                        kilobytes(sum(event["output_bytes"] or 0 for event in events)),
                        json.dumps(example),
                    ]
                )
            )
        sequences: Counter[tuple[str, str]] = Counter()
        previous: dict[str, str] = {}
        for event in self.events:
            if event["tool"] != "Bash":
                continue
            current = shape(event["input"] or "") if not is_nock(event["input"] or "") else "nock"
            before = previous.get(event["session"])
            if before and before != current:
                sequences[(before, current)] += 1
            previous[event["session"]] = current
        recurring = [(pair, count) for pair, count in sequences.most_common(8) if count >= 3]
        if recurring:
            lines += [
                "",
                "Recurring pairs (one command, then the next): "
                + "; ".join(f"{a} → {b} ×{count}" for (a, b), count in recurring),
            ]
        biggest = sorted(self.events, key=lambda event: -(event["output_bytes"] or 0))[:8]
        biggest = [event for event in biggest if (event["output_bytes"] or 0) > 4000]
        if biggest:
            lines += ["", "Largest outputs an agent had to read:"]
            lines += [
                f"- {kilobytes(event['output_bytes'])} — {event['tool']}: {(event['input'] or '')[:120]}"
                for event in biggest
            ]
        failing = [event for event in bash if event["failed"]]
        if failing:
            counted = Counter((event["input"] or "").split("\n")[0][:120] for event in failing)
            lines += ["", "Most repeated failing commands:"] + [
                f"- ×{count} {command}" for command, count in counted.most_common(8)
            ]
        return "\n".join(lines)

    def reading(self) -> str:
        """What agents read and searched for most: knowledge they keep rebuilding."""
        reads = Counter(event["input"] for event in self.events if event["tool"] == "Read")
        searches = Counter(
            event["input"] for event in self.events if event["tool"] in ("Grep", "Glob")
        )
        mix = Counter(event["tool"] for event in self.events)
        if not mix:
            return ""
        lines = [
            "# What agents read",
            "",
            "Tool calls by kind: "
            + ", ".join(f"{tool} {count}" for tool, count in mix.most_common(12)),
        ]
        repeated = [(path, count) for path, count in reads.most_common(15) if count > 2]
        if repeated:
            lines.append("Most read: " + ", ".join(f"{path} ×{count}" for path, count in repeated))
        searched = [(pattern, count) for pattern, count in searches.most_common(10) if count > 2]
        if searched:
            lines.append(
                "Most searched: "
                + ", ".join(f"{pattern!r} ×{count}" for pattern, count in searched)
            )
        return "\n".join(lines)

    def sessions_table(self) -> str:
        sessions = self.window.sessions
        if not sessions:
            return ""
        failed = Counter(event["session"] for event in self.events if event["failed"])
        calls = Counter(event["session"] for event in self.events)
        lines = [
            "# Sessions",
            "",
            "started,id,title,prompts,tool_calls,failed,interrupts,compactions,tokens,api_cost",
        ]
        for row in sessions[-SECTION_ROWS * 2 :]:
            tokens = sum(
                row[key] or 0
                for key in (
                    "input_tokens",
                    "output_tokens",
                    "cache_read_tokens",
                    "cache_write_tokens",
                )
            )
            lines.append(
                ",".join(
                    [
                        (row["started"] or "-")[:16],
                        row["id"][:8],
                        json.dumps((row["title"] or "")[:60]),
                        str(row["prompts"] or 0),
                        str(calls[row["id"]]),
                        str(failed[row["id"]]),
                        str(row["interrupts"] or 0),
                        str(row["compactions"] or 0),
                        f"{tokens / 1000:.0f}k",
                        f"${row['cost']:.2f}" if row["cost"] is not None else "unknown",
                    ]
                )
            )
        return "\n".join(lines)


QUERY_HELP = """\
# Digging deeper

`.nock/nock query "SELECT …"` reads the telemetry (read-only SQLite). Tables:
calls (every nock call: tool, arguments, session, started, duration,
exit_code, output_bytes, full_bytes, cached, error), runs (supervised
processes, their logs in .nock/local/logs/run-ID.log), sessions, prompts
(session, moment, text), events (session, moment, tool, input, failed,
output_bytes, duration — every tool call of every session). Example:
`.nock/nock query "SELECT input, output_bytes FROM events WHERE tool = 'Bash' AND input LIKE '%pytest%' ORDER BY output_bytes DESC LIMIT 5"`."""


class Knowledge:
    """What the round's map part reads: the items submitted, changed or
    decided since the last round in full, every topic with its items in a
    line, and the map as it stands."""

    def __init__(self, project: Project, window: Window) -> None:
        self.topics = Topics(project)
        self.since = window.since or ""

    def render(self) -> str:
        topics = self.topics
        every = topics.every()
        recent = [item for item in every if item["updated"] > self.since]
        lines = [
            f"# Submitted, changed or decided since the last round ({self.since or 'never'})",
            "",
        ]
        if not recent:
            lines.append("Nothing.")
        for item in recent:
            lines += [f"## [{item['ref']}] {item['title']}", "", "```json"]
            lines += [json.dumps(topics.shown(item), indent=2, ensure_ascii=False), "```", ""]
        lines += ["", "# Every topic and its items", ""]
        for name in topics.names():
            row = topics.row(name)
            lines.append(f"## {name} ({row['state']}, {row['open']} open): {row['description']}")
            lines += [
                f"- [{item['ref']}] {item['verdict']}: {item['title']}"
                for item in topics.items(name)
            ]
        if not topics.names():
            lines.append("None yet.")
        problems = topics.citation_problems()
        current = topics.map.read_text() if topics.map.is_file() else ""
        lines += ["", "# The map as it stands", "", current.strip() or "There is no map yet."]
        if problems:
            lines += ["", "Its citations that no longer hold:"]
            lines += [f"- line {problem.line}: {problem.message}" for problem in problems]
        return "\n".join(lines) + "\n"


class Evidence:
    """What the round's nock part reads: this window's numbers beside every
    earlier round's — the first is the baseline."""

    def __init__(
        self,
        project: Project,
        metrics: dict[str, Any],
        rounds: list[dict[str, Any]],
        feedback: list[str] | None = None,
    ) -> None:
        self.project = project
        self.metrics = metrics
        self.rounds = [record for record in rounds if record.get("metrics")]
        self.feedback = feedback or []

    def render(self) -> str:
        columns = [*(record["round"] for record in self.rounds), "this window"]
        rows = [*(record["metrics"] for record in self.rounds), self.metrics]
        lines = [
            "# nock, in numbers",
            "",
            "Each column is a round's window, computed the same way every time; the first is the baseline."
            if self.rounds
            else "This is the first round: these numbers are the baseline the next rounds compare to.",
            "",
            "| | " + " | ".join(columns) + " |",
            "|---|" + "---|" * len(columns),
        ]
        for key in self.metrics:
            lines.append(f"| {key} | " + " | ".join(str(row.get(key, "-")) for row in rows) + " |")
        lines += ["", METRICS_HELP, "", QUERY_HELP]
        if self.feedback:
            lines += ["", "# Where consultants said nock fell short", ""]
            lines += [f"- {said}" for said in self.feedback]
        return "\n".join(lines) + "\n"


METRICS_HELP = """\
What they count: sessions the human started in the window (`days` long) and
what they asked (`requests`), interrupted and compacted; every tool call
they made and how many failed, counted from the window's start even in a
session that began before it; `headless_sessions`, the `claude -p` runs nock
did not dispatch, kept out of everything else; tokens, in all and by kind, of
the sessions; `api_cost`, what they would cost at API prices (a subscription
does not pay per token), over the priced ones, and `unpriced_sessions`; commits. `nock_*`: calls
to nock, and how many `failed` (the tool ran and its answer was no: exit 1, or
the failing code of a command it ran, such as pytest's under `run` — never
nock refusing), were `refused` by nock (40s: called wrong, a precondition,
policy) or `broke` (50s); `consultations` answered. `topics`: how many there are. `items_*`:
submitted in the window (and how many hold a decision), decided by the owner
in it (accepted, rejected), and every one still open. `tools`: the project's
own commands, how many were used, and how often. `map_*`: the map's length
and the items it cites."""
