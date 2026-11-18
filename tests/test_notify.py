"""Review notifications: the owner is told when a task is their turn again
(its review is ready, an agent answered them, or proposed something), once
per task per few minutes, in the studio's page while one is watching and on
the desktop otherwise; never for what the owner did, never without a display.
No test shows a real notification: the suite has no display (`CI`), and the
desktop's command is only built, against stand-in programs on PATH."""

from __future__ import annotations

import json
import os
import urllib.request
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest

from nock.notify import (
    ICON,
    WATCHED,
    WINDOW,
    Notifications,
    Reason,
    Watching,
    desktop_command,
    display,
)
from nock.project import Project
from nock.utils import now, parse_moment

from .store import compose, open_topic, propose, reply, state, submit, topics_in


def told(project: Project) -> list[dict[str, Any]]:
    return project.store.rows("SELECT topic, reason, text, shown FROM notifications ORDER BY id")


def later(moment: str, seconds: float) -> str:
    start = parse_moment(moment)
    assert start is not None
    return (start + timedelta(seconds=seconds)).isoformat().replace("+00:00", "Z")


def test_a_review_ready_tells_the_owner_once_with_what_waits(project: Project) -> None:
    root = project.root
    submit(root)
    state(root, "orders", state="active", status="building")
    assert told(project) == []
    compose(root, "orders", [{"kind": "item", "item": "sqlite"}])
    state(root, "orders", state="review", status="built")
    assert told(project) == [
        {
            "topic": "orders",
            "reason": "review",
            "text": "orders: the review is ready",
            "shown": "nowhere",
        }
    ]
    # A burst: a proposal and a status in the same few minutes add nothing.
    propose(root)
    state(root, "orders", status="built, one more")
    assert len(told(project)) == 1
    # Another task is told of on its own.
    open_topic(root, "billing")
    compose(root, "billing", [{"kind": "text", "text": "Done."}])
    assert [row["topic"] for row in told(project)] == ["orders", "billing"]


def test_it_is_the_owners_turn_when_an_agent_answers_them_or_proposes(project: Project) -> None:
    root = project.root
    open_topic(root, "asked")
    topics_in(root).send("asked", "Why SQLite?", now=False)
    reply(root, "asked", "One file is enough at today's load.")
    propose(root, topic="proposed")
    assert [(row["topic"], row["reason"], row["text"]) for row in told(project)] == [
        ("asked", "answered", "asked: an agent answered you"),
        ("proposed", "proposed", "proposed: a new proposal"),
    ]


def test_nothing_is_told_of_the_owners_own_doing_or_an_agent_talking_on(project: Project) -> None:
    root = project.root
    ref = propose(root)
    before = len(told(project))
    reply(root, "orders", "A note, unasked.")
    topics = topics_in(root)
    topics.judge(ref, "accepted")
    topics.note("orders", {"item": "archive"}, "Fine.")
    topics.send("orders", "Thanks.", now=False)
    assert len(told(project)) == before


def test_a_burst_is_one_notification_per_topic_per_window(project: Project) -> None:
    notifications = Notifications(project)
    start = now()
    assert notifications.tell("orders", Reason.REVIEW, {}, start) is not None
    assert notifications.tell("orders", Reason.ANSWERED, {}, later(start, 60)) is None
    assert notifications.tell("orders", Reason.ANSWERED, {}, later(start, WINDOW - 1)) is None
    assert notifications.tell("billing", Reason.REVIEW, {}, later(start, 60)) is not None
    again = notifications.tell("orders", Reason.PROPOSED, {"open": 2}, later(start, WINDOW + 1))
    assert again is not None and again["text"] == "orders: a new proposal (2 proposals to decide)"


def test_one_setting_turns_them_off(project: Project) -> None:
    config = project.local / "config.toml"
    config.write_text("notifications = false\n" + config.read_text())
    submit(project.root)
    compose(project.root, "orders", [{"kind": "item", "item": "sqlite"}])
    assert told(project) == []


def test_a_studio_page_watching_takes_them_and_its_poll_hands_them_over(
    project: Project, page: str
) -> None:
    def poll(query: str) -> dict[str, Any]:
        with urllib.request.urlopen(f"{page}notifications?{query}") as response:
            return json.loads(response.read())

    notifications = Notifications(project)
    assert notifications.address("orders") == f"{page}#/t/orders"
    first = poll("seen=focused")
    assert first == {"latest": 0, "notifications": []}
    submit(project.root)
    compose(project.root, "orders", [{"kind": "item", "item": "sqlite"}])
    [shown] = poll("after=0&seen=notifying")["notifications"]
    assert shown["shown"] == "studio" and shown["address"] == "#/t/orders"
    assert shown["text"] == "orders: the review is ready"
    assert poll(f"after={shown['id']}&seen=focused")["notifications"] == []
    # A page away without the browser's notifications, or silent too long, leaves it to the desktop.
    start = now()
    poll("seen=unwatched")
    away = notifications.tell("billing", Reason.REVIEW, {}, start)
    notifications.watched(Watching.FOCUSED, start)
    silent = notifications.tell("other", Reason.REVIEW, {}, later(start, WATCHED + 1))
    assert away is not None and silent is not None
    assert away["shown"] == silent["shown"] == "nowhere"


def test_with_no_studio_running_the_link_names_the_configured_port(project: Project) -> None:
    notifications = Notifications(project)
    assert notifications.address("orders") == "http://127.0.0.1:8765/#/t/orders"
    config = project.local / "config.toml"
    config.write_text(config.read_text() + "[studio]\nport = 9001\n")
    assert Notifications(Project.discover(project.root)).address("eval") == (
        "http://127.0.0.1:9001/#/t/eval"
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
    address = "http://127.0.0.1:8765/#/t/eval"
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
        *("-appIcon", str(ICON), "-contentImage", str(ICON)),
    ]
    assert desktop_command("nock", "text", address, "eval", "linux") is None
    sender = stand_in(tmp_path, "notify-send")
    assert desktop_command("nock", "text", address, "eval", "linux") == [
        str(sender),
        "--app-name=nock",
        f"--icon={ICON}",
        "nock",
        f"text\n{address}",
    ]
    assert desktop_command("nock", "text", address, "eval", "win32") is None
    assert os.environ["PATH"] == str(tmp_path)
