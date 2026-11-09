"""The studio's evaluation explorer: a scenario as a graph — its rules as
columns left to right, each column's jobs folded into groups by the parameter
that forks the runs (a row per value), a group splitting on demand by the
parameters that fork inside it — with each job's status read live from the
files, what a change would rerun, and the scenario's comparisons in counts.

Snakemake describes the jobs once (`GRAPH`: every job, its parameters, inputs,
the jobs before it and its cache entry), which takes as long as a dry run; the
description is kept in `.nock/local/evals/` under a fingerprint of what shapes
it (the scenario's files, the checkout's commit and changes, the checkpoints
done) and derived again in the background when that changes. Statuses come
from the results, the cache and Snakemake's own state — its lock, its
incomplete markers and the log of the run going on — so a page polls them
cheaply while a run goes. Nothing here runs a step or writes outside
`.nock/local/`. How a scenario is worded (titles, what a rule means, parameter
labels, the key numbers, highlights and declared comparisons) is the optional
`evals/NAME/studio.json`; without it, a rule means the comment above it in the
Snakefile."""

from __future__ import annotations

import ast
import base64
import hashlib
import json
import os
import re
import statistics
import subprocess
import threading
import time
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from functools import cached_property
from pathlib import Path
from typing import Any, NotRequired, TypedDict

from nock.commands import schema_of
from nock.errors import NotFoundError, PreconditionError, UsageError
from nock.evaluation import CACHE, PROFILE, RESULTS, SNAKEMAKE, Scenario, uv
from nock.schema import validate
from nock.steps import COST, ERROR, METRICS

WORDS = "studio.json"
FORMAT = 1
"""The kept description's format: one written by another is derived again."""
FINGERPRINT_EVERY = 15.0
"""Seconds between checks of whether the description still holds."""
STATUS_EVERY = 2.0
"""Seconds a reading of the statuses serves every request."""
FILE_BYTES = 200_000
"""How much of a file the page shows: its end, for a log."""
# Runs in uv's interpreter with Snakemake: loads the workflow as `--list-untracked`
# would, builds the DAG of every target rule, and prints every job instead.
GRAPH = r"""
import json, sys
from snakemake.cli import main
from snakemake import workflow
from snakemake.caching import AbstractOutputFileCache
from snakemake.caching.hash import ProvenanceHashMap


def flat(value, prefix, into):
    if isinstance(value, dict) and value:
        for key, item in value.items():
            flat(item, f"{prefix}.{key}" if prefix else str(key), into)
    elif isinstance(value, (str, int, float, bool)) or value is None:
        into[prefix] = value
    else:
        into[prefix] = json.dumps(value, default=str)[:200]


def jobs(self, *arguments, **keywords):
    # Every rule that only names what to make is a target, beside the default one.
    if not self.dag_settings.targets:
        named = {rule.name for rule in self.rules if not rule.output}
        if self.default_target is not None:
            named.add(self.default_target)
        self.dag_settings.targets = named
    self._prepare_dag(forceall=False, ignore_incomplete=True, lock_warn_only=True)
    self._build_dag()
    hashes = ProvenanceHashMap()
    found = []
    for job in self.dag.jobs:
        params = {}
        for name, value in job.params.items():
            if name != "keyed":
                flat(value, name, params)
        before = self.dag.dependencies[job]
        produced = {str(path) for files in before.values() for path in files}
        entry = None
        if job.rule.cache and job.output:
            try:
                provenance = self.async_run(hashes.get_provenance_hash(job))
                for output, extension in AbstractOutputFileCache.get_outputfiles(None, job):
                    entry = provenance + extension
                    break
            except Exception:
                entry = None
        found.append({
            "rule": job.rule.name,
            "checkpoint": bool(job.rule.is_checkpoint),
            "output": str(job.output[0]) if job.output else None,
            "after": [str(other.output[0]) if other.output else other.rule.name for other in before],
            "first": str(job.input[0]) if job.input else None,
            "sources": sorted({str(path) for path in job.input if str(path) not in produced}),
            "params": params,
            "names": [name for name in job.params.keys() if name],
            "script": job.rule.script,
            "entry": entry,
            "estimate_cents": job.resources.get("estimate_cents") if hasattr(job.resources, "get") else None,
        })
    print("NOCK-GRAPH " + json.dumps(found, default=str), flush=True)


workflow.Workflow.list_untracked = jobs
main(sys.argv[1:])
"""


class Status(StrEnum):
    DONE = "done"
    RUNNING = "running"
    FAILED = "failed"
    STALE = "stale"
    MISSING = "missing"


STATUS_WORDS = {
    Status.DONE: "done",
    Status.RUNNING: "running",
    Status.FAILED: "failed",
    Status.STALE: "stale",
    Status.MISSING: "not yet run",
}


# --- the words a scenario may give ---------------------------------------------------


class Branch(TypedDict):
    id: str
    label: NotRequired[str]
    verdict: NotRequired[str]
    """`good` or `bad`: the branch ends the trajectory with it."""
    equals: NotRequired[Any]
    """Taken when the metric is this value."""
    above: NotRequired[float]
    """Taken when the metric is above this number. A branch with neither takes the rest."""


class Decision(TypedDict):
    """Code over a step's metrics that picks one of its branches."""

    after: str
    """The rule whose outputs it reads."""
    label: str
    """Its short label, a question: `Fixed?`."""
    metric: str
    """The key of the outputs' metrics.json it reads."""
    branches: list[Branch]
    condition: NotRequired[str]
    """The full condition, in words."""
    measure: NotRequired[str]
    """The name of the measure its good branch counts: `Bugs fixed`."""


class ResultWords(TypedDict):
    """One result an output holds: a file inside it, or the metrics under a prefix."""

    name: str
    kind: str
    """How it is shown: facts, text, patch, list, checks or steps."""
    about: NotRequired[str]
    file: NotRequired[str]
    metrics: NotRequired[str]
    """A prefix of metrics.json's keys, true or false each: shown as checks."""


class ScoreWords(TypedDict):
    metric: str
    name: NotRequired[str]
    about: NotRequired[str]
    better: NotRequired[str]
    """`higher` (the default) or `lower`."""
    of: NotRequired[str]
    """A metric holding what the score is out of."""


class RuleWords(TypedDict):
    title: NotRequired[str]
    """The column's title: `Observation`."""
    means: NotRequired[str]
    """What one of its outputs is, in a sentence; the comment above the rule by default."""
    metrics: NotRequired[list[str]]
    """The numbers a group shows, first the key one; the first two of metrics.json by default."""
    highlights: NotRequired[list[str]]
    """Sentences about one output, `{name}` filled from its metrics, cost and parameters;
    a sentence naming something the output lacks is left out."""
    results: NotRequired[list[ResultWords]]
    """What one of its outputs holds, for the Experiments tab; its metrics and diff.patch by default."""
    score: NotRequired[ScoreWords]
    """The metric that scores one of its outputs, for the Experiments tab."""


class ParameterWords(TypedDict):
    label: NotRequired[str]
    """What the parameter is: `Instrumentation setup`."""
    values: NotRequired[dict[str, str]]
    """Its values in words: `{"none": "no skill"}`."""
    about: NotRequired[str]
    """What it is, in a sentence."""
    pooled: NotRequired[bool]
    """Added up rather than compared, like a bug in a bank: the Experiments tab's variants
    are the values of the parameters that are not."""
    repeat: NotRequired[bool]
    """It repeats a step (`rep` by default)."""
    controls: NotRequired[list[str]]
    """Its values that are a control, not a case: `["none"]` for no bug."""


class Analysis(TypedDict):
    step: str
    """The rule whose current outputs are counted."""
    by: str
    """The parameter whose values are set side by side."""
    metric: str
    """A key of metrics.json: counted true (or above zero) out of the outputs that have it."""
    name: NotRequired[str]
    """The question, in words."""
    where: NotRequired[dict[str, str]]
    """Only the outputs with these parameter values."""
    baseline: NotRequired[str]
    """The value of `by` the others are set against; the first by default."""


class Words(TypedDict):
    """`evals/NAME/studio.json`: how the studio words a scenario. Every key is optional."""

    rules: NotRequired[dict[str, RuleWords]]
    parameters: NotRequired[dict[str, ParameterWords]]
    metrics: NotRequired[dict[str, str]]
    """Labels of metrics.json's keys."""
    lanes: NotRequired[str]
    """The parameter whose values are the graph's rows; the earliest that forks by default."""
    analyses: NotRequired[list[Analysis]]
    """The comparisons the scenario was run to answer, written down first."""
    question: NotRequired[str]
    """What the experiment asks, for the Experiments tab."""
    decisions: NotRequired[list[Decision]]
    """Code over a step's metrics that picks a branch, for the Experiments tab."""


