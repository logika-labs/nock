"""Where the project stands with nock, in one place: whether a reflection round
is due, the decisions by status and review, those rejected and waiting to be
redone, the questions the owner answered, a round summary not yet shared, a
newer nock, and — in a Logika project — whether a logika round is worth
offering. `nock status` prints it; a
session the human starts begins with it."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from nock.decisions import Decisions, Review, Status
from nock.logika import SKILL, LogikaRound
from nock.reflect import Reflection
from nock.releases import Updates
from nock.share import Sharing

if TYPE_CHECKING:
    from nock.project import Project


def brief(decision: dict[str, Any]) -> dict[str, Any]:
    return {"number": decision["number"], "title": decision["title"], "note": decision["note"]}


# What the owner's review of a question means.
ANSWERS = {Review.ACCEPTED: "yes", Review.REJECTED: "no", Review.UNREVIEWED: "answered in a note"}


# The most items of a kind the session start lists; `nock status` has them all.
SHOWN = 3


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
            "newer_nock": Updates(self.project).newer(),
            "logika": LogikaRound(self.project).standing(),
        }

    def lines(self, standing: dict[str, Any]) -> list[str]:
        """The standing, said in a few short lines; nothing when nothing calls."""
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
                f"nock: decisions — {parts}: review them on `.nock/nock studio`, or with `/nock-triage`."
            )
        rework = standing["to_rework"]
        lines += [
            f"- rework [D{decision['number']}] {decision['title']}{said(decision)}"
            for decision in rework[:SHOWN]
        ]
        if len(rework) > SHOWN:
            lines.append(f"- and {len(rework) - SHOWN} more — `.nock/nock status` lists them")
        answered = standing["answered"]
        if answered:
            lines.append(
                "nock: questions the owner answered — act on each, then edit it to done saying what you did:"
            )
            lines += [
                f"- [D{item['number']}] {item['title']} — {ANSWERS[item['answer']]}{said(item)}"
                for item in answered[:SHOWN]
            ]
            if len(answered) > SHOWN:
                lines.append(f"- and {len(answered) - SHOWN} more — `.nock/nock status` lists them")
        notes = [item for item in standing["notes"] if item not in standing["backlog"]]
        if standing["backlog"] or notes:
            parts = [
                f"{count} {what}"
                for count, what in (
                    (len(standing["backlog"]), "todo(s) the owner accepted"),
                    (len(notes), "note(s) the owner left on decisions lately"),
                )
                if count
            ]
            lines.append(
                f"nock: the owner's backlog — {', '.join(parts)}: `.nock/nock status` lists them."
            )
        if standing["newer_nock"]:
            lines.append(
                f"nock: nock {standing['newer_nock']} is out (this project has "
                f"{Updates(self.project).installed()}) — `.nock/nock upgrade` upgrades it."
            )
        if standing["unshared"]:
            lines.append(
                f"nock: the {standing['unshared']} round's summary is not shared yet — "
                "`.nock/nock share` shows it; sharing it helps nock's makers improve nock."
            )
        logika = standing["logika"]
        if logika and logika["due"]:
            install = "" if logika["skill"] else " (`.nock/nock init` installs the skill)"
            lines.append(
                f"nock: {logika['due']} — when the human wants one, `/{SKILL}`{install} turns the "
                "ledger and its captured data into rules, with them; never start it unasked."
            )
        return lines
