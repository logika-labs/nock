"""Asking about the topics: the owner's question, from the studio's Ask, goes
to a fresh headless agent that reads the topics, their items and threads (and
the code, if it must) and answers through `nock topics answer` — markdown,
and the items it relied on, held to naming only items that exist."""

from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any, NotRequired, TypedDict

from nock.dispatch import Dispatcher
from nock.errors import Failed, NotFoundError, PolicyError, UsageError
from nock.templates import Library
from nock.topics import Topics
from nock.utils import read_json, write_json

if TYPE_CHECKING:
    from nock.project import Project

ROLE = "asker"
BRIEFS = Path(__file__).resolve().parent / "briefs"
# Set in the asked agent's environment: where its `nock topics answer` writes.
SUBMISSION_VARIABLE = "NOCK_ANSWER"
# The longest an answer may take, in seconds.
DEADLINE = 600


class Answer(TypedDict):
    answer: str
    """The answer, in markdown, as the owner should read it: short and specific."""
    items: NotRequired[list[str]]
    """The items it rests on, as `topic/slug`; the owner is shown each as a card."""


class Asker:
    def __init__(self, project: Project) -> None:
        self.project = project

    def ask(self, question: str) -> dict[str, Any]:
        if not question.strip():
            raise UsageError("the question is empty")
        topics = Topics(self.project)
        listing = "\n".join(
            f"- `{row['name']}` ({row['open']} open, {row['accepted']} accepted,"
            f" {row['rejected']} rejected): {row['description']}"
            for row in (topics.row(name) for name in topics.names())
        )
        brief = Library(self.project.code_path("briefs"), BRIEFS).render(
            "ask.md", question=question.strip(), topics=listing
        )
        submission = self.project.local / "answers" / f"{uuid.uuid4()}.json"
        session = Dispatcher(self.project).launch(
            ROLE,
            brief,
            self.project.here,
            variables={SUBMISSION_VARIABLE: str(submission)},
            deadline=DEADLINE,
        )
        if submission.is_file():
            answered = read_json(submission)
        elif session.exit_code == 0 and session.result:
            answered = {"answer": session.result.strip(), "items": []}
        else:
            raise Failed(
                f"the agent gave no answer (exit {session.exit_code}; log: {session.log})",
                [f"refused: {line}" for line in session.denied],
            )
        return {
            "answer": answered["answer"],
            "items": answered.get("items") or [],
            "session": session.id,
        }

    def submit(self, answer: Answer) -> str:
        target = os.environ.get(SUBMISSION_VARIABLE)
        if self.project.current_role() != ROLE or not target:
            raise PolicyError("only an agent the studio's Ask dispatched submits an answer")
        if not answer["answer"].strip():
            raise UsageError("`answer` is empty: say what you found, or that the topics do not say")
        topics = Topics(self.project)
        refs, problems = [], []
        for ref in answer.get("items") or []:
            try:
                topic, slug = topics.resolve(ref)
            except NotFoundError:
                problems.append(f"items: there is no item {ref}")
                continue
            refs.append(f"{topic}/{slug}")
        if problems:
            raise UsageError(
                "the answer names items that do not exist — fix it and submit again", problems
            )
        write_json(Path(target), {"answer": answer["answer"].strip(), "items": refs})
        return (
            "submitted: the owner reads your answer, and the items it names as cards. You are done."
        )
