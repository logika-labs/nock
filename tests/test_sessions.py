"""Sessions as telemetry counts them: a `claude -p` run is headless and kept
out of the owner's numbers, a transcript is read on as it grows and never
counted twice, and a session's cost is its tokens at API prices — or unknown."""

from __future__ import annotations

import json
import os
import shutil
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from nock.prices import Prices
from nock.project import Project
from nock.reflect import Material, Reflection
from nock.sessions import Sessions, encoded

from .conftest import PRICES, nock
from .test_telemetry_and_reflection import transcript


def stamp(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def prompt(text: str, moment: datetime, entrypoint: str = "cli") -> dict[str, Any]:
    return {
        "type": "user",
        "timestamp": stamp(moment),
        "entrypoint": entrypoint,
        "cwd": "/work",
        "message": {"role": "user", "content": text},
    }


def call(
    message: str, tool_use: str, command: str, moment: datetime, input_tokens: int = 100
) -> dict[str, Any]:
    return {
        "type": "assistant",
        "timestamp": stamp(moment),
        "message": {
            "id": message,
            "model": "claude-opus-5-5",
            "usage": {"input_tokens": input_tokens, "output_tokens": 10},
            "content": [
                {"type": "tool_use", "id": tool_use, "name": "Bash", "input": {"command": command}}
            ],
        },
    }


def result(tool_use: str, size: int, moment: datetime, failed: bool = False) -> dict[str, Any]:
    return {
        "type": "user",
        "timestamp": stamp(moment),
        "message": {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": tool_use,
                    "content": "x" * size,
                    "is_error": failed,
                }
            ],
        },
    }


def lines(records: list[dict[str, Any]]) -> str:
    return "".join(json.dumps(record) + "\n" for record in records)


def place(project: Project, session: str, text: str) -> Path:
    directory = Path(os.environ["CLAUDE_CONFIG_DIR"]) / "projects" / encoded(project.root)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{session}.jsonl"
    path.write_text(text)
    return path


def kept(project: Project, session: str) -> dict[str, Any]:
    """What the store holds of a session, without what names or dates the read."""
    (row,) = project.store.rows("SELECT * FROM sessions WHERE id = ?", (session,))
    return {
        "session": {k: v for k, v in row.items() if k not in ("id", "transcript", "ingested")},
        "events": project.store.rows(
            "SELECT moment, tool, input, failed, output_bytes, duration FROM events"
            " WHERE session = ? ORDER BY rowid",
            (session,),
        ),
        "prompts": project.store.rows(
            "SELECT moment, text FROM prompts WHERE session = ? ORDER BY rowid", (session,)
        ),
    }


