"""Checks: every test of the work, as one verdict. A check says the code is
wrong (exit 1) or the machine is (42) — never both, so the first look names the
cause. A project's checks are its configured commands (`[checks.NAME] command
= …` in `.nock/config.toml`) and its `@nock.check` functions; nock adds its own
over the toolbox and the generated files. Checks that share a `chain` run
one after another (they share a build, a lock, a cache); everything else runs
side by side."""

from __future__ import annotations

import fcntl
import os
import time
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from nock.errors import Error, ExitCode, NotFoundError
from nock.fixtures import Call, CommandFailed, Scope
from nock.render import PACKAGE_INTERNAL, crash

if TYPE_CHECKING:
    from nock.project import Project


class Outcome(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    """The code is wrong."""
    BROKEN = "broken"
    """The machine is wrong: a missing tool, a hang, a timeout, a crash."""


@dataclass
class Result:
    outcome: Outcome
    problems: list[str] = field(default_factory=list)
    exit_code: int = ExitCode.SUCCESS


@dataclass
class Verdict:
    results: dict[str, Result]

    @property
    def exit_code(self) -> int:
        """1 when any check failed and none broke; the broken code otherwise."""
        for result in self.results.values():
            if result.outcome is Outcome.BROKEN:
                return result.exit_code
        if any(result.outcome is Outcome.FAILED for result in self.results.values()):
            return ExitCode.SUBJECT_FAILED
        return ExitCode.SUCCESS

    def problems(self) -> list[str]:
        """Each failing or broken check's findings, a line each, prefixed by its name."""
        lines = []
        for name, result in self.results.items():
            if result.outcome is Outcome.PASSED:
                continue
            marker = f"{name} (broken)" if result.outcome is Outcome.BROKEN else name
            for problem in result.problems or ["failed"]:
                first, *rest = problem.split("\n")
                lines.append(f"{marker}: {first}")
                lines += [f"  {line}" for line in rest]
        return lines


class Checks:
    """Every check the project has, run as one gate."""

    def __init__(self, project: Project) -> None:
        self.project = project

    def available(self) -> dict[str, str]:
        """Name → description."""
        found = {
            name: str(settings.get("description") or settings["command"])
            for name, settings in self.project.configuration.section("checks").items()
            if isinstance(settings, dict) and settings.get("command")
        }
        for name, entry in self.project.registry.checks.items():
            found[name] = entry.description
        disabled = self.project.configuration.get("checks.disabled", []) or []
        return {name: value for name, value in found.items() if name not in disabled}

    def chains(self) -> dict[str, list[str]]:
        """Chain → its checks, in the order they are configured. A check with
        no `chain` is a chain of its own."""
        chains: dict[str, list[str]] = {}
        sections = self.project.configuration.section("checks")
        for name in self.available():
            settings = sections.get(name)
            chain = settings.get("chain") if isinstance(settings, dict) else None
            chains.setdefault(str(chain or name), []).append(name)
        return chains

    def run(self, only: list[str] | None = None, fix: bool = False) -> Verdict:
        """The checks named (a chain's name stands for its checks), or all of
        them: each chain's checks one after another, the chains side by side."""
        available = self.available()
        chains = self.chains()
        missing = [name for name in only or [] if name not in available and name not in chains]
        if missing:
            named = [name for name in chains if name not in available]
            raise NotFoundError(
                f"no check named {', '.join(missing)}; there are: {', '.join(available)}"
                + (f"; chains: {', '.join(named)}" if named else "")
            )
        chosen = {
            name
            for item in only or list(available)
            for name in (chains[item] if item in chains and item not in available else [item])
        }
        plan = [[name for name in chain if name in chosen] for chain in chains.values()]
        plan = [chain for chain in plan if chain]
        results: dict[str, Result] = {}
        with self.slot(), ThreadPoolExecutor(max_workers=len(plan) or 1) as pool:
            for finished in pool.map(lambda chain: self.run_chain(chain, fix), plan):
                results.update(finished)
        return Verdict({name: results[name] for name in available if name in results})

    def run_chain(self, chain: list[str], fix: bool) -> dict[str, Result]:
        return {name: self.run_one(name, fix) for name in chain}

    def run_one(self, name: str, fix: bool) -> Result:
        settings = self.project.configuration.section("checks").get(name)
        registry = self.project.registry
        values = {"project": self.project, "call": Call(None, f"check {name}"), "fix": fix}
        try:
            with Scope(registry, values) as scope:
                if isinstance(settings, dict) and settings.get("command"):
                    return self.run_command(scope, settings, fix)
                found = scope.call(registry.checks[name].function)
        except CommandFailed as failure:
            return Result(Outcome.FAILED, [str(failure.value)], ExitCode.SUBJECT_FAILED)
        except Error as error:
            if error.exit_code == ExitCode.SUBJECT_FAILED:
                return Result(Outcome.FAILED, [str(error)], ExitCode.SUBJECT_FAILED)
            return Result(Outcome.BROKEN, [str(error)], error.exit_code)
        except Exception as error:
            return Result(
                Outcome.BROKEN,
                [f"the check crashed — {crash(error, PACKAGE_INTERNAL)}"],
                ExitCode.INTERNAL,
            )
        problems = (
            [str(item) for item in found]
            if isinstance(found, (list, tuple))
            else ([] if not found else [str(found)])
        )
        if problems:
            return Result(Outcome.FAILED, problems, ExitCode.SUBJECT_FAILED)
        return Result(Outcome.PASSED)

    def run_command(self, scope: Scope, settings: dict[str, Any], fix: bool) -> Result:
        """A configured command: exit 0 passes, any of its failure codes
        (default 1) fails, anything else is the machine."""
        sh = scope.get("sh")
        directory = settings.get("directory")
        bounds = {
            "deadline": float(settings["deadline"]) if "deadline" in settings else None,
            "silence": float(settings["silence"]) if "silence" in settings else None,
        }
        command = settings["command"]
        if fix and settings.get("fix"):
            sh(settings["fix"], check=False, directory=directory, **bounds)
        output = sh(command, check=False, directory=directory, **bounds)
        if output.ok:
            return Result(Outcome.PASSED)
        characters = int(self.project.configuration.get("output.characters")) // 2
        if output.code in (settings.get("failure_codes") or [1]):
            evidence = output.excerpt(characters) if output.text.strip() else ""
            return Result(
                Outcome.FAILED,
                [evidence or f"exited {output.code}, printing nothing"],
                ExitCode.SUBJECT_FAILED,
            )
        code = (
            output.code
            if output.code in (ExitCode.TIMED_OUT, ExitCode.HUNG)
            else ExitCode.PRECONDITIONS
        )
        return Result(
            Outcome.BROKEN,
            [f"exited {output.code} — the machine, not the code:\n{output.excerpt(characters)}"],
            code,
        )

    @contextmanager
    def slot(self) -> Iterator[None]:
        """One of `checks.concurrency` machine-wide slots, so parallel callers
        do not run their suites all at once and slow each other to a crawl."""
        capacity = max(1, int(self.project.configuration.get("checks.concurrency", 2)))
        directory = self.project.local / "locks"
        directory.mkdir(parents=True, exist_ok=True)
        while True:
            for index in range(capacity):
                handle = (directory / f"check-slot-{index}.lock").open("w")
                try:
                    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    handle.close()
                    continue
                try:
                    yield
                finally:
                    fcntl.flock(handle, fcntl.LOCK_UN)
                    handle.close()
                return
            time.sleep(1 + (os.getpid() % 7) / 10)
