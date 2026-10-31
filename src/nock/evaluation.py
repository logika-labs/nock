"""Evaluations (`nock eval`): a scenario in `evals/NAME/` is an ordered chain
of steps, each turning the snapshot before it into the next while reading
named parameters. A snapshot is named by a short hash of its identity — the
step, the parameter values read up to it, and the content digests of those
values' files and of the steps' code — so a run reuses every snapshot whose
identity still matches and computes the rest; one whose digests no longer
match is stale, kept and marked. Comparing leaves is `nock.comparison`; the
step's own side, run in a process of its own, is `nock.steps`."""

from __future__ import annotations

import ast
import hashlib
import itertools
import json
import os
import secrets
import shutil
import subprocess
import sys
import threading
from collections.abc import Iterator
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from functools import cached_property
from pathlib import Path
from typing import TYPE_CHECKING, Any

from nock.errors import NotFoundError, PreconditionError, UsageError
from nock.git import Git, GitError
from nock.processes import Supervisor
from nock.schema import Validator
from nock.utils import format_duration, now, read_json, write_json

if TYPE_CHECKING:
    from nock.project import Project

SCENARIOS = "evals"
HASH_LENGTH = 12
# What an assignment may carry beside parameter values; no parameter takes these names.
RESERVED = ("scenario", "budget_usd")
# Never part of a digest or a manifest: caches and git's own bookkeeping.
UNHASHED = ("__pycache__", ".git", ".DS_Store")
LFS_POINTER = b"version https://git-lfs.github.com/spec/v1"
# The names of the calls a step's code reads a parameter through.
READERS = ("value", "file", "files")
PARALLEL = 4

GITATTRIBUTES = """\
# Snapshot artefacts: small ones are committed as they are. Keep big ones in
# Git LFS (`git lfs install` once per machine) by uncommenting a line:
# snapshots/*/artefacts/** filter=lfs diff=lfs merge=lfs -text
# snapshots/*/artefacts/**/*.tar filter=lfs diff=lfs merge=lfs -text
"""
GITIGNORE = """\
# Or leave snapshot artefacts out of git, each machine keeping its own (results
# and manifests are still committed; a clone is told what it lacks):
# snapshots/*/artefacts/
"""

ESTIMATE: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {"seconds": {"type": "number"}, "cost_usd": {"type": "number"}},
}
GLOBS: dict[str, Any] = {
    "anyOf": [{"type": "string"}, {"type": "array", "items": {"type": "string"}}]
}
SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["steps", "parameters"],
    "additionalProperties": False,
    "properties": {
        "description": {"type": "string"},
        "steps": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["name"],
                "additionalProperties": False,
                "properties": {
                    "name": {"type": "string", "pattern": "^[a-z0-9][a-z0-9_-]*$"},
                    "description": {"type": "string"},
                    "reads": {"type": "array", "items": {"type": "string"}},
                    "code": GLOBS,
                    "deadline": {"type": "number"},
                    "silence": {"type": "number"},
                    "estimate": ESTIMATE,
                },
            },
        },
        "parameters": {
            "type": "object",
            "additionalProperties": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "description": {"type": "string"},
                    "files": {"type": "string"},
                    "values": {
                        "anyOf": [
                            {"type": "array"},
                            {"type": "object", "additionalProperties": GLOBS},
                        ]
                    },
                },
            },
        },
    },
}


class Outcome(StrEnum):
    """What became of a node in a plan or a run."""

    REUSED = "reused"
    COMPUTE = "compute"
    COMPUTED = "computed"
    FAILED = "failed"
    """The step ran and failed, now or in an earlier run: a result, with its log."""
    BLOCKED = "blocked"
    """The snapshot before failed, or its artefacts are not in this checkout."""
    OVER_BUDGET = "over budget"


