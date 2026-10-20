"""Questions: what an agent asks the owner while it works — one committed file
per question in the main checkout's `.nock/questions/` — answered on a page
(`nock questions page`) and handed back to the session that asked. Answered,
they are the project's record of its decisions."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import webbrowser
from enum import StrEnum
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import TYPE_CHECKING, Any, NotRequired, TypedDict

from nock.commands import schema_of
from nock.dispatch import Dispatcher
from nock.errors import Error, NotFoundError, UsageError
from nock.schema import validate
from nock.templates import Library
from nock.utils import now, read_json, write_json

if TYPE_CHECKING:
    from nock.project import Project

ROLE = "elaborator"
QUESTION_VARIABLE = "NOCK_QUESTION"
PACKAGE = Path(__file__).resolve().parent
BRIEFS = PACKAGE / "briefs"
# The git states in which a commit would land in the middle of someone's work.
BUSY_MARKERS = ("MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD", "rebase-merge", "rebase-apply")


class Priority(StrEnum):
    BLOCKING = "blocking"
    """Work waits on the answer now."""
    IMPORTANT = "important"
    """It changes what users, customers or other agents experience."""
    NORMAL = "normal"
    """Internal plumbing, tests, tooling."""


class State(StrEnum):
    OPEN = "open"
    """Waiting on the owner."""
    PENDING = "pending"
    """The owner chose, commented or asked for more; waiting on an agent."""
    CLOSED = "closed"
    """Decided: `answer` says what."""


class Draft(TypedDict):
    title: str
    """One line."""
    context: str
    """Markdown: what is open, what you already know, and why it matters."""
    options: NotRequired[list[str]]
    """The answers you see, numbered from 1 in this order."""
    recommended: NotRequired[int]
    """The number of the option you would take (default 1)."""
    priority: NotRequired[Priority]


class Owner(TypedDict):
    choice: int | None
    comment: str | None
    elaborate: bool


NO_INPUT: Owner = {"choice": None, "comment": None, "elaborate": False}


def said(question: dict[str, Any]) -> str:
    """The owner's input in a line: `chose 2 (Postgres); asked for more; said: …`."""
    owner = question["owner"]
    choice = owner["choice"]
    parts = [f"chose {choice} ({question['options'][choice - 1]})"] if choice else []
    parts += ["asked for more"] if owner["elaborate"] else []
    parts += [f"said: {owner['comment']}"] if owner["comment"] else []
    return "; ".join(parts)


def has_input(owner: Owner) -> bool:
    return bool(owner["choice"] or (owner["comment"] or "").strip() or owner["elaborate"])


