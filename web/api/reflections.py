"""api.nock.dev: where `nock share` sends a reflection round's summary. One
endpoint, `POST /reflections`, keeps what it is sent in SQLite — the summary,
its visibility and the round's date, nothing about the sender — and answers
with the id. Nothing is shown anywhere yet. Standard library only.

    python3 reflections.py --database /srv/nock-api/reflections.db --port 8610
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import UTC, datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS reflections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    received TEXT NOT NULL,
    visibility TEXT NOT NULL CHECK (visibility IN ('private', 'public')),
    round TEXT,
    summary TEXT NOT NULL
);
"""
# The longest summary kept; the round asks for a few hundred words.
LONGEST = 20_000
VISIBILITIES = ("private", "public")


class Server(ThreadingHTTPServer):
    def __init__(self, database: Path, port: int) -> None:
        super().__init__(("127.0.0.1", port), Handler)
        self.database = database
        with sqlite3.connect(database) as connection:
            connection.executescript(SCHEMA)

    def keep(self, visibility: str, round: str | None, summary: str) -> int:
        with sqlite3.connect(self.database) as connection:
            cursor = connection.execute(
                "INSERT INTO reflections (received, visibility, round, summary) VALUES (?, ?, ?, ?)",
                (datetime.now(UTC).isoformat(timespec="seconds"), visibility, round, summary),
            )
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
        if self.path.rstrip("/") != "/reflections":
            self.answer(HTTPStatus.NOT_FOUND, {"error": "nothing here"})
            return
        try:
            length = int(self.headers.get("Content-Length", 0))
            if length > LONGEST * 4:
                raise ValueError("too long")
            sent = json.loads(self.rfile.read(length))
            summary, visibility = sent["summary"], sent["visibility"]
            round = sent.get("round")
            if not isinstance(summary, str) or not summary.strip() or len(summary) > LONGEST:
                raise ValueError(f"`summary` is text of at most {LONGEST} characters")
            if visibility not in VISIBILITIES:
                raise ValueError(f"`visibility` is one of {', '.join(VISIBILITIES)}")
            if round is not None and (not isinstance(round, str) or len(round) > 40):
                raise ValueError("`round` is the round's date")
        except (ValueError, KeyError, TypeError) as error:
            self.answer(HTTPStatus.BAD_REQUEST, {"error": str(error)})
            return
        identity = self.store.keep(visibility, round, summary.strip())
        self.answer(HTTPStatus.CREATED, {"id": identity, "visibility": visibility})

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