def digest_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def short_hash(identity: dict[str, Any]) -> str:
    canonical = json.dumps(identity, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return digest_bytes(canonical.encode())[:HASH_LENGTH]


def files_under(path: Path) -> Iterator[Path]:
    """`path` itself when it is a file; every file under it when a directory."""
    if path.is_file():
        yield path
        return
    for found in sorted(path.rglob("*")):
        if found.is_file() and not any(part in UNHASHED for part in found.parts):
            yield found


def is_lfs_pointer(path: Path) -> bool:
    try:
        with path.open("rb") as handle:
            return handle.read(len(LFS_POINTER)) == LFS_POINTER
    except OSError:
        return False


def manifest(directory: Path) -> list[dict[str, Any]]:
    """Every artefact in `directory`: its path, digest and size."""
    if not directory.is_dir():
        return []
    return [
        {
            "path": path.relative_to(directory).as_posix(),
            "digest": digest_bytes(path.read_bytes()),
            "bytes": path.stat().st_size,
        }
        for path in files_under(directory)
    ]


def value_key(value: Any) -> str:
    """How a value is named in an assignment and on a page: `none`, `3`, `true`."""
    return value if isinstance(value, str) else json.dumps(value)


@dataclass
class Value:
    """One value a parameter takes: a literal, or a name and the files that are it."""

    value: Any
    files: list[Path] = field(default_factory=list)

    @property
    def key(self) -> str:
        return value_key(self.value)


@dataclass
class Parameter:
    name: str
    description: str
    values: dict[str, Value]
    from_files: bool
    """Its values are files (or directories), so its identity is their content."""
    problems: list[str] = field(default_factory=list)


@dataclass
class Definition:
    """A step as scenario.json declares it."""

    name: str
    description: str
    reads: list[str]
    code: list[str]
    deadline: float | None
    silence: float | None
    estimate: dict[str, float]


class Scenario:
    """One scenario: its steps, its parameters and the digests that name its
    snapshots. `drafts` maps paths in the scenario's directory to text that
    stands in for those files, so a change can be weighed before it is made."""

    def __init__(self, project: Project, name: str, drafts: dict[str, str] | None = None) -> None:
        self.project = project
        self.name = name
        self.directory = project.here / SCENARIOS / name
        self.drafts = {key.removeprefix("./"): value for key, value in (drafts or {}).items()}
        if not (self.directory / "scenario.json").is_file():
            raise NotFoundError(f"no scenario `{name}`: {SCENARIOS}/{name}/scenario.json")
        self.lock = threading.Lock()
        self.digests: dict[str, str] = {}

    @property
    def snapshots_directory(self) -> Path:
        return self.directory / "snapshots"

    @property
    def runs_directory(self) -> Path:
        return self.directory / "runs"

    def read_bytes(self, path: Path) -> bytes:
        relative = path.relative_to(self.directory).as_posix() if self.inside(path) else None
        if relative is not None and relative in self.drafts:
            return self.drafts[relative].encode()
        return path.read_bytes()

    def inside(self, path: Path) -> bool:
        return path.is_relative_to(self.directory)

    @cached_property
    def definition(self) -> dict[str, Any]:
        text = self.read_bytes(self.directory / "scenario.json").decode()
        try:
            value = json.loads(text)
        except json.JSONDecodeError as error:
            raise PreconditionError(f"{self.name}/scenario.json is not JSON: {error}") from error
        problems = Validator().problems(value, SCHEMA)
        if problems:
            raise PreconditionError(f"{self.name}/scenario.json: {'; '.join(problems)}")
        return value

    @cached_property
    def steps(self) -> list[Definition]:
        return [
            Definition(
                name=step["name"],
                description=step.get("description", ""),
                reads=list(step.get("reads", [])),
                code=globs(step.get("code", [])),
                deadline=step.get("deadline"),
                silence=step.get("silence"),
                estimate=dict(step.get("estimate", {})),
            )
            for step in self.definition["steps"]
        ]

    @cached_property
    def parameters(self) -> dict[str, Parameter]:
        return {
            name: self.parameter(name, declared)
            for name, declared in self.definition["parameters"].items()
        }

    def parameter(self, name: str, declared: dict[str, Any]) -> Parameter:
        description = str(declared.get("description", ""))
        if "files" in declared:
            values: dict[str, Value] = {}
            problems = []
            for path in self.glob(str(declared["files"])):
                if path.name.startswith("."):
                    continue
                named = path.name if path.is_dir() else path.stem
                if named in values:
                    problems.append(f"`{name}`: two files are the value `{named}`")
                values[named] = Value(named, [path])
            return Parameter(name, description, values, True, problems)
        given = declared.get("values", [])
        if isinstance(given, dict):
            return Parameter(
                name,
                description,
                {
                    key: Value(
                        key, [path for pattern in globs(patterns) for path in self.glob(pattern)]
                    )
                    for key, patterns in given.items()
                },
                True,
            )
        literals = {value_key(value): Value(value) for value in given}
        return Parameter(name, description, literals, False)

    def glob(self, pattern: str) -> list[Path]:
        """A pattern is the scenario directory's; one starting with `/` is the working tree's."""
        base = self.project.here if pattern.startswith("/") else self.directory
        pattern = pattern.lstrip("/")
        if not pattern:
            return [base]
        return sorted(path for path in base.glob(pattern) if path.name not in UNHASHED)

    def step_index(self, name: str) -> int | None:
        return next((index for index, step in enumerate(self.steps) if step.name == name), None)

    def reads_through(self, index: int) -> list[str]:
        """The parameters read by the steps up to `index`, in the order first read."""
        seen: list[str] = []
        for step in self.steps[: index + 1]:
            seen += [name for name in step.reads if name not in seen]
        return seen

    def step_file(self, step: Definition) -> Path:
        return self.directory / "steps" / f"{step.name}.py"

    def step_digest(self, step: Definition) -> str:
        files = [
            self.step_file(step),
            *(path for pattern in step.code for path in self.glob(pattern)),
        ]
        return self.digest_of(f"step:{step.name}", files)

    def value_digest(self, parameter: str, value: Value) -> str:
        return self.digest_of(f"value:{parameter}={value.key}", value.files)

    def digest_of(self, key: str, paths: list[Path]) -> str:
        with self.lock:
            if key in self.digests:
                return self.digests[key]
        hasher = hashlib.sha256()
        for path in paths:
            base = path if path.is_dir() else path.parent
            for found in files_under(path) if path.exists() else []:
                where = (
                    self.relative(found) if path.is_file() else found.relative_to(base).as_posix()
                )
                hasher.update(f"{where}\0{digest_bytes(self.read_bytes(found))}\n".encode())
        digest = hasher.hexdigest()[:16]
        with self.lock:
            self.digests[key] = digest
        return digest

    def relative(self, path: Path) -> str:
        if self.inside(path):
            return path.relative_to(self.directory).as_posix()
        return "/" + path.relative_to(self.project.here).as_posix()

    def identity(self, index: int, chosen: dict[str, Value]) -> dict[str, Any]:
        """What names the snapshot after step `index` for these values."""
        reads = self.reads_through(index)
        return {
            "step": self.steps[index].name,
            "parameters": {name: chosen[name].value for name in reads},
            "digests": {
                "parameters": {
                    name: self.value_digest(name, chosen[name])
                    for name in reads
                    if self.parameters[name].from_files
                },
                "steps": [
                    {"step": step.name, "digest": self.step_digest(step)}
                    for step in self.steps[: index + 1]
                ],
            },
        }

    # --- the check -------------------------------------------------------------

    def problems(self) -> list[str]:
        """What is wrong with the scenario itself: its file, its steps, what they read."""
        try:
            steps, parameters = self.steps, self.parameters
        except PreconditionError as error:
            return [str(error)]
        problems = [
            f"{self.name}: {problem}" for item in parameters.values() for problem in item.problems
        ]
        for name, parameter in parameters.items():
            if name in RESERVED:
                problems.append(
                    f"{self.name}: `{name}` is reserved in an assignment; rename the parameter"
                )
            if not parameter.values:
                problems.append(f"{self.name}: parameter `{name}` has no values")
            for value in parameter.values.values():
                if parameter.from_files and not value.files:
                    problems.append(f"{self.name}: `{name}={value.key}` matches no file")
        seen: set[str] = set()
        for index, step in enumerate(steps):
            if step.name in seen:
                problems.append(f"{self.name}: two steps are named `{step.name}`")
            seen.add(step.name)
            undeclared = [name for name in step.reads if name not in parameters]
            if undeclared:
                problems.append(
                    f"{self.name}: step `{step.name}` reads {', '.join(undeclared)}, which scenario.json does not declare"
                )
            path = self.step_file(step)
            if not path.is_file():
                problems.append(f"{self.name}: step `{step.name}` has no {self.relative(path)}")
                continue
            problems += [
                f"{self.name}: {self.relative(path)}: {problem}"
                for problem in code_problems(
                    self.read_bytes(path).decode(), self.reads_through(index)
                )
            ]
        read = {name for step in steps for name in step.reads}
        problems += [
            f"{self.name}: no step reads parameter `{name}`"
            for name in parameters
            if name not in read
        ]
        return problems

    # --- assignments ------------------------------------------------------------

    def choose(self, assignment: dict[str, Any]) -> dict[str, list[Value]]:
        """Each parameter's values in this assignment: a value, a list, or `*`
        for all; a parameter with one value needs no mention."""
        unknown = [
            name for name in assignment if name not in self.parameters and name not in RESERVED
        ]
        if unknown:
            raise UsageError(
                f"{self.name} has no parameter {', '.join(unknown)}; it has: {', '.join(self.parameters)}"
            )
        chosen: dict[str, list[Value]] = {}
        for name, parameter in self.parameters.items():
            if name not in assignment:
                if len(parameter.values) != 1:
                    raise UsageError(
                        f'the assignment leaves `{name}` open: give a value, a list or "*" '
                        f"(its values: {', '.join(parameter.values)})"
                    )
                chosen[name] = list(parameter.values.values())
                continue
            given = assignment[name]
            if given == "*":
                chosen[name] = list(parameter.values.values())
                continue
            picked = []
            for item in given if isinstance(given, list) else [given]:
                value = parameter.values.get(value_key(item)) or parameter.values.get(str(item))
                if value is None:
                    raise UsageError(
                        f"`{name}` has no value {value_key(item)}; its values: {', '.join(parameter.values)}"
                    )
                if value not in picked:
                    picked.append(value)
            chosen[name] = picked
        return chosen

    def values_of(self, parameters: dict[str, Any]) -> dict[str, Value] | None:
        """The `Value`s a snapshot's parameters name, or None when one is gone."""
        found = {}
        for name, value in parameters.items():
            parameter = self.parameters.get(name)
            item = parameter.values.get(value_key(value)) if parameter else None
            if item is None:
                return None
            found[name] = item
        return found


def globs(value: str | list[str]) -> list[str]:
    return [value] if isinstance(value, str) else list(value)


def code_problems(source: str, readable: list[str]) -> list[str]:
    """A step's code: a `run(step)`, reading only the parameters read up to it
    (`step.value("x")`, `step.file("x")`, `step.files("x")`, `step.parameters["x"]`)."""
    try:
        tree = ast.parse(source)
    except SyntaxError as error:
        return [f"does not parse: {error.msg} (line {error.lineno})"]
    problems = []
    if not any(isinstance(node, ast.FunctionDef) and node.name == "run" for node in tree.body):
        problems.append("defines no `run(step)`")
    for node in ast.walk(tree):
        name = None
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in READERS
            and node.args
            and isinstance(node.args[0], ast.Constant)
        ):
            name = node.args[0].value
        elif (
            isinstance(node, ast.Subscript)
            and isinstance(node.value, ast.Attribute)
            and node.value.attr == "parameters"
            and isinstance(node.slice, ast.Constant)
        ):
            name = node.slice.value
        if isinstance(name, str) and name not in readable:
            problems.append(
                f"line {getattr(node, 'lineno', 0)} reads `{name}`, which neither this step nor one before it reads"
            )
    return problems