def test_a_claude_p_run_is_headless_and_kept_out_of_the_owner_s_numbers(
    project: Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    transcript(project, "person", ["Fix the login bug"], [("pytest", 10, False)])
    transcript(
        project,
        "grader",
        ["Grade this diff", "Answer in JSON"],
        [("cat diff", 10, False), ("cat rubric", 10, True)],
        entrypoint="sdk-cli",
    )
    Sessions(project).catch_up()
    roles = {row["id"]: row["role"] for row in project.store.rows("SELECT id, role FROM sessions")}
    assert roles == {"person": "interactive", "grader": "headless"}
    window = Reflection(project).window()
    assert [row["id"] for row in window.sessions] == ["person"]
    metrics = Reflection(project).metrics(window)
    assert (metrics["sessions"], metrics["headless_sessions"]) == (1, 1)
    assert (metrics["requests"], metrics["tool_calls"], metrics["failed_tool_calls"]) == (1, 1, 0)
    assert "Grade this diff" not in Material(project, window, None).render()
    listed = json.loads(nock(project.root, "query", "sessions", "--json").stdout)
    assert {row["id"]: row["role"] for row in listed} == roles
    monkeypatch.setenv("CLAUDE_CODE_ENTRYPOINT", "sdk-cli")
    assert project.current_role() == "headless"
    monkeypatch.setenv("CLAUDE_CODE_ENTRYPOINT", "cli")
    assert project.current_role() is None


def test_a_growing_transcript_read_twice_counts_each_thing_once(project: Project) -> None:
    start = datetime.now(UTC).replace(microsecond=0) - timedelta(hours=1)
    second = timedelta(seconds=1)
    first = lines(
        [
            prompt("Build it", start),
            call("m1", "t1", "make build", start + second),
            # A message's blocks come as records of their own, each with its usage.
            call("m1", "t1-again", "make build", start + second),
        ]
    )
    # The result is still being written when the transcript is first read.
    late = json.dumps(result("t1", 50, start + 3 * second, failed=True)) + "\n"
    rest = lines(
        [
            prompt("Now test it", start + 4 * second),
            call("m2", "t2", "make test", start + 5 * second, input_tokens=200),
            result("t2", 7, start + 6 * second),
        ]
    )
    path = place(project, "long", first + late[:20])
    sessions = Sessions(project)
    assert sessions.catch_up() == 1
    early = kept(project, "long")
    assert early["session"]["prompts"] == 1 and early["session"]["input_tokens"] == 100
    assert [event["output_bytes"] for event in early["events"]] == [0, 0]
    with path.open("a") as handle:
        handle.write(late[20:] + rest)
    assert sessions.catch_up() == 1
    assert sessions.catch_up() == 0
    grown = kept(project, "long")
    whole = place(project, "whole", path.read_text())
    sessions.ingest(whole)
    assert grown == kept(project, "whole")
    assert grown["session"]["input_tokens"] == 300 and grown["session"]["prompts"] == 2
    assert [row["text"] for row in grown["prompts"]] == ["Build it", "Now test it"]
    assert [
        (e["input"], e["failed"], e["output_bytes"], e["duration"]) for e in grown["events"]
    ] == [
        ("make build", 1, 50, 2.0),
        ("make build", 0, 0, None),
        ("make test", 0, 7, 1.0),
    ]


def test_a_session_still_running_counts_in_usage_without_ending(project: Project) -> None:
    today = datetime.now(UTC).replace(microsecond=0) - timedelta(hours=1)
    weeks_ago = today - timedelta(days=13)
    place(
        project,
        "running",
        lines(
            [
                prompt("Plan the month", weeks_ago),
                call("m1", "t1", "ls", weeks_ago),
                result("t1", 3, weeks_ago),
                prompt("Next step", today),
                call("m2", "t2", "make", today),
                result("t2", 3, today),
            ]
        ),
    )
    metrics = json.loads(nock(project.root, "config", "share", "--json").stdout)["would_send"][
        "metrics"
    ]
    # Only what the session did inside the week's window is the week's work.
    assert (metrics["sessions"], metrics["requests"], metrics["tool_calls"]) == (1, 1, 1)
    assert metrics["input_tokens"] == 200 and metrics["tokens"] == 220


def test_a_session_costs_its_tokens_at_the_table_s_api_prices(project: Project) -> None:
    transcript(
        project, "opus", ["work"], [("a", 1, False), ("b", 1, False)], model="claude-opus-5-5"
    )
    Sessions(project).catch_up()
    (row,) = project.store.rows("SELECT cost FROM sessions")
    # Twice 100 input, 20 output and 1000 cache-read tokens at 4, 20 and 0.2 dollars per million.
    assert row["cost"] == pytest.approx(2 * (100 * 4e-6 + 20 * 2e-5 + 1000 * 2e-7))
    cached = json.loads((project.local / "prices.json").read_text())
    assert cached["models"]["claude-opus-5-5"]["cache_read"] == 2e-7
    metrics = Reflection(project).metrics(Reflection(project).window())
    assert metrics["api_cost"] == pytest.approx(0.002) and metrics["unpriced_sessions"] == 0


def test_a_dated_model_name_is_priced_as_its_undated_one(project: Project) -> None:
    transcript(project, "haiku", ["work"], [("a", 1, False)], model="claude-haiku-4-5-20991231")
    Sessions(project).catch_up()
    (row,) = project.store.rows("SELECT cost FROM sessions")
    assert row["cost"] == pytest.approx(100 * 1e-6 + 20 * 5e-6 + 1000 * 1e-7)


def test_an_unpriced_session_is_unknown_never_zero_and_priced_once_it_can_be(
    project: Project,
) -> None:
    offline = {"tried": time.time()}
    (project.local / "prices.json").write_text(json.dumps(offline))
    transcript(project, "offline", ["work"], [("a", 1, False)], model="claude-opus-5-5")
    transcript(project, "unknown", ["work"], [("a", 1, False)], model="claude-test")
    Sessions(project).catch_up()
    window = Reflection(project).window()
    metrics = Reflection(project).metrics(window)
    assert (metrics["api_cost"], metrics["unpriced_sessions"]) == (None, 2)
    assert "cost unknown" in Material(project, window, None).overview()
    usage = json.loads(nock(project.root, "config", "share", "--json").stdout)["would_send"]
    assert usage["schema"] == 3 and usage["metrics"]["api_cost"] is None
    listed = json.loads(nock(project.root, "query", "sessions", "--json").stdout)
    assert {row["api_cost"] for row in listed} == {"unknown"}
    # Back online: the cache and its failed try are gone, the table is fetched.
    (project.local / "prices.json").unlink()
    Prices(project, PRICES.as_uri()).table()
    Sessions(project).catch_up()
    window = Reflection(project).window()
    assert Reflection(project).metrics(window)["unpriced_sessions"] == 1
    overview = Material(project, window, None).overview()
    assert "at API prices, 1 session(s) unpriced" in overview


def test_a_transcript_replaced_by_a_shorter_one_is_read_afresh(project: Project) -> None:
    path = transcript(project, "s1", ["one", "two"], [("a", 1, False), ("b", 1, False)])
    Sessions(project).catch_up()
    shutil.copy(transcript(project, "s2", ["three"], []), path)
    Sessions(project).catch_up()
    assert kept(project, "s1")["prompts"][0]["text"] == "three"
    assert kept(project, "s1")["events"] == []
