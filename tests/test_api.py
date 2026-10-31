"""api.nock.dev (`web/api/reflections.py`), run for real on a free port with a
real SQLite database: what it keeps, and every body it refuses."""

from __future__ import annotations

import importlib.util
import json
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


class Api:
    def __init__(self, database: Path) -> None:
        self.database = database
        self.server = API.Server(database, 0)
        self.address = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def post(self, path: str, body: Any) -> tuple[int, dict[str, Any]]:
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        request = urllib.request.Request(
            self.address + path,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as error:
            return error.code, json.loads(error.read() or b"{}")

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
    assert row["project"] == built["project"] and row["schema"] == 2
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
        ({"schema": 1}, "`schema` is 2"),
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
