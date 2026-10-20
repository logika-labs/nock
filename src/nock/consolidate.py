"""Consolidation: an agent, following the `/consolidate` skill, reads the
decisions made since the last round and keeps the map —
`.nock/questions/map.md`, what the decisions mean for the work and how they
bear on each other — and records what the work taught as lessons, questions
decided at once. The `nock-map` check holds the map's citations to standing
decisions."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from nock.questions import Questions, State, live
from nock.utils import now, parse_moment, read_json, write_json

if TYPE_CHECKING:
    from nock.project import Project

RECORD = "consolidated.json"


class Consolidation:
    def __init__(self, project: Project) -> None:
        self.project = project
        self.questions = Questions(project)

    @property
    def record(self) -> Path:
        """When the last round landed and what it covered: committed beside the map."""
        return self.questions.directory / RECORD

    def last(self) -> str | None:
        return read_json(self.record).get("finished") if self.record.is_file() else None

    def decided_since(self) -> list[dict[str, Any]]:
        """The decisions made since the last round — not the lessons a round recorded."""
        since = self.last() or ""
        return [
            question
            for question in self.questions.all()
            if question["state"] == State.CLOSED
            and question["updated"] > since
            and not question.get("lesson")
        ]

    def due(self) -> str:
        """Why a round is due, or nothing when it is not."""
        settings = self.project.configuration
        decided = self.decided_since()
        count = len(decided)
        if count >= int(settings.get("consolidate.questions")):
            return f"consolidation is due ({count} decisions since the last)"
        since = parse_moment(self.last()) or min(
            (parse_moment(question["updated"]) or datetime.now(UTC) for question in decided),
            default=None,
        )
        days = (datetime.now(UTC) - since).total_seconds() / 86400 if since else 0
        if days >= float(settings.get("consolidate.days")) and count >= int(
            settings.get("consolidate.minimum")
        ):
            return f"consolidation is due ({count} decisions over {days:.0f} days)"
        return ""

    def material(self) -> str:
        """The decisions since the last round in full, every standing one, and the map."""
        lines = [f"# Decided since the last round ({self.last() or 'never'})", ""]
        decided = self.decided_since()
        if not decided:
            lines.append("Nothing.")
        for question in decided:
            lines += [f"## [Q{question['number']}] {question['title']}", "", "```json"]
            lines += [json.dumps(shown(question), indent=2, ensure_ascii=False), "```", ""]
        lines += ["", "# Every standing decision", ""]
        lines += [
            f"- [Q{question['number']}] {question['title']}"
            + (f" — touches {', '.join(question['touches'])}" if question.get("touches") else "")
            for question in self.questions.all()
            if live(question)
        ] or ["None yet."]
        current = self.questions.map.read_text() if self.questions.map.is_file() else ""
        lines += ["", "# The map as it stands", "", current.strip() or "There is no map yet."]
        return "\n".join(lines) + "\n"

    def finish(self) -> Path:
        """Record the round: when it finished, and the decisions it covered."""
        covered = [question["number"] for question in self.decided_since()]
        write_json(self.record, {"finished": now(), "covered": covered})
        return self.record


def shown(question: dict[str, Any]) -> dict[str, Any]:
    """A decision as the round reads it: what was asked, what was decided."""
    keys = ("title", "context", "options", "recommended", "answer", "touches", "supersedes")
    return {key: question[key] for key in keys if question.get(key)}
