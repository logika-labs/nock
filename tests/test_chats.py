"""The studio's chat: the owner talks with a headless agent that streams its
answer as it writes and continues its session turn by turn (a new one,
briefed with the transcript, when the session is gone); a new chat names the
one left; Tidy up reorganizes the topics in one commit that Undo reverts.
The agent is the scripted stand-in; nothing calls a model."""

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest

from nock.dispatch import SEATS, Dispatcher
from nock.project import Project
from nock.sessions import find_transcript
from nock.studio import Studio
from nock.topics import Topics

from .conftest import git
from .test_topics import run, submit

DEADLINE = 60


@pytest.fixture
def page(project: Project) -> Iterator[str]:
    server = Studio(project, 0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield server.address
    server.shutdown()
    server.server_close()


def get(address: str, route: str) -> Any:
    with urllib.request.urlopen(f"{address}chat{route}") as response:
        return json.loads(response.read())


def post(address: str, route: str, body: dict[str, Any]) -> tuple[int, Any]:
    request = urllib.request.Request(
        f"{address}chat/{route}", data=json.dumps(body).encode(), method="POST"
    )
    try:
        with urllib.request.urlopen(request) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read())


def until(check: Callable[[], Any]) -> Any:
    deadline = time.monotonic() + DEADLINE
    while True:
        found = check()
        if found:
            return found
        assert time.monotonic() < deadline, "waited too long"
        time.sleep(0.05)


def answered(address: str, chat: str) -> dict[str, Any]:
    return until(
        lambda: (lambda shown: None if shown["running"] else shown)(get(address, f"/{chat}"))
    )


def asked(log: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in log.read_text().splitlines()] if log.is_file() else []


