"""The project's settings: nock's defaults, overlaid by `.nock/config.toml`,
overlaid by the machine's own `.nock/local/config.toml`."""

from __future__ import annotations

import copy
import tomllib
from enum import StrEnum
from pathlib import Path
from typing import Any

from nock.errors import PreconditionError

DEFAULTS: dict[str, Any] = {
    # The project's main branch.
    "branch": "main",
    # Whether nock speaks up unasked: the primer's advice, the toolbox and the
    # occasional standing at a session's start, the owner's word at a prompt,
    # the items about an edited file. False keeps nock silent unless asked
    # (telemetry is still recorded).
    "reminders": True,
    "output": {
        # The most characters a call prints before the rest goes to a file. Claude
        # Code shows a failed command only ~10k characters, middle cut, no path.
        "characters": 8000,
        # The most rows of a table a call prints before the rest goes to a file.
        "rows": 60,
    },
    "run": {
        # Bounds on a supervised process (`sh`, `nock run`), in seconds; silence
        # is how long it may print nothing before it counts as hung.
        "deadline": 3600,
        "silence": 900,
        # A dot on stdout per this many seconds of silence, so a watcher knows
        # the process is alive.
        "heartbeat": 60,
    },
    "environment": {
        # What the project's tools, checks, generators and hooks run in. `python`
        # is the interpreter nock re-executes itself on, so tools can import the
        # project's packages (a path is relative to the working tree, so each
        # worktree has its own; empty is whatever runs the shim). `setup` is the
        # command that makes it when it is missing (`uv sync`). `path` puts
        # directories first on PATH (relative ones to the working tree, `~`
        # expanded), and `dotenv` names a file whose variables are set unless
        # already set (the working tree's, else the main checkout's).
        "python": "",
        "setup": "",
        "path": [],
        "dotenv": "",
    },
    "permissions": {
        # How Claude Code treats a `confirm=True` command (`nock init` writes the
        # rules): "ask" has the owner approve each call, even in bypass mode;
        # "allow" lets the agent run it, when the owner's request calls for it.
        "confirm": "ask",
    },
    "eval": {
        # Where each evaluation scenario's cache lives. Empty is evals/NAME/cache/,
        # committed beside the code; a directory (`~` expanded, a relative path
        # from the working tree) holds it as DIRECTORY/NAME instead, outside git,
        # for outputs too big to commit (whole repositories, databases).
        "cache": "",
    },
    "checks": {
        # How many check suites may run at once on this machine.
        "concurrency": 2,
        # Globs of paths no check depends on (prose, records), so that
        # `check --changed` does not run everything when only they change.
        "unaffected": [],
    },
    "reflect": {
        # A round is due after this many sessions since the last one, or this
        # many days — whichever comes first, given a session to look at.
        "sessions": 15,
        "days": 7,
        # In a Logika project, a logika round is offered this many days after
        # the last one, once the ledger has changed since.
        "logika": {"days": 30},
    },
    "agent": {
        # The headless agent nock dispatches (consult, the studio's Ask) and its model
        # ("" is Claude Code's default); bounds in seconds.
        "command": ["claude"],
        "model": "",
        "deadline": 1800,
        "silence": 600,
    },
    "consult": {
        # Whether the consultant runs, and the primer asks agents to consult.
        "enabled": True,
        # The longest a consultation may take, in seconds: the caller waits.
        "deadline": 600,
    },
    "upgrade": {
        # Whether a session the human starts says when a newer nock is out
        # (PyPI is asked at most once a day), and where releases are looked up.
        "check": True,
        # Whether that session upgrades a core vendored from PyPI to it by
        # itself, once per release, when the merge is clean; off, it only says so.
        "auto": True,
        "index": "https://pypi.org/pypi/nock",
    },
    # `share`, whether nock shares a usage report with its makers (counts and
    # categories, and a random id for the project), weekly, has no default: unset
    # is unanswered and sends nothing until the owner says yes (`nock usage share
    # yes|no` writes it); false sends nothing at all, summaries included — only
    # what someone writes and sends themselves with `nock report` still goes.
    "endpoints": {
        # Where `nock share` sends a round's summary, when the owner says so.
        "reflections": "https://api.nock.dev/reflections",
        # Where the usage reports go, once a week at most.
        "usage": "https://api.nock.dev/usage",
        # Where `nock report` sends what the user wrote, on their word.
        "reports": "https://api.nock.dev/reports",
    },
    "pricing": {
        # Sessions are costed at API prices (API-equivalent: a subscription does
        # not pay per token) from LiteLLM's public table, fetched with a plain GET
        # at most daily and cached in .nock/local/; false never fetches it.
        "fetch": True,
        "table": "https://raw.githubusercontent.com/BerriAI/litellm/main/model_prices_and_context_window.json",
        # Any other key is a model-name prefix whose prices override the table's:
        # dollars per million tokens, {input, output, cache_read, cache_write}.
    },
}


class Confirm(StrEnum):
    """What Claude Code does when an agent calls a `confirm=True` command."""

    ASK = "ask"
    ALLOW = "allow"


def merged(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = merged(result[key], value)
        else:
            result[key] = value
    return result


class Configuration:
    """Settings read by dotted key: `configuration.get("run.deadline")`."""

    def __init__(self, files: list[Path]) -> None:
        self.values = DEFAULTS
        for file in files:
            if file.is_file():
                try:
                    self.values = merged(self.values, tomllib.loads(file.read_text()))
                except tomllib.TOMLDecodeError as error:
                    raise PreconditionError(f"{file} is not valid TOML: {error}") from error

    def get(self, key: str, default: Any = None) -> Any:
        value: Any = self.values
        for part in key.split("."):
            if not isinstance(value, dict) or part not in value:
                return default
            value = value[part]
        return value

    def confirm(self) -> Confirm:
        value = self.get("permissions.confirm")
        try:
            return Confirm(value)
        except ValueError:
            raise PreconditionError(
                f'permissions.confirm is {value!r}; it is "ask" or "allow"'
            ) from None

    def section(self, key: str) -> dict[str, Any]:
        value = self.get(key, {})
        return value if isinstance(value, dict) else {}
