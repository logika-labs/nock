"""Real infrastructure: one Postgres 17 container per test run (per worker under xdist), a database per
test cloned from a migrated template, and the server itself on a free port under real uvicorn, on a
virtual clock.

- `postgres`: the run's server; `admin`: a connection to its `postgres` database, to make more.
- `database_url`: a fresh database with every migration applied; `empty_database_url`: one with nothing.
- `clock`: the virtual time the server reads; `api`: the server, answering over HTTP.
- `spans`: the spans the server emits, through the real OpenTelemetry SDK into memory.
"""

import json
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.request
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
import pytest
import uvicorn
from opentelemetry import trace
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from psycopg import sql
from psycopg.rows import dict_row

from nock_api import app, migrate
from nock_api.limit import Limit

IMAGE = "postgres:17-alpine"
TEMPLATE = "migrated"
STARTUP = 60.0


@dataclass(frozen=True)
class Postgres:
    container: str
    port: int

    def url(self, database: str) -> str:
        return f"postgresql://postgres:postgres@127.0.0.1:{self.port}/{database}"


def docker(*arguments: str) -> str:
    return subprocess.run(
        ["docker", *arguments], check=True, capture_output=True, text=True
    ).stdout.strip()


@pytest.fixture(scope="session")
def postgres() -> Iterator[Postgres]:
    container = docker(
        "run", "--detach", "--rm", "--publish", "127.0.0.1::5432",
        "--env", "POSTGRES_PASSWORD=postgres", "--tmpfs", "/var/lib/postgresql/data",
        "--label", "nock-api-tests", IMAGE,
    )  # fmt: skip
    try:
        port = int(docker("port", container, "5432/tcp").splitlines()[0].rsplit(":", 1)[1])
        server = Postgres(container, port)
        deadline = time.monotonic() + STARTUP
        while True:
            try:
                with psycopg.connect(server.url("postgres"), autocommit=True, connect_timeout=2):
                    break
            except psycopg.OperationalError:
                if time.monotonic() > deadline:
                    raise
                time.sleep(0.2)
        with psycopg.connect(server.url("postgres"), autocommit=True) as admin:
            admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(TEMPLATE)))
        with psycopg.connect(server.url(TEMPLATE), autocommit=True) as connection:
            migrate.migrate(connection, migrate.MIGRATIONS)
        yield server
    finally:
        subprocess.run(["docker", "rm", "--force", container], capture_output=True)


@pytest.fixture(scope="session")
def admin(postgres: Postgres) -> Iterator[psycopg.Connection]:
    with psycopg.connect(postgres.url("postgres"), autocommit=True) as connection:
        yield connection


def fresh(postgres: Postgres, admin: psycopg.Connection, template: str) -> Iterator[str]:
    name = f"t_{uuid.uuid4().hex[:16]}"
    admin.execute(
        sql.SQL("CREATE DATABASE {} TEMPLATE {}").format(
            sql.Identifier(name), sql.Identifier(template)
        )
    )
    yield postgres.url(name)
    admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))


@pytest.fixture
def database_url(postgres: Postgres, admin: psycopg.Connection) -> Iterator[str]:
    yield from fresh(postgres, admin, TEMPLATE)


@pytest.fixture
def empty_database_url(postgres: Postgres, admin: psycopg.Connection) -> Iterator[str]:
    yield from fresh(postgres, admin, "template0")


class Clock:
    """Virtual time: what `now()` answers, moved only by the test."""

    def __init__(self) -> None:
        self.moment = datetime(2026, 11, 3, 12, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.moment

    def advance(self, seconds: float) -> None:
        self.moment += timedelta(seconds=seconds)


@pytest.fixture
def clock() -> Clock:
    return Clock()


class Api:
    """The server, run by uvicorn on a socket of its own, as the box runs it."""

    def __init__(self, database_url: str, clock: Clock, limit: Limit) -> None:
        self.database_url = database_url
        self.limit = limit
        self.socket = socket.socket()
        self.socket.bind(("127.0.0.1", 0))
        self.port = self.socket.getsockname()[1]
        self.address = f"http://127.0.0.1:{self.port}"
        config = uvicorn.Config(
            app.create(database_url, clock, limit),
            log_level="warning",
            access_log=False,
            proxy_headers=False,
            server_header=False,
        )
        self.server = uvicorn.Server(config)
        self.thread = threading.Thread(
            target=self.server.run, kwargs={"sockets": [self.socket]}, daemon=True
        )
        self.thread.start()
        deadline = time.monotonic() + STARTUP
        while not self.server.started:
            assert self.thread.is_alive() and time.monotonic() < deadline, (
                "the server did not start"
            )
            time.sleep(0.01)

    def stop(self) -> None:
        self.server.should_exit = True
        self.thread.join(10)
        self.socket.close()

    def exchange(
        self, path: str, body: Any, sender: str | None = None, method: str = "POST"
    ) -> tuple[int, dict[str, Any], dict[str, str]]:
        data = (
            None if body is None else body if isinstance(body, bytes) else json.dumps(body).encode()
        )
        headers = {"Content-Type": "application/json"}
        if sender is not None:
            headers["X-Forwarded-For"] = sender
        request = urllib.request.Request(
            self.address + path, data=data, headers=headers, method=method
        )
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                answer = response.status, json.loads(response.read()), response.headers
        except urllib.error.HTTPError as error:
            answer = error.code, json.loads(error.read() or b"{}"), error.headers
        status, sent, headers = answer
        return status, sent, {name.lower(): value for name, value in headers.items()}

    def post(self, path: str, body: Any, sender: str | None = None) -> tuple[int, dict[str, Any]]:
        status, answer, _ = self.exchange(path, body, sender)
        return status, answer

    def get(self, path: str) -> tuple[int, dict[str, Any]]:
        status, answer, _ = self.exchange(path, None, method="GET")
        return status, answer

    def rows(self, table: str) -> list[dict[str, Any]]:
        query = sql.SQL("SELECT * FROM {} ORDER BY id").format(sql.Identifier(table))
        with (
            psycopg.connect(self.database_url) as connection,
            connection.cursor(row_factory=dict_row) as cursor,
        ):
            return cursor.execute(query).fetchall()

    def answer_to(self, head: bytes) -> bytes:
        """The status code for a request of headers only: a body announced is never sent, so an answer
        at all shows it was refused unread."""
        with socket.create_connection(("127.0.0.1", self.port), timeout=10) as connection:
            connection.sendall(head + b"\r\n")
            return connection.recv(64).split(b" ")[1]


@pytest.fixture
def limit() -> Limit:
    return Limit()


@pytest.fixture
def api(database_url: str, clock: Clock, limit: Limit) -> Iterator[Api]:
    running = Api(database_url, clock, limit)
    yield running
    running.stop()


class Spans:
    def __init__(self) -> None:
        self.exporter = InMemorySpanExporter()
        self.provider = TracerProvider()
        self.provider.add_span_processor(SimpleSpanProcessor(self.exporter))

    def finished(self) -> list[ReadableSpan]:
        return list(self.exporter.get_finished_spans())


@pytest.fixture(scope="session")
def spans_provider() -> Spans:
    collected = Spans()
    trace.set_tracer_provider(collected.provider)
    return collected


@pytest.fixture
def spans(spans_provider: Spans) -> Spans:
    spans_provider.exporter.clear()
    return spans_provider
