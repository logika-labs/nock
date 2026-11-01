"""A step's side of `nock eval`: a Snakemake rule's script, run in the
interpreter Snakemake runs on with nock on its path, wraps its work in
`Step(snakemake).run(function)`. The rule's output is a directory; the
function's numbers become its `metrics.json`, what it spent and how long it
took its `cost.json` (Snakemake's `benchmark:` cannot be used with its cache),
and a raise its `error.json` — a failed result, cached like any other until
`nock eval prune` deletes it. Saved state is `state.tar` in the output
(`pack`, `unpack`), and a repository's changes against the state before are
`diff.patch` beside it."""

from __future__ import annotations

import json
import subprocess
import tarfile
import tempfile
import time
import traceback
from collections.abc import Callable
from pathlib import Path
from typing import Any

from nock.dispatch import READING, Dispatcher, Seat
from nock.errors import UsageError
from nock.project import Project

ROLE = "evaluated"
METRICS = "metrics.json"
COST = "cost.json"
ERROR = "error.json"
STATE = "state.tar"
DIFF = "diff.patch"
# What a repository's first state is diffed against.
EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"


class Step:
    """One job of a rule: its parameters (the wildcards), its inputs, and its
    output directory, where whatever it leaves is the snapshot."""

    def __init__(self, snakemake: Any) -> None:
        self.snakemake = snakemake
        self.rule: str = snakemake.rule
        self.directory = Path(snakemake.output[0]).resolve()
        self.cost_usd = 0.0
        self.refused: list[str] = []
        """What Claude Code refused this step's agents."""

    def value(self, name: str) -> str:
        """A parameter's value: the wildcard of that name."""
        wildcards = dict(self.snakemake.wildcards.items())
        if name not in wildcards:
            raise UsageError(
                f"rule `{self.rule}` has no wildcard `{name}`: it has {', '.join(wildcards) or 'none'}"
            )
        return str(wildcards[name])

    def input(self, name: str | None = None) -> Path:
        """An input by its name in the rule, or the first."""
        inputs = self.snakemake.input
        if name is None:
            return Path(inputs[0]).resolve()
        if name not in dict(inputs.items()):
            raise UsageError(f"rule `{self.rule}` has no input named `{name}`")
        return Path(inputs[name]).resolve()

    def metrics(self, name: str | None = None) -> dict[str, Any]:
        """An earlier step's numbers: the `metrics.json` of an input."""
        path = self.input(name) / METRICS
        return json.loads(path.read_text()) if path.is_file() else {}

    def spend(self, usd: float) -> None:
        """Count what the step spent (an API call, say) into its `cost.json`."""
        self.cost_usd += usd

    def unpack(self, name: str | None = None) -> Path:
        """The state an input saved (`state.tar`), extracted into a fresh directory to work in."""
        directory = Path(tempfile.mkdtemp(prefix=f"nock-{self.rule}-"))
        with tarfile.open(self.input(name) / STATE) as archive:
            archive.extractall(directory, filter="tar")
        return directory

    def pack(self, directory: Path) -> None:
        """Save `directory` whole (a repository's `.git` too) as this step's
        `state.tar`; when it is a git repository, its changes against its
        HEAD — the state before, committed — go to `diff.patch`."""
        self.directory.mkdir(parents=True, exist_ok=True)
        if (directory / ".git").exists():
            subprocess.run(["git", "add", "-A", "-N"], cwd=directory, check=True)
            head = subprocess.run(
                ["git", "rev-parse", "--verify", "-q", "HEAD"], cwd=directory, capture_output=True
            )
            diff = subprocess.run(
                ["git", "diff", "--binary", "HEAD" if head.returncode == 0 else EMPTY_TREE],
                cwd=directory,
                check=True,
                capture_output=True,
            ).stdout
            (self.directory / DIFF).write_bytes(diff)
            subprocess.run(["git", "add", "-A"], cwd=directory, check=True)
            subprocess.run(
                [
                    "git",
                    "-c",
                    "user.name=nock",
                    "-c",
                    "user.email=nock@localhost",
                    "commit",
                    "-q",
                    "--allow-empty",
                    "-m",
                    f"nock eval: {self.rule}",
                ],
                cwd=directory,
                check=True,
            )
        with tarfile.open(self.directory / STATE, "w") as archive:
            archive.add(directory, arcname=".")

    @property
    def project(self) -> Project:
        return Project.discover(Path.cwd())

    def agent(
        self,
        brief: str,
        *,
        allowed: tuple[str, ...] | list[str],
        directory: Path | None = None,
        tools: tuple[str, ...] | list[str] = READING,
        denied: tuple[str, ...] | list[str] = (),
        deadline: float | None = None,
    ) -> str | None:
        """A headless agent, dispatched as nock dispatches its own — in
        `dontAsk`, with only `tools` and the `allowed` rules (Claude Code's
        rule syntax: `Edit`, `Bash(pytest:*)`), everything else refused —
        working in `directory` (the output by default); its session's cost
        is spent. Returns its last message; what was refused is in `refused`."""
        project = self.project
        seat = Seat(tuple(tools), tuple(allowed), tuple(denied))
        where = directory or self.directory
        where.mkdir(parents=True, exist_ok=True)
        session = Dispatcher(project).launch(ROLE, brief, where, deadline=deadline, seat=seat)
        rows = project.store.rows("SELECT cost FROM sessions WHERE id = ?", (session.id,))
        self.spend(float(rows[0]["cost"] or 0) if rows else 0.0)
        self.refused += session.denied
        if session.exit_code != 0:
            raise RuntimeError(f"the agent exited {session.exit_code} (log: {session.log})")
        return session.result

    def run(self, function: Callable[[Step], dict[str, Any] | None]) -> None:
        """Run the step: its numbers to `metrics.json`, its spending to
        `cost.json` with its seconds, a raise to `error.json` with its traceback."""
        self.directory.mkdir(parents=True, exist_ok=True)
        began = time.monotonic()
        try:
            metrics = function(self) or {}
            if not isinstance(metrics, dict):
                raise TypeError(
                    f"the step returned {type(metrics).__name__}: a step returns a dict"
                )
            (self.directory / METRICS).write_text(json.dumps(metrics, indent=2) + "\n")
        except Exception as error:
            traceback.print_exc()
            (self.directory / ERROR).write_text(
                json.dumps(
                    {
                        "error": f"{type(error).__name__}: {error}",
                        "traceback": traceback.format_exc(),
                    },
                    indent=2,
                )
                + "\n"
            )
        spent = {"usd": round(self.cost_usd, 6), "seconds": round(time.monotonic() - began, 3)}
        (self.directory / COST).write_text(json.dumps(spent) + "\n")
