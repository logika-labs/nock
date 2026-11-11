"""The project's environment, which its tools, checks, generators and hooks
run in: the interpreter that can import the project's own packages
(`environment.python`, which nock re-executes itself on), directories put
first on PATH, and a dotenv file's variables. nock itself stays
standard-library, so any Python 3.12 or newer runs it."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from nock.errors import Error
from nock.project import Project
from nock.utils import cache_bytecode

# Set on the process nock re-executes itself as, and removed at once, so a
# nock that a tool starts decides afresh.
REEXECUTED_VARIABLE = "NOCK_REEXECUTED"
DOTENV_LINE = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$")


class Environment:
    """What `[environment]` in the settings asks for, for one project."""

    def __init__(self, project: Project) -> None:
        self.project = project
        self.settings = project.configuration.section("environment")

    def enter(self, arguments: list[str], setup: bool = True) -> list[str]:
        """Re-execute nock on the project's interpreter unless it already runs
        on it, then apply PATH and the dotenv to this process, which its
        children inherit. A missing interpreter is made by `environment.setup`
        first, when `setup` allows (never in a hook, which must be quick).
        Returns notes for the caller: an interpreter still missing leaves nock
        on the one it has."""
        notes = []
        if os.environ.pop(REEXECUTED_VARIABLE, None) is None:
            configured = str(self.settings.get("python") or "")
            interpreter = self.interpreter(configured)
            command = str(self.settings.get("setup") or "")
            if configured and interpreter is None and command and setup:
                notes += self.set_up(command)
                interpreter = self.interpreter(configured)
            if configured and interpreter is None:
                remedy = f"`{command}`" if command else "its setup"
                notes.append(
                    f"the project's interpreter {configured} (environment.python) is missing, so "
                    f"tools that need the project's packages will not load — run {remedy} first"
                )
            elif interpreter is not None and not running(interpreter):
                cache_bytecode()
                os.execve(
                    interpreter,
                    [str(interpreter), "-m", "nock", *arguments],
                    {**os.environ, REEXECUTED_VARIABLE: "1"},
                )
        self.apply()
        return notes

    def set_up(self, command: str) -> list[str]:
        """Run `environment.setup` in the working tree, its output on stderr so
        the call's own output stays clean."""
        sys.stderr.write(f"nock: setting the project's environment up: {command}\n")
        sys.stderr.flush()
        result = subprocess.run(
            command, shell=True, cwd=self.project.here, stdout=sys.stderr, stderr=sys.stderr
        )
        return [] if result.returncode == 0 else [f"`{command}` exited {result.returncode}"]

    def interpreter(self, configured: str) -> Path | None:
        """A path is relative to the working tree, so each worktree uses its
        own; a bare name is looked up on PATH."""
        if not configured:
            return None
        if "/" not in configured:
            found = shutil.which(configured)
            return Path(os.path.abspath(found)) if found else None
        path = Path(os.path.abspath(self.project.here / Path(configured).expanduser()))
        return path if path.is_file() and os.access(path, os.X_OK) else None

    def apply(self) -> None:
        directories = [
            str(self.project.here / Path(str(entry)).expanduser())
            for entry in self.settings.get("path") or []
        ]
        if directories:
            os.environ["PATH"] = os.pathsep.join([*directories, os.environ.get("PATH", "")])
        dotenv = self.dotenv()
        if dotenv is not None:
            for name, value in parse_dotenv(dotenv.read_text()).items():
                os.environ.setdefault(name, value)

    def dotenv(self) -> Path | None:
        """The working tree's file, else the main checkout's: a dotenv is
        rarely committed, so a fresh worktree has none of its own."""
        name = self.settings.get("dotenv")
        if not name:
            return None
        for base in (self.project.here, self.project.root):
            path = base / str(name)
            if path.is_file():
                return path
        return None


def enter(arguments: list[str]) -> None:
    """Run on the project's interpreter, with its PATH and dotenv, before
    anything loads its tools."""
    try:
        project = Project.discover()
    except Error:
        return
    for note in Environment(project).enter(arguments, setup=arguments[:1] != ["hook"]):
        sys.stderr.write(f"nock: {note}\n")


def running(interpreter: Path) -> bool:
    """Whether this process already runs on `interpreter`: the same file, or
    another name for it in the same directory (a venv's `python` and
    `python3`), so it has the same site-packages and needs no re-execution."""
    current = Path(os.path.abspath(sys.executable))
    if current == interpreter:
        return True
    try:
        return current.parent == interpreter.parent and os.path.samefile(current, interpreter)
    except OSError:
        return False


def parse_dotenv(text: str) -> dict[str, str]:
    """`NAME=value` lines, `export` allowed, values optionally quoted;
    comments and anything else skipped."""
    found = {}
    for line in text.splitlines():
        if line.lstrip().startswith("#"):
            continue
        match = DOTENV_LINE.match(line)
        if not match:
            continue
        name, value = match.groups()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        else:
            value = value.split(" #", 1)[0].rstrip()
        found[name] = value
    return found
