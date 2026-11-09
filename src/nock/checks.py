"""Checks: every test of the work, as one verdict. A check says the code is
wrong (exit 1) or the machine is (42) — never both, so the first look names the
cause. A project's checks are its configured commands (`[checks.NAME] command
= …` in `.nock/config.toml`) and its `@nock.check` functions; nock adds its own
over the toolbox and the generated files. Checks that share a `chain` run
one after another (they share a build, a lock, a cache); everything else runs
side by side.

`check` runs only the checks the branch's changes can affect (`check --all`
runs every one): the paths changed since it left the main branch, committed
or not. A check's
`paths` are globs (`**` any directories, `*` within one, a leading `!`
excludes; the last that matches wins); one without any is affected by every
change, and a change no check's `paths` or `checks.unaffected` names runs them
all. A command check's `focus` globs name the paths its command can be pointed
at: when every affecting change matches one and still exists, they are
appended to the command, so `pytest` runs only the test files changed."""

from __future__ import annotations

import fcntl
import functools
import os
import re
import shlex
import time
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from nock.errors import Error, ExitCode, NotFoundError
from nock.fixtures import Call, CommandFailed, Scope
from nock.git import Git, GitError
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

    def run(
        self, only: list[str] | None = None, fix: bool = False, changed: bool = False
    ) -> Verdict:
        """The checks named (a chain's name stands for its checks), or all of
        them: each chain's checks one after another, the chains side by side;
        with `changed`, only those the branch's changes can affect."""
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
        focus: dict[str, list[str]] = {}
        if changed:
            paths = self.changed_paths()
            if paths is not None:
                chosen, focus = self.affected(chosen, paths)
        plan = [[name for name in chain if name in chosen] for chain in chains.values()]
        plan = [chain for chain in plan if chain]
        if not plan:
            return Verdict({})
        results: dict[str, Result] = {}
        with self.slot(), ThreadPoolExecutor(max_workers=len(plan)) as pool:
            for finished in pool.map(lambda chain: self.run_chain(chain, fix, focus), plan):
                results.update(finished)
        return Verdict({name: results[name] for name in available if name in results})

    def changed_paths(self) -> list[str] | None:
        """The paths changed since the branch left the main branch: committed,
        staged, unstaged and untracked; None when there is no main branch to
        compare with, which stands for everything."""
        git = Git(self.project.here)
        try:
            base = git("merge-base", "HEAD", str(self.project.configuration.get("branch")))
            tracked = git("diff", "--name-only", "--no-renames", base, "--")
            untracked = git("ls-files", "--others", "--exclude-standard")
        except GitError:
            return None
        return sorted({line for line in [*tracked.splitlines(), *untracked.splitlines()] if line})

    def affected(
        self, chosen: set[str], changed: list[str]
    ) -> tuple[set[str], dict[str, list[str]]]:
        """Of the checks chosen, those the changed paths can affect, and for
        each with `focus` that all its affecting paths fit, those paths."""
        sections = self.project.configuration.section("checks")
        declared = {name: self.paths_of(name) for name in self.available()}
        unaffected = list(self.project.configuration.get("checks.unaffected", []) or [])
        if any(
            not matches(path, unaffected)
            and not any(matches(path, globs) for globs in declared.values() if globs)
            for path in changed
        ):
            return chosen, {}
        selected: set[str] = set()
        focus: dict[str, list[str]] = {}
        for name in chosen:
            globs = declared.get(name, [])
            relevant = [path for path in changed if not globs or matches(path, globs)]
            if not relevant:
                continue
            selected.add(name)
            settings = sections.get(name)
            targets = list(settings.get("focus") or []) if isinstance(settings, dict) else []
            if targets and all(
                matches(path, targets) and (self.project.here / path).exists() for path in relevant
            ):
                focus[name] = relevant
        return selected, focus

    def paths_of(self, name: str) -> list[str]:
        settings = self.project.configuration.section("checks").get(name)
        if isinstance(settings, dict) and "paths" in settings:
            return [str(glob) for glob in settings["paths"]]
        entry = self.project.registry.checks.get(name)
        return list(entry.paths) if entry is not None else []

    def run_chain(
        self, chain: list[str], fix: bool, focus: dict[str, list[str]]
    ) -> dict[str, Result]:
        return {name: self.run_one(name, fix, focus.get(name)) for name in chain}

    def run_one(self, name: str, fix: bool, focus: list[str] | None = None) -> Result:
        settings = self.project.configuration.section("checks").get(name)
        registry = self.project.registry
        values = {"project": self.project, "call": Call(None, f"check {name}"), "fix": fix}
        try:
            with Scope(registry, values) as scope:
                if isinstance(settings, dict) and settings.get("command"):
                    return self.run_command(scope, settings, fix, focus)
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

    def run_command(
        self, scope: Scope, settings: dict[str, Any], fix: bool, focus: list[str] | None = None
    ) -> Result:
        """A configured command, pointed at `focus` when given: exit 0 passes,
        any of its failure codes (default 1) fails, anything else is the
        machine."""
        sh = scope.get("sh")
        directory = settings.get("directory")
        bounds = {
            "deadline": float(settings["deadline"]) if "deadline" in settings else None,
            "silence": float(settings["silence"]) if "silence" in settings else None,
        }
        command = settings["command"]
        if focus:
            command = (
                f"{command} {shlex.join(focus)}" if isinstance(command, str) else [*command, *focus]
            )
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


def matches(path: str, globs: list[str]) -> bool:
    """Whether the globs take in the path: the last that matches it decides,
    and one starting with `!` leaves it out."""
    taken = False
    for glob in globs:
        excluded = glob.startswith("!")
        if compiled(glob.removeprefix("!")).fullmatch(path):
            taken = not excluded
    return taken


@functools.cache
def compiled(glob: str) -> re.Pattern[str]:
    """`**` is any directories (`a/**/b` takes `a/b`), `*` and `?` stay
    within one, the rest is literal."""
    parts, index = [], 0
    while index < len(glob):
        if glob.startswith("**/", index):
            parts.append("(?:.*/)?")
            index += 3
        elif glob.startswith("**", index):
            parts.append(".*")
            index += 2
        elif glob[index] == "*":
            parts.append("[^/]*")
            index += 1
        elif glob[index] == "?":
            parts.append("[^/]")
            index += 1
        else:
            parts.append(re.escape(glob[index]))
            index += 1
    return re.compile("".join(parts))
