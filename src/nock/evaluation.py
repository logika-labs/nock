"""Evaluations (`nock eval`): a scenario in `evals/NAME/` is a Snakemake
workflow — rules are steps, wildcards parameters, a rule's output a directory
under `results/RULE/NAME=VALUE/…` — run with the profile `nock eval init`
writes. Every rule is cached by Snakemake's provenance hash (its code, params
and input contents, and those of the rules before it) in `cache/`, which is
committed, so a fresh clone reuses what was computed anywhere (or, with
`eval.cache` set, in a directory outside git, for outputs too big to commit);
`results/` is what this checkout has materialised from it. nock adds what
Snakemake lacks: a budget, the reasons a dry run reruns, which outputs are
stale or failed, retrying the failed, pruning, importing outputs computed
elsewhere, and reading the results with SQL (`nock.results`). The step's own
side is `nock.steps`. Snakemake and DuckDB run through uv, never imported."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, NotRequired, TypedDict

from nock.errors import NotFoundError, PreconditionError, UsageError
from nock.processes import Output, Supervisor
from nock.steps import COST, ERROR, METRICS, attempts_of

if TYPE_CHECKING:
    from nock.project import Project

SCENARIOS = "evals"
SNAKEMAKE = "snakemake==9.27.1"
RESULTS = "results"
CACHE = "cache"
PROFILE = "profile"
LFS_POINTER = b"version https://git-lfs.github.com/spec/v1"
# Runs in uv's interpreter with Snakemake: loads the workflow as `--list-untracked`
# would, with the profile and the targets, and prints each cached output's entry
# in the cache (its provenance hash, and the extension Snakemake keeps) instead.
PROVENANCE = r"""
import json, sys
from snakemake.cli import main
from snakemake import workflow
from snakemake.caching import AbstractOutputFileCache
from snakemake.caching.hash import ProvenanceHashMap


def entries(self, *arguments, **keywords):
    self._prepare_dag(forceall=False, ignore_incomplete=True, lock_warn_only=True)
    self._build_dag()
    hashes = ProvenanceHashMap()
    found = {}
    for job in self.dag.jobs:
        if not job.rule.cache or not job.output:
            continue
        provenance = self.async_run(hashes.get_provenance_hash(job))
        for output, extension in AbstractOutputFileCache.get_outputfiles(None, job):
            found[str(output)] = provenance + extension
    print("NOCK-ENTRIES " + json.dumps(found), flush=True)


workflow.Workflow.list_untracked = entries
main(sys.argv[1:])
"""

SNAKEFILE = """\
# A nock eval scenario: rules are steps, wildcards are parameters. Each rule's
# output is a directory under results/RULE/NAME={NAME}/..., cached by content
# (`cache: "omit-software"`) with its wildcards in its params, so every set of
# values is its own snapshot. `nock docs eval.snakefile` has the conventions.

REPS = [1, 2, 3]

wildcard_constraints:
    rep="[^/]+",


rule all:
    input:
        expand("results/example/rep={rep}", rep=REPS),


rule example:
    output:
        directory("results/example/rep={rep}"),
    params:
        keyed=lambda wildcards: dict(wildcards),
    cache: "omit-software"
    script:
        "steps/example.py"
"""
EXAMPLE_STEP = '''\
from nock.steps import Step


def run(step):
    """Return the step's numbers; spend with step.spend(usd)."""
    return {"rep": int(step.value("rep"))}