class Snapshot:
    """A snapshot on disk: `snapshots/HASH/snapshot.json`, and its artefacts beside it."""

    def __init__(self, directory: Path, data: dict[str, Any]) -> None:
        self.directory = directory
        self.data = data

    @property
    def hash(self) -> str:
        return self.directory.name

    @property
    def step(self) -> str:
        return str(self.data.get("step", ""))

    @property
    def parameters(self) -> dict[str, Any]:
        return dict(self.data.get("parameters", {}))

    @property
    def failed(self) -> bool:
        return self.data.get("status") == Outcome.FAILED

    @property
    def artefacts(self) -> Path:
        return self.directory / "artefacts"

    def label(self) -> str:
        values = " ".join(f"{name}={value_key(value)}" for name, value in self.parameters.items())
        return f"{self.step} {values}".strip()

    def missing(self) -> list[dict[str, str]]:
        """The artefacts its manifest names that this checkout lacks, and why."""
        found = []
        for entry in self.data.get("artefacts", []):
            path = self.artefacts / entry["path"]
            if not path.is_file():
                found.append({"path": entry["path"], "why": "absent"})
            elif path.stat().st_size != entry["bytes"] and is_lfs_pointer(path):
                found.append(
                    {"path": entry["path"], "why": "in Git LFS, not fetched (git lfs pull)"}
                )
            elif path.stat().st_size != entry["bytes"]:
                found.append({"path": entry["path"], "why": "changed since it was made"})
        return found


