"""What a Logika project's rounds read (the `logika.rules`, `logika.analytics`
and `logika.instrument` protocols in `nock.rounds`). In a Logika project — a
`logika.json` ledger, and the `logika` CLI on PATH — the owner runs the first
two with the `/logika` skill: **rules**, a subagent per directory, gives each
event `logika map` lists as unread its rule over its values, or the reason it
gets none, and each verdict-only event the values it decided on;
**analytics** declares what is worth measuring (identities, dimensions,
funnels, milestones, views). **instrument** is never adopted: an agent runs
it by name for one area, instrumenting it and writing its rules until the
map leaves each item closed or with its reason. `Material`, `Analytics` and
`Instrument` are what each reads; `Logika`, the ledger and when a round is
worth offering; `Map`, what `logika map` leaves open."""

from __future__ import annotations

import json
import posixpath
import shutil
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING, Any

from nock.errors import Failed, PreconditionError
from nock.git import Git, GitError
from nock.topics import Topics
from nock.utils import read_json

if TYPE_CHECKING:
    from nock.project import Project

LEDGER = "logika.json"
PROGRAM = "logika"
# What a round decides, and suggests, goes in this topic so the next round finds it.
TOPIC = "logika"
# The round's parts: each a brief in `nock docs` (`reflection.logika.PART`), and a material file.
SECTION_ROWS = 40
# What `logika map` leaves open, by kind: functions that log nothing, events whose
# params are all verdicts, events no rule reads.
OPEN = ("silent", "verdicts", "unread")
# The change kind an instrument round leaves an open item with, its target the item.
REASON = "reason"
# `logika map` reads the tree offline: past this it is stuck, not slow.
MAP_SECONDS = 300


def flattened(events: Any, prefix: str = "") -> list[tuple[str, dict[str, Any]]]:
    """Every declared event by its full path (`checkout.captured`), parents first."""
    found: list[tuple[str, dict[str, Any]]] = []
    for event in events if isinstance(events, list) else []:
        if isinstance(event, dict) and isinstance(event.get("name"), str):
            path = f"{prefix}{event['name']}"
            found.append((path, event))
            found += flattened(event.get("children"), f"{path}.")
    return found


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
        params = {
            name: param
            for name, param in (ledger.get("params") or {}).items()
            if isinstance(param, dict)
        }
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
            "identities": sum(1 for param in params.values() if param.get("identity")),
            "dimensions": sum(1 for param in params.values() if param.get("dimension")),
            "funnels": len(ledger.get("funnels") or []),
            "milestones": len(ledger.get("milestones") or []),
            "views": len(ledger.get("views") or []),
            "components": len(components),
            "instrumented": sum(
                1 for item in components if isinstance(item, dict) and item.get("instrumented")
            ),
        }


class Logika:
    """A Logika project as its rounds read it: the ledger, the commits that
    changed it, and when a round is worth offering."""

    def __init__(self, project: Project) -> None:
        self.project = project
        self.ledger = Ledger(project)

    def unavailable(self) -> str:
        return self.ledger.unavailable()

    def changes(self, since: str | None) -> list[str]:
        """The commits that changed the ledger since `since`, newest first."""
        try:
            output = Git(self.project.here)(
                "log",
                "--format=%ad %s",
                "--date=short",
                *([f"--since={since}"] if since else []),
                f"--max-count={SECTION_ROWS}",
                "HEAD",
                "--",
                LEDGER,
            )
        except GitError:
            return []
        return output.splitlines()

    def problems(self) -> list[str]:
        """The ledger parses."""
        try:
            self.ledger.read()
        except Failed as error:
            return [f"{error}: {error.value}" if error.value else str(error)]
        return []


