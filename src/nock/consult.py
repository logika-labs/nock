"""Consulting: a fresh agent reads the project's topics and their decisions,
their map, its tools and checks, and answers — advice before an agent's
change (the items the work must keep to, the tools that do its steps, the
checks that judge it), or the owner's question from the studio's Ask —
through `nock consult --submit`, which holds what it names to what exists.
Behind `consult.enabled`: off, nothing is dispatched."""

from __future__ import annotations

import difflib
import os
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any, NotRequired, TypedDict

from nock.checks import Checks
from nock.commands import schema_of
from nock.dispatch import Dispatcher
from nock.docs import Docs
from nock.errors import Failed, NotFoundError, PolicyError, UsageError
from nock.schema import validate
from nock.templates import Library
from nock.topics import Topics
from nock.utils import now, read_json, write_json

if TYPE_CHECKING:
    from nock.project import Project

ROLE = "consultant"
# The longest a consultation may take, in seconds: the caller waits.
DEADLINE = 600
BRIEFS = Path(__file__).resolve().parent / "briefs"
# Set in the consultant's environment: where its `nock consult --submit` writes.
SUBMISSION_VARIABLE = "NOCK_CONSULTATION"
# Set by whoever wants the answer as data (the studio's Ask): where it goes, with
# the decisions it rests on.
RESULT_VARIABLE = "NOCK_CONSULT_RESULT"
OFF = (
    "nock's consultant is off in this project (`consult.enabled = false` in .nock/config.toml):"
    " go ahead without it."
)


class Consultation(TypedDict):
    intent: str
    """What you are about to do, in a few sentences: what changes, why, which files if you know."""
    context: str
    """What you know already: the request, what you read and tried."""


class Advice(TypedDict):
    answer: str
    """What the asker should know and do, as they should read it: short and specific."""
    items: NotRequired[list[str]]
    """The items that bear on the work, as `topic/slug`; the agent is shown each one's title and verdict."""
    tools: NotRequired[list[str]]
    """The `.nock/nock` commands that do steps of the work; the agent is shown their usage."""
    checks: NotRequired[list[str]]
    """The checks or chains the work should pass before it is done."""
    docs: NotRequired[list[str]]
    """The `nock docs` terms the agent should read; it is shown their articles."""
    feedback: NotRequired[str]
    """Where nock fell short for this task, in general terms, for the next reflection round."""


class Consultant:
    def __init__(self, project: Project) -> None:
        self.project = project

    @property
    def enabled(self) -> bool:
        return self.project.configuration.get("consult.enabled") is not False

    def consult(self, consultation: Consultation) -> str:
        if not self.enabled:
            return OFF
        path = Topics(self.project).map
        tools = [
            f"`.nock/nock {tool.command.usage()}`: {tool.command.summary}"
            for tool in self.project.registry.project_tools()
        ]
        checks = [
            f"`{name}`: {description}"
            for name, description in Checks(self.project).available().items()
        ]
        brief = Library(self.project.code_path("briefs"), BRIEFS).render(
            "consult.md",
            **consultation,
            map=path.read_text().strip() if path.is_file() else "",
            tools="\n".join(f"- {line}" for line in tools),
            checks="\n".join(f"- {line}" for line in checks),
        )
        submission = self.project.local / "consultations" / f"{uuid.uuid4()}.json"
        session = Dispatcher(self.project).launch(
            ROLE,
            brief,
            self.project.here,
            variables={SUBMISSION_VARIABLE: str(submission)},
            deadline=DEADLINE,
        )
        submitted: dict[str, Any] | None = read_json(submission) if submission.is_file() else None
        if submitted is None:
            # A project's own brief may still answer in its last message.
            if session.exit_code != 0 or not session.result:
                raise Failed(
                    f"the consultant gave no advice (exit {session.exit_code}; log: {session.log})",
                    [f"refused: {line}" for line in session.denied],
                )
            answer = session.result.strip()
        else:
            answer = self.answer(submitted)
        write_json(
            submission,
            {
                **consultation,
                "moment": now(),
                "caller": self.project.current_session(),
                "session": session.id,
                "submitted": submitted,
                "denied": session.denied,
            },
        )
        result = os.environ.get(RESULT_VARIABLE)
        if result:
            items = (submitted or {}).get("items") or []
            write_json(
                Path(result),
                {
                    "answer": (submitted or {}).get("answer") or answer,
                    "items": items,
                    "session": session.id,
                },
            )
        return answer

    def answer(self, submitted: dict[str, Any]) -> str:
        """The advice exactly as submitted, then what it names: each item's
        verdict, each tool's usage, the checks to pass."""
        parts = [str(submitted["answer"]).strip()]
        topics = Topics(self.project)
        named = [topics.item(ref) for ref in submitted.get("items") or []]
        if named:
            lines = [
                "The decisions this rests on (each topic's view in .nock/local/views/ has them in full):"
            ]
            for item in named:
                lines.append(f"- [{item['ref']}] ({item['verdict']}) {item['title']}")
            parts.append("\n".join(lines))
        tools = [self.project.registry.tool(path) for path in submitted.get("tools") or []]
        if tools:
            parts.append(
                "\n".join(
                    ["Tools for it:"]
                    + [
                        f"- `.nock/nock {tool.command.usage()}`: {tool.command.summary}"
                        for tool in tools
                        if tool is not None
                    ]
                )
            )
        checks = submitted.get("checks") or []
        if checks:
            parts.append(f"Before you finish: `.nock/nock check {' '.join(checks)}`.")
        terms = submitted.get("docs") or []
        if terms:
            parts.append("Read first (`.nock/nock docs`):\n\n" + Docs().read(terms))
        return "\n\n".join(parts)

    def submit(self, advice: Advice) -> str:
        """The consultant's advice, held to naming only what exists, kept for its caller."""
        target = os.environ.get(SUBMISSION_VARIABLE)
        if self.project.current_role() != ROLE or not target:
            raise PolicyError(
                "only the consultant nock dispatches submits an answer — to consult,"
                ' `.nock/nock consult "what you are about to do, or your question"`'
            )
        problems = []
        if not str(advice.get("answer") or "").strip():
            problems.append(
                "`answer` is empty: say what the asker should know, or that nothing in nock bears on it"
            )
        topics = Topics(self.project)
        for ref in advice.get("items") or []:
            try:
                topics.resolve(ref)
            except NotFoundError:
                problems.append(f"items: there is no item {ref}")
        registry = self.project.registry
        paths = [tool.command.path for tool in registry.tools]
        for path in advice.get("tools") or []:
            if registry.tool(path) is None:
                close = difflib.get_close_matches(path, paths, n=1)
                hint = f" — did you mean `{close[0]}`?" if close else ""
                problems.append(f"tools: no command `{path}`{hint}")
        checks = Checks(self.project)
        known = {*checks.available(), *checks.chains()}
        for name in advice.get("checks") or []:
            if name not in known:
                problems.append(
                    f"checks: no check or chain `{name}` (there are: {', '.join(sorted(known)) or 'none'})"
                )
        docs = Docs()
        problems += [
            f"docs: `{word}` is not a term — `.nock/nock docs` lists them"
            for word in advice.get("docs") or []
            if docs.find(word) is None
        ]
        if problems:
            raise UsageError(
                "the advice names what does not exist — fix it and submit again", problems
            )
        validate(advice, schema_of(Advice))
        write_json(Path(target), dict(advice))
        return (
            "submitted: the agent reads your advice exactly as written, then the items, "
            "tools and checks it names. You are done."
        )