class Questions:
    def __init__(self, project: Project) -> None:
        self.project = project

    @property
    def directory(self) -> Path:
        """The main checkout's, whichever worktree asks: the owner answers there."""
        return self.project.root / ".nock" / "questions"

    def path(self, number: int) -> Path:
        return self.directory / f"{number:04d}.json"

    def all(self) -> list[dict[str, Any]]:
        if not self.directory.is_dir():
            return []
        return [read_json(path) for path in sorted(self.directory.glob("[0-9]*.json"))]

    def get(self, number: int) -> dict[str, Any]:
        path = self.path(number)
        if not path.is_file():
            raise NotFoundError(f"no question {number} — `.nock/nock questions` lists them")
        return read_json(path)

    def save(self, question: dict[str, Any]) -> None:
        question["updated"] = now()
        write_json(self.path(question["number"]), question)

    # --- the agent's side -----------------------------------------------------

    def ask(self, draft: Draft) -> tuple[int, str | None]:
        """File the question under the next number and commit it; the number,
        and why it is not committed when it could not be."""
        with self.project.lock("questions"):
            numbers = [question["number"] for question in self.all()]
            number = max(numbers, default=0) + 1
            question: dict[str, Any] = {
                "number": number,
                "priority": str(draft.get("priority", Priority.NORMAL)),
                "state": str(State.OPEN),
                **self.drafted(draft),
                "owner": dict(NO_INPUT),
                "answer": None,
                "asked": {
                    "moment": now(),
                    "session": self.project.current_session(),
                    "role": self.project.current_role() or "interactive",
                },
            }
            self.save(question)
            return number, self.commit(number, f"Question {number}: {draft['title']}")

    def drafted(self, draft: Draft) -> dict[str, Any]:
        options = draft.get("options", [])
        recommended = draft.get("recommended", 1) if options else None
        if recommended is not None and not 1 <= recommended <= len(options):
            raise UsageError(f"`recommended` is {recommended}; the options are 1 to {len(options)}")
        return {
            "title": draft["title"],
            "context": draft["context"],
            "options": options,
            "recommended": recommended,
        }

    def rewrite(self, number: int, draft: Draft) -> str | None:
        """Say again what the owner found missing: the question is open again."""
        question = self.get(number)
        if question["state"] == State.CLOSED:
            raise UsageError(f"question {number} is closed")
        question.update(self.drafted(draft), state=str(State.OPEN), owner=dict(NO_INPUT))
        if "priority" in draft:
            question["priority"] = str(draft["priority"])
        self.save(question)
        return self.commit(number, f"Question {number}, elaborated: {question['title']}")

    def answer(self, number: int, answer: str) -> str | None:
        """Record the decision, the owner's input folded in, and close it."""
        if not answer.strip():
            raise UsageError("the answer is empty")
        question = self.get(number)
        question.update(state=str(State.CLOSED), answer=answer.strip(), owner=dict(NO_INPUT))
        self.save(question)
        return self.commit(number, f"Question {number}, answered: {question['title']}")

    def commit(self, number: int, message: str) -> str | None:
        """Commit the one file in the main checkout — unless that would land in
        the middle of a merge or rebase there; then say so, and leave it."""
        git = self.project.git
        git_directory = Path(git("rev-parse", "--absolute-git-dir"))
        busy = next((marker for marker in BUSY_MARKERS if (git_directory / marker).exists()), None)
        relative = str(self.path(number).relative_to(self.project.root))
        if busy is not None:
            return (
                f"not committed: the main checkout is mid-operation ({busy}); {relative} is written"
            )
        git("add", "--", relative)
        git("commit", "--quiet", "--no-verify", "--only", "-m", message, "--", relative)
        return None

    # --- the owner's side -----------------------------------------------------

    def respond(self, number: int, owner: Owner) -> dict[str, Any]:
        """The owner's choice, comment or request for more — written, never
        committed: the agent that acts on it commits the outcome."""
        question = self.get(number)
        if question["state"] == State.CLOSED:
            raise UsageError(f"question {number} is closed")
        choice = owner["choice"]
        if choice is not None and not 1 <= choice <= len(question["options"]):
            raise UsageError(f"no option {choice} in question {number}")
        question["owner"] = owner
        question["state"] = str(State.PENDING if has_input(owner) else State.OPEN)
        self.save(question)
        return question

    def pending(self) -> list[dict[str, Any]]:
        return [question for question in self.all() if question["state"] == State.PENDING]

    def news_for(self, session: str) -> list[dict[str, Any]]:
        """The owner's input on this session's questions that it has not been
        told yet; telling it is recorded."""
        news = [
            question
            for question in self.pending()
            if question["asked"].get("session") == session and not question["owner"]["elaborate"]
        ]
        told = {
            (row["question"], row["updated"])
            for row in self.project.store.rows(
                "SELECT question, updated FROM told WHERE session = ?", (session,)
            )
        }
        news = [
            question for question in news if (question["number"], question["updated"]) not in told
        ]
        for question in news:
            self.project.store.insert(
                "told",
                {
                    "session": session,
                    "question": question["number"],
                    "updated": question["updated"],
                },
            )
        return news

    # --- elaborating ------------------------------------------------------------

    def elaborate(self, number: int) -> dict[str, Any]:
        """A headless agent says more about the question, as the owner asked;
        the question is open again when it has."""
        question = self.get(number)
        brief = Library(self.project.code_path("briefs"), BRIEFS).render(
            "elaborate.md", question=question, rendered=json.dumps(question, indent=2)
        )
        session = Dispatcher(self.project).launch(
            ROLE, brief, self.project.root, {QUESTION_VARIABLE: str(number)}
        )
        question = self.get(number)
        if question["state"] == State.PENDING and question["owner"]["elaborate"]:
            question["owner"]["elaborate"] = False
            question["state"] = str(State.PENDING if has_input(question["owner"]) else State.OPEN)
            self.save(question)
            return {
                "elaborated": False,
                "session": session.id,
                "problem": f"the session ended (exit {session.exit_code}) without rewriting the question: {(session.result or '')[:400]}",
            }
        return {"elaborated": True, "session": session.id}

    def elaborate_in_background(self, number: int) -> None:
        subprocess.Popen(
            [sys.executable, "-m", "nock", "questions", "elaborate", str(number)],
            cwd=self.project.root,
            env={**os.environ, "PYTHONPATH": str(PACKAGE.parent)},
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )


class Server(ThreadingHTTPServer):
    """The owner's page: every question, answered in place. Local, and only
    while `nock questions page` runs."""

    def __init__(self, questions: Questions, port: int) -> None:
        super().__init__(("127.0.0.1", port), Handler)
        self.questions = questions

    @property
    def address(self) -> str:
        return f"http://127.0.0.1:{self.server_address[1]}/"

    def run(self, open_browser: bool) -> None:
        print(f"questions: {self.address} (Ctrl-C to stop)", flush=True)
        if open_browser:
            webbrowser.open(self.address)
        try:
            self.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            self.server_close()


class Handler(BaseHTTPRequestHandler):
    """`GET /` the page, `GET /questions` every question, `POST /questions/N`
    the owner's input on one."""

    @property
    def questions(self) -> Questions:
        assert isinstance(self.server, Server)
        return self.server.questions

    def do_GET(self) -> None:
        if self.path == "/":
            self.send(HTTPStatus.OK, (PACKAGE / "questions.html").read_bytes(), "text/html")
        elif self.path == "/questions":
            self.send_json(HTTPStatus.OK, {"questions": self.questions.all()})
        else:
            self.send_json(HTTPStatus.NOT_FOUND, {"error": "no such page"})

    def do_POST(self) -> None:
        number = self.path.removeprefix("/questions/")
        if not number.isdigit():
            self.send_json(HTTPStatus.NOT_FOUND, {"error": "no such question"})
            return
        questions = self.questions
        try:
            owner = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
            validate(owner, schema_of(Owner))
            question = questions.respond(int(number), owner)
        except json.JSONDecodeError as error:
            self.send_json(HTTPStatus.BAD_REQUEST, {"error": str(error)})
            return
        except Error as error:
            status = (
                HTTPStatus.NOT_FOUND if isinstance(error, NotFoundError) else HTTPStatus.BAD_REQUEST
            )
            self.send_json(status, {"error": str(error)})
            return
        if owner["elaborate"]:
            questions.elaborate_in_background(int(number))
        self.send_json(HTTPStatus.OK, question)

    def send_json(self, status: HTTPStatus, value: Any) -> None:
        self.send(status, json.dumps(value).encode(), "application/json")

    def send(self, status: HTTPStatus, body: bytes, kind: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", f"{kind}; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *arguments: Any) -> None:
        pass
