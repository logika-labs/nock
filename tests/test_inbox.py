"""What the owner said reaches agents through `nock inbox`: Address now
first, then the global chat, comments, verdicts; each reader shown an entry
once, and an entry gone for everyone once an agent addressed it. `search`,
`config` and `query` are the other ways in."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from nock.inbox import Inbox, listeners
from nock.project import Project
from nock.topics import Author, Topics

from .conftest import git, nock
from .test_topics import DECISION, submit


def inbox(project: Project, *arguments: str) -> list[dict[str, Any]]:
    result = nock(project.root, "inbox", *arguments, "--json")
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_the_owner_s_word_comes_most_urgent_first_and_once_per_reader(
    project: Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "maker")
    mine = submit(project.root)
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "other")
    theirs = submit(project.root, {**DECISION, "title": "Refunds are capped"})
    topics = Topics(project)
    topics.reply(theirs, "Capped at what?", Author.OWNER)
    topics.reply(mine, "Why not Postgres?", Author.OWNER)
    topics.judge(theirs, {"verdict": "accepted"})  # type: ignore[typeddict-item]
    folder = topics.shared.topic_folder("orders")
    path = topics.shared.draft(folder, {"kind": "message", "text": "Look now.", "now": True})
    topics.shared.settle({"author": "owner", "on_behalf": "interactive"}, only=[path])
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "maker")
    found = inbox(project)
    assert [(entry["kind"], entry["ref"]) for entry in found] == [
        ("now", "orders"),
        ("comment", mine),
        ("verdict", theirs),
    ]
    assert found[1]["yours"] is True and found[2]["verdict"] == "accepted"
    # Shown once to this reader; another still sees what is not addressed — an
    # acceptance asks nothing more once an agent has heard it.
    assert inbox(project) == []
    assert [entry["kind"] for entry in inbox(project, "--all")] == ["now", "comment"]
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "helper")
    assert [entry["kind"] for entry in inbox(project)] == ["now", "comment"]
    # An agent's answer addresses a comment for everyone.
    topics.reply(mine, "One file is enough.", Author.AGENT)
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "late")
    assert [entry["kind"] for entry in inbox(project)] == ["now"]


def test_waiting_returns_a_message_at_once_and_verdicts_once_the_owner_is_quiet(
    project: Project,
) -> None:
    ref = submit(project.root)
    topics = Topics(project)
    topics.judge(ref, {"verdict": "rejected", "comment": "Postgres."})  # type: ignore[typeddict-item]
    clock = [2_000_000_000.0]
    waited: list[float] = []

    def pause(seconds: float) -> None:
        waited.append(seconds)
        clock[0] += seconds

    reader = Inbox(project, "s1")
    # The verdict came "now" by the store's clock, long before this one: quiet already.
    found = reader.wait(30, 60, now=lambda: clock[0], pause=pause)
    assert [entry["kind"] for entry in found] == ["verdict"] and waited == []
    reader.mark_shown(found)
    assert reader.wait(5, 60, now=lambda: clock[0], pause=pause) == []
    assert sum(waited) >= 5
    assert listeners(project, now=clock[0]) == []


def test_search_finds_decisions_and_topics_with_their_views(project: Project) -> None:
    ref = submit(project.root)
    found = json.loads(nock(project.root, "search", "sqlite", "--json").stdout)
    (decision,) = found["decisions"]
    assert decision["ref"] == ref and decision["view"].endswith("views/orders.md")
    assert Path(decision["view"]).read_text().startswith("# orders")


def test_config_writes_the_team_s_settings_and_the_machine_s_where_each_belongs(
    project: Project,
) -> None:
    settings = project.root / ".nock" / "shared" / "settings.toml"
    set_team = json.loads(nock(project.root, "config", "inbox.settle", "30", "--json").stdout)
    assert set_team["value"] == 30 and set_team["kept"] == str(settings)
    assert "[inbox]\nsettle = 30\n" in settings.read_text()
    assert git(project.root, "status", "--porcelain") == ""
    machine = json.loads(nock(project.root, "config", "studio.port", "8800", "--json").stdout)
    assert machine["kept"].endswith(".nock/local/config.toml") and machine["value"] == 8800
    listed = {row["key"]: row for row in json.loads(nock(project.root, "config", "--json").stdout)}
    assert listed["inbox.settle"]["value"] == 30 and listed["studio.port"]["value"] == 8800
    refused = nock(project.root, "config", "checks.concurrency", "4")
    assert refused.returncode == 40 and "written by hand" in refused.stderr


def test_query_reads_the_telemetry_and_its_views(project: Project) -> None:
    nock(project.root, "status")
    rows = json.loads(nock(project.root, "query", "SELECT tool FROM calls", "--json").stdout)
    assert {"tool": "status"} in rows
    calls = json.loads(nock(project.root, "query", "calls", "--json").stdout)
    assert calls and calls[0]["call"].startswith("query")