class Material:
    """What the rules part reads, computed: what the ledger already says must
    hold, per component and per event; what changed since the last round; and
    the decisions and suggestions earlier rounds left."""

    def __init__(self, logika: Logika, ledger: dict[str, Any], last: dict[str, Any] | None) -> None:
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
            self.decided(),
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
                    *([f"--since={self.since}"] if self.since else []),
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
            "a rule's trigger or follow-up (`logika map` says which events no rule reads).",
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

    def decided(self) -> str:
        """What earlier rounds decided and suggested (the `logika` topic), and where each stands."""
        topics = Topics(self.logika.project)
        found = topics.items(TOPIC) if TOPIC in topics.names() else []
        if not found:
            return f"# Decisions and proposals\n\nNothing in the `{TOPIC}` topic yet."
        lines = [
            "# Decisions and proposals",
            "",
            f"The items of the `{TOPIC}` topic, the open proposals first. A decision holds;"
            " an open proposal waits for the owner; an accepted one is to be carried out; a"
            " rejected one is dropped: don't bring it back.",
            "",
        ]
        for item in sorted(
            found, key=lambda item: (item["status"] != "open", item["created"]["moment"])
        ):
            lines.append(f"- [{item['ref']}] {item['status']}: {item['title']} — {item['means']}")
        return "\n".join(lines)


class Analytics(Material):
    """What the analytics part reads: what the ledger already measures — the
    params marked as identities or dimensions, the numeric ones, the funnels,
    milestones and views — beside the components, the history, the last
    round and the earlier rounds' decisions."""

    def render(self) -> str:
        sections = [
            self.measured(),
            self.params(),
            self.declared(),
            self.components(),
            self.direction(),
            self.previous(),
            self.decided(),
        ]
        return "\n\n".join(section for section in sections if section) + "\n"

    def measured(self) -> str:
        counts = self.logika.ledger.counts(self.ledger)
        return (
            f"# What the ledger measures\n\n`{LEDGER}`, ledger `{self.ledger.get('ledger', '?')}`: "
            f"{counts['events']} events, {counts['params']} params ({counts['identities']} "
            f"identities, {counts['dimensions']} dimensions), {counts['funnels']} funnels, "
            f"{counts['milestones']} milestones, {counts['views']} views. Every declared event "
            "and numeric param is measured already; identities, dimensions, funnels, "
            "milestones and views are declared."
        )

    def params(self) -> str:
        params = {
            name: param
            for name, param in (self.ledger.get("params") or {}).items()
            if isinstance(param, dict)
        }
        if not params:
            return "# Params\n\nThe ledger declares none yet."
        carried: dict[str, list[str]] = {}
        for path, event in flattened(self.ledger.get("events")):
            for param in event.get("params") or []:
                carried.setdefault(str(param), []).append(path)
        lines = [
            "# Params",
            "",
            "Each param, its flags and the events that carry it: an identity is someone or "
            "something worth following (actives, retention, funnels); a dimension a small "
            "stable set worth breaking down by, never an id.",
            "",
            "param,type,identity,dimension,pii,events",
        ]
        for name, param in params.items():
            lines.append(
                ",".join(
                    [
                        name,
                        str(param.get("type", "?")),
                        "yes" if param.get("identity") else "-",
                        "yes" if param.get("dimension") else "-",
                        "yes" if param.get("pii") else "-",
                        " ".join(carried.get(name, [])) or "-",
                    ]
                )
            )
        return "\n".join(lines)

    def declared(self) -> str:
        lines = ["# Funnels, milestones and views", ""]
        for funnel in self.ledger.get("funnels") or []:
            if isinstance(funnel, dict):
                steps = " → ".join(map(str, funnel.get("steps") or []))
                lines.append(
                    f"- funnel `{funnel.get('name')}` within {funnel.get('within')}: {steps}"
                )
        for milestone in self.ledger.get("milestones") or []:
            if isinstance(milestone, dict):
                lines.append(
                    f"- milestone `{milestone.get('name')}`: {milestone.get('from')} → {milestone.get('to')}"
                )
        for view in self.ledger.get("views") or []:
            if isinstance(view, dict):
                lines.append(f"- view `{view.get('name')}`: {len(view.get('panels') or [])} panels")
        if len(lines) == 2:
            lines.append("None yet.")
        return "\n".join(lines)


