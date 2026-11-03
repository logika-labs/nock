"""api.nock.dev (`web/api/reflections.py`), run for real on a free port with a
real SQLite database: what it keeps, every body it refuses, and its rate
limit on a virtual clock."""

from __future__ import annotations

import importlib.util
import json
import socket
import sqlite3
import threading
import urllib.error
import urllib.request
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from nock.project import Project
from nock.usage import Usage

from .test_quiet_and_sharing import end_session

SOURCE = Path(__file__).resolve().parent.parent / "web" / "api" / "reflections.py"


def load() -> ModuleType:
    specification = importlib.util.spec_from_file_location("reflections", SOURCE)
    assert specification and specification.loader
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


API = load()


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class Api:
    def __init__(self, database: Path) -> None:
        self.database = database
        self.clock = Clock()
        self.server = API.Server(database, 0, self.clock)
        self.address = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def post(self, path: str, body: Any, sender: str | None = None) -> tuple[int, dict[str, Any]]:
        status, answer, _ = self.exchange(path, body, sender)
        return status, answer

    def exchange(
        self, path: str, body: Any, sender: str | None = None
    ) -> tuple[int, dict[str, Any], dict[str, str]]:
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        headers = {"Content-Type": "application/json"}
        if sender is not None:
            headers["X-Forwarded-For"] = sender
        request = urllib.request.Request(
            self.address + path, data=data, headers=headers, method="POST"
        )
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return response.status, json.loads(response.read()), dict(response.headers)
        except urllib.error.HTTPError as error:
            return error.code, json.loads(error.read() or b"{}"), dict(error.headers)

    def rows(self, table: str) -> list[dict[str, Any]]:
        with sqlite3.connect(self.database) as connection:
            connection.row_factory = sqlite3.Row
            return [dict(row) for row in connection.execute(f"SELECT * FROM {table}")]


@pytest.fixture
def api(tmp_path: Path) -> Iterator[Api]:
    running = Api(tmp_path / "api.db")
    yield running
    running.server.shutdown()
    running.server.server_close()


REPORT: dict[str, Any] = {
    "schema": 2,
    "project": "6f1c2b9e-3d4a-4e5f-8a7b-1c2d3e4f5a6b",
    "nock": "0.3.0",
    "python": "3.12",
    "platform": "darwin",
    "settings": {"reminders": True, "consult": True, "logika": False},
    "metrics": {"days": 7.0, "sessions": 3, "cost": 1.25},
    "commands": {
        "decide": {"calls": 1, "failures": 0},
        "decisions edit": {"calls": 2, "failures": 1},
    },
    "toolbox": {"tools": 1, "checks": 2, "hooks": 0, "generators": 0, "load_failures": 0},
    "rounds": {"nock": 1, "logika": 0},
}


def test_the_report_nock_builds_is_kept(project: Project, api: Api) -> None:
    end_session(project, "s1")
    built = Usage(project).report(sending=True)
    status, answer = api.post("/usage", built)
    assert (status, answer) == (201, {"id": 1})
    (row,) = api.rows("usage")
    assert row["project"] == built["project"] and row["schema"] == 3
    assert json.loads(row["report"]) == built


@pytest.mark.parametrize(
    ("change", "said"),
    [
        ({"tools": [{"tool": "deploy", "calls": 1, "failures": 0}]}, "unexpected fields: tools"),
        ({"level": "anonymous"}, "unexpected fields: level"),
        ({"settings": {**REPORT["settings"], "branch": "main"}}, "unexpected fields: branch"),
        ({"commands": {"decide": {"calls": 1, "failures": 0, "arguments": "x"}}}, "unexpected"),
        ({"commands": {"acme_payroll": {"calls": 1, "failures": 0}}}, "commands"),
        ({"metrics": {"Fix the login bug": 1}}, "metrics"),
        ({"metrics": {"sessions": "three"}}, "metrics.sessions"),
        ({"metrics": {"sessions": True}}, "metrics.sessions"),
        ({"toolbox": {**REPORT["toolbox"], "tools": -1}}, "toolbox.tools"),
        ({"project": "/Users/someone/acme"}, "`project` is a random UUID"),
        ({"project": "6F1C2B9E-3D4A-4E5F-8A7B-1C2D3E4F5A6B"}, "`project` is a random UUID"),
        ({"schema": 1}, "`schema` is one of 2, 3"),
        ({"schema": 2, "metrics": {"api_cost": None}}, "metrics.api_cost"),
        ({"platform": "a laptop at acme"}, "platform"),
    ],
)
def test_a_report_with_anything_unexpected_is_refused_whole(
    api: Api, change: dict[str, Any], said: str
) -> None:
    status, answer = api.post("/usage", {**REPORT, **change})
    assert status == 400 and said in answer["error"]
    assert api.rows("usage") == []