class Snapshots:
    """A scenario's snapshots, and which of them are stale."""

    def __init__(self, scenario: Scenario) -> None:
        self.scenario = scenario

    def all(self) -> list[Snapshot]:
        found = []
        directory = self.scenario.snapshots_directory
        for path in sorted(directory.glob("*/snapshot.json")) if directory.is_dir() else []:
            try:
                found.append(Snapshot(path.parent, read_json(path)))
            except PreconditionError:
                found.append(Snapshot(path.parent, {}))
        return found

    def get(self, hash: str) -> Snapshot | None:
        path = self.scenario.snapshots_directory / hash / "snapshot.json"
        if not path.is_file():
            return None
        return Snapshot(path.parent, read_json(path))

    def staleness(self, snapshot: Snapshot) -> str | None:
        """Why the snapshot no longer matches the scenario, or None when it does."""
        scenario = self.scenario
        index = scenario.step_index(snapshot.step)
        if index is None:
            return f"the scenario has no step `{snapshot.step}` now"
        reads = scenario.reads_through(index)
        if sorted(reads) != sorted(snapshot.parameters):
            return f"the steps up to `{snapshot.step}` read {', '.join(reads) or 'nothing'} now"
        chosen = scenario.values_of(snapshot.parameters)
        if chosen is None:
            return "one of its parameter values is gone"
        current = scenario.identity(index, chosen)
        if short_hash(current) == snapshot.hash:
            return None
        recorded = snapshot.data.get("digests", {})
        changed = [
            f"{name}={value_key(snapshot.parameters[name])}"
            for name, digest in current["digests"]["parameters"].items()
            if recorded.get("parameters", {}).get(name) != digest
        ]
        was = {entry["step"]: entry["digest"] for entry in recorded.get("steps", [])}
        steps = [entry["step"] for entry in current["digests"]["steps"]]
        if steps != [entry["step"] for entry in recorded.get("steps", [])]:
            return f"the steps up to `{snapshot.step}` are now {', '.join(steps)}"
        changed += [
            f"step `{entry['step']}`"
            for entry in current["digests"]["steps"]
            if was.get(entry["step"]) != entry["digest"]
        ]
        return (
            f"changed since: {', '.join(changed)}" if changed else "its identity no longer matches"
        )

    def prunable(self) -> list[tuple[Snapshot, str]]:
        """Stale and failed snapshots, with why."""
        found = []
        for snapshot in self.all():
            stale = self.staleness(snapshot)
            if stale:
                found.append((snapshot, f"stale: {stale}"))
            elif snapshot.failed:
                found.append((snapshot, "failed"))
        return found

    def problems(self) -> list[str]:
        """Snapshots whose name no longer fits their identity, and committed
        ones whose artefacts are not where their manifests say."""
        problems = []
        snapshots = self.all()
        tracked = tracked_files(self.scenario.project.here, self.scenario.snapshots_directory)
        unaccounted: list[tuple[Snapshot, str, str]] = []
        for snapshot in snapshots:
            name = f"{self.scenario.name}: snapshot {snapshot.hash}"
            if not snapshot.data:
                problems.append(f"{name}: snapshot.json is not readable JSON")
                continue
            identity = {key: snapshot.data.get(key) for key in ("step", "parameters", "digests")}
            if short_hash(identity) != snapshot.hash:
                problems.append(
                    f"{name}: its identity hashes to {short_hash(identity)}, not its name"
                )
            if self.relative(snapshot.directory / "snapshot.json") not in tracked:
                continue
            for entry in snapshot.data.get("artefacts", []):
                file = snapshot.artefacts / entry["path"]
                path = self.relative(file)
                if path not in tracked or not file.is_file():
                    unaccounted.append((snapshot, entry["path"], path))
        ignored = ignored_files(self.scenario.project.here, [path for _, _, path in unaccounted])
        for snapshot, artefact, path in unaccounted:
            if path in ignored:
                continue
            where = (
                "is not committed" if (snapshot.artefacts / artefact).is_file() else "is missing"
            )
            problems.append(
                f"{self.scenario.name}: snapshot {snapshot.hash} ({snapshot.label()}) is committed, "
                f"but its artefact {artefact} {where}"
            )
        return problems

    def relative(self, path: Path) -> str:
        return path.relative_to(self.scenario.project.here).as_posix()


def tracked_files(root: Path, directory: Path) -> set[str]:
    if not directory.is_dir():
        return set()
    try:
        listed = Git(root)("ls-files", "-z", "--", str(directory.relative_to(root)))
    except GitError:
        return set()
    return {path for path in listed.split("\0") if path}


def ignored_files(root: Path, paths: list[str]) -> set[str]:
    if not paths:
        return set()
    result = subprocess.run(
        ["git", "check-ignore", "--no-index", "--stdin", "-z"],
        cwd=root,
        input="\0".join(paths),
        capture_output=True,
        text=True,
    )
    return {path for path in result.stdout.split("\0") if path}


class Runs:
    """A scenario's runs: `runs/ID/run.json`, each keeping its own numbers."""

    def __init__(self, scenario: Scenario) -> None:
        self.scenario = scenario

    def all(self) -> list[dict[str, Any]]:
        directory = self.scenario.runs_directory
        found = []
        for path in sorted(directory.glob("*/run.json")) if directory.is_dir() else []:
            try:
                found.append(read_json(path))
            except PreconditionError:
                continue
        return found

    def get(self, identifier: str) -> dict[str, Any] | None:
        path = self.scenario.runs_directory / identifier / "run.json"
        return read_json(path) if path.is_file() else None

    def through(self) -> dict[str, list[str]]:
        """Snapshot → the runs that reused or computed it."""
        found: dict[str, list[str]] = {}
        for run in self.all():
            for node in run.get("nodes", []):
                if node.get("outcome") in (Outcome.REUSED, Outcome.COMPUTED, Outcome.FAILED):
                    found.setdefault(node["snapshot"], []).append(run["id"])
        return found


# --- plans and runs ---------------------------------------------------------------


@dataclass
class Node:
    """One snapshot an assignment calls for: a step and the values read up to it."""

    index: int
    step: Definition
    chosen: dict[str, Value]
    hash: str
    parent: Node | None
    children: list[Node] = field(default_factory=list)
    outcome: Outcome = Outcome.COMPUTE
    why: str = ""
    seconds: float | None = None
    cost: float | None = None
    results: dict[str, Any] | None = None

    @property
    def parameters(self) -> dict[str, Any]:
        return {name: value.value for name, value in self.chosen.items()}

    def label(self, new_only: bool = False) -> str:
        reads = self.step.reads if new_only else list(self.chosen)
        known = self.parent.chosen if new_only and self.parent else {}
        values = " ".join(
            f"{name}={self.chosen[name].key}"
            for name in reads
            if name in self.chosen and name not in known
        )
        return f"{self.step.name} {values}".strip()

    def descendants(self) -> Iterator[Node]:
        for child in self.children:
            yield child
            yield from child.descendants()


@dataclass
class Estimate:
    seconds: float
    cost: float
    known: bool


