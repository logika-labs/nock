"""Questions: asked and committed on the main checkout, answered by the owner on
the page, handed back to the session that asked, elaborated by a dispatched
agent, and closed."""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from collections.abc import Iterator
from pathlib import Path

import pytest

from nock.hooks import HookRunner
from nock.project import Project
from nock.questions import Questions, Server

from .conftest import git, nock

DRAFT = {
    "title": "Which database",
    "context": "We need to store **orders**.",
    "options": ["SQLite", "Postgres"],
    "recommended": 2,
    "priority": "blocking",
}


def ask(directory: Path, draft: dict[str, object] = DRAFT) -> int:
    result = nock(directory, "ask", json.dumps(draft))
    assert result.returncode == 0, result.stderr
    return int(result.stdout.split()[-1])


@pytest.fixture
def page(project: Project) -> Iterator[str]:
    server = Server(Questions(project), 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server.address
    server.shutdown()
    server.server_close()


def post(address: str, number: int, owner: dict[str, object]) -> tuple[int, dict[str, object]]:
    request = urllib.request.Request(
        f"{address}questions/{number}",
        data=json.dumps(owner).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read())


def test_a_question_asked_in_a_worktree_is_committed_on_the_main_checkout(
    project: Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    worktree = project.root.with_name("feature")
    git(project.root, "worktree", "add", "-q", "-b", "feature", str(worktree))
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "s1")
    number = ask(worktree)
    assert number == 1
    assert not (worktree / ".nock" / "questions").exists()
    assert git(project.root, "log", "-1", "--format=%s") == "Question 1: Which database"
    assert git(project.root, "status", "--porcelain") == ""
    question = Questions(project).get(1)
    assert question["state"] == "open" and question["recommended"] == 2
    assert question["asked"]["session"] == "s1"
    listed = nock(project.root, "questions", "list", "--json")
    assert [row["number"] for row in json.loads(listed.stdout)] == [1]
    assert ask(project.root, {"title": "Second", "context": "x"}) == 2


def test_a_recommendation_must_name_an_option(project: Project) -> None:
    result = nock(project.root, "ask", json.dumps({**DRAFT, "recommended": 3}))
    assert result.returncode == 40 and "the options are 1 to 2" in result.stderr


def test_a_question_mid_merge_is_written_but_not_committed(project: Project) -> None:
    (Path(git(project.root, "rev-parse", "--absolute-git-dir")) / "MERGE_HEAD").write_text("x\n")
    result = nock(project.root, "ask", json.dumps(DRAFT))
    assert result.returncode == 0 and "not committed" in result.stdout
    assert Questions(project).path(1).is_file()


def test_the_owner_answers_on_the_page_and_the_asking_session_hears_once(
    project: Project, page: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "s1")
    number = ask(project.root)
    with urllib.request.urlopen(page) as response:
        assert b"<h1>Questions</h1>" in response.read()
    with urllib.request.urlopen(f"{page}questions") as response:
        assert json.loads(response.read())["questions"][0]["title"] == "Which database"
    status, error = post(page, number, {"choice": 9, "comment": None, "elaborate": False})
    assert status == 400 and "no option 9" in str(error["error"])
    status, question = post(page, number, {"choice": 1, "comment": "cheap", "elaborate": False})
    assert status == 200 and question["state"] == "pending"

    prompt = HookRunner(project, {"session_id": "s1"}).handle("UserPromptSubmit")
    assert prompt is not None
    told = prompt["hookSpecificOutput"]["additionalContext"]
    assert "question 1 (Which database): chose 1 (SQLite); said: cheap" in told
    assert HookRunner(project, {"session_id": "s1"}).handle("UserPromptSubmit") is None
    assert HookRunner(project, {"session_id": "s2"}).handle("UserPromptSubmit") is None
    start = HookRunner(project, {"session_id": "s3"}).handle("SessionStart")
    assert start is not None
    assert (
        "answered question(s) 1 (Which database)"
        in start["hookSpecificOutput"]["additionalContext"]
    )

    result = nock(project.root, "questions", "answer", "1", "SQLite: it is cheap, and enough.")
    assert result.returncode == 0, result.stderr
    question = Questions(project).get(1)
    assert question["state"] == "closed" and question["owner"]["choice"] is None
    assert git(project.root, "log", "-1", "--format=%s") == "Question 1, answered: Which database"
    assert nock(project.root, "questions", "list", "--json").stdout.strip() == "[]"
    status, error = post(page, number, {"choice": 1, "comment": None, "elaborate": False})
    assert status == 400 and "closed" in str(error["error"])


def test_an_elaborating_agent_rewrites_the_question_and_opens_it_again(project: Project) -> None:
    number = ask(project.root)
    questions = Questions(project)
    questions.respond(number, {"choice": None, "comment": "what load?", "elaborate": True})
    result = nock(project.root, "questions", "elaborate", str(number))
    assert result.returncode == 0, result.stdout + result.stderr
    question = questions.get(number)
    assert question["state"] == "open" and question["owner"]["comment"] is None
    assert question["title"] == "Which database, now that we know the load"
    assert question["recommended"] == 1 and question["priority"] == "blocking"
    assert git(project.root, "log", "-1", "--format=%s").startswith("Question 1, elaborated")


def test_an_elaboration_that_rewrites_nothing_leaves_the_comment_for_an_agent(
    project: Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    number = ask(project.root)
    questions = Questions(project)
    questions.respond(number, {"choice": None, "comment": "what load?", "elaborate": True})
    monkeypatch.setenv("FAKE_ELABORATE", "silent")
    result = nock(project.root, "questions", "elaborate", str(number))
    assert result.returncode == 1 and "was not elaborated" in result.stdout + result.stderr
    question = questions.get(number)
    assert question["state"] == "pending" and question["owner"]["elaborate"] is False
    assert question["owner"]["comment"] == "what load?"
