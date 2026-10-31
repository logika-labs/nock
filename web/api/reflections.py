"""api.nock.dev: what nock sends its makers. `POST /reflections` keeps a
reflection round's summary that `nock share` sends on the owner's word;
`POST /usage` keeps a weekly anonymous usage report. Both are kept in SQLite
with the moment they arrived and nothing about the sender, and answer with
the id. A body with a field it should not have is refused whole. Nothing is
shown anywhere yet. Standard library only.

    python3 reflections.py --database /srv/nock-api/reflections.db --port 8610
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sqlite3
import uuid
from datetime import UTC, datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS reflections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    received TEXT NOT NULL,
    round TEXT,
    summary TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS usage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    received TEXT NOT NULL,
    project TEXT NOT NULL,
    schema INTEGER NOT NULL,
    report TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS usage_by_project ON usage (project);
"""
# The longest summary kept; the round asks for a few hundred words.
LONGEST = 20_000
# The largest usage report read, in bytes; a real one is about two thousand.
LARGEST_REPORT = 32_000
# The usage report's shape this server reads (nock's `usage.SCHEMA`).
REPORT_SCHEMA = 2
NAME = re.compile(r"[a-z][a-z0-9_-]{0,39}")
COMMAND = re.compile(r"[a-z][a-z0-9-]*( [a-z][a-z0-9-]*){0,3}")
VERSION = re.compile(r"\d{1,4}(\.\d{1,4}){1,3}([a-z0-9.+-]{0,20})")
PYTHON = re.compile(r"\d\.\d{1,3}")
PLATFORM = re.compile(r"[a-z][a-z0-9]{0,19}")
SETTINGS = ("reminders", "consult", "logika")
TOOLBOX = ("tools", "checks", "hooks", "generators", "load_failures")
COUNT = ("calls", "failures")


class Refused(ValueError):
    """The body is not what the endpoint keeps."""


def fields(
    value: Any, where: str, required: tuple[str, ...], optional: tuple[str, ...] = ()
) -> dict[str, Any]:
    """An object with exactly these fields (the optional ones aside)."""
    if not isinstance(value, dict):
        raise Refused(f"`{where}` is an object")
    unexpected = sorted(set(value) - set(required) - set(optional))
    if unexpected:
        raise Refused(f"`{where}` has unexpected fields: {', '.join(unexpected)}")
    missing = [name for name in required if name not in value]
    if missing:
        raise Refused(f"`{where}` lacks {', '.join(missing)}")
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
        raise Refused(f"`{where}` is an object of at most {most} entries")
    for key in value:
        text(key, f"{where}: {key[:40]}", pattern)
    return value


def report(sent: Any) -> dict[str, Any]:
    """A usage report as nock builds it (`usage.Usage.report`), or `Refused`."""
    body = fields(
        sent,
        "report",
        (
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
        ),
    )
    if body["schema"] != REPORT_SCHEMA or isinstance(body["schema"], bool):
        raise Refused(f"`schema` is {REPORT_SCHEMA}: this server reads no other")
    project = body["project"]
    try:
        canonical = isinstance(project, str) and str(uuid.UUID(project, version=4)) == project
    except ValueError:
        canonical = False
    if not canonical:
        raise Refused("`project` is a random UUID, version 4, in lower case")
    text(body["nock"], "nock", VERSION)
    text(body["python"], "python", PYTHON)
    text(body["platform"], "platform", PLATFORM)
    for name, value in fields(body["settings"], "settings", SETTINGS).items():
        if not isinstance(value, bool):
            raise Refused(f"`settings.{name}` is true or false")
    for name, value in names(body["metrics"], "metrics", NAME, 64).items():
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
    """A summary and its round's date, or `Refused`."""
    body = fields(sent, "body", ("summary",), ("round",))
    summary, round = body["summary"], body.get("round")
    if not isinstance(summary, str) or not summary.strip() or len(summary) > LONGEST:
        raise Refused(f"`summary` is text of at most {LONGEST} characters")
    if round is not None and (not isinstance(round, str) or len(round) > 40):
        raise Refused("`round` is the round's date")
    return summary.strip(), round


class Server(ThreadingHTTPServer):
    def __init__(self, database: Path, port: int) -> None:
        super().__init__(("127.0.0.1", port), Handler)
        self.database = database
        with sqlite3.connect(database) as connection:
            connection.executescript(SCHEMA)

    def keep(self, statement: str, values: tuple[Any, ...]) -> int:
        received = datetime.now(UTC).isoformat(timespec="seconds")
        with sqlite3.connect(self.database) as connection:
            cursor = connection.execute(statement, (received, *values))
            return int(cursor.lastrowid or 0)


class Handler(BaseHTTPRequestHandler):
    server_version = "nock"
    sys_version = ""

    @property
    def store(self) -> Server:
        assert isinstance(self.server, Server)
        return self.server

    def do_GET(self) -> None:
        if self.path == "/health":
            self.answer(HTTPStatus.OK, {"ok": True})
        else:
            self.answer(HTTPStatus.NOT_FOUND, {"error": "nothing here"})

    def do_POST(self) -> None:
        path = self.path.rstrip("/")
        largest = {"/reflections": LONGEST * 4, "/usage": LARGEST_REPORT}.get(path)
        if largest is None:
            self.answer(HTTPStatus.NOT_FOUND, {"error": "nothing here"})
            return
        try:
            length = int(self.headers.get("Content-Length", 0))
            if length > largest:
                self.answer(
                    HTTPStatus.REQUEST_ENTITY_TOO_LARGE, {"error": f"at most {largest} bytes"}
                )
                return
            sent = json.loads(self.rfile.read(length))
            if path == "/usage":
                body = report(sent)
                identity = self.store.keep(
                    "INSERT INTO usage (received, project, schema, report) VALUES (?, ?, ?, ?)",
                    (body["project"], body["schema"], json.dumps(body, sort_keys=True)),
                )
            else:
                summary, round = reflection(sent)
                identity = self.store.keep(
                    "INSERT INTO reflections (received, round, summary) VALUES (?, ?, ?)",
                    (round, summary),
                )
        except (ValueError, TypeError) as error:
            self.answer(HTTPStatus.BAD_REQUEST, {"error": str(error)})
            return
        self.answer(HTTPStatus.CREATED, {"id": identity})

    def answer(self, status: HTTPStatus, value: Any) -> None:
        body = json.dumps(value).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *arguments: Any) -> None:
        pass


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--port", type=int, default=8610)
    arguments = parser.parse_args()
    Server(arguments.database, arguments.port).serve_forever()


if __name__ == "__main__":
    main()
