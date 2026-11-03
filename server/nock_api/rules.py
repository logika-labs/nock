"""What the API keeps, field by field: a round's summary and a usage report exactly as nock builds them
(`src/nock/share.py`, `src/nock/usage.py`). A body with any field it should not have is refused whole."""

import math
import re
import uuid
from typing import Any

# The longest summary kept; the round asks for a few hundred words.
LONGEST = 20_000
# The largest body read, in bytes, per path: a summary's JSON escapes may take four bytes a character;
# a real usage report is about two thousand.
LARGEST = {"/reflections": LONGEST * 4, "/usage": 32_000}
# The usage report's shapes this server reads (nock's `usage.SCHEMA`): 3 adds metrics that may be
# null — `api_cost` when no session in the window was priced.
REPORT_SCHEMAS = (2, 3)
NAME = re.compile(r"[a-z][a-z0-9_-]{0,39}")
COMMAND = re.compile(r"[a-z][a-z0-9-]*( [a-z][a-z0-9-]*){0,3}")
VERSION = re.compile(r"\d{1,4}(\.\d{1,4}){1,3}([a-z0-9.+-]{0,20})")
PYTHON = re.compile(r"\d\.\d{1,3}")
PLATFORM = re.compile(r"[a-z][a-z0-9]{0,19}")
SETTINGS = ("reminders", "consult", "logika")
TOOLBOX = ("tools", "checks", "hooks", "generators", "load_failures")
COUNT = ("calls", "failures")
REPORT = (
    "schema",
    "project",
    "nock",
    "python",
    "platform",
    "settings",
    "metrics",
    "commands",
    "toolbox",
    "rounds",
)


class Refused(ValueError):
    """The body is not what the endpoint keeps. `reason` is one of a few words that say why without
    repeating anything sent, for the server's own telemetry."""

    def __init__(self, message: str, reason: str = "value") -> None:
        super().__init__(message)
        self.reason = reason


def fields(
    value: Any, where: str, required: tuple[str, ...], optional: tuple[str, ...] = ()
) -> dict[str, Any]:
    """An object with exactly these fields (the optional ones aside)."""
    if not isinstance(value, dict):
        raise Refused(f"`{where}` is an object", "fields")
    unexpected = sorted(set(value) - set(required) - set(optional))
    if unexpected:
        raise Refused(f"`{where}` has unexpected fields: {', '.join(unexpected)}", "fields")
    missing = [name for name in required if name not in value]
    if missing:
        raise Refused(f"`{where}` lacks {', '.join(missing)}", "fields")
    return value


def count(value: Any, where: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value < 10**12:
        raise Refused(f"`{where}` is a whole number of at least 0")


def number(value: Any, where: str) -> None:
    if (
        isinstance(value, bool)
        or not isinstance(value, int | float)
        or not math.isfinite(value)
        or not 0 <= value < 10**12
    ):
        raise Refused(f"`{where}` is a number of at least 0")


def text(value: Any, where: str, pattern: re.Pattern[str]) -> None:
    if not isinstance(value, str) or not pattern.fullmatch(value):
        raise Refused(f"`{where}` is not what it should be")


def names(value: Any, where: str, pattern: re.Pattern[str], most: int) -> dict[str, Any]:
    """An object keyed by nock's own names, never more than `most` of them."""
    if not isinstance(value, dict) or len(value) > most:
        raise Refused(f"`{where}` is an object of at most {most} entries", "fields")
    for key in value:
        text(key, f"{where}: {key[:40]}", pattern)
    return value


def storable(value: str) -> bool:
    """Text Postgres can hold: no NUL, and nothing that is not Unicode (a lone surrogate)."""
    if "\x00" in value:
        return False
    try:
        value.encode()
    except UnicodeEncodeError:
        return False
    return True


def report(sent: Any) -> dict[str, Any]:
    """A usage report as nock builds it (`usage.Usage.report`), or `Refused`."""
    body = fields(sent, "report", REPORT)
    if body["schema"] not in REPORT_SCHEMAS or isinstance(body["schema"], bool):
        raise Refused(
            f"`schema` is one of {', '.join(map(str, REPORT_SCHEMAS))}: this server reads no other",
            "schema",
        )
    project = body["project"]
    try:
        canonical = isinstance(project, str) and str(uuid.UUID(project, version=4)) == project
    except ValueError:
        canonical = False
    if not canonical:
        raise Refused("`project` is a random UUID, version 4, in lower case", "project")
    text(body["nock"], "nock", VERSION)
    text(body["python"], "python", PYTHON)
    text(body["platform"], "platform", PLATFORM)
    for name, value in fields(body["settings"], "settings", SETTINGS).items():
        if not isinstance(value, bool):
            raise Refused(f"`settings.{name}` is true or false")
    for name, value in names(body["metrics"], "metrics", NAME, 64).items():
        if value is None and body["schema"] >= 3:
            continue
        number(value, f"metrics.{name}")
    for name, counts in names(body["commands"], "commands", COMMAND, 120).items():
        for field, value in fields(counts, f"commands.{name}", COUNT).items():
            count(value, f"commands.{name}.{field}")
    for name, value in fields(body["toolbox"], "toolbox", TOOLBOX).items():
        count(value, f"toolbox.{name}")
    for name, value in names(body["rounds"], "rounds", NAME, 20).items():
        count(value, f"rounds.{name}")
    return body


def reflection(sent: Any) -> tuple[str, str | None]:
    """A summary, stripped, and its round's date, or `Refused`."""
    body = fields(sent, "body", ("summary",), ("round",))
    summary, round = body["summary"], body.get("round")
    if (
        not isinstance(summary, str)
        or not summary.strip()
        or len(summary) > LONGEST
        or not storable(summary)
    ):
        raise Refused(f"`summary` is text of at most {LONGEST} characters")
    if round is not None and (not isinstance(round, str) or len(round) > 40 or not storable(round)):
        raise Refused("`round` is the round's date")
    return summary.strip(), round