class Plan:
    """The tree an assignment makes of a scenario: a node per snapshot, each
    reused or to compute, with the estimate of what computing costs."""

    def __init__(self, scenario: Scenario, assignment: dict[str, Any]) -> None:
        self.scenario = scenario
        self.assignment = assignment
        budget = assignment.get("budget_usd")
        if budget is not None and not isinstance(budget, (int, float)):
            raise UsageError("`budget_usd` is a number of dollars")
        self.budget: float | None = float(budget) if budget is not None else None
        if not scenario.steps:
            raise PreconditionError(f"{scenario.name} has no steps yet: add them to scenario.json")
        self.chosen = scenario.choose(assignment)
        self.snapshots = Snapshots(scenario)
        self.roots = self.expand(0, {}, None)
        self.nodes = [node for root in self.roots for node in [root, *root.descendants()]]
        self.estimates = self.history()

    def expand(self, index: int, chosen: dict[str, Value], parent: Node | None) -> list[Node]:
        step = self.scenario.steps[index]
        new = [name for name in step.reads if name not in chosen]
        nodes = []
        for combination in itertools.product(*(self.chosen[name] for name in new)):
            values = {**chosen, **dict(zip(new, combination, strict=True))}
            hash = short_hash(self.scenario.identity(index, values))
            node = Node(index, step, values, hash, parent)
            existing = self.snapshots.get(hash)
            if existing is not None:
                node.outcome = Outcome.FAILED if existing.failed else Outcome.REUSED
                node.seconds = existing.data.get("seconds")
                node.cost = existing.data.get("cost_usd")
                node.results = existing.data.get("results")
            elif parent is not None and parent.outcome in (Outcome.FAILED, Outcome.BLOCKED):
                node.outcome = Outcome.BLOCKED
                node.why = f"`{parent.label()}` " + (
                    "failed" if parent.outcome is Outcome.FAILED else "is blocked"
                )
            elif parent is not None and parent.outcome is Outcome.REUSED:
                missing = self.snapshots.get(parent.hash)
                lacking = missing.missing() if missing else []
                if lacking:
                    node.outcome = Outcome.BLOCKED
                    node.why = (
                        f"snapshot {parent.hash} lacks {len(lacking)} artefact(s) here: "
                        + "; ".join(f"{item['path']} ({item['why']})" for item in lacking[:3])
                    )
            if index + 1 < len(self.scenario.steps):
                node.children = self.expand(index + 1, values, node)
            nodes.append(node)
        return nodes

    def history(self) -> dict[str, Estimate]:
        """Each step's mean time and cost over the snapshots it made, else its declared estimate."""
        made: dict[str, list[Snapshot]] = {}
        for snapshot in self.snapshots.all():
            made.setdefault(snapshot.step, []).append(snapshot)
        estimates = {}
        for step in self.scenario.steps:
            past = made.get(step.name, [])
            if past:
                estimates[step.name] = Estimate(
                    sum(float(item.data.get("seconds") or 0) for item in past) / len(past),
                    sum(float(item.data.get("cost_usd") or 0) for item in past) / len(past),
                    True,
                )
            else:
                estimates[step.name] = Estimate(
                    float(step.estimate.get("seconds", 0)),
                    float(step.estimate.get("cost_usd", 0)),
                    bool(step.estimate),
                )
        return estimates

    def to_compute(self) -> list[Node]:
        return [node for node in self.nodes if node.outcome is Outcome.COMPUTE]

    def summary(self, parallel: int) -> dict[str, Any]:
        """What the run would do: counts, and the time and cost of computing."""
        counts = {outcome.value: 0 for outcome in Outcome}
        for node in self.nodes:
            counts[node.outcome.value] += 1
        computing = self.to_compute()
        seconds = sum(self.estimates[node.step.name].seconds for node in computing)
        longest = max(
            (
                sum(
                    self.estimates[item.step.name].seconds
                    for item in self.path(node)
                    if item.outcome is Outcome.COMPUTE
                )
                for node in computing
            ),
            default=0.0,
        )
        cost = sum(self.estimates[node.step.name].cost for node in computing)
        unknown = sorted(
            {node.step.name for node in computing if not self.estimates[node.step.name].known}
        )
        result: dict[str, Any] = {
            "scenario": self.scenario.name,
            "snapshots": len(self.nodes),
            "leaves": sum(1 for node in self.nodes if not node.children),
            **{key: value for key, value in counts.items() if value and key != Outcome.COMPUTE},
            "to_compute": counts[Outcome.COMPUTE],
            "estimated_seconds": round(max(longest, seconds / max(1, parallel)), 1),
            "estimated_cost_usd": round(cost, 4),
        }
        if unknown:
            result["no_estimate_for"] = unknown
        if self.budget is not None:
            result["budget_usd"] = self.budget
            if cost > self.budget:
                result["say"] = "the estimate passes the budget: the run stops starting steps there"
        return result

    def path(self, node: Node) -> list[Node]:
        found = []
        current: Node | None = node
        while current is not None:
            found.append(current)
            current = current.parent
        return found[::-1]

    def tree(self) -> str:
        """The tree, a line per snapshot: what it is, and whether it is reused or computed."""
        lines = []
        for node in self.nodes:
            mark = node.outcome.value
            if node.outcome is Outcome.COMPUTE:
                estimate = self.estimates[node.step.name]
                mark += (
                    f" ~{format_duration(estimate.seconds)}" if estimate.known else " (no estimate)"
                )
                if estimate.cost:
                    mark += f" ~${estimate.cost:.2f}"
            if node.why:
                mark += f": {node.why}"
            lines.append(f"{'  ' * node.index}{node.label(new_only=True)}  [{node.hash}] {mark}")
        return "\n".join(lines)


def run_identifier() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%S") + "-" + secrets.token_hex(2)


