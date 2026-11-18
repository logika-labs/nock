"""What the owner said reaches agents through `nock inbox`: a message sent
for an answer now first, then other messages with the notes they carry,
proposals accepted (to carry out) and rejected, Done on a review; each reader
shown an entry once, and an entry gone for everyone once an agent acted on
it. `search`, `config` and `query` are the other ways in."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from nock.inbox import Inbox, listeners
from nock.project import Project

from .conftest import git, nock
from .store import compose, item_event, open_topic, propose, reply, submit, topics_in


def inbox(project: Project, *arguments: str) -> list[dict[str, Any]]:
    result = nock(project.root, "inbox", *arguments, "--json")
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_the_owner_s_word_comes_most_urgent_first_and_once_per_reader(
    project: Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = project.root
    submit(root)
    accepted = propose(root, slug="archive")
    rejected = propose(root, slug="purge")
    open_topic(root, "refunds")
    topics = topics_in(root)
    topics.judge(accepted, "accepted")
    topics.judge(rejected, "rejected")
    topics.note("orders", {"item": "sqlite"}, "Why not Postgres?")
    topics.send("orders", "Look at my note.", now=True)
    topics.send("refunds", "Capped at what?", now=False)
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "agent-session")
    found = inbox(project)
    assert [(entry["kind"], entry["ref"]) for entry in found] == [
        ("now", "orders"),
        ("message", "refunds"),
        ("accepted", accepted),
        ("rejected", rejected),
    ]
    assert found[0]["yours"] is True
    assert found[0]["notes"] == [{"on": "item sqlite", "text": "Why not Postgres?"}]
    # Shown once to this reader; another still sees what is not acted on — a
    # rejection asks nothing more once an agent has heard it.
    assert inbox(project) == []
    assert [entry["kind"] for entry in inbox(project, "--all")] == ["now", "message", "accepted"]
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "helper")
    assert [entry["kind"] for entry in inbox(project)] == ["now", "message", "accepted"]
    # An agent's answer and a proposal carried out are acted on for everyone.
    reply(root, "orders", "Load is low.")
    item_event(root, accepted, {"kind": "implemented", "means": "Archived nightly."})
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "late")
    assert [entry["kind"] for entry in inbox(project)] == ["message"]


def test_done_on_a_review_reaches_agents_once(project: Project) -> None:
    root = project.root
    submit(root)
    compose(root, "orders", [{"kind": "item", "item": "sqlite"}])
    topics_in(root).done("orders")
    first = Inbox(project, "s1").entries()
    assert [entry["kind"] for entry in first] == ["reviewed"]
    Inbox(project, "s1").mark_shown(first)
    assert Inbox(project, "s2").entries() == []


def test_waiting_returns_a_message_at_once_and_verdicts_once_the_owner_is_quiet(
    project: Project,
) -> None:
    ref = propose(project.root)
    topics_in(project.root).judge(ref, "rejected")
    clock = [2_000_000_000.0]
    waited: list[float] = []

    def pause(seconds: float) -> None:
        waited.append(seconds)
        clock[0] += seconds

    reader = Inbox(project, "s1")
    # The verdict came "now" by the store's clock, long before this one: quiet already.
    found = reader.wait(30, 60, now=lambda: clock[0], pause=pause)
    assert [entry["kind"] for entry in found] == ["rejected"] and waited == []
    reader.mark_shown(found)
    assert reader.wait(5, 60, now=lambda: clock[0], pause=pause) == []
    assert sum(waited) >= 5
    assert listeners(project, now=clock[0]) == []


def test_search_finds_items_and_topics_with_their_views(project: Project) -> None:
    ref = submit(project.root)
    found = json.loads(nock(project.root, "search", "sqlite", "--json").stdout)
    (item,) = found["items"]
    assert item["ref"] == ref and item["view"].endswith("views/orders.md")
    assert Path(item["view"]).read_text().startswith("# orders")


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
