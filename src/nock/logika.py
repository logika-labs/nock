"""The `logika` reflection topic. In a Logika project — a `logika.json` ledger,
and the `logika` CLI on PATH — the owner runs a round with the
`/nock-reflect-logika` skill: it turns the instrumented code and the data it
captures into the ledger's rules (validations, paths, timeouts, rules,
invariants), each shown silent on real captures and firing on a replay, asks
the owner what only they know, and suggests the instrumentation a rule would
need. `nock reflect start --topic logika` writes what it reads, and
`nock reflect finish --topic logika` records it and commits `.nock/` and
`logika.json`. Its rounds are kept apart from nock's own, so neither moves
the other's window."""

from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from nock.decisions import Decisions, Status
from nock.errors import Failed, PreconditionError
from nock.git import Git, GitError
from nock.reflect import REPORT, Record, Rounds, Topic, commit, schema
from nock.schema import validate
from nock.utils import now, parse_moment, read_json, write_json

if TYPE_CHECKING:
    from nock.project import Project

LEDGER = "logika.json"
PROGRAM = "logika"
SKILL = "nock-reflect-logika"
# What a round asks about, and suggests, is tagged so the next round finds it.
TAG = "logika"
SECTION_ROWS = 40


def flattened(events: Any, prefix: str = "") -> list[tuple[str, dict[str, Any]]]:
    """Every declared event by its full path (`checkout.captured`), parents first."""
    found: list[tuple[str, dict[str, Any]]] = []
    for event in events if isinstance(events, list) else []:
        if isinstance(event, dict) and isinstance(event.get("name"), str):
            path = f"{prefix}{event['name']}"
            found.append((path, event))
            found += flattened(event.get("children"), f"{path}.")
    return found


def since_option(since: str | None) -> list[str]:
    """`--since` for git, as a raw timestamp: git reads an ISO moment's `Z` as local time."""
    moment = parse_moment(since)
    return [f"--since=@{int(moment.timestamp())}"] if moment else []


def event_of(reference: Any) -> str:
    """The event an `event.param` reference names: `checkout.captured.order_id` → `checkout.captured`."""
    return str(reference).rsplit(".", 1)[0]


class Ledger:
    """The project's `logika.json`, as a round reads it."""

    def __init__(self, project: Project) -> None:
        self.project = project

    @property
    def path(self) -> Path:
        return self.project.here / LEDGER

    def unavailable(self) -> str:
        """Why a logika round cannot run here, or nothing when it can."""
        if not self.path.is_file():
            return f"not a Logika project: there is no {LEDGER} at {self.project.here}"
        if shutil.which(PROGRAM) is None:
            return f"`{PROGRAM}` is not on PATH: install the Logika CLI first"
        return ""

    def read(self) -> dict[str, Any]:
        try:
            ledger = read_json(self.path)
        except PreconditionError as error:
            raise Failed(f"{LEDGER} does not parse", str(error)) from error
        if not isinstance(ledger, dict):
            raise Failed(f"{LEDGER} is not a JSON object")
        return ledger

    def counts(self, ledger: dict[str, Any]) -> dict[str, int]:
        """What the ledger says must hold, in numbers: the next round compares."""
        events = [event for _, event in flattened(ledger.get("events"))]
        components = (ledger.get("map") or {}).get("components") or []
        return {
            "params": len(ledger.get("params") or {}),
            "events": len(events),
            "spans": sum(1 for event in events if "span" in event),
            "validated": sum(1 for event in events if event.get("validate")),
            "with_paths": sum(1 for event in events if (event.get("span") or {}).get("paths")),
            "with_timeout": sum(1 for event in events if (event.get("span") or {}).get("timeout")),
            "rules": len(ledger.get("rules") or []),
            "invariants": len(ledger.get("invariants") or []),
            "components": len(components),
            "instrumented": sum(
                1 for item in components if isinstance(item, dict) and item.get("instrumented")
            ),
        }


