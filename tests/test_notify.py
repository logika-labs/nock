"""Review notifications: the owner is told when a topic is their turn again (it
moved to review, an agent answered them, an item they rejected has a new
version), once per topic per few minutes, in the studio's page while one is
watching and on the desktop otherwise; never for what the owner did, never
without a display. No test shows a real notification: the suite has no
display (`CI`), and the desktop's command is only built, against stand-in
programs on PATH."""

from __future__ import annotations

import json
import os
import urllib.request
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest

from nock.notify import WATCHED, WINDOW, Notifications, Reason, Watching, desktop_command, display
from nock.project import Project
from nock.topics import Author, Topics
from nock.utils import now, parse_moment

from .test_topics import DECISION, judge, page, run, submit  # noqa: F401  (page is a fixture)

FILE = {"title": "The README", "files": ["README.md"]}


def told(project: Project) -> list[dict[str, Any]]:
    return project.store.rows("SELECT topic, reason, text, shown FROM notifications ORDER BY id")


def later(moment: str, seconds: float) -> str:
    start = parse_moment(moment)
    assert start is not None
    return (start + timedelta(seconds=seconds)).isoformat().replace("+00:00", "Z")


def test_a_topic_moving_to_review_tells_the_owner_once_with_what_waits(project: Project) -> None:
    submit(project.root)
    submit(project.root, {**DECISION, "title": "Orders keep their history"})
    submit(project.root, FILE)
    run(project.root, "topics", "update", "orders", '{"state": "active", "status": "building"}')
    assert told(project) == []
    run(project.root, "topics", "update", "orders", '{"state": "review", "status": "built"}')
    assert told(project) == [
        {
            "topic": "orders",
            "reason": "review",
            "text": "orders is ready for review: 2 decisions, 1 file",
            "shown": "nowhere",
        }
    ]
    # A burst: more items and a reply in the same few minutes add nothing.
    submit(project.root, {**DECISION, "title": "Orders are never deleted"})
    run(project.root, "topics", "update", "orders", '{"status": "built, one more"}')
    assert len(told(project)) == 1
    # Another topic is told of on its own.
    submit(project.root, FILE, topic="billing")
    run(project.root, "topics", "update", "billing", '{"state": "review"}')
    assert [row["topic"] for row in told(project)] == ["orders", "billing"]


def test_it_is_the_owners_turn_when_an_agent_answers_them_or_reworks_what_they_rejected(
    project: Project,
) -> None:
    topics = Topics(project)
    asked = submit(project.root, topic="asked")
    topics.update_item(asked, None, reply="Why SQLite?", author=Author.OWNER)
    run(project.root, "items", "update", asked, "--reply", "One file is enough at today's load.")
    rejected = submit(project.root, FILE, topic="rejected")
    judge(project.root, rejected, "rejected", "Bolder.")
    run(project.root, "items", "update", rejected, "--version", "{}")
    submit(project.root, topic="talked")
    topics.update_topic("talked", {}, reply="Where are we?", author=Author.OWNER)
    run(project.root, "topics", "update", "talked", "--reply", "Halfway.")
    assert [(row["topic"], row["reason"], row["text"]) for row in told(project)] == [
        ("asked", "answered", "asked is your turn again: an agent answered you; 1 decision open"),
        (
            "rejected",
            "reworked",
            "rejected is your turn again: a new version of an item you rejected; 1 file open",
        ),
        ("talked", "answered", "talked is your turn again: an agent answered you; 1 decision open"),
    ]


def test_nothing_is_told_of_the_owners_own_doing_or_an_agent_talking_on(project: Project) -> None:
    topics = Topics(project)
    ref = submit(project.root)
    run(project.root, "items", "update", ref, "--reply", "A note, unasked.")
    run(project.root, "items", "update", ref, "--version", "{}")
    topics.update_item(ref, None, reply="Fine.", author=Author.OWNER)
    judge(project.root, ref, "accepted")
    topics.update_topic("orders", {}, reply="Thanks.", author=Author.OWNER)
    assert told(project) == []


