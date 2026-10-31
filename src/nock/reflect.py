"""Reflection rounds: an agent, following the `/nock-reflect` skill, has three
subagents look at what the work has been since the last round — one improves
the toolbox (`.nock/tools/`), one keeps the map of decisions
(`.nock/decisions/map.md`), one weighs how well nock itself is serving the
project — and writes the owner a report, and a summary abstract enough to
share. `nock reflect start` computes what they read; `nock reflect finish`
checks the round and commits it. Each round keeps its numbers, so the next
holds its changes to them, and the first is the baseline."""

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
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, NotRequired, TypedDict

from nock.checks import Checks
from nock.commands import schema_of
from nock.decisions import Decisions, live
from nock.errors import Failed, PreconditionError
from nock.git import Git, GitError
from nock.schema import validate
from nock.sessions import Sessions
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
# What the round's lead writes beside its record.
REPORT = "report.md"
SHARE = "share.md"
# The checks a round must pass before it counts: nock's own.
ROUND_CHECKS = ["nock-tools", "nock-generators", "nock-map", "nock-share"]


class Change(TypedDict):
    kind: Literal["add", "change", "retire", "check", "generator", "other"]
    target: str
    """The tool, check or file: `failures`, `.nock/tools/db.py`."""
    why: str
    """The evidence: what in the material called for it."""
    expect: str
    """What should be measurably different by the next round, and how to tell."""


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


class Rounds:
    """Every round: `.nock/reflections/DATE/` — its record, report and shareable
    summary, committed — and, while it runs, what it reads, in
    `.nock/local/reflections/DATE/`."""

    def __init__(self, project: Project) -> None:
        self.project = project

    @property
    def directory(self) -> Path:
        return self.project.code_path("reflections")

    @property
    def scratch(self) -> Path:
        return self.project.local / "reflections"

    def all(self) -> list[dict[str, Any]]:
        """Every finished round, oldest first (rounds from before rounds had
        directories included)."""
        if not self.directory.is_dir():
            return []
        records = []
        paths = [*self.directory.glob("*/record.json"), *self.directory.glob("*.json")]
        for path in paths:
            try:
                record = read_json(path)
            except PreconditionError:
                continue
            record.setdefault(
                "round", path.parent.name if path.name == "record.json" else path.stem
            )
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
            for path in self.scratch.glob("*/round.json")
            if not (self.directory / path.parent.name / "record.json").is_file()
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