class LogikaRound:
    def __init__(self, project: Project) -> None:
        self.project = project
        self.ledger = Ledger(project)
        self.rounds = Rounds(project, Topic.LOGIKA)

    # --- when -------------------------------------------------------------------------

    def due(self) -> str:
        """Why a logika round is worth offering, or nothing: never run while the
        ledger declares events, or `reflect.logika.days` since the last one with
        the ledger changed since. It is only ever offered, never run."""
        if self.ledger.unavailable():
            return ""
        try:
            ledger = self.ledger.read()
        except Failed:
            return ""
        last = self.rounds.last()
        if last is None:
            events = self.ledger.counts(ledger)["events"]
            return (
                f"no logika round has run, and the ledger declares {events} events"
                if events
                else ""
            )
        since = parse_moment(last.get("finished"))
        if since is None:
            return ""
        days = (datetime.now(UTC) - since).total_seconds() / 86400
        if days < float(self.project.configuration.get("reflect.logika.days", 30)):
            return ""
        changes = self.changes(last.get("finished"))
        return (
            f"a logika round is due ({len(changes)} commits changed {LEDGER} in the "
            f"{days:.0f} days since the last)"
            if changes
            else ""
        )

    def standing(self) -> dict[str, Any] | None:
        """For `nock status` and the session start; nothing outside a Logika project."""
        if self.ledger.unavailable():
            return None
        last = self.rounds.last()
        return {
            "due": self.due() or None,
            "last": last.get("finished") if last else None,
            "skill": (self.project.here / ".claude" / "skills" / SKILL / "SKILL.md").is_file(),
        }

    def changes(self, since: str | None) -> list[str]:
        """The commits that changed the ledger since `since`, newest first."""
        try:
            output = Git(self.project.here)(
                "log",
                "--format=%ad %s",
                "--date=short",
                *since_option(since),
                f"--max-count={SECTION_ROWS}",
                "HEAD",
                "--",
                LEDGER,
            )
        except GitError:
            return []
        return output.splitlines()

    # --- a round ------------------------------------------------------------------------

    def start(self) -> dict[str, Any]:
        """Start a logika round, or pick up the one under way, and write what it reads."""
        problem = self.ledger.unavailable()
        if problem:
            raise PreconditionError(problem)
        ledger = self.ledger.read()
        name = self.rounds.current() or self.rounds.new_name()
        scratch = self.rounds.scratch / name
        scratch.mkdir(parents=True, exist_ok=True)
        last = self.rounds.last()
        since = last.get("finished") if last else None
        write_json(
            scratch / "round.json",
            {
                "round": name,
                "since": since,
                "started": now(),
                "ledger": self.ledger.counts(ledger),
            },
        )
        material = scratch / f"{TAG}.md"
        material.write_text(Material(self, ledger, last).render())
        (self.rounds.directory / name).mkdir(parents=True, exist_ok=True)
        return {
            "round": name,
            "since": since,
            "material": {TAG: str(material)},
            "write": [str((self.rounds.directory / name / REPORT).relative_to(self.project.here))],
        }

    def finish(self, record: Record) -> dict[str, Any]:
        """Check the round and commit it: the report written, the ledger still
        parsing, the record kept with the ledger's numbers before and after."""
        name = self.rounds.current()
        if name is None:
            raise PreconditionError(
                "no logika round is under way — `.nock/nock reflect start --topic logika` starts one"
            )
        validate(record, schema())
        report = self.rounds.directory / name / REPORT
        if not report.is_file() or not report.read_text().strip():
            raise PreconditionError(f"write {REPORT} in {report.parent} first")
        ledger = self.ledger.read()
        started = read_json(self.rounds.scratch / name / "round.json")
        write_json(
            self.rounds.directory / name / "record.json",
            {
                **record,
                "round": name,
                "since": started["since"],
                "started": started["started"],
                "finished": now(),
                "ledger_before": started["ledger"],
                "ledger": self.ledger.counts(ledger),
            },
        )
        commit(self.project, f"Logika round {name}: {record['summary']}", (LEDGER,))
        return {"round": name, "report": str(report.relative_to(self.project.here))}


