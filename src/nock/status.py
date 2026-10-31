"""Where the project stands with nock, in one place: whether a reflection round
is due, the decisions by status and review, those rejected and waiting to be
redone, the questions the owner answered, and a round summary not yet shared. `nock status` prints it; a
session the human starts begins with it."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from nock.decisions import Decisions, Review, Status
from nock.reflect import Reflection
from nock.share import Sharing

if TYPE_CHECKING:
    from nock.project import Project


def brief(decision: dict[str, Any]) -> dict[str, Any]:
    return {"number": decision["number"], "title": decision["title"], "note": decision["note"]}


# What the owner's review of a question means.
ANSWERS = {Review.ACCEPTED: "yes", Review.REJECTED: "no", Review.UNREVIEWED: "answered in a note"}


def said(decision: dict[str, Any]) -> str:
    return f" — the owner: {decision['note']}" if decision["note"] else ""


class Standing:
    def __init__(self, project: Project) -> None:
        self.project = project

    def collect(self) -> dict[str, Any]:
        reflection = Reflection(self.project)
        window = reflection.window()
        decisions = Decisions(self.project)
        return {
            "reflection": {
                "due": reflection.due() or None,
                "last": window.since,
                "sessions_since": len(window.sessions),
                "days_since": round(reflection.days(window), 1),
            },
            "decisions": decisions.counts(),
            "to_rework": [brief(decision) for decision in decisions.to_rework()],
            # What the owner approved and has not been done, and what they said since the last round.
            "backlog": [
                brief(decision)
                for decision in decisions.matching(
                    {"status": Status.TODO, "review": Review.ACCEPTED}
                )
            ],
            "answered": [
                {**brief(decision), "answer": decision["review"]}
                for decision in decisions.answered()
            ],
            "notes": [
                brief(decision)
                for decision in decisions.matching({})
                if decision["note"]
                and decision["review"] != Review.REJECTED
                and decision["status"] != Status.QUESTION
                and decision["updated"] > (window.since or "")
            ],
            "unshared": Sharing(self.project).unshared(),
        }

    def lines(self, standing: dict[str, Any]) -> list[str]:
        """The standing, said in a few lines; nothing when nothing calls for the owner."""
        lines = []
        due = standing["reflection"]["due"]
        if due:
            lines.append(f"nock: {due} — offer the human `/nock-reflect`, which runs one.")
        counts = standing["decisions"]
        waiting = [
            f"{counts[Status.QUESTION][Review.UNREVIEWED]} question(s)",
            f"{counts[Status.TODO][Review.UNREVIEWED]} todo(s)",
            f"{counts[Status.DONE][Review.UNREVIEWED]} done unreviewed",
            f"{counts[Status.DONE][Review.REJECTED]} rejected to rework",
        ]
        if any(not part.startswith("0 ") for part in waiting):
            parts = ", ".join(part for part in waiting if not part.startswith("0 "))
            lines.append(
                f"nock: decisions — {parts}: review them on `.nock/nock web`, or with `/nock-triage`."
            )
        for decision in standing["to_rework"]:
            lines.append(f"- rework [D{decision['number']}] {decision['title']}{said(decision)}")
        if standing["answered"]:
            lines.append(
                "nock: questions the owner answered — act on each, then edit it to done saying what you did:"
            )
            lines += [
                f"- [D{item['number']}] {item['title']} — {ANSWERS[item['answer']]}{said(item)}"
                for item in standing["answered"]
            ]
        if standing["backlog"]:
            lines.append("nock: the owner's backlog — todos they accepted, not done yet:")
            lines += [
                f"- [D{item['number']}] {item['title']}{said(item)}" for item in standing["backlog"]
            ]
        notes = [item for item in standing["notes"] if item not in standing["backlog"]]
        if notes:
            lines.append(
                "nock: what the owner said about decisions lately — some may ask for something:"
            )
            lines += [f"- [D{item['number']}] {item['title']}{said(item)}" for item in notes]
        if standing["unshared"]:
            lines.append(
                f"nock: the {standing['unshared']} round's summary is not shared yet — "
                "`.nock/nock share` shows it; sharing it helps nock's makers improve nock."
            )
        return lines
