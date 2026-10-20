"""Consulting: before something serious, an agent asks a fresh one — which
reads the project's decisions, their map and its documents — to reframe the
task, and waits for the answer."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, TypedDict

from nock.dispatch import Dispatcher
from nock.errors import Failed
from nock.templates import Library

if TYPE_CHECKING:
    from nock.project import Project

ROLE = "consultant"
BRIEFS = Path(__file__).resolve().parent / "briefs"


class Consultation(TypedDict):
    intent: str
    """What you are about to do, or are stuck on, in a few sentences."""
    context: str
    """What you know already: the request, what you read and tried, what worries you."""


class Consultant:
    def __init__(self, project: Project) -> None:
        self.project = project

    def consult(self, consultation: Consultation) -> str:
        brief = Library(self.project.code_path("briefs"), BRIEFS).render(
            "consult.md", **consultation
        )
        session = Dispatcher(self.project).launch(
            ROLE,
            brief,
            self.project.here,
            deadline=float(self.project.configuration.get("consult.deadline")),
        )
        if session.exit_code != 0 or not session.result:
            raise Failed(
                f"the consultant gave no answer (exit {session.exit_code}; log: {session.log})"
            )
        return session.result.strip()