def test_the_answer_streams_as_it_is_written_and_the_chat_continues_its_session(
    project: Project, page: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    gate, log = tmp_path / "gate", tmp_path / "asked.jsonl"
    monkeypatch.setenv("FAKE_CHAT_GATE", str(gate))
    monkeypatch.setenv("FAKE_LOG", str(log))
    monkeypatch.setenv("FAKE_CHAT", "Orders live in one SQLite file beside the app")
    status, started = post(page, "send", {"text": "Where do orders live?"})
    assert status == 200 and started["running"] and started["kind"] == "chat"
    chat = started["id"]
    # Half the words are out, the rest held back: the page sees them already.
    live = until(lambda: get(page, f"/{chat}")["live"]["text"] or None)
    assert live == "Orders live in one"
    shown = get(page, f"/{chat}")
    assert shown["running"] and shown["live"]["activity"] == ["Bash: .nock/nock topics list"]
    status, refused = post(page, "send", {"id": chat, "text": "And refunds?"})
    assert status == 400 and "still answering" in refused["error"]
    gate.touch()
    shown = answered(page, chat)
    owner, agent = shown["messages"]
    assert owner == {**owner, "author": "owner", "text": "Where do orders live?"}
    assert agent["text"] == "Orders live in one SQLite file beside the app"
    assert agent["activity"] == ["Bash: .nock/nock topics list"] and "problem" not in agent
    first = asked(log)[0]
    assert first["role"] == "chatter" and not first["resumed"]
    assert (
        "Where do orders live?" in first["prompt"] and "`.nock/nock topics list" in first["prompt"]
    )
    # The chat's next message continues the same Claude Code session.
    monkeypatch.delenv("FAKE_CHAT")
    post(page, "send", {"id": chat, "text": "And refunds?"})
    shown = answered(page, chat)
    assert [entry["text"] for entry in shown["messages"]][-1] == "You said: And refunds?"
    second = asked(log)[-1]
    assert second["resumed"] and second["session"] == first["session"] == shown["session"]
    assert second["prompt"] == "And refunds?"
    # Kept on this machine, never committed.
    assert (project.root / ".nock" / "local" / "chats" / f"{chat}.json").is_file()
    assert git(project.root, "status", "--porcelain") == ""


def test_a_chat_whose_session_is_gone_continues_in_a_new_one_told_what_was_said(
    project: Project, page: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    log = tmp_path / "asked.jsonl"
    monkeypatch.setenv("FAKE_LOG", str(log))
    chat = post(page, "send", {"text": "Where do orders live?"})[1]["id"]
    before = answered(page, chat)["session"]
    transcript = find_transcript(project.root, before)
    assert transcript is not None
    transcript.unlink()
    post(page, "send", {"id": chat, "text": "And refunds?"})
    shown = answered(page, chat)
    again = asked(log)[-1]
    assert not again["resumed"] and again["session"] == shown["session"] != before
    assert "# The conversation so far" in again["prompt"]
    assert "**Owner:** Where do orders live?" in again["prompt"]
    assert "**Agent:** You said: Where do orders live?" in again["prompt"]
    assert [entry["text"] for entry in shown["messages"]] == [
        "Where do orders live?",
        "You said: Where do orders live?",
        "And refunds?",
        "You said: And refunds?",
    ]


def test_a_failed_resume_falls_back_to_a_new_session_once(
    project: Project, page: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    log = tmp_path / "asked.jsonl"
    monkeypatch.setenv("FAKE_LOG", str(log))
    chat = post(page, "send", {"text": "Where do orders live?"})[1]["id"]
    before = answered(page, chat)["session"]
    # A transcript is found beside the project (a worktree's), but Claude Code,
    # in the project, no longer resumes the session.
    transcript = find_transcript(project.root, before)
    assert transcript is not None
    elsewhere = transcript.parent.with_name(transcript.parent.name + "-elsewhere")
    elsewhere.mkdir()
    transcript.rename(elsewhere / transcript.name)
    assert find_transcript(project.root, before) is not None
    post(page, "send", {"id": chat, "text": "And refunds?"})
    shown = answered(page, chat)
    tries = asked(log)[1:]
    assert [entry["resumed"] for entry in tries] == [True, False]
    assert shown["messages"][-1]["text"] == "You said: And refunds?"
    assert "problem" not in shown["messages"][-1]


def test_an_answer_is_stopped_and_keeps_what_was_written(
    page: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FAKE_CHAT_GATE", str(tmp_path / "never"))
    monkeypatch.setenv("FAKE_CHAT", "one two three four")
    chat = post(page, "send", {"text": "Anything?"})[1]["id"]
    until(lambda: get(page, f"/{chat}")["live"]["text"] == "one two")
    post(page, "stop", {"id": chat})
    reply = answered(page, chat)["messages"][-1]
    assert reply["problem"] == "stopped" and reply["text"] == "one two"


def test_a_new_chat_names_the_one_left_and_every_chat_is_listed(
    page: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = post(page, "send", {"text": "Where do orders live?"})[1]["id"]
    answered(page, first)
    # Until it is named, a chat is listed by its first words.
    assert get(page, "")["chats"][0]["title"] == "Where do orders live?"
    status, leaving = post(page, "leave", {"id": first})
    assert status == 200
    row = until(
        lambda: next(
            (row for row in get(page, "")["chats"] if row["id"] == first and not row["naming"]),
            None,
        )
    )
    assert row["title"] == "Where orders live" and row["summary"] == "The owner asked; SQLite."
    second = post(page, "send", {"text": "What about refunds?"})[1]["id"]
    answered(page, second)
    assert [row["id"] for row in get(page, "")["chats"]] == [second, first]
    # Named once: leaving it again with nothing new said names nothing.
    assert post(page, "leave", {"id": first})[1] == {"naming": False}
    # Any chat continues.
    post(page, "send", {"id": first, "text": "And now?"})
    assert answered(page, first)["messages"][-1]["text"] == "You said: And now?"
    assert leaving == {"naming": True}


def test_tidy_up_lands_as_one_commit_only_drops_and_undo_reverts_it(
    project: Project, page: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    kept = submit(project.root)
    stale = submit(project.root, {"title": "Orders live in a CSV", "decision": {"answer": "No."}})
    misplaced = submit(
        project.root,
        {"title": "Refunds are capped", "decision": {"answer": "At the charge."}},
    )
    submit(project.root, {"title": "Billing is monthly", "decision": {"answer": "Yes."}}, "billing")
    head = git(project.root, "rev-parse", "HEAD")
    monkeypatch.setenv(
        "FAKE_TIDY",
        json.dumps(
            [
                ["items", "update", misplaced, json.dumps({"topic": "billing"})],
                ["items", "judge", kept, json.dumps({"verdict": "accepted"})],
                ["items", "judge", kept, json.dumps({"verdict": "rejected"})],
                [
                    "items",
                    "judge",
                    stale,
                    json.dumps(
                        {"verdict": "rejected", "rework": False, "comment": "Dropped: superseded."}
                    ),
                ],
                ["topics", "update", "billing", json.dumps({"priority": 1, "status": "first"})],
                ["topics", "update", "orders", json.dumps({"priority": 2, "status": "next"})],
            ]
        ),
    )
    monkeypatch.setenv("FAKE_TIDY_SUMMARY", "Moved refunds to billing\n\n- billing first")
    status, started = post(page, "tidy", {})
    assert status == 200 and started["kind"] == "tidy" and started["title"] == "Tidy up"
    assert post(page, "tidy", {})[0] == 400
    shown = answered(page, started["id"])
    owner, agent = shown["messages"]
    assert owner["author"] == "owner" and "Tidy up Work" in owner["text"]
    # What it said along the way is shown; its last message is the summary.
    assert (
        agent["text"] == "Reading the topics first.\n\nMoved refunds to billing\n\n- billing first"
    )
    assert shown["summary"] == "Moved refunds to billing - billing first"
    # One commit for everything it did, and nothing left uncommitted.
    commits = git(project.root, "log", "--format=%H %s", f"{head}..HEAD").splitlines()
    assert len(commits) == 1 and commits[0].endswith(" Work tidied up: Moved refunds to billing")
    assert shown["tidy"]["commit"] == commits[0].split()[0]
    assert git(project.root, "status", "--porcelain") == ""
    topics = Topics(project)
    assert topics.item(misplaced)["topic"] == "billing"
    assert topics.item(kept)["verdict"] == "open"
    rejected = topics.item(stale)
    assert rejected["verdict"] == "dropped"
    assert rejected["thread"][-1]["text"] == "Dropped: superseded."
    assert rejected["decided"]["role"] == "tidier"
    # The Work list follows the order it gave.
    with urllib.request.urlopen(f"{page}topics") as response:
        listed = json.loads(response.read())["topics"]
    assert [topic["name"] for topic in listed] == ["billing", "orders"]
    assert listed[0]["priority"] == 1 and listed[0]["status"] == "first"
    assert [row["name"] for row in run(project.root, "topics", "list", "--full")["rows"]] == [
        "billing",
        "orders",
    ]
    # Undo reverts that commit.
    status, undone = post(page, "undo", {"id": started["id"]})
    assert status == 200 and undone["tidy"]["reverted"]
    assert git(project.root, "log", "-1", "--format=%s").startswith('Revert "Work tidied up')
    topics = Topics(project)
    assert topics.item(misplaced)["topic"] == "orders"
    assert topics.item(stale)["verdict"] == "open"
    assert "priority" not in topics.topic("billing")
    assert git(project.root, "status", "--porcelain") == ""
    status, again = post(page, "undo", {"id": started["id"]})
    assert status == 400 and "undone already" in again["error"]
    status, refused = post(page, "send", {"id": started["id"], "text": "more"})
    assert status == 400 and "takes no messages" in refused["error"]


def test_a_tidy_up_that_changes_nothing_commits_nothing(
    project: Project, page: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    submit(project.root)
    head = git(project.root, "rev-parse", "HEAD")
    shown = answered(page, post(page, "tidy", {})[1]["id"])
    assert shown["tidy"] == {"commit": None}
    assert git(project.root, "rev-parse", "HEAD") == head
    assert post(page, "undo", {"id": shown["id"]})[0] == 400


def test_the_chat_reads_as_the_ask_does_and_tidy_up_writes_only_through_nock(
    project: Project,
) -> None:
    dispatcher = Dispatcher(project)
    chatter = dispatcher.command("chatter")
    allowed = set(SEATS["chatter"].allowed)
    assert allowed - set(SEATS["asker"].allowed) == {"Bash(.nock/nock docs:*)"}
    assert chatter[chatter.index("--permission-mode") + 1] == "dontAsk"
    assert "Write" not in SEATS["chatter"].tools and "Edit" not in SEATS["tidier"].tools
    assert all(
        rule.startswith(("Bash(.nock/nock ", "Bash(git ")) for rule in SEATS["tidier"].allowed
    )
    namer = dispatcher.command("namer")
    assert namer[namer.index("--tools") + 1] == "" and "--allowedTools" not in namer


def test_a_topic_s_priority_orders_the_list_and_zero_takes_it_away(project: Project) -> None:
    submit(project.root)
    submit(project.root, {"title": "Billing is monthly", "decision": {"answer": "Yes."}}, "billing")
    names = lambda: [row["name"] for row in run(project.root, "topics", "list", "--full")["rows"]]  # noqa: E731
    newest = names()
    assert newest == ["billing", "orders"]
    run(project.root, "topics", "update", "orders", json.dumps({"priority": 1}))
    assert names() == ["orders", "billing"]
    assert run(project.root, "topics", "show", "orders")["priority"] == 1
    run(project.root, "topics", "update", "orders", json.dumps({"priority": 0}))
    assert "priority" not in run(project.root, "topics", "show", "orders")


def test_the_recorder_s_server_is_set_in_the_settings_on_this_machine_only(
    project: Project, page: str
) -> None:
    def settings(body: dict[str, Any]) -> tuple[int, Any]:
        request = urllib.request.Request(
            f"{page}settings", data=json.dumps(body).encode(), method="POST"
        )
        try:
            with urllib.request.urlopen(request) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as error:
            return error.code, json.loads(error.read())

    local = project.root / ".nock" / "local" / "config.toml"
    before = local.read_text()
    chosen = {
        "transcribe_url": "http://127.0.0.1:8000/v1",
        "transcribe_model": "Systran/faster-whisper-small",
        "transcribe_key_variable": "WHISPER_KEY",
    }
    assert settings(chosen) == (200, chosen)
    written = local.read_text()
    assert (
        written.startswith(before)
        and '[studio]\ntranscribe_url = "http://127.0.0.1:8000/v1"' in written
    )
    # Changed again, each key's line is replaced in place.
    assert settings({**chosen, "transcribe_model": "whisper-1"})[0] == 200
    assert local.read_text().count("transcribe_model") == 1
    assert 'transcribe_model = "whisper-1"' in local.read_text()
    status, refused = settings({**chosen, "transcribe_key_variable": "sk-abc 123"})
    assert status == 400 and "never the key itself" in refused["error"]
    with urllib.request.urlopen(page) as response:
        shown = response.read().decode()
    assert 'value="http://127.0.0.1:8000/v1"' in shown and 'value="WHISPER_KEY"' in shown
    assert git(project.root, "status", "--porcelain") == ""