class Runner:
    """Computes what a plan says to, up to `parallel` steps at once, each in
    its own process; resumable, since each snapshot is written whole when its
    step ends, and never computing a snapshot that already exists."""

    def __init__(self, plan: Plan, parallel: int = PARALLEL) -> None:
        self.plan = plan
        self.scenario = plan.scenario
        self.project = plan.scenario.project
        self.parallel = max(1, parallel)
        self.identifier = run_identifier()
        self.started = now()
        self.spent = 0.0
        self.stopped = False
        self.computed: set[str] = set()
        """The snapshots this run made (and so paid for)."""

    def run(self) -> dict[str, Any]:
        plan = self.plan
        ready = [
            node
            for node in plan.to_compute()
            if node.parent is None or node.parent.outcome is Outcome.REUSED
        ]
        flying: dict[Future[None], Node] = {}
        clock = datetime.now(UTC)
        with ThreadPoolExecutor(max_workers=self.parallel) as pool:
            while ready or flying:
                while ready and len(flying) < self.parallel:
                    node = ready.pop(0)
                    if self.over_budget(node, flying.values()):
                        self.stop(node)
                        continue
                    flying[pool.submit(self.compute, node)] = node
                if not flying:
                    break
                finished, _ = wait(flying, return_when=FIRST_COMPLETED)
                for future in finished:
                    node = flying.pop(future)
                    future.result()
                    if node.hash in self.computed:
                        self.spent += node.cost or 0
                    if node.outcome in (Outcome.COMPUTED, Outcome.REUSED):
                        ready += [
                            child for child in node.children if child.outcome is Outcome.COMPUTE
                        ]
                    else:
                        for child in node.descendants():
                            if child.outcome is Outcome.COMPUTE:
                                child.outcome = Outcome.BLOCKED
                                child.why = f"`{node.label()}` failed"
                self.record(None)
        return self.record((datetime.now(UTC) - clock).total_seconds())

    def over_budget(self, node: Node, flying: Any) -> bool:
        budget = self.plan.budget
        if budget is None:
            return False
        if self.stopped:
            return True
        estimates = self.plan.estimates
        committed = self.spent + sum(estimates[item.step.name].cost for item in flying)
        return committed + estimates[node.step.name].cost > budget

    def stop(self, node: Node) -> None:
        self.stopped = True
        for item in [node, *node.descendants()]:
            if item.outcome is Outcome.COMPUTE:
                item.outcome = Outcome.OVER_BUDGET
                item.why = f"${self.spent:.2f} spent of ${self.plan.budget:.2f}"

    def compute(self, node: Node) -> None:
        """Run one step in a copy of the snapshot before it; the snapshot is
        moved into place whole, so a reader never sees half of one."""
        scenario = self.scenario
        with self.project.lock(f"eval-{scenario.name}-{node.hash}"):
            existing = Snapshots(scenario).get(node.hash)
            if existing is not None:
                node.outcome = Outcome.FAILED if existing.failed else Outcome.REUSED
                node.results = existing.data.get("results")
                return
            work = self.project.local / "eval" / scenario.name / f"{node.hash}.{os.getpid()}"
            shutil.rmtree(work, ignore_errors=True)
            artefacts = work / "artefacts"
            parent = Snapshots(scenario).get(node.parent.hash) if node.parent else None
            if parent is not None and parent.artefacts.is_dir():
                shutil.copytree(parent.artefacts, artefacts, symlinks=True)
            artefacts.mkdir(parents=True, exist_ok=True)
            request = work / "request.json"
            write_json(request, self.request(node, artefacts, work / "outcome.json"))
            began = datetime.now(UTC)
            output = Supervisor(
                self.project,
                [sys.executable, "-m", "nock.steps", str(request)],
                directory=artefacts,
                deadline=node.step.deadline,
                silence=node.step.silence,
                environment={
                    **os.environ,
                    "PYTHONPATH": os.pathsep.join(
                        [
                            str(Path(__file__).resolve().parent.parent),
                            os.environ.get("PYTHONPATH", ""),
                        ]
                    ).rstrip(os.pathsep),
                },
            ).run()
            seconds = round((datetime.now(UTC) - began).total_seconds(), 3)
            outcome_path = work / "outcome.json"
            outcome = read_json(outcome_path) if outcome_path.is_file() else {}
            failed = not output.ok or "results" not in outcome
            identity = scenario.identity(node.index, node.chosen)
            data: dict[str, Any] = {
                **identity,
                "status": Outcome.FAILED.value if failed else Outcome.COMPUTED.value,
                "results": outcome.get("results", {}),
                "seconds": seconds,
                "cost_usd": round(float(outcome.get("cost_usd") or 0), 6),
                "created": now(),
                "run": self.identifier,
                "log": "log.txt",
                "artefacts": manifest(artefacts),
            }
            if failed:
                data["error"] = outcome.get("error") or output.note or f"exited {output.code}"
            shutil.copyfile(output.log, work / "log.txt")
            request.unlink()
            outcome_path.unlink(missing_ok=True)
            write_json(work / "snapshot.json", data)
            target = scenario.snapshots_directory / node.hash
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(work), str(target))
            node.outcome = Outcome.FAILED if failed else Outcome.COMPUTED
            self.computed.add(node.hash)
            node.why = str(data.get("error", ""))
            node.seconds, node.cost, node.results = seconds, data["cost_usd"], data["results"]

    def request(self, node: Node, artefacts: Path, outcome: Path) -> dict[str, Any]:
        """What the step's process is told: who it is, its values, and the results before it."""
        before = {}
        for item in self.plan.path(node)[:-1]:
            snapshot = Snapshots(self.scenario).get(item.hash)
            before[item.step.name] = snapshot.data.get("results", {}) if snapshot else {}
        return {
            "scenario": str(self.scenario.directory),
            "step": node.step.name,
            "code": str(self.scenario.step_file(node.step)),
            "repository": str(self.project.here),
            "root": str(self.project.root),
            "directory": str(artefacts),
            "outcome": str(outcome),
            "parameters": node.parameters,
            "readable": self.scenario.reads_through(node.index),
            "files": {
                name: [str(path) for path in value.files]
                for name, value in node.chosen.items()
                if value.files
            },
            "before": before,
        }

    def record(self, seconds: float | None) -> dict[str, Any]:
        """runs/ID/run.json: written as the run goes, so an interrupted run shows
        what it did, and kept with its own numbers, so pruning loses no history."""
        plan = self.plan
        by: dict[str, list[str]] = {
            outcome.value: [] for outcome in Outcome if outcome is not Outcome.COMPUTE
        }
        for node in plan.nodes:
            if node.outcome is not Outcome.COMPUTE:
                by[node.outcome.value].append(node.hash)
        record = {
            "id": self.identifier,
            "scenario": self.scenario.name,
            "commit": self.commit(),
            "assignment": plan.assignment,
            "started": self.started,
            "finished": now() if seconds is not None else None,
            "seconds": round(seconds, 1) if seconds is not None else None,
            "cost_usd": round(
                sum(node.cost or 0 for node in plan.nodes if node.hash in self.computed), 6
            ),
            "snapshots": {key: value for key, value in by.items() if value},
            "nodes": [
                {
                    "snapshot": node.hash,
                    "step": node.step.name,
                    "parameters": node.parameters,
                    "parent": node.parent.hash if node.parent else None,
                    "outcome": node.outcome.value,
                    **({"why": node.why} if node.why else {}),
                    "seconds": node.seconds,
                    "cost_usd": node.cost,
                    **(
                        {"results": node.results}
                        if not node.children and node.results is not None
                        else {}
                    ),
                }
                for node in plan.nodes
            ],
        }
        write_json(self.scenario.runs_directory / self.identifier / "run.json", record)
        return record

    def commit(self) -> dict[str, Any]:
        """The commit the scenario ran at, and whether its files differed from it."""
        git = Git(self.project.here)
        try:
            head = git.head()
        except GitError:
            return {"sha": None, "dirty": True}
        where = self.scenario.directory.relative_to(self.project.here).as_posix()
        dirty = git(
            "status",
            "--porcelain",
            "--",
            where,
            f":!{where}/snapshots",
            f":!{where}/runs",
            check=False,
        )
        return {"sha": head, "dirty": bool(dirty.strip())}


