"""The project's settings: nock's defaults, overlaid by `.nock/config.toml`,
overlaid by the machine's own `.nock/local/config.toml`."""

from __future__ import annotations

import copy
import json
import re
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
    # Whether nock tells the owner when a topic is their turn again (it moved to
    # review, an agent answered them, an item they rejected has a new version):
    # on the desktop, or in the studio's page while it is open. Nothing shows
    # without a display (CI, a headless agent).
    "notifications": True,
    "run": {
        # Bounds on a supervised process (`sh`, `nock run`), in seconds; silence
        # is how long it may print nothing before it counts as hung.
        "deadline": 3600,
        "silence": 900,
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
    "checks": {
        # Globs of paths no check depends on (prose, records), so that
        # `check` does not run everything when only they change.
        "unaffected": [],
    },
    "agent": {
        # The headless agent nock dispatches (consult, the studio's Ask) and its model
        # ("" is Claude Code's default); bounds in seconds.
        "command": ["claude"],
        "model": "",
        "deadline": 1800,
        "silence": 600,
    },
    "studio": {
        # The port `nock studio` serves on, and the one a notification's link
        # names while no studio runs.
        "port": 8765,
        # Where the studio's recorder sends what the owner says, to have it
        # written into the chat: a Whisper server speaking OpenAI's
        # `/v1/audio/transcriptions` (OpenAI itself, whisper.cpp's server,
        # faster-whisper-server). Empty turns the recorder off. A bare server, or
        # one ending in `/v1`, gets `/v1/audio/transcriptions` added.
        "transcribe_url": "",
        # The `model` sent with each recording: OpenAI's is "whisper-1"; whisper.cpp
        # ignores it; faster-whisper-server takes its own ("Systran/faster-whisper-small").
        "transcribe_model": "whisper-1",
        # The name of the environment variable holding the server's key, sent as
        # a bearer token ("OPENAI_API_KEY"); empty sends none. Never the key itself.
        "transcribe_key_variable": "",
    },
    "inbox": {
        # How long `nock inbox --wait` waits, in seconds: under Claude Code's
        # ten-minute limit on a command.
        "wait": 540,
        # How long the owner is quiet after a verdict or a comment before the
        # waiting agent hears them, so a triage lands as one batch.
        "settle": 60,
    },
    "consult": {
        # Whether the consultant runs, and the primer asks agents to consult.
        "enabled": True,
    },
    "upgrade": {
        # Whether a session the human starts says when a newer nock is out
        # (PyPI is asked at most once a day), and where releases are looked up:
        # tests point it at a local index, since a hook or `nock upgrade` runs as
        # its own process.
        "check": True,
        # Whether that session upgrades a core vendored from PyPI to it by
        # itself, once per release, when the merge is clean; off, it only says so.
        "auto": True,
        "index": "https://pypi.org/pypi/nock",
    },
    # `share`, whether nock shares a usage report with its makers (counts and
    # categories, and a random id for the project), weekly, has no default: unset
    # is unanswered and sends nothing until the owner says yes (`nock config share
    # true|false` writes it); false sends nothing at all, summaries included — only
    # what someone writes and sends themselves with `nock report` still goes.
    "endpoints": {
        # Where `nock share` sends a round's summary, when the owner says so.
        "reflections": "https://api.nock.dev/reflections",
        # Where the usage reports go, once a week at most.
        "usage": "https://api.nock.dev/usage",
        # Where `nock report` sends what the user wrote, on their word.
        "reports": "https://api.nock.dev/reports",
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


def with_table_settings(text: str, table: str, values: dict[str, Any]) -> str:
    """A TOML file's text with `key = "value"` set in `[table]`: each key's
    line replaced where the table has it, the rest added at the table's end;
    the table added at the file's end when it has none."""
    lines = text.splitlines(keepends=True)
    if lines and not lines[-1].endswith("\n"):
        lines[-1] += "\n"
    start = next((index for index, line in enumerate(lines) if line.strip() == f"[{table}]"), None)
    if start is None:
        if lines and lines[-1].strip():
            lines.append("\n")
        lines.append(f"[{table}]\n")
        start = len(lines) - 1
    end = next(
        (index for index in range(start + 1, len(lines)) if lines[index].lstrip().startswith("[")),
        len(lines),
    )
    while end > start + 1 and not lines[end - 1].strip():
        end -= 1
    added = []
    for key, value in values.items():
        setting = f"{key} = {json.dumps(value)}\n"
        found = next(
            (index for index in range(start + 1, end) if re.match(rf"^\s*{key}\s*=", lines[index])),
            None,
        )
        if found is None:
            added.append(setting)
        else:
            lines[found] = setting
    lines[end:end] = added
    return "".join(lines)


# Who a setting belongs to, which says the file `nock config KEY VALUE`
# writes: the team's in `.nock/shared/settings.toml`, committed with the topics;
# one machine's in `.nock/local/config.toml`. The code's (checks, environment,
# permissions, …) stay in `.nock/config.toml`, written by hand.
TEAM = ("share", "reminders", "inbox", "consult", "agent")
MACHINE = (
    "notifications",
    "studio.port",
    "studio.transcribe_url",
    "studio.transcribe_model",
    "studio.transcribe_key_variable",
)


def scope_of(key: str) -> str | None:
    """`team`, `machine`, or None for a key `nock config` does not write."""
    if key in MACHINE:
        return "machine"
    if key.split(".")[0] in TEAM:
        return "team"
    return None


def with_key(text: str, key: str, value: Any) -> str:
    """A TOML file's text with a dotted key set: `share`, `studio.port`,
    `inbox.settle`."""
    table, _, name = key.rpartition(".")
    if table:
        return with_table_settings(text, table, {name: value})
    lines = text.splitlines(keepends=True)
    tables = [index for index, line in enumerate(lines) if line.lstrip().startswith("[")]
    top = tables[0] if tables else len(lines)
    setting = f"{key} = {json.dumps(value)}\n"
    for index in range(top):
        if re.match(rf"^#?\s*{re.escape(key)}\s*=", lines[index]):
            lines[index] = setting
            return "".join(lines)
    lines.insert(top, setting + ("\n" if tables else ""))
    return "".join(lines)