class Selection(TypedDict):
    """A group (a rule and parameter values) or one run (`run`, its output) chosen on the page."""

    rule: str
    filter: NotRequired[dict[str, str | None]]
    run: NotRequired[str]


class Change(TypedDict):
    """What if this changed: a parameter's value (`value`), one of the inputs a step's
    params carry (`input`, such as a version), or a file the steps read (`code`)."""

    kind: str
    name: str
    value: NotRequired[str]


class View(TypedDict):
    """What the page shows: which target's jobs, rows by which parameter, what is
    selected (left to right), which groups are split, and a change to weigh."""

    target: NotRequired[str]
    lanes: NotRequired[str]
    path: NotRequired[list[Selection]]
    expanded: NotRequired[list[str]]
    change: NotRequired[Change]


# --- the description of the jobs --------------------------------------------------------


@dataclass
class Job:
    """One job: its output (its id), rule, parameters from its path (a name repeated
    in the path is `NAME#2`), the jobs it reads (`first` is its main input), the
    inputs its params carry, flattened, and its cache entry."""

    id: str
    rule: str
    parameters: dict[str, str]
    after: list[str]
    first: str | None = None
    params: dict[str, Any] = field(default_factory=dict)
    names: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    script: str | None = None
    entry: str | None = None
    checkpoint: bool = False
    estimate_usd: float | None = None
    target: bool = False


def path_parameters(path: str) -> dict[str, str]:
    """An output's parameters in the order of its path; a repeated name is `NAME#2`."""
    found: dict[str, str] = {}
    for part in path.split("/"):
        if "=" not in part:
            continue
        name, value = part.split("=", 1)
        key, count = name, 1
        while key in found:
            count += 1
            key = f"{name}#{count}"
        found[key] = value
    return found


@dataclass
class Graph:
    """The jobs of a scenario's default target, as Snakemake described them."""

    jobs: dict[str, Job]
    fingerprint: str = ""
    derived_at: float = 0.0
    seconds: float = 0.0
    checkpoints: list[str] = field(default_factory=list)
    """The checkpoint outputs done when it was derived: one more, and what follows it is known."""

    @classmethod
    def of(cls, rows: list[dict[str, Any]], fingerprint: str = "") -> Graph:
        jobs: dict[str, Job] = {}
        for row in rows:
            output = row.get("output")
            cents = row.get("estimate_cents")
            job = Job(
                id=output or row["rule"],
                rule=row["rule"],
                parameters=path_parameters(output) if output else {},
                after=list(row.get("after") or []),
                first=row.get("first"),
                params=dict(row.get("params") or {}),
                names=list(row.get("names") or []),
                sources=list(row.get("sources") or []),
                script=row.get("script"),
                entry=row.get("entry"),
                checkpoint=bool(row.get("checkpoint")),
                estimate_usd=float(cents) / 100 if isinstance(cents, (int, float)) else None,
                target=output is None,
            )
            jobs[job.id] = job
        return cls(jobs, fingerprint)

    def to_json(self) -> dict[str, Any]:
        return {
            "format": FORMAT,
            "fingerprint": self.fingerprint,
            "derived_at": self.derived_at,
            "seconds": self.seconds,
            "checkpoints": self.checkpoints,
            "jobs": [asdict(job) for job in self.jobs.values()],
        }

    @classmethod
    def from_json(cls, value: dict[str, Any]) -> Graph:
        jobs = {row["id"]: Job(**row) for row in value["jobs"]}
        return cls(
            jobs,
            value.get("fingerprint", ""),
            value.get("derived_at", 0.0),
            value.get("seconds", 0.0),
            value.get("checkpoints", []),
        )

    # --- shape -------------------------------------------------------------------------

    @cached_property
    def children(self) -> dict[str, list[str]]:
        found: dict[str, list[str]] = {}
        for job in self.jobs.values():
            for before in job.after:
                found.setdefault(before, []).append(job.id)
        return found

    def targets(self) -> list[str]:
        """The rules that only name what to make (`all`, a request's rule): the targets."""
        return sorted({job.rule for job in self.jobs.values() if job.target})

    @cached_property
    def rules(self) -> list[str]:
        """The rules with outputs, in the order they run: by the longest chain before them."""
        depends: dict[str, set[str]] = {}
        for job in self.jobs.values():
            if job.target:
                continue
            depends.setdefault(job.rule, set())
            for before in job.after:
                other = self.jobs.get(before)
                if other is not None and not other.target and other.rule != job.rule:
                    depends[job.rule].add(other.rule)
        depth: dict[str, int] = {}

        def visit(rule: str, seen: frozenset[str]) -> int:
            if rule in depth:
                return depth[rule]
            earlier = [
                visit(other, seen | {rule}) + 1 for other in depends[rule] if other not in seen
            ]
            depth[rule] = max(earlier, default=0)
            return depth[rule]

        for rule in depends:
            visit(rule, frozenset())
        first_seen = {rule: index for index, rule in enumerate(depends)}
        return sorted(depends, key=lambda rule: (depth[rule], first_seen[rule]))

    def ancestors(self, ids: Iterable[str]) -> set[str]:
        found: set[str] = set()
        todo = list(ids)
        while todo:
            at = todo.pop()
            for before in self.jobs[at].after if at in self.jobs else []:
                if before not in found:
                    found.add(before)
                    todo.append(before)
        return found

    def descendants(self, ids: Iterable[str], children: dict[str, list[str]]) -> set[str]:
        found: set[str] = set()
        todo = list(ids)
        while todo:
            for after in children.get(todo.pop(), []):
                if after not in found:
                    found.add(after)
                    todo.append(after)
        return found

    def scope(self, targets: list[str]) -> set[str]:
        """The jobs a run of `targets` (target rules or outputs) makes."""
        roots = [
            job.id
            for job in self.jobs.values()
            if (job.target and job.rule in targets) or job.id in targets
        ]
        return {
            job_id
            for job_id in self.ancestors(roots) | set(roots)
            if job_id in self.jobs and not self.jobs[job_id].target
        }

    def varying(self, ids: Iterable[str]) -> list[str]:
        """The parameters that take more than one value (or are missing from some) among
        `ids`, in the order they first appear, rule by rule."""
        rules = {rule: index for index, rule in enumerate(self.rules)}
        chosen = [self.jobs[job_id] for job_id in ids]
        chosen.sort(key=lambda job: rules.get(job.rule, 0))
        order: list[str] = []
        values: dict[str, set[str]] = {}
        # Per rule, how many of its jobs have the parameter: a parameter some of a
        # rule's jobs lack forks there (a planner only for one setup); one a whole
        # rule lacks does not.
        having: dict[tuple[str, str], int] = {}
        sizes: dict[str, int] = {}
        # Where each first appears: its rule, then its furthest place in a path, so a
        # parameter only some paths carry keeps its place among the others.
        first: dict[str, tuple[int, int]] = {}
        for job in chosen:
            sizes[job.rule] = sizes.get(job.rule, 0) + 1
            rank = rules.get(job.rule, 0)
            for place, (name, value) in enumerate(job.parameters.items()):
                if name not in values:
                    order.append(name)
                    values[name] = set()
                    first[name] = (rank, place)
                elif first[name][0] == rank:
                    first[name] = (rank, max(first[name][1], place))
                values[name].add(value)
                having[job.rule, name] = having.get((job.rule, name), 0) + 1
        partly = {name for (rule, name), count in having.items() if count < sizes[rule]}
        order.sort(key=lambda name: first[name])
        return [name for name in order if len(values[name]) > 1 or name in partly]


# --- what Snakemake is doing ---------------------------------------------------------------


def record_path(subject: Path, identifier: str) -> Path:
    """Where Snakemake keeps a record about `identifier` (an output) under `subject`:
    its url-safe base64, cut into parts a directory name holds."""
    encoded = base64.urlsafe_b64encode(identifier.encode()).decode()
    try:
        limit = os.pathconf(subject, "PC_NAME_MAX") if subject.exists() else 255
    except (OSError, ValueError):
        limit = 255
    parts = [encoded[index : index + limit - 1] for index in range(0, len(encoded), limit - 1)]
    return subject.joinpath(*["@" + part for part in parts[:-1]], parts[-1])


