"""A step's side of `nock eval run`: the process one step runs in, started as
`python -m nock.steps REQUEST` in a copy of the snapshot before it, on the
project's interpreter (`[environment]`), so a step can import the project's
packages. The step's module defines `run(step)`, which gets a `Step` and
returns its results, a dict of JSON values."""

from __future__ import annotations

import importlib.util
import json
import sys
import traceback
from pathlib import Path
from typing import Any

from nock.dispatch import READING, Dispatcher, Seat
from nock.errors import UsageError
from nock.project import Project
from nock.utils import read_json, write_json

ROLE = "evaluated"


class Step:
    """What a step reads and where it writes: `directory` is the state, which
    starts as the snapshot before it and becomes this snapshot's artefacts."""

    def __init__(self, request: dict[str, Any]) -> None:
        self.request = request
        self.name: str = request["step"]
        self.scenario = Path(request["scenario"])
        self.repository = Path(request["repository"])
        self.directory = Path(request["directory"])
        self.parameters: dict[str, Any] = dict(request["parameters"])
        """The values read by this step and those before it, by name."""
        self.cost_usd = 0.0
        self.refused: list[str] = []
        """What Claude Code refused this step's agents."""

    def value(self, name: str) -> Any:
        """A parameter's value: a literal, or the name of a file-valued one's value."""
        if name not in self.parameters:
            raise UsageError(
                f"step `{self.name}` reads only {', '.join(self.parameters) or 'nothing'}: "
                f"declare `{name}` in its `reads` in scenario.json"
            )
        return self.parameters[name]

    def files(self, name: str) -> list[Path]:
        """The files that are a parameter's value."""
        self.value(name)
        return [Path(path) for path in self.request["files"].get(name, [])]

    def file(self, name: str) -> Path:
        """The one file (or directory) that is a parameter's value."""
        found = self.files(name)
        if len(found) != 1:
            raise UsageError(f"`{name}` is {len(found)} files, not one: use `step.files`")
        return found[0]

    def results(self, step: str | None = None) -> dict[str, Any]:
        """An earlier step's results on this path; by default the one just before."""
        before: dict[str, Any] = self.request["before"]
        if not before:
            return {}
        name = step or list(before)[-1]
        if name not in before:
            raise UsageError(f"no step `{name}` before `{self.name}`: {', '.join(before)}")
        return before[name]

    def spend(self, usd: float) -> None:
        """Count what the step spent (an API call, say) toward the run's cost and budget."""
        self.cost_usd += usd

    @property
    def project(self) -> Project:
        return Project(Path(self.request["root"]), self.repository)

    def agent(
        self,
        brief: str,
        *,
        allowed: tuple[str, ...] | list[str],
        tools: tuple[str, ...] | list[str] = READING,
        denied: tuple[str, ...] | list[str] = (),
        deadline: float | None = None,
    ) -> str | None:
        """A headless agent, dispatched as nock dispatches its own — in
        `dontAsk`, with only `tools` and the `allowed` rules (Claude Code's
        rule syntax: `Edit`, `Bash(pytest:*)`), everything else refused —
        working in this step's directory; its session's cost is spent.
        Returns its last message; what was refused is in `step.refused`."""
        project = self.project
        seat = Seat(tuple(tools), tuple(allowed), tuple(denied))
        session = Dispatcher(project).launch(
            ROLE, brief, self.directory, deadline=deadline, seat=seat
        )
        rows = project.store.rows("SELECT cost FROM sessions WHERE id = ?", (session.id,))
        self.spend(float(rows[0]["cost"] or 0) if rows else 0.0)
        self.refused += session.denied
        if session.exit_code != 0:
            raise RuntimeError(f"the agent exited {session.exit_code} (log: {session.log})")
        return session.result


def main(arguments: list[str]) -> int:
    request = read_json(Path(arguments[0]))
    outcome = Path(request["outcome"])
    step = Step(request)
    try:
        specification = importlib.util.spec_from_file_location(
            f"nock_steps.{step.name}", request["code"]
        )
        assert specification is not None and specification.loader is not None
        module = importlib.util.module_from_spec(specification)
        specification.loader.exec_module(module)
        results = module.run(step)
        if results is None:
            results = {}
        if not isinstance(results, dict):
            raise TypeError(f"run() returned {type(results).__name__}: a step returns a dict")
        json.dumps(results)
    except BaseException as error:
        traceback.print_exc()
        message = f"{type(error).__name__}: {error}"
        write_json(outcome, {"error": message, "cost_usd": step.cost_usd})
        return 1
    write_json(outcome, {"results": results, "cost_usd": step.cost_usd})
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
