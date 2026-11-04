"""Where the project stands with nock, in one place: whether a reflection round
is due, the decisions by status and review, those rejected and waiting to be
redone, those tagged important that wait on the owner's review, the assets
waiting on review and those to make again, a round
summary not yet shared, a
newer nock, and whether another kind of round (a logika round, in a Logika
project) is worth offering. `nock status` prints it; a
session the human starts begins with it."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from nock.assets import Assets
from nock.assets import Review as AssetReview
from nock.decisions import Decisions, Review, Status
from nock.kinds import offered
from nock.reflect import Reflection
from nock.releases import Updates
from nock.share import Sharing

if TYPE_CHECKING:
    from nock.project import Project


def brief(decision: dict[str, Any]) -> dict[str, Any]:
    return {"number": decision["number"], "title": decision["title"], "note": decision["note"]}


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
        assets = Assets(self.project)
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
            # The owner's calls, each answered as the agent proposed until they review it.
            "important": [brief(decision) for decision in decisions.important()],
            "notes": [
                brief(decision)
                for decision in decisions.matching({})
                if decision["note"]
                and decision["review"] != Review.REJECTED
                and decision["updated"] > (window.since or "")
            ],
            "assets": assets.counts(),
            # The latest versions the owner rejected or left a note on: someone makes the next.
            "assets_to_remake": [
                {
                    "key": version["key"],
                    "version": version["version"],
                    "title": version["title"],
                    "review": version["review"],
                    "feedback": version["feedback"],
                }
                for version in assets.to_remake()
            ],
            "unshared": Sharing(self.project).unshared(),
            "newer_nock": Updates(self.project).newer(),
            # The other kinds of round that can run here, each offered when due.
            "rounds": {
                kind.kind: {
                    **(kind.standing() or {}),
                    "title": kind.title,
                    "skill_name": kind.skill,
                }
                for kind in offered(self.project)
            },
        }

    def lines(self, standing: dict[str, Any]) -> list[str]:
        """The standing, said in a few short lines; nothing when nothing calls."""
        lines = []
        due = standing["reflection"]["due"]
        if due:
            lines.append(f"nock: {due} — offer the human `/nock-reflect`, which runs one.")
        counts = standing["decisions"]
        waiting = [
            f"{len(standing['important'])} important",
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
        important = standing["important"]
        if important:
            lines.append(
                "nock: important decisions awaiting review — agents carry on with each as"
                " proposed until it is accepted or rejected:"
            )
            lines += [
                f"- [D{item['number']}] {item['title']}{said(item)}" for item in important[:SHOWN]
            ]
            if len(important) > SHOWN:
                lines.append(
                    f"- and {len(important) - SHOWN} more — `.nock/nock status` lists them"
                )
        assets = standing["assets"]
        remake = standing["assets_to_remake"]
        if assets[AssetReview.UNREVIEWED] or remake:
            parts = [
                f"{count} {what}"
                for count, what in (
                    (assets[AssetReview.UNREVIEWED], "unreviewed"),
                    (len(remake), "to make again"),
                )
                if count
            ]
            lines.append(f"nock: assets — {', '.join(parts)}: review them on `.nock/nock studio`.")
        lines += [
            f"- make again asset `{item['key']}` (version {item['version']}, {item['review']})"
            f" {item['title']}{said({'note': item['feedback']})}"
            for item in remake[:SHOWN]
        ]
        if len(remake) > SHOWN:
            lines.append(f"- and {len(remake) - SHOWN} more — `.nock/nock status` lists them")
        if remake:
            lines.append(
                "  (`.nock/nock assets show KEY` has how each was made; `assets add` registers"
                " the next version, answering the note.)"
            )
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
        for kind, offer in standing["rounds"].items():
            if not offer.get("due"):
                continue
            install = "" if offer["skill"] else " (`.nock/nock init` installs the skill)"
            lines.append(
                f"nock: {offer['due']} — when the human wants one, `/{offer['skill_name']}`{install}"
                f" runs the {offer['title']} with them (`.nock/nock reflect {kind}`); never start"
                " it unasked."
            )
        return lines