def test_a_report_missing_a_field_too_large_or_not_json_is_refused(api: Api) -> None:
    missing = {key: value for key, value in REPORT.items() if key != "rounds"}
    assert api.post("/usage", missing)[0] == 400
    assert api.post("/usage", b"not json")[0] == 400
    many = {f"metric_{index}": index for index in range(65)}
    assert api.post("/usage", {**REPORT, "metrics": many})[0] == 400
    assert api.post("/usage", b"{" + b" " * API.LARGEST_REPORT + b"}")[0] == 413
    assert api.post("/elsewhere", REPORT)[0] == 404
    assert api.rows("usage") == []


def test_a_summary_is_kept_without_anything_about_its_sender(api: Api) -> None:
    status, answer = api.post("/reflections", {"summary": " Early days. ", "round": "2026-10-31"})
    assert (status, answer) == (201, {"id": 1})
    assert [
        {k: v for k, v in row.items() if k != "received"} for row in api.rows("reflections")
    ] == [{"id": 1, "round": "2026-10-31", "summary": "Early days."}]
    refused, said = api.post("/reflections", {"summary": "Hi.", "visibility": "public"})
    assert refused == 400 and "unexpected fields: visibility" in said["error"]
    assert api.post("/reflections", {"summary": "  "})[0] == 400
    assert len(api.rows("reflections")) == 1


def answer_to(api: Api, head: bytes) -> bytes:
    """The status code for a request of headers only: a body announced is never sent,
    so an answer at all shows it was refused unread."""
    with socket.create_connection(api.server.server_address, timeout=10) as connection:
        connection.sendall(head + b"\r\n")
        return connection.recv(64).split(b" ")[1]


def test_bodies_past_the_proxy_s_cap_or_without_a_length_are_refused_unread(api: Api) -> None:
    for path in (b"/usage", b"/reflections"):
        head = b"POST " + path + b" HTTP/1.1\r\nHost: x\r\nContent-Length: 131072\r\n"
        assert answer_to(api, head) == b"413"
    negative = b"POST /usage HTTP/1.1\r\nHost: x\r\nContent-Length: -1\r\n"
    assert answer_to(api, negative) == b"400"
    assert answer_to(api, b"POST /usage HTTP/1.1\r\nHost: x\r\n") == (b"411")
    assert api.rows("usage") == [] and api.rows("reflections") == []


def test_an_address_gets_a_burst_of_five_then_six_a_minute_across_both_endpoints(
    api: Api,
) -> None:
    sender = "203.0.113.7"
    for path in ("/usage", "/reflections", "/usage", "/reflections", "/usage"):
        assert api.post(path, REPORT if path == "/usage" else {"summary": "Hi."}, sender)[0] == 201
    status, answer, headers = api.exchange("/reflections", {"summary": "Hi."}, sender)
    assert status == 429 and "a minute" in answer["error"]
    assert headers["Retry-After"] == "10"
    assert api.post("/usage", REPORT, sender)[0] == 429
    assert api.post("/usage", REPORT, "198.51.100.4")[0] == 201
    api.clock.now += 9
    assert api.post("/usage", REPORT, sender)[0] == 429
    api.clock.now += 1
    assert api.post("/usage", REPORT, sender)[0] == 201
    assert api.post("/usage", REPORT, sender)[0] == 429
    api.clock.now += 60
    assert [api.post("/usage", REPORT, sender)[0] for _ in range(6)] == [201] * 5 + [429]
    assert len(api.rows("usage")) == 3 + 1 + 1 + 5


def test_the_first_forwarded_address_is_the_sender(api: Api) -> None:
    for index in range(5):
        assert api.post("/usage", REPORT, f"203.0.113.9, 10.0.0.{index}")[0] == 201
    assert api.post("/usage", REPORT, "203.0.113.9")[0] == 429
    assert api.post("/usage", REPORT, "10.0.0.1")[0] == 201


def test_addresses_are_held_in_memory_only_and_forgotten_once_idle(
    api: Api, monkeypatch: pytest.MonkeyPatch
) -> None:
    for index in range(4):
        assert api.post("/usage", REPORT, f"203.0.113.{index}")[0] == 201
    assert list(api.server.limit.buckets) == [f"203.0.113.{index}" for index in range(4)]
    api.clock.now += 9
    api.post("/usage", REPORT, "203.0.113.0")
    api.clock.now += 1
    api.post("/usage", REPORT, "198.51.100.1")
    assert list(api.server.limit.buckets) == ["203.0.113.0", "198.51.100.1"]
    api.clock.now += 15
    api.post("/usage", REPORT, "198.51.100.2")
    assert list(api.server.limit.buckets) == ["198.51.100.2"]
    monkeypatch.setattr(API, "MOST_ADDRESSES", 3)
    for index in range(6):
        api.post("/usage", REPORT, f"192.0.2.{index}")
    assert list(api.server.limit.buckets) == ["192.0.2.3", "192.0.2.4", "192.0.2.5"]
    assert b"203.0.113" not in api.database.read_bytes()