def test_a_burst_is_one_notification_per_topic_per_window(project: Project) -> None:
    notifications = Notifications(project)
    start = now()
    assert notifications.tell("orders", Reason.REVIEW, [], start) is not None
    assert notifications.tell("orders", Reason.ANSWERED, [], later(start, 60)) is None
    assert notifications.tell("orders", Reason.ANSWERED, [], later(start, WINDOW - 1)) is None
    assert notifications.tell("billing", Reason.REVIEW, [], later(start, 60)) is not None
    again = notifications.tell("orders", Reason.REWORKED, [], later(start, WINDOW + 1))
    assert again is not None and again["text"] == (
        "orders is your turn again: a new version of an item you rejected"
    )


def test_one_setting_turns_them_off(project: Project) -> None:
    config = project.local / "config.toml"
    config.write_text("notifications = false\n" + config.read_text())
    submit(project.root)
    run(project.root, "topics", "update", "orders", '{"state": "review"}')
    assert told(project) == []


def test_a_studio_page_watching_takes_them_and_its_poll_hands_them_over(
    project: Project,
    page: str,  # noqa: F811
) -> None:
    def poll(query: str) -> dict[str, Any]:
        with urllib.request.urlopen(f"{page}notifications?{query}") as response:
            return json.loads(response.read())

    notifications = Notifications(project)
    assert notifications.address("orders") == f"{page}#topics/orders"
    first = poll("seen=focused")
    assert first == {"latest": 0, "notifications": []}
    submit(project.root)
    run(project.root, "topics", "update", "orders", '{"state": "review"}')
    [shown] = poll("after=0&seen=notifying")["notifications"]
    assert shown["shown"] == "studio" and shown["address"] == "#topics/orders"
    assert shown["text"] == "orders is ready for review: 1 decision"
    assert poll(f"after={shown['id']}&seen=focused")["notifications"] == []
    # A page away without the browser's notifications, or silent too long, leaves it to the desktop.
    start = now()
    poll("seen=unwatched")
    away = notifications.tell("billing", Reason.REVIEW, [], start)
    notifications.watched(Watching.FOCUSED, start)
    silent = notifications.tell("other", Reason.REVIEW, [], later(start, WATCHED + 1))
    assert away is not None and silent is not None
    assert away["shown"] == silent["shown"] == "nowhere"


def test_with_no_studio_running_the_link_names_the_configured_port(project: Project) -> None:
    notifications = Notifications(project)
    assert notifications.address("orders") == "http://127.0.0.1:8765/#topics/orders"
    config = project.local / "config.toml"
    config.write_text(config.read_text() + "[studio]\nport = 9001\n")
    assert Notifications(Project.discover(project.root)).address("eval") == (
        "http://127.0.0.1:9001/#topics/eval"
    )


def test_no_display_shows_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    assert display() is False
    monkeypatch.setenv("CI", "true")
    assert display() is False


def stand_in(directory: Path, name: str) -> Path:
    path = directory / name
    path.write_text("#!/bin/sh\nexit 0\n")
    path.chmod(0o755)
    return path


def test_the_desktop_command_opens_the_topic_on_a_click_where_the_platform_can(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    address = "http://127.0.0.1:8765/#topics/eval"
    monkeypatch.setenv("PATH", str(tmp_path))
    plain = desktop_command("nock · demo", "eval is ready for review", address, "eval", "darwin")
    assert plain is not None and plain[0] == "osascript"
    assert plain[-2:] == ["nock · demo", f"eval is ready for review — {address}"]
    notifier = stand_in(tmp_path, "terminal-notifier")
    clicked = desktop_command("nock · demo", "eval is ready for review", address, "eval", "darwin")
    assert clicked == [
        str(notifier),
        *("-title", "nock · demo", "-message", "eval is ready for review", "-open", address),
        *("-group", "nock-eval"),
    ]
    assert desktop_command("nock", "text", address, "eval", "linux") is None
    sender = stand_in(tmp_path, "notify-send")
    assert desktop_command("nock", "text", address, "eval", "linux") == [
        str(sender),
        "--app-name=nock",
        "nock",
        f"text\n{address}",
    ]
    assert desktop_command("nock", "text", address, "eval", "win32") is None
    assert os.environ["PATH"] == str(tmp_path)