# --- every scenario ------------------------------------------------------------------


class Evaluations:
    """The project's scenarios, `evals/*/scenario.json` in the working tree."""

    def __init__(self, project: Project) -> None:
        self.project = project
        self.directory = project.here / SCENARIOS

    def names(self) -> list[str]:
        if not self.directory.is_dir():
            return []
        return sorted(path.parent.name for path in self.directory.glob("*/scenario.json"))

    def scenario(self, name: str | None, drafts: dict[str, str] | None = None) -> Scenario:
        """The scenario named, or the only one there is."""
        names = self.names()
        if name is None:
            if len(names) != 1:
                raise UsageError(
                    'name the scenario (`"scenario": …`): '
                    + (", ".join(names) if names else "there are none yet — `nock eval init NAME`")
                )
            name = names[0]
        if name not in names:
            raise NotFoundError(
                f"no scenario `{name}`; there are: {', '.join(names) or 'none — `nock eval init NAME`'}"
            )
        return Scenario(self.project, name, drafts)

    def init(self, name: str) -> list[str]:
        directory = self.directory / name
        if (directory / "scenario.json").exists():
            raise UsageError(f"{SCENARIOS}/{name}/ exists already")
        if not name.replace("-", "").replace("_", "").isalnum() or name != name.lower():
            raise UsageError("a scenario's name is lowercase letters, digits, `-` and `_`")
        written = {
            "scenario.json": json.dumps(
                {"description": "", "steps": [], "parameters": {}}, indent=2
            )
            + "\n",
            "parameters/.gitkeep": "",
            "steps/.gitkeep": "",
            ".gitattributes": GITATTRIBUTES,
            ".gitignore": GITIGNORE,
        }
        for path, text in written.items():
            (directory / path).parent.mkdir(parents=True, exist_ok=True)
            (directory / path).write_text(text)
        return [f"{SCENARIOS}/{name}/{path}" for path in written]

    def problems(self) -> list[str]:
        problems = []
        for name in self.names():
            scenario = Scenario(self.project, name)
            found = scenario.problems()
            problems += found
            if not found:
                problems += Snapshots(scenario).problems()
        return problems

    def find(self, word: str) -> tuple[Scenario, str, Any]:
        """What `nock eval show WORD` names: a scenario, a run, or a snapshot (a hash's prefix will do)."""
        if word in self.names():
            return Scenario(self.project, word), "scenario", None
        for name in self.names():
            scenario = Scenario(self.project, name)
            run = Runs(scenario).get(word)
            if run is not None:
                return scenario, "run", run
        matches = [
            (Scenario(self.project, name), path.name)
            for name in self.names()
            for path in (self.directory / name / "snapshots").glob(f"{word}*")
            if (path / "snapshot.json").is_file()
        ]
        if len(matches) > 1:
            raise UsageError(f"`{word}` starts {len(matches)} snapshots' names; give more of it")
        if matches:
            scenario, hash = matches[0]
            return scenario, "snapshot", Snapshots(scenario).get(hash)
        raise NotFoundError(
            f"`{word}` names no scenario, run or snapshot; the scenarios: {', '.join(self.names()) or 'none'}"
        )

    # --- what `show` says ----------------------------------------------------------

    def overview(self) -> list[dict[str, Any]]:
        rows = []
        for name in self.names():
            scenario = Scenario(self.project, name)
            try:
                steps = scenario.steps
                parameters = scenario.parameters
            except PreconditionError as error:
                rows.append({"scenario": name, "problem": str(error)})
                continue
            counts = self.counts(scenario)
            runs = Runs(scenario).all()
            rows.append(
                {
                    "scenario": name,
                    "steps": " → ".join(step.name for step in steps),
                    "parameters": " ".join(
                        f"{key}({len(item.values)})" for key, item in parameters.items()
                    ),
                    **counts,
                    "runs": len(runs),
                    "last_run": runs[-1]["id"] if runs else None,
                }
            )
        return rows

    def counts(self, scenario: Scenario) -> dict[str, int]:
        snapshots = Snapshots(scenario)
        counts = {"current": 0, "stale": 0, "failed": 0}
        for snapshot in snapshots.all():
            if snapshots.staleness(snapshot):
                counts["stale"] += 1
            elif snapshot.failed:
                counts["failed"] += 1
            else:
                counts["current"] += 1
        return counts

    def show_scenario(self, scenario: Scenario) -> dict[str, Any]:
        snapshots = Snapshots(scenario)
        stale = []
        missing = []
        for snapshot in snapshots.all():
            why = snapshots.staleness(snapshot)
            if why:
                stale.append({"snapshot": snapshot.hash, "is": snapshot.label(), "why": why})
            lacking = snapshot.missing()
            if lacking and not why:
                missing.append(
                    {
                        "snapshot": snapshot.hash,
                        "is": snapshot.label(),
                        "lacks": "; ".join(f"{item['path']} ({item['why']})" for item in lacking),
                    }
                )
        result: dict[str, Any] = {
            "scenario": scenario.name,
            "description": scenario.definition.get("description") or None,
            "steps": [
                {
                    "step": step.name,
                    "reads": " ".join(step.reads),
                    "description": step.description,
                }
                for step in scenario.steps
            ],
            "parameters": {
                name: ", ".join(parameter.values) for name, parameter in scenario.parameters.items()
            },
            "snapshots": self.counts(scenario),
            "runs": [
                {
                    "run": run["id"],
                    "assignment": json.dumps(run.get("assignment", {})),
                    "computed": len(run.get("snapshots", {}).get("computed", [])),
                    "reused": len(run.get("snapshots", {}).get("reused", [])),
                    "failed": len(run.get("snapshots", {}).get("failed", [])),
                    "cost_usd": run.get("cost_usd"),
                    "seconds": run.get("seconds"),
                }
                for run in Runs(scenario).all()[-10:]
            ],
        }
        if stale:
            result["stale"] = stale
            result["say"] = (
                "a run computes fresh snapshots beside the stale; `nock eval prune` deletes them"
            )
        if missing:
            result["missing_here"] = missing
        return result

    def show_snapshot(self, scenario: Scenario, snapshot: Snapshot) -> dict[str, Any]:
        lacking = {item["path"]: item["why"] for item in snapshot.missing()}
        data = snapshot.data
        result: dict[str, Any] = {
            "scenario": scenario.name,
            "snapshot": snapshot.hash,
            "step": snapshot.step,
            "parameters": snapshot.parameters,
            "status": data.get("status"),
            "stale": Snapshots(scenario).staleness(snapshot),
            "results": data.get("results"),
            "seconds": data.get("seconds"),
            "cost_usd": data.get("cost_usd"),
            "created": data.get("created"),
            "artefacts": [
                {
                    "path": entry["path"],
                    "bytes": entry["bytes"],
                    "here": lacking.get(entry["path"], "yes"),
                }
                for entry in data.get("artefacts", [])
            ],
            "runs": Runs(scenario).through().get(snapshot.hash, []),
        }
        if data.get("status") == Outcome.FAILED:
            result["error"] = data.get("error")
            result["log"] = str((snapshot.directory / "log.txt").relative_to(self.project.here))
        return result

    def show_run(self, run: dict[str, Any]) -> dict[str, Any]:
        leaves = [node for node in run.get("nodes", []) if "results" in node]
        return {
            "run": run["id"],
            "scenario": run.get("scenario"),
            "commit": run.get("commit"),
            "assignment": run.get("assignment"),
            "started": run.get("started"),
            "finished": run.get("finished") or "not finished: interrupted, or still running",
            "seconds": run.get("seconds"),
            "cost_usd": run.get("cost_usd"),
            "snapshots": {key: len(value) for key, value in run.get("snapshots", {}).items()},
            "leaves": [
                {
                    "snapshot": node["snapshot"],
                    **{name: value_key(value) for name, value in node["parameters"].items()},
                    "outcome": node["outcome"],
                    "results": json.dumps(node.get("results"), sort_keys=True),
                }
                for node in leaves
            ],
        }

    def prune(self, name: str | None, dry: bool) -> list[dict[str, Any]]:
        """Delete stale and failed snapshots with their artefacts (or, `dry`, say which)."""
        scenarios = (
            [self.scenario(name)]
            if name
            else [Scenario(self.project, item) for item in self.names()]
        )
        rows = []
        for scenario in scenarios:
            for snapshot, why in Snapshots(scenario).prunable():
                rows.append(
                    {
                        "scenario": scenario.name,
                        "snapshot": snapshot.hash,
                        "is": snapshot.label(),
                        "why": why,
                    }
                )
                if not dry:
                    shutil.rmtree(snapshot.directory)
        return rows

    # --- the studio's page ---------------------------------------------------------

    def page(self) -> list[dict[str, Any]]:
        """Everything the Evals tab draws, read from the files."""
        return [self.page_scenario(name) for name in self.names()]

    def page_scenario(self, name: str) -> dict[str, Any]:
        scenario = Scenario(self.project, name)
        try:
            steps, parameters = scenario.steps, scenario.parameters
        except PreconditionError as error:
            return {"name": name, "problem": str(error)}
        snapshots = Snapshots(scenario)
        through = Runs(scenario).through()
        seen: list[str] = []
        listed_steps = []
        for step in steps:
            forks = [item for item in step.reads if item not in seen]
            seen += forks
            path = scenario.step_file(step)
            listed_steps.append(
                {
                    "name": step.name,
                    "description": step.description,
                    "reads": step.reads,
                    "new": forks,
                    "file": scenario.relative(path),
                    "code": path.read_text() if path.is_file() else None,
                }
            )
        return {
            "name": name,
            "description": scenario.definition.get("description", ""),
            "steps": listed_steps,
            "parameters": [
                {
                    "name": key,
                    "description": parameter.description,
                    "values": [
                        {
                            "value": value.value,
                            "key": value.key,
                            "files": [
                                {"path": scenario.relative(path), "text": small_text(path)}
                                for path in value.files
                                if path.is_file()
                            ],
                        }
                        for value in parameter.values.values()
                    ],
                }
                for key, parameter in parameters.items()
            ],
            "snapshots": [
                {
                    "hash": snapshot.hash,
                    "step": snapshot.step,
                    "parameters": snapshot.parameters,
                    "status": snapshot.data.get("status"),
                    "stale": snapshots.staleness(snapshot),
                    "results": snapshot.data.get("results"),
                    "seconds": snapshot.data.get("seconds"),
                    "cost_usd": snapshot.data.get("cost_usd"),
                    "artefacts": snapshot.data.get("artefacts", []),
                    "missing": snapshot.missing(),
                    "runs": through.get(snapshot.hash, []),
                }
                for snapshot in snapshots.all()
            ],
            "runs": Runs(scenario).all(),
        }

    def dry(self, name: str, assignment: dict[str, Any], drafts: dict[str, str]) -> dict[str, Any]:
        """What a run of `assignment` would reuse and compute, were the drafts the files."""
        plan = Plan(self.scenario(name, drafts), assignment)
        return {
            "summary": plan.summary(PARALLEL),
            "nodes": [
                {
                    "snapshot": node.hash,
                    "step": node.step.name,
                    "parameters": node.parameters,
                    "parent": node.parent.hash if node.parent else None,
                    "outcome": node.outcome.value,
                    "why": node.why,
                }
                for node in plan.nodes
            ],
        }


def small_text(path: Path, limit: int = 20_000) -> str | None:
    """A value file's text, for drafting on the page; None when big or binary."""
    if path.stat().st_size > limit:
        return None
    try:
        return path.read_text()
    except UnicodeDecodeError:
        return None