class Map:
    """`logika map --json` at the repository's root: what logs nothing, what
    logs only its verdicts and what no rule reads, as the open items an
    instrument round closes."""

    def __init__(self, project: Project) -> None:
        self.project = project

    def read(self) -> dict[str, Any]:
        """The map, or `Failed` saying why there is none."""
        command = f"`{PROGRAM} map --json`"
        try:
            done = subprocess.run(
                [PROGRAM, "map", "--json"],
                cwd=self.project.here,
                capture_output=True,
                text=True,
                timeout=MAP_SECONDS,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise Failed(f"{command} did not run: {error}") from error
        if done.returncode:
            said = (done.stderr or done.stdout).strip().splitlines()
            raise Failed(f"{command} exited {done.returncode}" + (f": {said[-1]}" if said else ""))
        try:
            found = json.loads(done.stdout)
        except json.JSONDecodeError as error:
            raise Failed(f"{command} printed no JSON: {error}") from error
        if not isinstance(found, dict):
            raise Failed(f"{command} printed no JSON object")
        return found

    def counts(self) -> dict[str, int] | None:
        """The open items by kind, or nothing when the map can't be read."""
        try:
            counts = self.read().get("counts")
        except Failed:
            return None
        if not isinstance(counts, dict):
            return None
        return {kind: int(counts.get(kind) or 0) for kind in OPEN}


def items(found: dict[str, Any]) -> list[str]:
    """Each open item as a round's submission names it: `silent <file>
    <function>`, the file from the repository root; `verdicts <event>`;
    `unread <event>`."""
    base = str(found.get("path") or ".")
    opened = found.get("open")
    if not isinstance(opened, dict):
        return []
    listed: list[str] = []
    for entry in opened.get("silent") or []:
        if isinstance(entry, dict):
            file = posixpath.normpath(posixpath.join(base, str(entry.get("file"))))
            listed += [f"silent {file} {function}" for function in entry.get("functions") or []]
    for kind in OPEN[1:]:
        listed += [f"{kind} {event}" for event in opened.get(kind) or []]
    return listed


class Instrument:
    """What an instrument round reads: the repository's map when it starts —
    its counts, its directories and each open item — and the reasons earlier
    instrument rounds left items open with (changes of kind `reason`, by
    their target, the latest standing)."""

    def __init__(self, mapping: Map, rounds: list[dict[str, Any]]) -> None:
        self.mapping = mapping
        self.reasons: dict[str, str] = {}
        for record in rounds:
            for change in record.get("changes") or []:
                if change.get("kind") == REASON:
                    self.reasons[str(change.get("target"))] = str(change.get("why"))

    def render(self) -> str:
        try:
            found = self.mapping.read()
        except Failed as error:
            sections = [f"# The map\n\n{error}: run it yourself.", self.earlier()]
        else:
            sections = [self.overview(found), self.directories(found), self.open(found)]
        return "\n\n".join(section for section in sections if section) + "\n"

    def overview(self, found: dict[str, Any]) -> str:
        counts = found.get("counts")
        counts = counts if isinstance(counts, dict) else {}
        left = ", ".join(f"{int(counts.get(kind) or 0)} {kind}" for kind in OPEN)
        return (
            f"# The map\n\n`{PROGRAM} map --json` at the repository's root when the round "
            f"started: {found.get('mode', '?')}, {found.get('files', '?')} files, "
            f"{found.get('events', '?')} events; open: {left}."
        )

    def directories(self, found: dict[str, Any]) -> str:
        listed = [entry for entry in found.get("directories") or [] if isinstance(entry, dict)]
        if not listed:
            return ""
        return "\n".join(
            [
                "# Directories",
                "",
                f"Each one's events and open items; `{PROGRAM} map <path>` maps one alone.",
                "",
            ]
            + [
                f"- {entry.get('path')}: {entry.get('events', 0)} events, "
                f"{entry.get('open', 0)} open"
                for entry in listed
            ]
        )

    def open(self, found: dict[str, Any]) -> str:
        listed = items(found)
        if not listed:
            return "# Open items\n\nNone: the map leaves nothing open."
        return "\n".join(
            [
                "# Open items",
                "",
                "Each as a submission's target names it. `left:` is the reason an earlier "
                "round gave: keep it, or close the item.",
                "",
            ]
            + [
                f"- {item}" + (f" — left: {self.reasons[item]}" if item in self.reasons else "")
                for item in listed
            ]
        )

    def earlier(self) -> str:
        if not self.reasons:
            return "# Reasons given\n\nNo earlier instrument round left an item with a reason."
        return "\n".join(
            ["# Reasons given", "", "What earlier instrument rounds left open, and why:", ""]
            + [f"- {item} — left: {reason}" for item, reason in self.reasons.items()]
        )