def recorded(subject: Path) -> list[str]:
    """The identifiers Snakemake keeps records about under `subject`."""
    found = []
    for root, _, files in os.walk(subject):
        for name in files:
            relative = Path(root, name).relative_to(subject)
            encoded = "".join(part.removeprefix("@") for part in relative.parts)
            try:
                found.append(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)).decode())
            except (ValueError, UnicodeDecodeError):
                continue
    return found


STAMP = re.compile(r"^\[(\w{3} \w{3} +\d+ [\d:]+ \d{4})\]$")
JOB_START = re.compile(r"^(?:local)?(?:rule|checkpoint) ([\w-]+):$")
JOB_FIELD = re.compile(r"^    (output|jobid): (.*)$")
FINISHED = re.compile(r"^Finished job(?:id:)? (\d+)")
ERROR_IN = re.compile(r"^Error in rule ([\w-]+):$")
PROGRESS = re.compile(r"^(\d+) of (\d+) steps \((.*)\) done$")


@dataclass
class Activity:
    """A Snakemake run going on in the scenario, from its lock and its log."""

    active: bool = False
    log: str | None = None
    command: str = ""
    targets: list[str] = field(default_factory=list)
    done: int = 0
    total: int = 0
    started_at: str | None = None
    running: dict[str, str] = field(default_factory=dict)
    """Output → when its job started, by the log."""
    failed: set[str] = field(default_factory=set)
    incomplete: set[str] = field(default_factory=set)


class Monitor:
    """Reads Snakemake's state in a scenario, the log incrementally: only what was
    appended since the last reading."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.state = directory / ".snakemake"
        self.log: Path | None = None
        self.offset = 0
        self.parsed = Activity()
        self.jobs: dict[str, str] = {}
        """Job id → output, of the jobs the log started."""
        self.pending: dict[str, str] = {}
        self.stamp: str | None = None
        self.current: str | None = None
        self.erring = False

    def latest_log(self) -> Path | None:
        logs = sorted((self.state / "log").glob("*.snakemake.log"))
        # A run that only weighed (a dry run, a summary) writes a log of a few bytes.
        real = [path for path in logs if path.stat().st_size > 200]
        return real[-1] if real else None

    def read(self) -> Activity:
        locks = self.state / "locks"
        active = locks.is_dir() and any(locks.glob("*.lock"))
        log = self.latest_log()
        if log != self.log:
            self.log, self.offset, self.parsed = log, 0, Activity()
            self.jobs, self.pending, self.current, self.erring = {}, {}, None, False
        if log is not None:
            with log.open("rb") as handle:
                handle.seek(self.offset)
                text = handle.read()
            end = text.rfind(b"\n") + 1
            self.offset += end
            for line in text[:end].decode(errors="replace").splitlines():
                self.line(line)
        activity = Activity(
            active=active,
            log=str(log) if log else None,
            command=self.parsed.command,
            targets=self.parsed.targets,
            done=self.parsed.done,
            total=self.parsed.total,
            started_at=self.parsed.started_at,
            running=dict(self.parsed.running) if active else {},
            failed=set(self.parsed.failed),
        )
        if active and (self.state / "incomplete").is_dir():
            activity.incomplete = set(recorded(self.state / "incomplete"))
        return activity

    def line(self, line: str) -> None:
        parsed = self.parsed
        if line.startswith("  Command: "):
            parsed.command = line.removeprefix("  Command: ").strip()
            parsed.targets = command_targets(parsed.command)
            return
        if line.startswith("  Date: ") and parsed.started_at is None:
            parsed.started_at = line.removeprefix("  Date: ").strip()
            return
        stamp = STAMP.match(line)
        if stamp:
            self.stamp = stamp.group(1)
            return
        started = JOB_START.match(line)
        if started:
            self.current, self.erring = "job", False
            self.pending = {}
            return
        failed = ERROR_IN.match(line)
        if failed:
            self.current, self.erring = "error", True
            self.pending = {}
            return
        item = JOB_FIELD.match(line)
        if item and self.current:
            self.pending[item.group(1)] = item.group(2).split(", ")[0].strip()
            if "output" in self.pending and "jobid" in self.pending:
                output, number = self.pending["output"], self.pending["jobid"]
                if self.erring:
                    parsed.failed.add(output)
                    parsed.running.pop(output, None)
                else:
                    self.jobs[number] = output
                    parsed.running[output] = self.stamp or ""
                self.current = None
            return
        finished = FINISHED.match(line)
        if finished:
            output = self.jobs.get(finished.group(1))
            if output:
                parsed.running.pop(output, None)
            return
        progress = PROGRESS.match(line)
        if progress:
            parsed.done, parsed.total = int(progress.group(1)), int(progress.group(2))


def command_targets(command: str) -> list[str]:
    """The targets a Snakemake command line names: its words that are no option or an option's value."""
    words = command.split()
    takes_value = {
        "--profile",
        "--cores",
        "-c",
        "--jobs",
        "-j",
        "--snakefile",
        "-s",
        "--directory",
        "-d",
    }
    found: list[str] = []
    index = next((i + 1 for i, word in enumerate(words) if word.endswith("snakemake")), 0)
    while index < len(words):
        word = words[index]
        if word in takes_value:
            index += 2
            continue
        if word in ("--resources", "--set-resources", "--config", "--forcerun", "-R"):
            index += 1
            while index < len(words) and not words[index].startswith("-"):
                index += 1
            continue
        if not word.startswith("-"):
            found.append(word)
        index += 1
    return found


# --- one output's facts --------------------------------------------------------------------


@dataclass
class Facts:
    """What a job's output says now."""

    status: Status
    entry: str | None = None
    usd: float | None = None
    seconds: float | None = None
    tokens: int | None = None
    metrics: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    where: str = ""
    """`results` (materialised here), `cache` (only in the cache) or ``."""
    since: str | None = None


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text())
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


class Reader:
    """Each job's facts from the files, re-reading only what changed: an output's
    files are read again when its directory (or the link to it) changes."""

    def __init__(self, scenario: Scenario) -> None:
        self.scenario = scenario
        self.cache = scenario.cache
        self.known: dict[str, tuple[tuple[int, int, int, str], Facts]] = {}

    def outputs(self, directory: Path) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        return (
            read_json(directory / COST),
            read_json(directory / METRICS),
            read_json(directory / ERROR),
        )

    def facts(self, job: Job, activity: Activity) -> Facts:
        path = self.scenario.directory / job.id
        running = activity.active and (job.id in activity.running or job.id in activity.incomplete)
        try:
            status = path.lstat()
        except OSError:
            status = None
        if status is None:
            entry = self.cache / job.entry if job.entry else None
            if running:
                return Facts(Status.RUNNING, since=activity.running.get(job.id))
            if entry is not None and os.path.lexists(entry) and entry.is_dir():
                return self.read(job, entry, job.entry, "cache")
            return Facts(Status.MISSING)
        try:
            inner = path.stat()
        except OSError:
            inner = status
        key = (status.st_ino, status.st_mtime_ns, inner.st_mtime_ns, job.entry or "")
        known = self.known.get(job.id)
        if known is not None and known[0] == key and not running:
            return known[1]
        if running and not (path / COST).exists():
            return Facts(Status.RUNNING, since=activity.running.get(job.id))
        try:
            entry_name = self.scenario.entry(path) if path.is_dir() else None
        except OSError:
            entry_name = None
        facts = self.read(job, path, entry_name, "results")
        if facts.status is Status.MISSING and running:
            facts.status = Status.RUNNING
        self.known[job.id] = (key, facts)
        return facts

    def read(self, job: Job, directory: Path, entry: str | None, where: str) -> Facts:
        cost, metrics, error = self.outputs(directory)
        if error:
            status = Status.FAILED
        elif (directory / COST).is_file():
            status = Status.DONE
            if where == "results" and job.entry and entry and entry != job.entry:
                status = Status.STALE
        else:
            status = Status.MISSING
        tokens = cost.get("tokens")
        return Facts(
            status,
            entry=entry,
            usd=float(cost["usd"]) if isinstance(cost.get("usd"), (int, float)) else None,
            seconds=float(cost["seconds"])
            if isinstance(cost.get("seconds"), (int, float))
            else None,
            tokens=int(tokens) if isinstance(tokens, (int, float)) else None,
            metrics=metrics,
            error=str(error.get("error")) if error else None,
            where=where,
        )


# --- words ---------------------------------------------------------------------------------