Step(snakemake).run(run)
'''
CONFIG = """\
# nock eval's Snakemake profile. nock sets SNAKEMAKE_OUTPUT_CACHE to cache/,
# where every rule marked `cache:` keeps its output by provenance hash.
cores: 4
cache: true
keep-going: true
rerun-incomplete: true
printshellcmds: true
# Limit what runs at once by resource: a rule takes `resources: agents=1`.
resources:
  - agents=2
"""
GITIGNORE = """\
# What this checkout materialised from cache/, and Snakemake's own state.
results/
.snakemake/
"""
GITATTRIBUTES = """\
# The cache is committed. Keep big entries in Git LFS (`git lfs install` once
# per machine) by uncommenting a line:
# cache/**/*.tar filter=lfs diff=lfs merge=lfs -text
"""


def uv() -> str:
    found = shutil.which("uv")
    if found is None:
        raise PreconditionError(
            "nock eval runs Snakemake and DuckDB through uv, which is not installed: "
            "https://docs.astral.sh/uv/getting-started/installation/"
        )
    return found


def parameters_of(path: str) -> dict[str, str]:
    """An output's parameters, from its path: `results/detect/arm=a/rep=1` → arm, rep."""
    return dict(part.split("=", 1) for part in path.split("/") if "=" in part)


def is_lfs_pointer(path: Path) -> bool:
    try:
        with path.open("rb") as handle:
            return handle.read(len(LFS_POINTER)) == LFS_POINTER
    except OSError:
        return False


@dataclass
class Job:
    """One job of a dry run, as Snakemake describes it."""

    rule: str
    checkpoint: bool = False
    outputs: list[str] = field(default_factory=list)
    wildcards: dict[str, str] = field(default_factory=dict)
    reason: str = ""
    resources: dict[str, str] = field(default_factory=dict)
    cached: dict[str, str] = field(default_factory=dict)
    """Output → the cache entry it will be restored from."""

    @property
    def from_cache(self) -> bool:
        return bool(self.outputs) and all(output in self.cached for output in self.outputs)

    def label(self) -> str:
        values = " ".join(f"{name}={value}" for name, value in self.wildcards.items())
        return f"{self.rule} {values}".strip()


JOB_HEAD = re.compile(r"^(local)?(rule|checkpoint) ([\w-]+):$")
JOB_LINE = re.compile(r"^    (\w+): (.*)$")
CACHED = re.compile(r"^Output file (.+) exists as (.+) in the cache\.$")


def parse_jobs(text: str) -> list[Job]:
    """The jobs a dry run (`-n --verbose`) lists, with the cache entries it would restore."""
    jobs: list[Job] = []
    current: Job | None = None
    cached: dict[str, str] = {}
    for line in text.splitlines():
        head = JOB_HEAD.match(line)
        if head:
            current = Job(head.group(3), checkpoint=head.group(2) == "checkpoint")
            jobs.append(current)
            continue
        found = CACHED.match(line)
        if found:
            cached[found.group(1)] = found.group(2)
            continue
        item = JOB_LINE.match(line)
        if current is None or item is None:
            current = None if not line.startswith("    ") else current
            continue
        key, value = item.groups()
        if key == "output":
            current.outputs = [part.strip() for part in value.split(", ")]
        elif key == "wildcards":
            current.wildcards = dict(
                part.strip().split("=", 1) for part in value.split(", ") if "=" in part
            )
        elif key == "reason":
            current.reason = value
        elif key == "resources":
            current.resources = dict(
                part.strip().split("=", 1) for part in value.split(", ") if "=" in part
            )
    for job in jobs:
        job.cached = {output: cached[output] for output in job.outputs if output in cached}
    return [job for job in jobs if job.outputs]


@dataclass
class Result:
    """An output this checkout has under results/: a step's directory."""

    path: str
    rule: str
    state: str = "current"
    """current, stale or failed."""
    why: str | None = None
    entry: str | None = None
    """The cache entry it is a link to."""

    @property
    def parameters(self) -> dict[str, str]:
        return parameters_of(self.path)


class Scenario:
    """One scenario's directory and the Snakemake that runs it."""

    def __init__(self, project: Project, name: str) -> None:
        self.project = project
        self.name = name
        self.directory = project.here / SCENARIOS / name
        if not (self.directory / "Snakefile").is_file():
            raise NotFoundError(f"no scenario `{name}`: {SCENARIOS}/{name}/Snakefile")

    @property
    def cache(self) -> Path:
        """`cache/` beside the Snakefile, committed; or, with `eval.cache` set, that
        directory's NAME, outside git."""
        configured = str(self.project.configuration.get("eval.cache") or "")
        if not configured:
            return self.directory / CACHE
        base = Path(configured).expanduser()
        return (base if base.is_absolute() else self.project.here / base) / self.name

    @property
    def committed(self) -> bool:
        """Whether the cache is the scenario's `cache/`, kept in git."""
        return self.cache == self.directory / CACHE

    @property
    def results(self) -> Path:
        return self.directory / RESULTS

    def environment(self) -> dict[str, str]:
        """Snakemake's: the cache, and nock on the path, so a step can import `nock.steps`."""
        self.cache.mkdir(parents=True, exist_ok=True)
        core = str(Path(__file__).resolve().parent.parent)
        path = os.environ.get("PYTHONPATH", "")
        return {
            **os.environ,
            "SNAKEMAKE_OUTPUT_CACHE": str(self.cache.resolve()),
            "PYTHONPATH": os.pathsep.join([core, path]) if path else core,
        }

    def command(self, *arguments: str) -> list[str]:
        return [uv(), "tool", "run", SNAKEMAKE, "--profile", PROFILE, *arguments]

    def snakemake(self, *arguments: str) -> str:
        """A Snakemake that reads and writes nothing of the results (a dry
        run, a summary): its output, or what went wrong."""
        result = subprocess.run(
            self.command(*arguments),
            cwd=self.directory,
            env=self.environment(),
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            said = (result.stderr or result.stdout).strip().splitlines()
            raise PreconditionError(
                f"snakemake {' '.join(arguments)} failed in {SCENARIOS}/{self.name}:\n"
                + "\n".join(said[-15:])
            )
        return result.stdout + result.stderr

    def jobs(self, targets: list[str] | None = None, forced: list[str] | None = None) -> list[Job]:
        """What a run of `targets` would do — with `forced` and what follows
        them rerun — the jobs, why each runs, and those the cache has."""
        arguments = ["-n", "--verbose", *(targets or [])]
        if forced:
            arguments += ["--forcerun", *forced]
        return parse_jobs(self.snakemake(*arguments))

    def run(self, targets: list[str], cores: int | None, limits: list[str] | None = None) -> Output:
        arguments = ["--cores", str(cores)] if cores else []
        if limits:
            arguments += ["--resources", *limits]
        return Supervisor(
            self.project,
            # Targets first: `--resources` takes every word after it.
            self.command(*targets, *arguments),
            directory=self.directory,
            deadline=0,
            silence=0,
            environment=self.environment(),
        ).run()

    def entries(self, targets: list[str] | None = None) -> dict[str, str]:
        """Each cached output of a run of `targets` and the cache entry it is
        kept under, computed or not: Snakemake's provenance hash of its job."""
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
                PROVENANCE,
                "--profile",
                PROFILE,
                "--list-untracked",
                *(targets or []),
            ],
            cwd=self.directory,
            env=self.environment(),
            capture_output=True,
            text=True,
        )
        for line in result.stdout.splitlines():
            if line.startswith("NOCK-ENTRIES "):
                return json.loads(line.removeprefix("NOCK-ENTRIES "))
        said = (result.stderr or result.stdout).strip().splitlines()
        raise PreconditionError(
            f"snakemake could not name the cache entries in {SCENARIOS}/{self.name}:\n"
            + "\n".join(said[-15:])
        )

    def summary(self) -> dict[str, tuple[str, str, str]]:
        """Every output of the default target: its rule, Snakemake's status and plan."""
        found = {}
        for line in self.snakemake("--summary").splitlines():
            parts = line.split("\t")
            if len(parts) >= 6 and parts[0] != "output_file":
                found[parts[0]] = (parts[2], parts[4], parts[5])
        return found

    def rulegraph(self) -> dict[str, Any]:
        """The rules in the order they run, and which feeds which, from `--rulegraph`."""
        names: dict[str, str] = {}
        edges = []
        for line in self.snakemake("--rulegraph").splitlines():
            node = re.match(r'\s*(\d+)\[label = "([^"]+)"', line)
            edge = re.match(r"\s*(\d+) -> (\d+)", line)
            if node:
                names[node.group(1)] = node.group(2)
            elif edge:
                edges.append((edge.group(1), edge.group(2)))
        return {
            "rules": sorted(names.values()),
            "edges": [[names[a], names[b]] for a, b in edges if a in names and b in names],
        }

    def rules(self) -> list[str]:
        return [
            line.strip()
            for line in self.snakemake("--list-rules").splitlines()
            if re.fullmatch(r"[\w-]+", line.strip())
        ]

    def materialised(self) -> list[Result]:
        """The outputs under results/: directories whose path below the rule is
        all `NAME=VALUE`, and that a step wrote (`cost.json` or `error.json`)."""
        found = []
        if not self.results.is_dir():
            return found
        for rule in sorted(path for path in self.results.iterdir() if path.is_dir()):
            for directory in walk(rule):
                if (directory / COST).is_file() or (directory / ERROR).is_file():
                    path = directory.relative_to(self.directory).as_posix()
                    found.append(Result(path, rule.name, entry=self.entry(directory)))
        return found

    def entry(self, directory: Path) -> str | None:
        """The cache entry an output is: the directory a link (after a run), or
        its files' links (after a restore), point into."""
        cache = self.cache.resolve()
        links = (
            [directory]
            if directory.is_symlink()
            else [child for child in directory.iterdir() if child.is_symlink()]
        )
        for link in links:
            target = link.resolve()
            for candidate in (target, target.parent):
                if candidate.parent == cache:
                    return candidate.name
        return None

    def states(self, jobs: list[Job] | None = None) -> list[Result]:
        """Each materialised output: current; stale, in Snakemake's words, when
        a run would compute it again (a rerun the cache answers with the same
        entry is no change: Snakemake reruns a script whose file is newer); or
        failed. `jobs` is a dry run of the default target, when one was made."""
        with ThreadPoolExecutor(2) as pool:
            summary = pool.submit(self.summary)
            planned = pool.submit(self.jobs) if jobs is None else None
            pending = {
                output: job
                for job in (planned.result() if planned else jobs or [])
                for output in job.outputs
            }
            outputs = summary.result()
        found = self.materialised()
        for result in found:
            job = pending.get(result.path)
            if result.path not in outputs:
                result.state, result.why = "stale", "no longer in the workflow"
            elif job is not None and Path(job.cached.get(result.path, "")).name != result.entry:
                result.state, result.why = "stale", job.reason
            elif (self.directory / result.path / ERROR).is_file():
                result.state = "failed"
        return found

    def problems(self) -> list[str]:
        """What is wrong with the scenario's files: the profile, rules not cached by their wildcards."""
        problems = []
        if not (self.directory / PROFILE / "config.yaml").is_file():
            problems.append(f"{self.name}: no {PROFILE}/config.yaml — `nock eval init` writes it")
        for rule, body in rule_blocks((self.directory / "Snakefile").read_text()):
            if not re.search(r"^\s+output:", body, re.MULTILINE):
                continue
            if not re.search(r"^\s+cache:", body, re.MULTILINE):
                problems.append(
                    f'{self.name}: rule `{rule}` is not cached (`cache: "omit-software"`), so its outputs never reach git'
                )
            elif not re.search(r"^\s+params:[\s\S]*wildcards", body, re.MULTILINE):
                problems.append(
                    f"{self.name}: rule `{rule}` keeps no wildcards in its params "
                    "(`keyed=lambda wildcards: dict(wildcards)`), so its values share one cache entry"
                )
        return problems


class Imported(TypedDict):
    output: str
    """Its path, `results/RULE/NAME=VALUE/…`: a job of the targets."""
    source: NotRequired[str]
    """A directory whose files the output is, cloned (copy-on-write where the
    filesystem can), never moved or changed."""
    metrics: NotRequired[dict[str, Any]]
    """Its numbers, written as its metrics.json."""
    cost: NotRequired[dict[str, Any]]
    """What it spent: usd, seconds and tokens, written as its cost.json."""
    error: NotRequired[str]
    """What went wrong, when it is a failed output: its error.json."""


class Import(TypedDict):
    outputs: list[Imported]
    """The outputs, each where the scenario's Snakefile puts it."""
    scenario: NotRequired[str]
    """The scenario; the only one there is by default."""
    targets: NotRequired[list[str]]
    """The targets whose jobs the outputs are; the default target's by default."""


def clone(source: Path, destination: Path) -> None:
    """`source` copied whole to `destination`, sharing the blocks where the
    filesystem can (APFS clones, Btrfs and XFS reflinks), so a large import
    costs little disk."""
    if sys.platform == "darwin":
        command = ["cp", "-R", "-p", "-c", str(source), str(destination)]
    elif sys.platform.startswith("linux"):
        command = ["cp", "-R", "-p", "--reflink=auto", str(source), str(destination)]
    else:
        shutil.copytree(source, destination, symlinks=True)
        return
    if subprocess.run(command, capture_output=True).returncode != 0:
        shutil.rmtree(destination, ignore_errors=True)
        shutil.copytree(source, destination, symlinks=True)


def rule_blocks(text: str) -> Iterator[tuple[str, str]]:
    """Each `rule NAME:` or `checkpoint NAME:` block of a Snakefile, by its indentation."""
    lines = text.splitlines()
    for index, line in enumerate(lines):
        head = re.match(r"^(rule|checkpoint) ([\w-]+):", line)
        if not head:
            continue
        body = []
        for following in lines[index + 1 :]:
            if following and not following[0].isspace() and not following.startswith("#"):
                break
            body.append(following)
        yield head.group(2), "\n".join(body)


def walk(directory: Path) -> Iterator[Path]:
    """Directories under `directory` named `NAME=VALUE`, through links into the cache."""
    for child in sorted(directory.iterdir()) if directory.is_dir() else []:
        if child.is_dir() and "=" in child.name:
            yield child
            yield from walk(child)


# --- running ------------------------------------------------------------------------


@dataclass
class Estimate:
    usd: float | None
    seconds: float | None


class Run:
    """`nock eval run`: a dry run first — what reruns and why, what the cache
    restores, what computing costs — then Snakemake with the profile, unless
    the estimate passes the budget."""

    def __init__(self, scenario: Scenario, targets: list[str], budget: float | None) -> None:
        self.scenario = scenario
        self.targets = targets
        self.budget = budget
        self.jobs = scenario.jobs(targets)
        self.estimates = self.history()

    def history(self) -> dict[str, Estimate]:
        """Each rule's mean cost and time over the outputs it made here."""
        spent: dict[str, list[dict[str, Any]]] = {}
        for result in self.scenario.materialised():
            path = self.scenario.directory / result.path / COST
            if path.is_file():
                try:
                    spent.setdefault(result.rule, []).append(read(path))
                except ValueError:
                    continue
        return {
            rule: Estimate(
                mean([float(item.get("usd") or 0) for item in items]),
                mean([float(item.get("seconds") or 0) for item in items]),
            )
            for rule, items in spent.items()
        }

    def estimate(self, job: Job) -> Estimate:
        known = self.estimates.get(job.rule)
        if known is not None:
            return known
        declared = job.resources.get("estimate_cents")
        return Estimate(int(declared) / 100 if declared and declared.isdigit() else None, None)

    def computing(self) -> list[Job]:
        return [job for job in self.jobs if not job.from_cache]

    def collisions(self) -> list[str]:
        """Outputs that would share one cache entry: a rule whose params do not carry its wildcards."""
        by_entry: dict[str, list[str]] = {}
        for job in self.jobs:
            for output, entry in job.cached.items():
                by_entry.setdefault(entry, []).append(output)
        return [
            f"{', '.join(outputs)} would all be restored from one cache entry: their rule's params "
            "must carry its wildcards (`keyed=lambda wildcards: dict(wildcards)`)"
            for outputs in by_entry.values()
            if len(outputs) > 1
        ]

    def pointers(self) -> list[str]:
        """Cache entries a run would read that are Git LFS pointers, not their content."""
        found: list[str] = []
        if not self.scenario.committed:
            return found
        for job in self.jobs:
            for entry in job.cached.values():
                path = Path(entry)
                files = [path] if path.is_file() else [p for p in path.rglob("*") if p.is_file()]
                found += [str(p) for p in files if is_lfs_pointer(p)]
        return found

    def summary(self) -> dict[str, Any]:
        computing = self.computing()
        known = [self.estimate(job) for job in computing]
        cost = sum(item.usd or 0 for item in known)
        unknown = sorted({job.rule for job in computing if self.estimate(job).usd is None})
        checkpoints = any(job.checkpoint for job in self.jobs)
        result: dict[str, Any] = {
            "scenario": self.scenario.name,
            "to_compute": len(computing),
            "from_cache": len(self.jobs) - len(computing),
            "estimated_cost_usd": round(cost, 4),
            "estimated_seconds": round(sum(item.seconds or 0 for item in known), 1),
        }
        if unknown:
            result["no_estimate_for"] = unknown
        if checkpoints:
            result["say"] = (
                "the jobs after a checkpoint are decided as it finishes: a dry run counts "
                "those it cannot yet see into the cache as computed"
            )
        if self.budget is not None:
            result["budget_usd"] = self.budget
        return result

    def lines(self) -> list[dict[str, Any]]:
        """A row per job: what it is, and whether it is restored or computed, and why."""
        rows = []
        for job in self.jobs:
            row: dict[str, Any] = {"job": job.label()}
            if job.from_cache:
                row["does"] = "from cache"
            else:
                estimate = self.estimate(job)
                row["does"] = (
                    "compute"
                    + (f" ~${estimate.usd:.2f}" if estimate.usd else "")
                    + (f" ~{estimate.seconds:.0f}s" if estimate.seconds else "")
                )
                row["why"] = job.reason
            rows.append(row)
        return rows

    def refusal(self) -> str | None:
        """Why the run must not start: shared cache entries, LFS pointers, or the budget."""
        problems = self.collisions()
        if problems:
            return "; ".join(problems)
        pointers = self.pointers()
        if pointers:
            return (
                f"{len(pointers)} cache file(s) are Git LFS pointers, not their content "
                f"(`git lfs pull`): {', '.join(pointers[:3])}"
            )
        if self.budget is None:
            return None
        summary = self.summary()
        if summary["estimated_cost_usd"] > self.budget:
            return (
                f"the estimate, ${summary['estimated_cost_usd']:.2f} for {summary['to_compute']} "
                f"job(s), passes the budget, ${self.budget:.2f}: narrow the targets, or raise it"
            )
        return None

    def execute(self, cores: int | None, limits: list[str] | None = None) -> dict[str, Any]:
        refused = self.refusal()
        if refused:
            raise UsageError(refused, self.summary())
        entries = {path.name for path in self.scenario.cache.iterdir()}
        before = {result.path: result.entry for result in self.scenario.materialised()}
        output = self.scenario.run(self.targets, cores, limits)
        made = [
            result
            for result in self.scenario.materialised()
            if result.path not in before or before[result.path] != result.entry
        ]
        computed = [result for result in made if result.entry not in entries]
        spent, tokens = 0.0, 0
        for result in computed:
            path = self.scenario.directory / result.path / COST
            if path.is_file():
                cost = read(path)
                spent += float(cost.get("usd") or 0)
                tokens += int(cost.get("tokens") or 0)
        failed = [
            result.path
            for result in made
            if (self.scenario.directory / result.path / ERROR).is_file()
        ]
        summary: dict[str, Any] = {
            "scenario": self.scenario.name,
            "computed": len(computed),
            "from_cache": len(made) - len(computed),
            "cost_usd": round(spent, 6),
        }
        if tokens:
            summary["tokens"] = tokens
        if failed:
            summary["failed"] = failed[:10]
        if not output.ok:
            summary["snakemake"] = (
                f"exited {output.code}: a job broke outside its step (log: {output.log})"
            )
        summary["next"] = (
            "`nock eval show` for what is current, stale and failed; `nock eval query` and "
            "`compare` to read it"
            + (
                f"; commit {SCENARIOS}/{self.scenario.name}/cache/ to share it"
                if self.scenario.committed
                else ""
            )
            + ("; `nock eval run --retry` computes the failed again" if failed else "")
        )
        return summary


def read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise ValueError(f"{path} is not a JSON object")
    return value


def mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


# --- every scenario ------------------------------------------------------------------


class Evaluations:
    """The project's scenarios, `evals/*/Snakefile` in the working tree."""

    def __init__(self, project: Project) -> None:
        self.project = project
        self.directory = project.here / SCENARIOS

    def names(self) -> list[str]:
        if not self.directory.is_dir():
            return []
        return sorted(path.parent.name for path in self.directory.glob("*/Snakefile"))

    def scenario(self, name: str | None) -> Scenario:
        """The scenario named, or the only one there is."""
        names = self.names()
        if name is None:
            if len(names) != 1:
                raise UsageError(
                    "name the scenario (`--scenario NAME`): "
                    + (", ".join(names) if names else "there are none yet — `nock eval init NAME`")
                )
            name = names[0]
        if name not in names:
            raise NotFoundError(
                f"no scenario `{name}`; there are: {', '.join(names) or 'none — `nock eval init NAME`'}"
            )
        return Scenario(self.project, name)

    def init(self, name: str) -> list[str]:
        directory = self.directory / name
        if (directory / "Snakefile").exists():
            raise UsageError(f"{SCENARIOS}/{name}/ exists already")
        if not name.replace("-", "").replace("_", "").isalnum() or name != name.lower():
            raise UsageError("a scenario's name is lowercase letters, digits, `-` and `_`")
        written = {
            "Snakefile": SNAKEFILE,
            "steps/example.py": EXAMPLE_STEP,
            f"{PROFILE}/config.yaml": CONFIG,
            "parameters/.gitkeep": "",
            f"{CACHE}/.gitkeep": "",
            ".gitignore": GITIGNORE,
            ".gitattributes": GITATTRIBUTES,
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
            if not found:
                try:
                    scenario.rules()
                except PreconditionError as error:
                    found.append(f"{name}: {error}")
            problems += found
        return problems

    def prune(self, name: str | None, dry: bool) -> list[dict[str, Any]]:
        """Stale and failed outputs: the cache entries no current output of the
        default target is, and the failed ones; deleted with their links unless `dry`."""
        scenarios = (
            [self.scenario(name)]
            if name
            else [Scenario(self.project, item) for item in self.names()]
        )
        rows = []
        for scenario in scenarios:
            rows += self.prunable(scenario)
        if not dry:
            for row in rows:
                self.remove(Scenario(self.project, row["scenario"]), row, keep=False)
        return rows

    def remove(self, scenario: Scenario, row: dict[str, Any], keep: bool) -> None:
        """A cache entry gone, or kept as its output's failed attempt (`keep`), and
        the output this checkout materialised from it."""
        entry = scenario.cache / row["entry"]
        if keep and row.get("output") and entry.is_dir():
            attempt = attempts_of(scenario.cache, row["output"])
            attempt.parent.mkdir(parents=True, exist_ok=True)
            shutil.rmtree(attempt, ignore_errors=True)
            entry.rename(attempt)
        elif entry.is_dir() and not entry.is_symlink():
            shutil.rmtree(entry)
        else:
            entry.unlink(missing_ok=True)
        if row.get("output"):
            output = scenario.directory / row["output"]
            if output.is_symlink():
                output.unlink()
            elif output.is_dir():
                # Restored from the cache: a directory of links into it.
                shutil.rmtree(output)

    def retry(self, scenario: Scenario) -> list[dict[str, Any]]:
        """The failed outputs, and what was computed from them, out of the cache
        so a run computes them again; each failed one kept as its attempt, which
        its step reads as `step.previous`."""
        rows = [
            row
            for row in self.prunable(scenario)
            if row["why"] in ("failed", "stale: computed from a failed output")
        ]
        for row in rows:
            self.remove(scenario, row, keep=row["why"] == "failed")
        return rows

    def load(self, record: Import) -> dict[str, Any]:
        """Outputs computed elsewhere, put into the scenario's cache under the
        entries their jobs would have, so a run restores them as if it had
        computed them: each output's files cloned from `source` (never moved or
        changed), with its metrics, cost and, for a failed one, its error."""
        scenario = self.scenario(record.get("scenario"))
        entries = scenario.entries(record.get("targets"))
        unknown = [item["output"] for item in record["outputs"] if item["output"] not in entries]
        if unknown:
            raise UsageError(
                f"{len(unknown)} output(s) are no cached job of "
                f"{' '.join(record.get('targets') or []) or 'the default target'}: "
                + ", ".join(unknown[:5])
            )
        sources = [item.get("source") for item in record["outputs"]]
        missing = [source for source in sources if source and not Path(source).is_dir()]
        if missing:
            raise NotFoundError(
                f"{len(missing)} source(s) are no directory: {', '.join(missing[:5])}"
            )
        cache = scenario.cache
        cache.mkdir(parents=True, exist_ok=True)
        wanted = [
            item for item in record["outputs"] if not (cache / entries[item["output"]]).exists()
        ]

        def put(item: Imported) -> None:
            staging = Path(tempfile.mkdtemp(prefix=".import-", dir=cache))
            payload = staging / "output"
            try:
                source = item.get("source")
                if source:
                    clone(Path(source), payload)
                else:
                    payload.mkdir()
                if "metrics" in item:
                    (payload / METRICS).write_text(json.dumps(item["metrics"], indent=2) + "\n")
                cost = {"usd": 0.0, "seconds": 0.0, **item.get("cost", {})}
                (payload / COST).write_text(json.dumps(cost) + "\n")
                error = item.get("error")
                if error:
                    (payload / ERROR).write_text(
                        json.dumps({"error": error, "imported": True}, indent=2) + "\n"
                    )
                payload.rename(cache / entries[item["output"]])
            finally:
                shutil.rmtree(staging, ignore_errors=True)

        with ThreadPoolExecutor(8) as pool:
            list(pool.map(put, wanted))
        return {
            "scenario": scenario.name,
            "imported": len(wanted),
            "present": len(record["outputs"]) - len(wanted),
            "failed": sum(1 for item in wanted if item.get("error")),
            "next": "`nock eval run --dry` restores them from the cache; `nock eval run` materialises them",
        }

    def prunable(self, scenario: Scenario) -> list[dict[str, Any]]:
        if not scenario.cache.is_dir():
            return []
        jobs = scenario.jobs()
        pending = [job.label() for job in jobs if job.checkpoint and job.from_cache]
        if pending:
            raise PreconditionError(
                f"{scenario.name}: the cache holds checkpoints this checkout has not restored "
                f"({', '.join(pending[:3])}), so what follows them cannot be judged: "
                "`nock eval run` restores them first"
            )
        states = scenario.states(jobs)
        failed = {
            result.entry: result for result in states if result.state == "failed" and result.entry
        }
        # What was computed from a failed output is keyed by its provenance, not its content:
        # once the failure is computed again, it would be restored as it was.
        after: set[str] = set()
        if failed:
            for job in scenario.jobs(forced=[result.path for result in failed.values()]):
                after |= set(job.outputs)
        for result in states:
            if result.state == "current" and result.path in after and result.entry:
                result.state, result.why = "stale", "computed from a failed output"
        keep = {Path(entry).name for job in jobs for entry in job.cached.values()}
        keep |= {result.entry for result in states if result.state == "current" and result.entry}
        linked = {result.entry: result for result in states if result.entry}
        rows = []
        for entry in sorted(scenario.cache.iterdir()):
            if entry.name.startswith(".") or entry.name in keep:
                continue
            name = entry.name
            key = name.split(".")[0].split("_")[0]
            result = failed.get(name) or failed.get(key) or linked.get(name) or linked.get(key)
            rows.append(
                {
                    "scenario": scenario.name,
                    "entry": name,
                    "output": result.path if result else None,
                    "why": "failed"
                    if result is not None and result.state == "failed"
                    else f"stale: {result.why}"
                    if result is not None and result.why
                    else "stale: no output of the workflow is it now",
                }
            )
        return rows
