"""nock: a project's toolbox, built by its agents for themselves — an
agent-friendly CLI framework, telemetry of every call and session, and
reflection rounds that turn that telemetry into better tools.

What a project's `.nock/tools/` modules use (`.nock/nock docs` explains it):

    import nock

    @nock.command(cache="src/**", examples=["--path tests"])
    def failures(sh, *, path: str = "tests") -> list[dict]: ...

    @nock.check
    def no_todos(root, changed) -> list[nock.Problem]: ...

    @nock.fixture
    def db(root): ...

    @nock.hook("session-start")
    def remind(payload) -> str: ...

    @nock.generator("src/errors.py")
    def errors(root) -> str: ...
"""

import importlib
import sys

if sys.version_info < (3, 12):  # noqa: UP036 — vendored, it runs on whatever python3 there is
    sys.exit("nock needs Python 3.12 or newer; set NOCK_PYTHON to one")

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nock.commands import Option
    from nock.errors import (
        ConflictError,
        Error,
        Exit,
        Failed,
        NotFoundError,
        PreconditionError,
        UsageError,
    )
    from nock.hooks import Block
    from nock.processes import Output
    from nock.project import Project
    from nock.render import Problem
    from nock.tools import check, command, fixture, generator, hook

# Where each name above lives: loaded on first use, so `python -m nock hook`
# loads only what the hook needs.
MODULES = {
    "Block": "nock.hooks",
    "ConflictError": "nock.errors",
    "Error": "nock.errors",
    "Exit": "nock.errors",
    "Failed": "nock.errors",
    "NotFoundError": "nock.errors",
    "Option": "nock.commands",
    "Output": "nock.processes",
    "PreconditionError": "nock.errors",
    "Problem": "nock.render",
    "Project": "nock.project",
    "UsageError": "nock.errors",
    "check": "nock.tools",
    "command": "nock.tools",
    "fixture": "nock.tools",
    "generator": "nock.tools",
    "hook": "nock.tools",
}


def __getattr__(name: str) -> object:
    if name not in MODULES:
        raise AttributeError(f"module 'nock' has no attribute {name!r}")
    value = getattr(importlib.import_module(MODULES[name]), name)
    globals()[name] = value
    return value


__all__ = [
    "Block",
    "ConflictError",
    "Error",
    "Exit",
    "Failed",
    "NotFoundError",
    "Option",
    "Output",
    "PreconditionError",
    "Problem",
    "Project",
    "UsageError",
    "check",
    "command",
    "fixture",
    "generator",
    "hook",
]
