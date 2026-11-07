"""The `logika` kind of reflection round. In a Logika project — a
`logika.json` ledger, and the `logika` CLI on PATH — the owner runs a round
with the `/nock-reflect-logika` skill, in two parts: **rules**, a subagent
per directory, gives each event's `risks` (a `concern.risk` key mapped to its
evidence params, or to why it doesn't apply) its rule over that evidence, or
the reason it gets none, from what `logika map` shows; **analytics** declares
what is worth measuring (identities, dimensions, funnels, milestones,
views). The session decides them itself, asks the owner only general
directions and genuine ambiguities, adds the instrumentation they need, and
ends with one `logika replay` noise check. `nock reflect logika` writes what
it reads, and `nock reflect logika finish` requires the ledger to parse,
records the round and commits `.nock/` and `logika.json`.
Its rounds are kept apart from nock's own, so neither moves the other's
window."""

from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from nock.errors import Failed, PreconditionError
from nock.git import Git, GitError
from nock.reflect import Record, Round
from nock.topics import Author, Topics, Verdict
from nock.utils import parse_moment, read_json

if TYPE_CHECKING:
    from nock.project import Project

LEDGER = "logika.json"
PROGRAM = "logika"
SKILL = "nock-reflect-logika"
# What a round decides, and suggests, goes in this topic so the next round finds it.
TOPIC = "logika"
# The round's parts: each a brief in `nock docs` (`reflection.logika.PART`), and a material file.
PARTS = ("rules", "analytics")
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


def event_of(reference: Any) -> str:
    """The event an `event.param` reference names: `checkout.captured.order_id` → `checkout.captured`."""
    return str(reference).rsplit(".", 1)[0]


def risks(declared: Any) -> str:
    """An event's risks, in a cell: `webhooks.retry by attempt will_retry; webhooks.once ruled out`."""
    if not isinstance(declared, dict) or not declared:
        return "-"
    said = [
        f"{key} by {' '.join(map(str, evidence))}"
        if isinstance(evidence, list)
        else f"{key} ruled out"
        for key, evidence in declared.items()
    ]
    return json.dumps("; ".join(said))


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


class LogikaRound(Round):
    """The ledger's rules, from the instrumented code and its captures, with the owner."""

    kind = "logika"
    title = "logika round"
    skill = SKILL
    also = (LEDGER,)

    def __init__(self, project: Project) -> None:
        super().__init__(project)
        self.ledger = Ledger(project)

    @classmethod
    def wanted(cls, root: Path) -> bool:
        return (root / LEDGER).is_file()

    def unavailable(self) -> str:
        return self.ledger.unavailable()

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

    # --- a round ------------------------------------------------------------------------

    def begin(self, name: str, scratch: Path) -> dict[str, Any]:
        """What the ledger already says, the commits since, what earlier rounds left."""
        ledger = self.ledger.read()
        last = self.rounds.last()
        written = {
            "rules": Material(self, ledger, last).render(),
            "analytics": Analytics(self, ledger, last).render(),
        }
        for part, text in written.items():
            (scratch / f"{part}.md").write_text(text)
        return {
            "since": last.get("finished") if last else None,
            "material": {part: str(scratch / f"{part}.md") for part in PARTS},
            "kept": {"ledger": self.ledger.counts(ledger)},
        }

    def problems(self, record: Record | None) -> list[str]:
        """The ledger parses."""
        try:
            self.ledger.read()
        except Failed as error:
            return [f"{error}: {error.value}" if error.value else str(error)]
        return []

    def kept(self, name: str, started: dict[str, Any]) -> dict[str, Any]:
        return {
            "ledger_before": started["ledger"],
            "ledger": self.ledger.counts(self.ledger.read()),
        }


class Material:
    """What the rules part reads, computed: what the ledger already says must
    hold, per component and per event; what changed since the last round; and
    the decisions and suggestions earlier rounds left."""

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
            "a rule's trigger or follow-up. risks: each `concern.risk` by its evidence params, "
            "or ruled out (`logika map` says which a rule guards).",
            "",
            "event,kind,params,validate,paths,timeout,rules,anomaly,risks",
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
                        risks(event.get("risks")),
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
            return f"# Decisions and suggestions\n\nNothing in the `{TOPIC}` topic yet."
        lines = [
            "# Decisions and suggestions",
            "",
            f"The items of the `{TOPIC}` topic, the open ones first. Each title is what was"
            " decided, or proposed for the owner to settle: accepted, it holds; rejected, its"
            " thread says what holds instead. An accepted todo is on the owner's backlog.",
            "",
        ]
        for item in sorted(
            found, key=lambda item: (item["verdict"] != Verdict.OPEN, item["created"]["moment"])
        ):
            said = [entry["text"] for entry in item["thread"] if entry["author"] == Author.OWNER]
            note = f" — the owner: {said[-1]}" if said else ""
            decision = topics.decision(item, item["versions"][-1])
            status = f"{decision['status']}, " if decision else ""
            lines.append(f"- [{item['ref']}] {status}{item['verdict']}: {item['title']}{note}")
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
