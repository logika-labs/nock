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

from nock.consolidate import Consolidation
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


def decide(project: Project, draft: dict[str, object], answer: str, *flags: str) -> int:
    number = ask(project.root, draft)
    result = nock(project.root, "questions", "answer", str(number), answer, *flags)
    assert result.returncode == 0, result.stderr
    return number


def edited(project: Project, session: str, path: str) -> str | None:
    payload = {"session_id": session, "tool_name": "Edit", "tool_input": {"file_path": path}}
    output = HookRunner(project, payload).handle("PostToolUse")
    return output["hookSpecificOutput"]["additionalContext"] if output else None


def test_an_edit_to_a_governed_file_shows_its_standing_decisions_once(project: Project) -> None:
    first = decide(project, DRAFT, "SQLite.", "--touches", "README.md")
    told = edited(project, "s1", str(project.root / "README.md"))
    assert told is not None and f"[Q{first}] Which database: SQLite." in told
    assert edited(project, "s1", "README.md") is None
    assert edited(project, "s1", str(project.root / ".nock" / "config.toml")) is None

    second = decide(
        project, {"title": "Which database, again", "context": "Load grew."}, "Postgres.",
        "--touches", "README.md", "--supersedes", str(first),
    )  # fmt: skip
    assert Questions(project).get(first)["superseded_by"] == second
    told = edited(project, "s2", "README.md")
    assert told is not None and f"[Q{second}]" in told and f"[Q{first}]" not in told
    again = nock(project.root, "questions", "answer", str(second), "x", "--supersedes", str(first))
    assert again.returncode == 40 and "not a standing decision" in again.stderr


def test_the_map_check_holds_citations_and_touches_to_what_exists(project: Project) -> None:
    number = decide(project, DRAFT, "SQLite.", "--touches", "README.md")
    questions = Questions(project)
    questions.map.write_text(f"- If you touch the database, SQLite [Q{number}].\n")
    assert nock(project.root, "check", "nock-map").returncode == 0
    questions.map.write_text(f"- [Q{number}] and [Q42]\n")
    (project.root / "README.md").unlink()
    result = nock(project.root, "check", "nock-map")
    assert result.returncode == 1
    assert ".nock/questions/map.md:1: [Q42] is no question" in result.stdout
    assert "touches `README.md`, which matches no file" in result.stdout


def consolidate_after_one_decision(project: Project) -> None:
    local = project.root / ".nock" / "local" / "config.toml"
    local.write_text(local.read_text() + "[consolidate]\nquestions = 1\n")


def test_a_round_reads_the_new_decisions_and_the_check_holds_its_map(project: Project) -> None:
    consolidate_after_one_decision(project)
    assert nock(project.root, "consolidate", "due").returncode == 1
    first = decide(project, DRAFT, "SQLite.")
    assert (
        "consolidation is due (1 decisions since the last)"
        in nock(project.root, "consolidate", "due").stdout
    )
    start = HookRunner(project, {"session_id": "s1"}).handle("SessionStart")
    assert start is not None and "/consolidate" in start["systemMessage"]
    material = nock(project.root, "consolidate", "material").stdout
    assert f"## [Q{first}] Which database" in material and "There is no map yet." in material

    lesson = {
        "title": "Round per total?",
        "context": "Totals drifted.",
        "answer": "Yes (inferred).",
    }
    recorded = nock(project.root, "questions", "record", json.dumps(lesson))
    number = int(recorded.stdout.split()[-1])
    questions = Questions(project)
    assert questions.get(number)["lesson"] is True and questions.get(number)["state"] == "closed"

    questions.map.write_text(f"- If you touch the database, SQLite [Q{first}]; rounding [Q99].\n")
    refused = nock(project.root, "check", "nock-map")
    assert refused.returncode == 1 and "[Q99] is no question" in refused.stdout
    questions.map.write_text(
        f"- If you touch the database, SQLite [Q{first}]; rounding [Q{number}].\n"
    )
    assert nock(project.root, "check", "nock-map").returncode == 0
    recorded = nock(project.root, "consolidate", "record")
    assert recorded.returncode == 0, recorded.stderr
    assert json.loads(Consolidation(project).record.read_text())["covered"] == [first]
    assert nock(project.root, "consolidate", "due").returncode == 1


def test_the_edit_hook_is_wired_for_edits_only(project: Project) -> None:
    settings = json.loads((project.root / ".claude" / "settings.json").read_text())
    (entry,) = settings["hooks"]["PostToolUse"]
    assert entry["matcher"] == "Edit|MultiEdit|Write|NotebookEdit"


def test_a_consultation_waits_for_the_reframed_task(project: Project) -> None:
    consultation = {"intent": "Move orders to Postgres.", "context": "SQLite is slow."}
    result = nock(project.root, "consult", json.dumps(consultation))
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.startswith("**The task, reframed**")
    roles = [row["role"] for row in project.store.rows("SELECT role FROM sessions")]
    assert roles == ["consultant"]
