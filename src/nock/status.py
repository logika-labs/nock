"""Where the project stands with nock, in one place: the subrounds due, a fit
run's summary not yet shared, a newer nock. `nock status` prints it; a
session the human starts begins with one line of it, the rounds due."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from nock.reflect import Reflection
from nock.releases import Updates
from nock.rounds import subrounds
from nock.share import Sharing

if TYPE_CHECKING:
    from nock.project import Project

# The most subrounds and skills the session start's line names.
NAMED = 4


class Standing:
    def __init__(self, project: Project) -> None:
        self.project = project

    def due(self) -> dict[str, dict[str, str]]:
        """Each subround due here, with why and the skill that runs it."""
        return {
            subround.name: {"why": why, "skill": f"/{subround.skill()}"}
            for subround in subrounds(self.project)
            if (why := subround.due())
        }

    def collect(self) -> dict[str, Any]:
        reflection = Reflection(self.project)
        window = reflection.window()
        return {
            "due": self.due(),
            "fit": {
                "last": window.since,
                "sessions_since": len(window.sessions),
                "days_since": round(reflection.days(window), 1),
            },
            "unshared": Sharing(self.project).unshared(),
            "newer_nock": Updates(self.project).newer(),
        }

    def line(self, due: dict[str, dict[str, str]]) -> str:
        """The rounds due, in one short line; nothing when none is."""
        if not due:
            return ""
        skills = list(dict.fromkeys(entry["skill"] for entry in due.values()))
        return (
            f"nock: due — {bounded(list(due))}; offer the human"
            f" {bounded([f'`{skill}`' for skill in skills])}, never start one unasked."
        )


def bounded(names: list[str]) -> str:
    """NAMES joined, the first few and how many more."""
    more = f" and {len(names) - NAMED} more" if len(names) > NAMED else ""
    return ", ".join(names[:NAMED]) + more
