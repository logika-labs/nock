"""What the Experiment tab is drawn from (`nock.experiments`): a scenario's
jobs, as Snakemake describes them, with each job's status read live from the
files.

Snakemake describes the jobs once (`GRAPH`: every job, its parameters, inputs,
the jobs before it and its cache entry), which takes as long as a dry run; the
description is kept in `.nock/local/evals/` under a fingerprint of what shapes
it (the scenario's files, the checkout's commit and changes, the checkpoints
done) and derived again in the background when that changes. Statuses come
from the results, the cache and Snakemake's own state — its lock, its
incomplete markers and the log of the run going on — so a page polls them
cheaply while a run goes. Nothing here runs a step or writes outside
`.nock/local/`. How a scenario is worded (its question, titles, what a rule
means and what its outputs hold, parameter labels, decisions) is the optional
`evals/NAME/studio.json`; without it, a rule means the comment above it in the
Snakefile."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import subprocess
import threading
import time
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from functools import cached_property
from pathlib import Path
from typing import Any, NotRequired, TypedDict

from nock.commands import schema_of
from nock.errors import PreconditionError, UsageError
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
    """The step's title: `Observation`."""
    means: NotRequired[str]
    """What one of its outputs is, in a sentence; the comment above the rule by default."""
    results: NotRequired[list[ResultWords]]
    """What one of its outputs holds; its metrics and diff.patch by default."""
    score: NotRequired[ScoreWords]
    """The metric that scores one of its outputs."""


class ParameterWords(TypedDict):
    label: NotRequired[str]
    """What the parameter is: `Instrumentation setup`."""
    values: NotRequired[dict[str, str]]
    """Its values in words: `{"none": "no skill"}`."""
    about: NotRequired[str]
    """What it is, in a sentence."""
    pooled: NotRequired[bool]
    """Added up rather than compared, like a bug in a bank: the experiment's variants
    are the values of the parameters that are not."""
    repeat: NotRequired[bool]
    """It repeats a step (`rep` by default)."""
    controls: NotRequired[list[str]]
    """Its values that are a control, not a case: `["none"]` for no bug."""


class Words(TypedDict):
    """`evals/NAME/studio.json`: how the studio words a scenario. Every key is optional."""

    rules: NotRequired[dict[str, RuleWords]]
    parameters: NotRequired[dict[str, ParameterWords]]
    metrics: NotRequired[dict[str, str]]
    """Labels of metrics.json's keys."""
    question: NotRequired[str]
    """What the experiment asks."""
    decisions: NotRequired[list[Decision]]
    """Code over a step's metrics that picks a branch."""


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


@dataclass
class Activity:
    """A Snakemake run going on in the scenario, from its lock and its log."""

    active: bool = False
    running: dict[str, str] = field(default_factory=dict)
    """Output → when its job started, by the log."""
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
        activity = Activity(active=active, running=dict(self.parsed.running) if active else {})
        if active and (self.state / "incomplete").is_dir():
            activity.incomplete = set(recorded(self.state / "incomplete"))
        return activity

    def line(self, line: str) -> None:
        parsed = self.parsed
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


# --- the explorer --------------------------------------------------------------------------


class Explorer:
    """One scenario's description, kept and refreshed in the background, and its
    statuses read on demand."""

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