class Material:
    """What a logika round reads, computed: what the ledger already says must
    hold, per component and per event; what changed since the last round; and
    the questions and suggestions earlier rounds left."""

    def __init__(
        self, logika: LogikaRound, ledger: dict[str, Any], last: dict[str, Any] | None
    ) -> None:
        self.logika = logika
        self.ledger = ledger
        self.last = last
        self.since = last.get("finished") if last else None

    def render(self) -> str:
        sections = [
            self.overview(),
            self.components(),
            self.events(),
            self.relations(),
            self.direction(),
            self.previous(),
            self.questions(),
        ]
        return "\n\n".join(section for section in sections if section) + "\n"

    def overview(self) -> str:
        counts = self.logika.ledger.counts(self.ledger)
        return (
            f"# The ledger\n\n`{LEDGER}`, ledger `{self.ledger.get('ledger', '?')}`: "
            f"{counts['params']} params, {counts['events']} events ({counts['spans']} spans; "
            f"{counts['validated']} with `validate`, {counts['with_paths']} with paths, "
            f"{counts['with_timeout']} with a timeout), {counts['rules']} rules, "
            f"{counts['invariants']} invariants; {counts['instrumented']} of "
            f"{counts['components']} components instrumented."
        )

    def components(self) -> str:
        components = (self.ledger.get("map") or {}).get("components") or []
        if not components:
            return "# Components\n\nThe map names none: the whole repository is one component."
        lines = [
            "# Components",
            "",
            "Commits since the last logika round touching each component's paths: where "
            "behaviour may have moved past the ledger.",
            "",
            "component,paths,languages,instrumented,commits_since,strategy",
        ]
        for component in components:
            if not isinstance(component, dict):
                continue
            paths = [str(path) for path in component.get("paths") or []]
            strategy = " ".join(str(component.get("strategy") or "-").split())
            lines.append(
                ",".join(
                    [
                        str(component.get("name", "?")),
                        " ".join(paths) or "-",
                        " ".join(str(language) for language in component.get("languages") or []),
                        "yes" if component.get("instrumented") else "no",
                        str(self.commits_touching(paths)),
                        json.dumps(strategy[:200] + ("…" if len(strategy) > 200 else "")),
                    ]
                )
            )
        return "\n".join(lines)

    def commits_touching(self, paths: list[str]) -> int | str:
        if not paths:
            return "-"
        try:
            return int(
                Git(self.logika.project.here)(
                    "rev-list",
                    "--count",
                    *since_option(self.since),
                    "HEAD",
                    "--",
                    *paths,
                )
            )
        except (GitError, ValueError):
            return "-"

    def events(self) -> str:
        events = flattened(self.ledger.get("events"))
        if not events:
            return "# Events\n\nThe ledger declares none yet: instrumentation comes first."
        rules = [rule for rule in self.ledger.get("rules") or [] if isinstance(rule, dict)]
        triggers = {event_of(rule.get("on")) for rule in rules}
        expected = {event_of(item) for rule in rules for item in rule.get("expect") or []}
        lines = [
            "# Events",
            "",
            "What each declared event already says must hold; `-` is nothing yet. on/expected: "
            "a rule's trigger or follow-up.",
            "",
            "event,kind,params,validate,paths,timeout,rules,anomaly",
        ]
        for path, event in events:
            span = event.get("span") if isinstance(event.get("span"), dict) else None
            role = [
                word for word, names in (("on", triggers), ("expected", expected)) if path in names
            ]
            lines.append(
                ",".join(
                    [
                        path,
                        "span" if span is not None else "leaf",
                        " ".join(str(param) for param in event.get("params") or []) or "-",
                        json.dumps(event["validate"]) if event.get("validate") else "-",
                        json.dumps(span.get("paths")) if span and span.get("paths") else "-",
                        str(span.get("timeout")) if span and span.get("timeout") else "-",
                        " ".join(role) or "-",
                        "yes" if event.get("anomaly") else "-",
                    ]
                )
            )
        return "\n".join(lines)

    def relations(self) -> str:
        rules = [rule for rule in self.ledger.get("rules") or [] if isinstance(rule, dict)]
        invariants = [
            item for item in self.ledger.get("invariants") or [] if isinstance(item, dict)
        ]
        lines = ["# Rules and invariants", ""]
        lines += [
            f"- rule: {rule.get('on')} → {' | '.join(map(str, rule.get('expect') or []))}"
            f" within {rule.get('within')}" + (f" if {rule['if']}" if rule.get("if") else "")
            for rule in rules
        ]
        lines += [
            f"- invariant `{item.get('name')}` (key {', '.join(map(str, item.get('key') or []))}): "
            f"{item.get('description')}"
            for item in invariants
        ]
        if not (rules or invariants):
            lines.append("None yet.")
        return "\n".join(lines)

    def direction(self) -> str:
        changes = self.logika.changes(self.since)
        since = f"since the last logika round ({self.since})" if self.since else "so far"
        if not changes:
            return f"# The ledger's history\n\nNo commit changed `{LEDGER}` {since}."
        return "\n".join(
            ["# The ledger's history", "", f"Commits that changed `{LEDGER}` {since}:", ""]
            + [f"- {line}" for line in changes]
        )

    def previous(self) -> str:
        if not self.last:
            return "# The last logika round\n\nThis is the first logika round."
        lines = [
            f"# The last logika round ({self.last['round']})",
            "",
            str(self.last["summary"]),
            "",
        ]
        for change in self.last.get("changes", []):
            lines.append(
                f"- {change.get('kind')} {change.get('target')}: expected {change.get('expect')}"
                + (f" (tested: {change['tested']})" if change.get("tested") else "")
            )
        if self.last.get("notes"):
            lines += ["", f"Notes it left: {self.last['notes']}"]
        return "\n".join(lines)

    def questions(self) -> str:
        """What earlier rounds asked and suggested (tagged `logika`), and where each stands."""
        found = Decisions(self.logika.project).matching({"tag": TAG})
        if not found:
            return f"# Questions and suggestions\n\nNone tagged `{TAG}` yet."
        lines = [
            "# Questions and suggestions",
            "",
            f"Decisions tagged `{TAG}`. A question's title is the answer proposed: accepted is "
            "yes, rejected is no with the note saying what holds. An accepted todo is on the "
            "owner's backlog.",
            "",
        ]
        order = {Status.QUESTION: 0, Status.TODO: 1, Status.DONE: 2}
        for decision in sorted(
            found, key=lambda item: (order[Status(item["status"])], item["number"])
        ):
            note = f" — the owner: {decision['note']}" if decision["note"] else ""
            lines.append(
                f"- [D{decision['number']}] {decision['status']}, {decision['review']}: "
                f"{decision['title']}{note}"
            )
        return "\n".join(lines)