SPENDING = re.compile(r"^(usd|cost.*|seconds|wall.*|turns|tokens.*|.*_usd|.*_s|.*_tokens)$")
MODEL = re.compile(r"claude-([a-z]+)-(\d+)-(\d+)(?:-\d{8})?")


def comments(snakefile: str) -> dict[str, str]:
    """The comment block right above each rule, as what it means: `# plain: X.` → `X.`"""
    found: dict[str, str] = {}
    lines = snakefile.splitlines()
    for index, line in enumerate(lines):
        head = re.match(r"^(rule|checkpoint) ([\w-]+):", line)
        if not head:
            continue
        block: list[str] = []
        at = index - 1
        while at >= 0 and lines[at].startswith("#"):
            block.insert(0, lines[at].lstrip("#").strip())
            at -= 1
        text = " ".join(part for part in block if part)
        name = head.group(2)
        text = re.sub(rf"^{re.escape(name)}\s*:\s*", "", text)
        if text:
            found[name] = text[0].upper() + text[1:]
    return found


def plural(count: int, one: str, many: str | None = None) -> str:
    return f"{count} {one if count == 1 else many or one + 's'}"


def money(value: float | None) -> str:
    if value is None:
        return "—"
    if value == 0:
        return "$0"
    return f"${value:,.0f}" if value >= 100 else f"${value:,.2f}"


def duration(seconds: float | None) -> str:
    if seconds is None:
        return "—"
    if seconds < 90:
        return f"{seconds:.0f} s"
    if seconds < 90 * 60:
        return f"{seconds / 60:.0f} min"
    return f"{seconds / 3600:.1f} h"


def number(value: Any) -> str:
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, float):
        return f"{value:,.0f}" if abs(value) >= 100 else f"{value:.3g}"
    if isinstance(value, int):
        return f"{value:,}"
    if value is None:
        return "—"
    if isinstance(value, (list, dict)):
        return f"{len(value)} items" if value else "none"
    return str(value)


def median(values: Iterable[float | None]) -> float | None:
    found = [value for value in values if value is not None]
    return statistics.median(found) if found else None


def truthy(value: Any) -> bool | None:
    """A metric as counted: true or above zero; None when it is no number."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value > 0
    return None


class Wording:
    """The scenario's words: its studio.json, the Snakefile's comments, and plain defaults."""

    def __init__(self, scenario: Scenario) -> None:
        path = scenario.directory / WORDS
        words: dict[str, Any] = {}
        if path.is_file():
            try:
                words = json.loads(path.read_text())
            except ValueError as error:
                raise UsageError(f"{scenario.name}/{WORDS} is not JSON: {error}") from error
            validate(words, schema_of(Words))
        self.words: Words = words  # type: ignore[assignment]
        self.comments = comments((scenario.directory / "Snakefile").read_text())

    def rule(self, rule: str) -> RuleWords:
        return self.words.get("rules", {}).get(rule, {})

    def title(self, rule: str) -> str:
        return self.rule(rule).get("title") or rule.replace("_", " ").replace("-", " ").capitalize()

    def means(self, rule: str) -> str:
        return self.rule(rule).get("means") or self.comments.get(rule, "")

    def parameter(self, name: str) -> str:
        label = self.words.get("parameters", {}).get(name, {}).get("label")
        if label:
            return label
        base, _, again = name.partition("#")
        label = self.words.get("parameters", {}).get(base, {}).get("label") or base.replace(
            "_", " "
        )
        return f"{label} ({again})" if again else label

    def value(self, name: str, value: str | None) -> str:
        if value is None:
            return f"no {self.parameter(name)}"
        words = self.words.get("parameters", {}).get(name) or self.words.get("parameters", {}).get(
            name.partition("#")[0], {}
        )
        named = words.get("values", {})
        if value in named:
            return named[value]
        model = MODEL.fullmatch(value)
        if model:
            return f"{model.group(1).title()} {model.group(2)}.{model.group(3)}"
        return value

    def metric(self, name: str) -> str:
        return self.words.get("metrics", {}).get(name) or name.replace("_", " ")

    def key_metrics(self, rule: str, seen: list[str]) -> list[str]:
        declared = self.rule(rule).get("metrics")
        if declared:
            return list(declared)
        # What it spent is said beside every output already.
        return [key for key in seen if not SPENDING.match(key)][:2]


# --- the explorer --------------------------------------------------------------------------


@dataclass
class Unit:
    """A group of jobs of one rule shown as one box: a value of the rows' parameter,
    then, when split, of the parameters that fork inside it; one job is a run."""

    rule: str
    filter: dict[str, str | None]
    jobs: list[str]
    depth: int = 0

    @property
    def id(self) -> str:
        return self.rule + "|" + json.dumps(self.filter, sort_keys=True)


class Explorer:
    """One scenario's explorer: the description kept and refreshed in the background,
    the statuses read on demand, and the views the page asks for."""

    def __init__(self, scenario: Scenario, store: Path) -> None:
        self.scenario = scenario
        key = hashlib.sha256(str(scenario.directory.resolve()).encode()).hexdigest()[:10]
        self.file = store / f"{scenario.name}-{key}.json"
        self.graph: Graph | None = None
        self.problem: str | None = None
        self.refreshing = False
        self.checked = 0.0
        self.lock = threading.Lock()
        self.thread: threading.Thread | None = None
        self.monitor = Monitor(scenario.directory)
        self.reader = Reader(scenario)
        self.read_at = 0.0
        self.reading: tuple[Activity, dict[str, Facts]] | None = None
        self.load()

    # --- the description ---------------------------------------------------------------

    def load(self) -> None:
        if not self.file.is_file():
            return
        try:
            kept = json.loads(self.file.read_text())
            if kept.get("format") == FORMAT:
                self.graph = Graph.from_json(kept)
        except (ValueError, KeyError, TypeError):
            self.graph = None

    def fingerprint(self, checkpoints: list[str]) -> str:
        """What the description depends on: the scenario's own files (not its results,
        cache or Snakemake's state), the checkout's commit and uncommitted changes —
        a Snakefile may read the repository — and the checkpoints done."""
        directory = self.scenario.directory
        skip = {RESULTS, CACHE, ".snakemake"}
        digest = hashlib.sha256()
        for root, directories, files in os.walk(directory):
            if Path(root) == directory:
                directories[:] = [name for name in directories if name not in skip]
            directories[:] = sorted(name for name in directories if not name.startswith("."))
            for name in sorted(files):
                if name == WORDS:
                    continue
                path = Path(root, name)
                try:
                    status = path.stat()
                except OSError:
                    continue
                digest.update(
                    f"{path.relative_to(directory)}:{status.st_mtime_ns}:{status.st_size}\n".encode()
                )
        for command in (["rev-parse", "HEAD"], ["status", "--porcelain", "--untracked-files=no"]):
            result = subprocess.run(
                ["git", *command], cwd=directory, capture_output=True, text=True
            )
            # The studio's words shape nothing Snakemake does.
            kept = [line for line in result.stdout.splitlines() if not line.endswith(f"/{WORDS}")]
            digest.update("\n".join(kept).encode())
        digest.update("\n".join(sorted(checkpoints)).encode())
        return digest.hexdigest()

    def derive(self) -> Graph:
        """Ask Snakemake for every job of the default target: a dry run's time."""
        began = time.monotonic()
        result = subprocess.run(
            [
                uv(),
                "run",
                "--no-project",
                "--quiet",
                "--with",
                SNAKEMAKE,
                "python",
                "-c",
                GRAPH,
                "--profile",
                PROFILE,
                "--list-untracked",
            ],
            cwd=self.scenario.directory,
            env=self.scenario.environment(),
            capture_output=True,
            text=True,
        )
        for line in result.stdout.splitlines():
            if line.startswith("NOCK-GRAPH "):
                graph = Graph.of(json.loads(line.removeprefix("NOCK-GRAPH ")))
                graph.seconds = round(time.monotonic() - began, 1)
                return graph
        said = (result.stderr or result.stdout).strip().splitlines()
        raise PreconditionError(
            f"snakemake could not describe the jobs of {self.scenario.name}:\n"
            + "\n".join(said[-15:])
        )

    def checkpoints_done(self, graph: Graph | None) -> list[str]:
        if graph is None:
            return []
        directory = self.scenario.directory
        return sorted(
            job.id
            for job in graph.jobs.values()
            if job.checkpoint and (directory / job.id / COST).exists()
        )

    def refresh(self) -> None:
        """Derive the description again when what it depends on changed."""
        try:
            checkpoints = self.checkpoints_done(self.graph)
            fingerprint = self.fingerprint(checkpoints)
            if self.graph is not None and self.graph.fingerprint == fingerprint:
                return
            self.refreshing = True
            graph = self.derive()
            graph.checkpoints = self.checkpoints_done(graph)
            graph.fingerprint = (
                fingerprint
                if graph.checkpoints == checkpoints
                else self.fingerprint(graph.checkpoints)
            )
            graph.derived_at = time.time()
            self.file.parent.mkdir(parents=True, exist_ok=True)
            staging = self.file.with_suffix(".tmp")
            staging.write_text(json.dumps(graph.to_json()))
            staging.replace(self.file)
            with self.lock:
                self.graph, self.problem, self.reading = graph, None, None
        except PreconditionError as error:
            self.problem = str(error)
        finally:
            self.refreshing = False

    def current(self, wait: bool = False) -> Graph | None:
        """The description, refreshed in the background when it is due — every
        `FINGERPRINT_EVERY` seconds, or at once when a checkpoint finished — or now,
        with `wait`."""
        if wait:
            if self.thread is not None:
                self.thread.join()
            self.checked = time.monotonic()
            self.refresh()
            return self.graph
        graph = self.graph
        due = time.monotonic() - self.checked > FINGERPRINT_EVERY or (
            graph is not None and self.checkpoints_done(graph) != graph.checkpoints
        )
        if due and (self.thread is None or not self.thread.is_alive()):
            self.checked = time.monotonic()
            self.thread = threading.Thread(target=self.refresh, daemon=True)
            self.thread.start()
        return self.graph

    # --- statuses ------------------------------------------------------------------------

    def read(self, graph: Graph) -> tuple[Activity, dict[str, Facts]]:
        with self.lock:
            if self.reading is not None and time.monotonic() - self.read_at < STATUS_EVERY:
                return self.reading
            activity = self.monitor.read()
            facts = {
                job.id: self.reader.facts(job, activity)
                for job in graph.jobs.values()
                if not job.target
            }
            self.reading, self.read_at = (activity, facts), time.monotonic()
            return self.reading

    # --- views ----------------------------------------------------------------------------

    def summary(self) -> dict[str, Any]:
        """The scenario in a line: its jobs by status, and the run going on."""
        graph = self.current()
        if graph is None:
            return {
                "name": self.scenario.name,
                "deriving": self.refreshing or self.problem is None,
                "problem": self.problem,
            }
        _, facts = self.read(graph)
        counts = {status.value: 0 for status in Status}
        for item in facts.values():
            counts[item.status.value] += 1
        return {
            "name": self.scenario.name,
            "steps": len(facts),
            "counts": counts,
            "refreshing": self.refreshing,
            "problem": self.problem,
        }

    def explore(self, view: View) -> dict[str, Any]:
        graph = self.current()
        if graph is None:
            return {
                "name": self.scenario.name,
                "deriving": self.problem is None,
                "problem": self.problem,
            }
        activity, facts = self.read(graph)
        return Exploration(self.scenario, graph, facts, activity, view).page() | {
            "refreshing": self.refreshing,
            "problem": self.problem,
            "derived_at": graph.derived_at,
            "derived_in": graph.seconds,
        }

    def detail(self, output: str) -> dict[str, Any]:
        graph = self.current()
        if graph is None or output not in graph.jobs:
            raise NotFoundError(f"no job makes {output}")
        activity, facts = self.read(graph)
        return Exploration(self.scenario, graph, facts, activity, {}).detail(output)

    def file_text(self, output: str, name: str) -> dict[str, Any]:
        """One file of an output, its end when long; only a file inside a job's output."""
        graph = self.current()
        if graph is None or output not in graph.jobs:
            raise NotFoundError(f"no job makes {output}")
        if not name or name.startswith("/") or ".." in Path(name).parts:
            raise UsageError("a file is named by its path inside the output")
        path = self.scenario.directory / output / name
        if not path.is_file():
            raise NotFoundError(f"{output} has no file {name}")
        size = path.stat().st_size
        with path.open("rb") as handle:
            if size > FILE_BYTES:
                handle.seek(size - FILE_BYTES)
            data = handle.read()
        return {
            "output": output,
            "name": name,
            "bytes": size,
            "truncated": size > FILE_BYTES,
            "text": data.decode(errors="replace"),
        }