class Reflection:
    def __init__(self, project: Project) -> None:
        self.project = project
        self.rounds = Rounds(project)

    # --- when -----------------------------------------------------------------

    def window(self) -> Window:
        last = self.rounds.last()
        since = last.get("finished") if last else None
        return Window(since, Sessions(self.project).since(since))

    def due(self) -> str:
        """Why a round is due, or nothing when it is not: enough sessions or
        enough days since the last one, and at least one session to look at."""
        settings = self.project.configuration
        window = self.window()
        count = len(window.sessions)
        if not count:
            return ""
        if count >= int(settings.get("reflect.sessions")):
            return f"a reflection round is due ({count} sessions since the last)"
        days = self.days(window)
        if days >= float(settings.get("reflect.days")):
            return f"a reflection round is due ({count} sessions over {days:.0f} days)"
        return ""

    def days(self, window: Window) -> float:
        since = parse_moment(window.since) or (
            parse_moment(window.sessions[0]["started"]) if window.sessions else None
        )
        return (datetime.now(UTC) - since).total_seconds() / 86400 if since else 0

    # --- a round ----------------------------------------------------------------

    def start(self) -> dict[str, Any]:
        """Start a round — or pick up the one started and not finished — and
        write what its three parts read."""
        Sessions(self.project).catch_up()
        name = self.rounds.current() or self.rounds.new_name()
        scratch = self.rounds.scratch / name
        scratch.mkdir(parents=True, exist_ok=True)
        window = self.window()
        last = self.rounds.last()
        metrics = self.metrics(window)
        write_json(
            scratch / "round.json",
            {"round": name, "since": window.since, "started": now(), "metrics": metrics},
        )
        material = {
            "process": Material(self.project, window, last).render(),
            "knowledge": Knowledge(self.project, window).render(),
            "nock": Evidence(self.project, metrics, self.rounds.all()).render(),
        }
        for part, text in material.items():
            (scratch / f"{part}.md").write_text(text)
        (self.rounds.directory / name).mkdir(parents=True, exist_ok=True)
        root = self.project.here
        return {
            "round": name,
            "since": window.since,
            # On the main checkout, wherever the round runs.
            "material": {part: str(scratch / f"{part}.md") for part in material},
            "write": [
                str((self.rounds.directory / name / file).relative_to(root))
                for file in (REPORT, SHARE)
            ],
        }

    def finish(self, record: Record) -> dict[str, Any]:
        """Check the round and commit it: its report and summary written,
        nock's checks passing, the record kept with the numbers it started from."""
        name = self.rounds.current()
        if name is None:
            raise PreconditionError("no round is under way — `.nock/nock reflect start` starts one")
        validate(record, schema())
        directory = self.rounds.directory / name
        missing = [
            file
            for file in (REPORT, SHARE)
            if not (directory / file).is_file() or not (directory / file).read_text().strip()
        ]
        if missing:
            raise PreconditionError(f"write {' and '.join(missing)} in {directory} first")
        problems = Checks(self.project).run(ROUND_CHECKS).problems()
        if problems:
            raise Failed("the round does not pass nock's checks yet", problems)
        started = read_json(self.rounds.scratch / name / "round.json")
        write_json(
            directory / "record.json",
            {
                **record,
                "round": name,
                "since": started["since"],
                "started": started["started"],
                "finished": now(),
                "metrics": started["metrics"],
                "snapshot": self.snapshot(started["since"]),
                "shared": None,
            },
        )
        self.commit(f"Reflection round {name}: {record['summary']}")
        return {"round": name, "share": str((directory / SHARE).relative_to(self.project.here))}

    def commit(self, message: str) -> None:
        """Commit `.nock/`, and the main checkout's decisions when the round ran
        in a worktree; nothing else in either."""
        places = [(self.project.here, ".nock")]
        if self.project.root != self.project.here:
            places.append((self.project.root, ".nock/decisions"))
        for root, path in places:
            git = Git(root)
            git("add", "--all", "--", path)
            if git("diff", "--cached", "--name-only", "--", path):
                git("commit", "--quiet", "--no-verify", "--only", "-m", message, "--", path)

    def record_shared(self, name: str, shared: dict[str, Any]) -> None:
        path = self.rounds.directory / name / "record.json"
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
        identities = [row["id"] for row in window.sessions]
        marks = ",".join("?" for _ in identities) or "''"
        events = self.project.store.rows(
            f"SELECT failed FROM events WHERE session IN ({marks})", tuple(identities)
        )
        calls = self.project.store.rows("SELECT exit_code FROM calls WHERE started > ?", (since,))
        codes = Counter(row["exit_code"] for row in calls)
        decisions = Decisions(self.project)
        every = decisions.all()
        recorded = [d for d in every if d["recorded"]["moment"] > since]
        reviewed = [d for d in every if d["reviewed"] and d["reviewed"]["moment"] > since]
        tools = [row for row in tool_rows(self.project, since) if row["source"] != "nock"]
        try:
            commits = int(
                self.project.git("rev-list", "--count", f"--since={since or '1970-01-01'}", "HEAD")
            )
        except GitError:
            commits = 0
        cited = (
            len(set(re.findall(r"\[D(\d+)\]", decisions.map.read_text())))
            if decisions.map.is_file()
            else 0
        )
        return {
            "days": round(self.days(window), 1),
            "sessions": len(window.sessions),
            "requests": sum(row["prompts"] or 0 for row in window.sessions),
            "interrupts": sum(row["interrupts"] or 0 for row in window.sessions),
            "compactions": sum(row["compactions"] or 0 for row in window.sessions),
            "tool_calls": len(events),
            "failed_tool_calls": sum(row["failed"] or 0 for row in events),
            "tokens": sum(
                (row["input_tokens"] or 0)
                + (row["output_tokens"] or 0)
                + (row["cache_read_tokens"] or 0)
                + (row["cache_write_tokens"] or 0)
                for row in window.sessions
            ),
            "cost": round(sum(row["cost"] or 0 for row in window.sessions), 2),
            "commits": commits,
            "nock_calls": len(calls),
            "nock_said_no": codes.get(1, 0),
            "nock_called_wrong": sum(n for code, n in codes.items() if code and 40 <= code < 50),
            "nock_broke": sum(n for code, n in codes.items() if code and code >= 50),
            "decisions_recorded": len(recorded),
            "decisions_todo": sum(1 for d in recorded if d["status"] == "todo"),
            "decisions_question": sum(1 for d in recorded if d["status"] == "question"),
            "decisions_reviewed": len(reviewed),
            "decisions_accepted": sum(1 for d in reviewed if d["review"] == "accepted"),
            "decisions_rejected": sum(1 for d in reviewed if d["review"] == "rejected"),
            "decisions_unreviewed": sum(
                1 for d in every if live(d) and d["review"] == "unreviewed"
            ),
            "tools": len(tools),
            "tools_used": sum(1 for row in tools if row["calls"]),
            "tool_calls_to_project_tools": sum(row["calls"] for row in tools),
            "map_lines": len(decisions.map.read_text().splitlines())
            if decisions.map.is_file()
            else 0,
            "map_citations": cited,
        }


def tool_rows(project: Project, since: str | None) -> list[dict[str, Any]]:
    """Per command over the window: calls, failures by kind, sessions, duration,
    how much it printed, how often it was capped or cached."""
    rows = project.store.rows("SELECT * FROM calls WHERE started > ? ORDER BY id", (since or "",))
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
        result.append(
            {
                "tool": path,
                "source": tool.source,
                "pinned": tool.pinned,
                "calls": len(calls),
                "sessions": len({row["session"] for row in calls if row["session"]}),
                "failures": sum(count for code, count in codes.items() if code not in (0, None)),
                "said_no": codes.get(1, 0),
                "usage_errors": sum(
                    count for code, count in codes.items() if code and 40 <= code < 50
                ),
                "machine_errors": sum(
                    count for code, count in codes.items() if code and code >= 50
                ),
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
        identities = [row["id"] for row in window.sessions]
        marks = ",".join("?" for _ in identities) or "''"
        self.events = project.store.rows(
            f"SELECT * FROM events WHERE session IN ({marks}) ORDER BY session, moment",
            tuple(identities),
        )
        self.prompts = project.store.rows(
            f"SELECT * FROM prompts WHERE session IN ({marks}) ORDER BY moment", tuple(identities)
        )
        self.calls = project.store.rows(
            "SELECT * FROM calls WHERE started > ? ORDER BY id", (self.since,)
        )

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
        tokens = sum(
            (row["input_tokens"] or 0)
            + (row["output_tokens"] or 0)
            + (row["cache_read_tokens"] or 0)
            + (row["cache_write_tokens"] or 0)
            for row in sessions
        )
        cost = sum(row["cost"] or 0 for row in sessions)
        since = (
            f"since the last round ({self.since})"
            if self.window.since
            else "since nock was installed"
        )
        return (
            f"# Overview\n\n{len(sessions)} sessions {since}: {len(self.prompts)} requests from the human, "
            f"{len(self.events)} tool calls, {len(self.calls)} calls to nock, "
            f"{tokens / 1e6:.1f}M tokens" + (f", ${cost:.2f}" if cost else "") + "."
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
            "Per command over the window (nock's own only when used). said_no is exit 1, "
            "usage_errors 40s (called wrong), machine_errors 50s (broke); capped is how often it "
            "printed less than it had.",
            "",
            "tool,source,calls,sessions,said_no,usage_errors,machine_errors,median_seconds,max_seconds,mean_bytes,capped,cached,last_used",
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
                        row["said_no"],
                        row["usage_errors"],
                        row["machine_errors"],
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
            code = row["exit_code"] or 0
            if row["tool"] not in known:
                unknown[row["tool"]] += 1
            elif 40 <= code < 50 and row["error"]:
                wrong[(row["tool"], row["error"][:160])] += 1
            elif code >= 50 and row["error"]:
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
            "started,id,title,prompts,tool_calls,failed,interrupts,compactions,tokens,cost",
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
                        f"${row['cost']:.2f}" if row["cost"] else "-",
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
    """What the round's map part reads: the decisions recorded, changed or
    reviewed since the last round in full, every standing one in a line, the
    tags in use, and the map as it stands."""

    def __init__(self, project: Project, window: Window) -> None:
        self.decisions = Decisions(project)
        self.since = window.since or ""

    def render(self) -> str:
        every = self.decisions.all()
        recent = [decision for decision in every if decision["updated"] > self.since]
        lines = [
            f"# Recorded, changed or reviewed since the last round ({self.since or 'never'})",
            "",
        ]
        if not recent:
            lines.append("Nothing.")
        for decision in recent:
            lines += [f"## [D{decision['number']}] {decision['title']}", "", "```json"]
            lines += [json.dumps(decision, indent=2, ensure_ascii=False), "```", ""]
        lines += ["", "# Every standing decision", ""]
        lines += [
            f"- [D{decision['number']}] {decision['status']}, {decision['review']}: {decision['title']}"
            + (f" — touches {', '.join(decision['touches'])}" if decision["touches"] else "")
            for decision in every
            if live(decision)
        ] or ["None yet."]
        tags = self.decisions.tags()
        lines += [
            "",
            "# Tags in use",
            "",
            ", ".join(f"{tag} ({count})" for tag, count in tags.items()),
        ]
        stale = self.decisions.stale()
        if stale:
            lines += ["", "# Done decisions whose files are gone", ""]
            lines += [
                f"- [D{decision['number']}] {decision['title']}: {', '.join(patterns)}"
                for decision, patterns in stale
            ]
        problems = self.decisions.citation_problems()
        current = self.decisions.map.read_text() if self.decisions.map.is_file() else ""
        lines += ["", "# The map as it stands", "", current.strip() or "There is no map yet."]
        if problems:
            lines += ["", "Its citations that no longer hold:"]
            lines += [f"- line {problem.line}: {problem.message}" for problem in problems]
        return "\n".join(lines) + "\n"


class Evidence:
    """What the round's nock part reads: this window's numbers beside every
    earlier round's — the first is the baseline."""

    def __init__(
        self, project: Project, metrics: dict[str, Any], rounds: list[dict[str, Any]]
    ) -> None:
        self.project = project
        self.metrics = metrics
        self.rounds = [record for record in rounds if record.get("metrics")]

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
        return "\n".join(lines) + "\n"


METRICS_HELP = """\
What they count: sessions the human started in the window (`days` long) and
what they asked (`requests`), interrupted and compacted; every tool call
they made and how many failed; tokens and dollars; commits. `nock_*`: calls
to nock, and how many said no (exit 1), were called wrong (40s) or broke
(50s). `decisions_*`: recorded in the window (and how many as todos and
questions),
reviewed by the owner in it (accepted, rejected), and every standing one
still unreviewed. `tools`: the project's own commands, how many were used,
and how often. `map_*`: the map's length and the decisions it cites."""