class Exploration:
    """One reading of a scenario as the page sees it: the target's jobs, narrowed by the
    selections, folded into units per column, with a change weighed."""

    def __init__(
        self,
        scenario: Scenario,
        graph: Graph,
        facts: dict[str, Facts],
        activity: Activity,
        view: View,
    ) -> None:
        self.scenario = scenario
        self.graph = graph
        self.facts = facts
        self.activity = activity
        self.view = view
        self.words = Wording(scenario)
        self.children = graph.children
        self.columns = graph.rules
        self.targets = graph.targets()
        self.target = self.choose_target()
        self.jobs = (
            graph.scope([self.target])
            if self.target
            else {job.id for job in graph.jobs.values() if not job.target}
        )
        self.varying = graph.varying(self.jobs)
        self.lanes = self.choose_lanes()
        self.medians = self.rule_medians()

    # --- choices --------------------------------------------------------------------

    def choose_target(self) -> str | None:
        asked = self.view.get("target")
        if asked in self.targets:
            return asked
        if self.activity.active:
            for target in self.activity.targets:
                if target in self.targets:
                    return target
        return "all" if "all" in self.targets else (self.targets[0] if self.targets else None)

    def choose_lanes(self) -> str | None:
        asked = self.view.get("lanes")
        if asked == "":
            return None
        if asked in self.varying:
            return asked
        declared = self.words.words.get("lanes")
        if declared in self.varying:
            return declared
        return self.varying[0] if self.varying else None

    def rule_medians(self) -> dict[str, tuple[float | None, float | None]]:
        """Each rule's median cost and time over its outputs computed, for estimates."""
        spent: dict[str, list[Facts]] = {}
        for job_id, item in self.facts.items():
            if item.status in (Status.DONE, Status.STALE) and item.usd is not None:
                spent.setdefault(self.graph.jobs[job_id].rule, []).append(item)
        return {
            rule: (median(item.usd for item in items), median(item.seconds for item in items))
            for rule, items in spent.items()
        }

    # --- narrowing ------------------------------------------------------------------

    def matches(self, job_id: str, selection: Selection) -> bool:
        job = self.graph.jobs[job_id]
        if job.rule != selection["rule"]:
            return False
        if "run" in selection:
            return job_id == selection["run"]
        return all(
            job.parameters.get(name) == value for name, value in selection.get("filter", {}).items()
        )

    def narrowed(self) -> tuple[dict[str, set[str]], list[dict[str, Any]], set[str], set[str]]:
        """Each column's jobs once every selection narrowed the columns to its right to
        its descendants; the breadcrumb; what is selected; and the lineage before it."""
        scope = {rule: set() for rule in self.columns}
        for job_id in self.jobs:
            scope.setdefault(self.graph.jobs[job_id].rule, set()).add(job_id)
        index = {rule: position for position, rule in enumerate(self.columns)}
        path = sorted(
            (item for item in self.view.get("path", []) if item.get("rule") in index),
            key=lambda item: index[item["rule"]],
        )
        crumbs: list[dict[str, Any]] = []
        selected: set[str] = set()
        lineage: set[str] = set()
        for selection in path:
            rule = selection["rule"]
            chosen = {job_id for job_id in scope[rule] if self.matches(job_id, selection)}
            if not chosen:
                break
            crumbs.append(
                {
                    "selection": selection,
                    "label": self.selection_words(selection),
                    "count": len(chosen),
                }
            )
            selected = chosen
            lineage |= self.graph.ancestors(chosen)
            after = self.graph.descendants(chosen, self.children)
            for later in self.columns[index[rule] + 1 :]:
                scope[later] &= after
        return scope, crumbs, selected, lineage & self.jobs

    def selection_words(self, selection: Selection) -> str:
        title = self.words.title(selection["rule"])
        if "run" in selection:
            parameters = self.graph.jobs[selection["run"]].parameters
            own = [name for name in self.varying if name in parameters]
            return (
                f"{title} · "
                + " · ".join(self.words.value(name, parameters[name]) for name in own[-2:])
                if own
                else title
            )
        values = [
            self.words.value(name, value) for name, value in selection.get("filter", {}).items()
        ]
        return " · ".join([title, *values]) if values else f"{title} · all"

    # --- units ----------------------------------------------------------------------

    def units(self, rule: str, ids: set[str]) -> list[Unit]:
        """The column's units: one per value of the rows' parameter, each split, when the
        page expanded it, by the next parameter that forks inside it."""
        expanded = set(self.view.get("expanded", []))
        order = [name for name in self.varying if name != self.lanes]
        found: list[Unit] = []

        def split(unit: Unit) -> None:
            found.append(unit)
            if unit.id not in expanded or len(unit.jobs) < 2:
                return
            inside = self.graph.varying(unit.jobs)
            name = next(
                (item for item in order if item in inside and item not in unit.filter), None
            )
            if name is None:
                for job_id in sorted(unit.jobs, key=self.order):
                    found.append(
                        Unit(rule, {**unit.filter, "#run": job_id}, [job_id], unit.depth + 1)
                    )
                return
            for value, members in self.by(unit.jobs, name):
                split(Unit(rule, {**unit.filter, name: value}, members, unit.depth + 1))

        if not ids:
            return found
        members = sorted(ids, key=self.order)
        lanes = self.lanes
        if lanes is None or all(lanes not in self.graph.jobs[job].parameters for job in members):
            split(Unit(rule, {}, members))
        else:
            for value, group in self.by(members, lanes):
                split(Unit(rule, {lanes: value}, group))
        return found

    def order(self, job_id: str) -> tuple[Any, ...]:
        parameters = self.graph.jobs[job_id].parameters
        return tuple(natural(parameters.get(name)) for name in self.varying)

    def by(self, ids: list[str], name: str) -> list[tuple[str | None, list[str]]]:
        groups: dict[str | None, list[str]] = {}
        for job_id in ids:
            groups.setdefault(self.graph.jobs[job_id].parameters.get(name), []).append(job_id)
        return sorted(groups.items(), key=lambda item: natural(item[0]))

    # --- the page -----------------------------------------------------------------------

    def page(self) -> dict[str, Any]:
        scope, crumbs, selected, lineage = self.narrowed()
        change = self.view.get("change")
        affected = self.affected(change) if change else set()
        columns = []
        placed: dict[str, str] = {}
        for rule in self.columns:
            ids = scope.get(rule, set())
            if not ids and not any(self.graph.jobs[job].rule == rule for job in self.jobs):
                continue
            units = self.units(rule, ids)
            shown = []
            for unit in units:
                for job_id in unit.jobs:
                    placed[job_id] = unit.id
                shown.append(self.unit_json(unit, selected, lineage, affected))
            columns.append(
                {
                    "rule": rule,
                    "title": self.words.title(rule),
                    "means": self.words.means(rule),
                    "count": len(ids),
                    "of": sum(1 for job in self.jobs if self.graph.jobs[job].rule == rule),
                    "counts": self.counts(ids),
                    "forks": [
                        {"name": name, "label": self.words.parameter(name)}
                        for name in self.graph.varying(ids)
                    ]
                    if len(ids) > 1
                    else [],
                    "units": shown,
                }
            )
        edges: dict[tuple[str, str], list[int]] = {}
        for job_id, unit in placed.items():
            job = self.graph.jobs[job_id]
            for position, before in enumerate(job.after):
                source = placed.get(before)
                if source is None or source == unit:
                    continue
                main = before == job.first or (job.first is None and position == 0)
                counted = edges.setdefault((source, unit), [0, 0])
                counted[0 if main else 1] += 1
        return {
            "name": self.scenario.name,
            "targets": [
                {"name": target, "steps": len(self.graph.scope([target]))}
                for target in self.targets
            ],
            "target": self.target,
            "lanes": self.lanes,
            "forks": [{"name": name, "label": self.words.parameter(name)} for name in self.varying],
            "constant": self.constant(),
            "crumbs": crumbs,
            "columns": columns,
            "edges": [
                {"from": source, "to": unit, "main": counts[0], "other": counts[1]}
                for (source, unit), counts in edges.items()
            ],
            "counts": self.counts(self.jobs),
            "changes": self.change_options(),
            "change": self.change_json(change, affected) if change else None,
            "analyses": self.analyses(),
            "signature": self.signature(),
        }

    def signature(self) -> str:
        """Changes when any status does: the page re-renders only then."""
        digest = hashlib.sha256()
        for job_id in sorted(self.jobs):
            digest.update(f"{job_id}:{self.facts[job_id].status}\n".encode())
        return digest.hexdigest()[:16]

    def constant(self) -> list[dict[str, str]]:
        """The parameters every job that has them shares: said once, not on every box."""
        values: dict[str, set[str]] = {}
        for job_id in self.jobs:
            for name, value in self.graph.jobs[job_id].parameters.items():
                values.setdefault(name, set()).add(value)
        return [
            {
                "name": name,
                "label": self.words.parameter(name),
                "value": self.words.value(name, next(iter(found))),
            }
            for name, found in values.items()
            if len(found) == 1 and name not in self.varying
        ]

    def counts(self, ids: Iterable[str]) -> dict[str, int]:
        counts = {status.value: 0 for status in Status}
        for job_id in ids:
            counts[self.facts[job_id].status.value] += 1
        return counts

    def unit_json(
        self, unit: Unit, selected: set[str], lineage: set[str], affected: set[str]
    ) -> dict[str, Any]:
        run = unit.filter.get("#run")
        members = unit.jobs
        counts = self.counts(members)
        own = {name: value for name, value in unit.filter.items() if name != "#run"}
        last = list(own.items())[-1] if own else None
        if run is not None:
            label = self.run_label(run, own)
        elif last is not None and unit.depth:
            label = f"{self.words.parameter(last[0])} {self.words.value(*last)}"
        elif last is not None:
            label = self.words.value(*last)
        else:
            label = "every run" if len(members) > 1 else self.run_label(members[0], own)
        inside = self.graph.varying(members) if len(members) > 1 else []
        splits = [
            name
            for name in self.varying
            if name in inside and name != self.lanes and name not in own
        ]
        found: dict[str, Any] = {
            "id": unit.id,
            "rule": unit.rule,
            "filter": own,
            "run": run or (members[0] if len(members) == 1 else None),
            "depth": unit.depth,
            "label": label,
            "count": len(members),
            "counts": counts,
            "status": self.status_of(counts),
            "selected": bool(members) and all(job in selected for job in members),
            "lineage": any(job in lineage for job in members),
            "splits": {"name": splits[0], "label": self.words.parameter(splits[0])}
            if splits
            else None,
            "expanded": unit.id in set(self.view.get("expanded", [])) and len(members) > 1,
            "numbers": self.numbers(unit.rule, members),
        }
        if affected:
            found["affected"] = sum(1 for job in members if job in affected)
        found["card"] = self.card(unit, label)
        return found

    def run_label(self, job_id: str, own: dict[str, str | None]) -> str:
        parameters = self.graph.jobs[job_id].parameters
        rest = [
            name
            for name in self.varying
            if name in parameters and name not in own and name != self.lanes
        ]
        if not rest:
            return "the one run"
        return " · ".join(
            f"{self.words.parameter(name)} {self.words.value(name, parameters[name])}"
            for name in rest[-2:]
        )

    def status_of(self, counts: dict[str, int]) -> str:
        for status in (Status.RUNNING, Status.FAILED, Status.STALE, Status.MISSING):
            if counts[status.value]:
                return status.value
        return Status.DONE.value

    def numbers(self, rule: str, members: list[str]) -> dict[str, Any]:
        done = [
            self.facts[job]
            for job in members
            if self.facts[job].status in (Status.DONE, Status.STALE)
        ]
        seen: list[str] = []
        for item in done:
            for key, value in item.metrics.items():
                if key not in seen and truthy(value) is not None:
                    seen.append(key)
        keys = self.words.key_metrics(rule, seen)
        return {
            "usd": median(item.usd for item in done),
            "seconds": median(item.seconds for item in done),
            "total_usd": sum(item.usd or 0 for item in done),
            "metrics": [self.metric_summary(key, done) for key in keys],
        }

    def metric_summary(self, key: str, done: list[Facts]) -> dict[str, Any]:
        values = [item.metrics[key] for item in done if key in item.metrics]
        counted = [truthy(value) for value in values]
        whether = [value for value in counted if value is not None]
        label = self.words.metric(key)
        if not values:
            return {"name": key, "label": label, "text": "—"}
        if all(isinstance(value, bool) for value in values):
            return {
                "name": key,
                "label": label,
                "x": sum(whether),
                "y": len(whether),
                "text": f"{sum(whether)}/{len(whether)}",
            }
        numbers = [
            float(value)
            for value in values
            if isinstance(value, (int, float)) and not isinstance(value, bool)
        ]
        if numbers and len(numbers) == len(values):
            if len(numbers) == 1:
                return {"name": key, "label": label, "text": number(values[0])}
            return {
                "name": key,
                "label": label,
                "x": sum(whether),
                "y": len(whether),
                "text": f"{sum(whether)}/{len(whether)} above 0, median {number(statistics.median(numbers))}",
                "short": f"{sum(whether)}/{len(whether)}>0",
            }
        if len(values) == 1:
            return {"name": key, "label": label, "text": number(values[0])}
        return {"name": key, "label": label, "text": f"{len(values)} values"}

    def card(self, unit: Unit, label: str) -> dict[str, Any]:
        """What hovering a unit shows: a title, what it means, its parameters in words,
        its statuses and its numbers."""
        members = unit.jobs
        rule = unit.rule
        if len(members) == 1:
            return self.run_card(members[0])
        values: dict[str, set[str | None]] = {}
        for job_id in members:
            parameters = self.graph.jobs[job_id].parameters
            for name in self.varying:
                values.setdefault(name, set()).add(parameters.get(name))
        shared = [
            {
                "label": self.words.parameter(name),
                "value": self.words.value(name, next(iter(found))),
            }
            for name, found in values.items()
            if len(found) == 1 and next(iter(found)) is not None
        ]
        forked = [
            {
                "label": self.words.parameter(name),
                "value": f"{len(found)} values: "
                + ", ".join(
                    self.words.value(name, value) for value in sorted(found, key=natural)[:6]
                )
                + ("…" if len(found) > 6 else ""),
            }
            for name, found in values.items()
            if len(found) > 1
        ]
        counts = self.counts(members)
        status = ", ".join(
            f"{counts[status.value]} {STATUS_WORDS[status]}"
            for status in Status
            if counts[status.value]
        )
        numbers = self.numbers(rule, members)
        highlights = []
        done = counts[Status.DONE.value] + counts[Status.STALE.value]
        if done:
            highlights.append(
                f"{done} of {plural(len(members), 'run')} done: median {money(numbers['usd'])} and "
                f"{duration(numbers['seconds'])} each, {money(numbers['total_usd'])} in all."
            )
        for metric in numbers["metrics"]:
            if metric["text"] != "—":
                highlights.append(f"{metric['label'].capitalize()}: {metric['text']}.")
        failures = sorted(
            {
                self.facts[job].error or ""
                for job in members
                if self.facts[job].status is Status.FAILED
            }
            - {""}
        )
        if failures:
            highlights.append(
                f"Failed with: {'; '.join(line(item, 140) for item in failures[:3])}."
            )
        return {
            "title": " · ".join([self.words.title(rule), label]),
            "means": self.words.means(rule),
            "parameters": shared + forked,
            "status": status,
            "state": self.status_of(counts),
            "highlights": highlights,
        }

    def title(self, job_id: str) -> str:
        job = self.graph.jobs[job_id]
        own = [name for name in self.varying if name in job.parameters]
        words = [self.words.value(name, job.parameters[name]) for name in own]
        return " · ".join([self.words.title(job.rule), *words[-4:]])

    def run_card(self, job_id: str) -> dict[str, Any]:
        job = self.graph.jobs[job_id]
        facts = self.facts[job_id]
        status = STATUS_WORDS[facts.status]
        why = ""
        if facts.status is Status.STALE:
            why = self.why_stale(job)
            status += f": {why}"
        elif facts.status is Status.DONE and facts.where == "cache":
            status += ", in the cache: the next run restores it here"
        elif facts.status is Status.RUNNING and facts.since:
            status += f" since {facts.since}"
        elif facts.status is Status.FAILED and facts.error:
            status += f": {line(facts.error, 200)}"
        return {
            "title": self.title(job_id),
            "means": self.words.means(job.rule),
            "parameters": [
                {"label": self.words.parameter(name), "value": self.words.value(name, value)}
                for name, value in job.parameters.items()
                if name in self.varying
            ],
            "status": status,
            "state": facts.status.value,
            "highlights": self.highlights(job, facts),
            "output": job_id,
        }

    def highlights(self, job: Job, facts: Facts) -> list[str]:
        if facts.status in (Status.MISSING, Status.RUNNING):
            estimate = self.estimate(job)
            return (
                [f"Expected to cost about {money(estimate[0])} and take {duration(estimate[1])}."]
                if estimate[0] is not None or estimate[1] is not None
                else []
            )
        said = []
        spent = f"It cost {money(facts.usd)} in {duration(facts.seconds)}"
        if facts.tokens:
            spent += f", {facts.tokens:,} tokens"
        said.append(spent + ".")
        declared = self.words.rule(job.rule).get("highlights")
        values = {
            **{key: number(value) for key, value in facts.metrics.items()},
            **{name: self.words.value(name, value) for name, value in job.parameters.items()},
            "usd": money(facts.usd),
            "seconds": duration(facts.seconds),
        }
        if declared:
            for template in declared:
                try:
                    said.append(template.format_map(values))
                except (KeyError, ValueError, IndexError):
                    continue
        else:
            for key, value in list(facts.metrics.items())[:8]:
                said.append(f"{self.words.metric(key).capitalize()}: {number(value)}.")
        if facts.error:
            said.append(f"Error: {line(facts.error, 300)}")
        return said

    def why_stale(self, job: Job) -> str:
        """What changed since the output was made: its params against those Snakemake
        recorded then, else an earlier step's output, else its code or input files."""
        changed = self.changed_params(job)
        if changed:
            return "; ".join(changed[:4]) + (
                f" and {len(changed) - 4} more" if len(changed) > 4 else ""
            )
        stale_before = [
            before
            for before in job.after
            if before in self.facts and self.facts[before].status is Status.STALE
        ]
        if stale_before:
            return f"made from an earlier step that is stale ({self.title(stale_before[0])})"
        return "its step's code, or a file it reads, changed"

    def changed_params(self, job: Job) -> list[str]:
        record = record_path(self.scenario.directory / ".snakemake" / "metadata", job.id)
        metadata = read_json(record)
        old_params = metadata.get("params")
        if not isinstance(old_params, list) or not job.names:
            return []
        before: dict[str, Any] = {}
        for name, text in zip(job.names, old_params, strict=False):
            if name == "keyed":
                continue
            try:
                value = ast.literal_eval(text)
            except (ValueError, SyntaxError):
                continue
            flatten(value, name, before)
        changed = []
        for key in sorted(set(before) | set(job.params)):
            old, new = before.get(key), job.params.get(key)
            if old != new and not (
                isinstance(old, (int, float))
                and isinstance(new, (int, float))
                and float(old) == float(new)
            ):
                changed.append(f"{key} changed ({line(str(old), 24)} → {line(str(new), 24)})")
        return changed

    def detail(self, job_id: str) -> dict[str, Any]:
        """One run, for its card: everything the hover says, and its files."""
        card = self.run_card(job_id)
        job = self.graph.jobs[job_id]
        directory = self.scenario.directory / job_id
        if not directory.is_dir() and job.entry and (self.scenario.cache / job.entry).is_dir():
            directory = self.scenario.cache / job.entry
        files = []
        if directory.is_dir():
            for child in sorted(directory.iterdir()):
                if child.name.startswith("."):
                    continue
                try:
                    size = child.stat().st_size if child.is_file() else None
                except OSError:
                    size = None
                files.append({"name": child.name, "bytes": size, "directory": child.is_dir()})
        inputs = [
            {"label": key, "value": line(str(value), 80)}
            for key, value in job.params.items()
            if not (isinstance(value, str) and value.startswith(f"{RESULTS}/"))
        ]
        return card | {
            "files": files,
            "readable": directory == self.scenario.directory / job_id,
            "inputs": inputs[:40],
            "before": [
                {"id": before, "title": self.title(before)}
                for before in job.after
                if before in self.facts
            ],
            "path": [{"rule": job.rule, "run": job_id}],
        }

    # --- what if ------------------------------------------------------------------------

    def change_options(self) -> dict[str, list[dict[str, Any]]]:
        """What the page offers to change: each forking parameter's values, each input
        the steps' params carry (versions first), each file the steps read."""
        values = []
        for name in self.varying:
            found = sorted(
                {self.graph.jobs[job].parameters.get(name) for job in self.jobs} - {None},
                key=natural,
            )
            values += [
                {
                    "kind": "value",
                    "name": name,
                    "value": value,
                    "label": f"{self.words.parameter(name)} = {self.words.value(name, value)}",
                }
                for value in found
            ]
        keys: dict[str, set[str]] = {}
        for job_id in self.jobs:
            job = self.graph.jobs[job_id]
            for key, value in job.params.items():
                if isinstance(value, str) and value.startswith(f"{RESULTS}/"):
                    continue
                if key in job.parameters:
                    continue
                keys.setdefault(key, set()).add(job.rule)
        inputs = [
            {
                "kind": "input",
                "name": key,
                "label": f"{key} ({', '.join(self.words.title(rule) for rule in sorted(rules, key=self.columns.index))})",
            }
            for key, rules in sorted(
                keys.items(), key=lambda item: ("version" not in item[0], item[0])
            )
        ]
        code: dict[str, set[str]] = {}
        for job_id in self.jobs:
            job = self.graph.jobs[job_id]
            for path in [*([job.script] if job.script else []), *job.sources]:
                code.setdefault(path, set()).add(job.rule)
        files = [
            {
                "kind": "code",
                "name": path,
                "label": f"{path} ({', '.join(self.words.title(rule) for rule in sorted(rules, key=self.columns.index))})",
            }
            for path, rules in sorted(code.items())
        ]
        return {"values": values, "inputs": inputs, "code": files}

    def affected(self, change: Change) -> set[str]:
        """The jobs a change reruns: those it touches, and everything made from them."""
        kind, name = change["kind"], change["name"]
        if kind not in ("value", "input", "code"):
            raise UsageError(f"a change is a `value`, an `input` or `code`, not `{kind}`")

        def touches(job: Job) -> bool:
            if kind == "value":
                return job.parameters.get(name) == change.get("value")
            if kind == "input":
                return name in job.params
            return job.script == name or name in job.sources

        touched = {job_id for job_id in self.jobs if touches(self.graph.jobs[job_id])}
        return (touched | self.graph.descendants(touched, self.children)) & self.jobs

    def estimate(self, job: Job) -> tuple[float | None, float | None]:
        usd, seconds = self.medians.get(job.rule, (None, None))
        return (usd if usd is not None else job.estimate_usd, seconds)

    def change_json(self, change: Change, affected: set[str]) -> dict[str, Any]:
        done = [
            job
            for job in affected
            if self.facts[job].status in (Status.DONE, Status.STALE, Status.FAILED)
        ]
        usd = 0.0
        seconds = 0.0
        unknown: set[str] = set()
        for job_id in affected:
            cost, time_taken = self.estimate(self.graph.jobs[job_id])
            if cost is None:
                unknown.add(self.graph.jobs[job_id].rule)
            usd += cost or 0
            seconds += time_taken or 0
        by_rule: dict[str, int] = {}
        for job_id in affected:
            rule = self.graph.jobs[job_id].rule
            by_rule[rule] = by_rule.get(rule, 0) + 1
        if change["kind"] == "value":
            what = f"{self.words.parameter(change['name'])} = {self.words.value(change['name'], change.get('value'))}"
        else:
            what = change["name"]
        return {
            "change": change,
            "words": f"Changing {what} reruns {plural(len(affected), 'step')}"
            + (f", {len(done)} of them done now" if done else "")
            + f": about {money(usd)} and {duration(seconds)} of compute"
            + (f" (no estimate for {', '.join(sorted(unknown))})" if unknown else "")
            + ".",
            "count": len(affected),
            "done": len(done),
            "usd": usd,
            "seconds": seconds,
            "rules": [
                {"rule": rule, "title": self.words.title(rule), "count": by_rule[rule]}
                for rule in self.columns
                if rule in by_rule
            ],
        }

    # --- the comparisons ------------------------------------------------------------------

    def analyses(self) -> list[dict[str, Any]]:
        """The scenario's declared comparisons, counted; without any, a suggestion per rule
        whose numbers count: its first such metric by the rows' parameter."""
        declared = self.words.words.get("analyses")
        if declared:
            return [self.analysis(item, suggested=False) for item in declared]
        found = []
        if self.lanes is None:
            return found
        for rule in self.columns:
            done = [
                self.facts[job]
                for job in self.jobs
                if self.graph.jobs[job].rule == rule
                and self.facts[job].status is Status.DONE
                and self.lanes in self.graph.jobs[job].parameters
            ]
            if not done:
                continue
            seen: list[str] = []
            for item in done:
                for key, value in item.metrics.items():
                    if key not in seen and truthy(value) is not None:
                        seen.append(key)
            # A yes-or-no count reads best as x/y: those first.
            flags = [
                key
                for key in seen
                if all(isinstance(item.metrics.get(key, False), bool) for item in done)
            ]
            keys = [
                key
                for key in self.words.key_metrics(rule, list(dict.fromkeys(flags + seen)))
                if key in seen
            ]
            for key in keys[:1]:
                found.append(
                    self.analysis({"step": rule, "by": self.lanes, "metric": key}, suggested=True)
                )
        return found

    def analysis(self, item: Analysis, suggested: bool) -> dict[str, Any]:
        step, by, metric = item["step"], item["by"], item["metric"]
        where = item.get("where", {})
        rows: dict[str | None, dict[str, Any]] = {}
        for job_id in self.jobs:
            job = self.graph.jobs[job_id]
            if job.rule != step or any(
                job.parameters.get(key) != value for key, value in where.items()
            ):
                continue
            value = job.parameters.get(by)
            row = rows.setdefault(
                value, {"x": 0, "y": 0, "total": 0.0, "failed": 0, "pending": 0, "runs": 0}
            )
            row["runs"] += 1
            facts = self.facts[job_id]
            if facts.status is Status.FAILED:
                row["failed"] += 1
            elif facts.status is not Status.DONE:
                row["pending"] += 1
            elif metric in facts.metrics:
                counted = truthy(facts.metrics[metric])
                if counted is not None:
                    row["y"] += 1
                    row["x"] += int(counted)
                    raw = facts.metrics[metric]
                    row["total"] += float(raw)
        ordered = sorted(rows, key=natural)
        baseline = item.get("baseline")
        first = baseline if baseline in rows else (ordered[0] if ordered else None)
        label = self.words.metric(metric)
        table = [
            {
                "value": value,
                "label": self.words.value(by, value),
                "x": rows[value]["x"],
                "y": rows[value]["y"],
                "total": rows[value]["total"],
                "failed": rows[value]["failed"],
                "pending": rows[value]["pending"],
                "baseline": value == first,
                "path": [{"rule": step, "filter": {**where, by: value}}],
            }
            for value in ordered
        ]
        others = [row for row in table if not row["baseline"]]
        base = next((row for row in table if row["baseline"]), None)
        sentence = ""
        if base is not None and others:
            sentence = (
                f"{label.capitalize()}: "
                + "; ".join(f"{row['label']} {row['x']}/{row['y']}" for row in others)
                + f", against {base['label']} {base['x']}/{base['y']}."
            )
        elif base is not None:
            sentence = f"{label.capitalize()}: {base['label']} {base['x']}/{base['y']}."
        pending = sum(row["pending"] for row in table)
        if pending:
            sentence += f" {plural(pending, 'run')} not done yet."
        return {
            "name": item.get("name")
            or f"{label.capitalize()} by {self.words.parameter(by)}, in {self.words.title(step)}",
            "suggested": suggested,
            "step": step,
            "by": by,
            "by_label": self.words.parameter(by),
            "metric": metric,
            "metric_label": label,
            "where": [
                {"label": self.words.parameter(key), "value": self.words.value(key, value)}
                for key, value in where.items()
            ],
            "sentence": sentence,
            "rows": table,
        }


def flatten(value: Any, prefix: str, into: dict[str, Any]) -> None:
    """A params value as GRAPH flattens it: `node.versions.cli`."""
    if isinstance(value, dict) and value:
        for key, item in value.items():
            flatten(item, f"{prefix}.{key}" if prefix else str(key), into)
    elif isinstance(value, (str, int, float, bool)) or value is None:
        into[prefix] = value
    else:
        into[prefix] = json.dumps(value, default=str)[:200]


def natural(value: str | None) -> tuple[int, float, str]:
    """Numbers in their order, before words in theirs; the missing last."""
    if value is None:
        return (2, 0.0, "")
    try:
        return (0, float(value), "")
    except ValueError:
        return (1, 0.0, value)


def line(text: str, limit: int) -> str:
    one = " ".join(text.split())
    return one if len(one) <= limit else one[: limit - 1] + "…"
