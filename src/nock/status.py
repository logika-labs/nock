"""Where the project stands with nock, in one place: whether a reflection round
is due, the open items by topic (new to the owner), what waits on an agent in
the topics (threads where the owner wrote last, items they rejected), a round
summary not yet shared, a newer nock, and whether another kind of round (a
logika round, in a Logika project) is worth offering. `nock status` prints
it; a session the human starts begins with it."""

from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING, Any

from nock.inbox import Inbox
from nock.kinds import offered
from nock.reflect import Reflection
from nock.releases import Updates
from nock.share import Sharing
from nock.shared import Shared
from nock.topics import Topics

if TYPE_CHECKING:
    from nock.project import Project


# The most items of a kind the session start lists; `nock status` has them all.
SHOWN = 3


class Standing:
    def __init__(self, project: Project) -> None:
        self.project = project

    def collect(self) -> dict[str, Any]:
        reflection = Reflection(self.project)
        window = reflection.window()
        topics = Topics(self.project)
        return {
            "reflection": {
                "due": reflection.due() or None,
                "last": window.since,
                "sessions_since": len(window.sessions),
                "days_since": round(reflection.days(window), 1),
            },
            # The open decisions by topic, and what waits on an agent.
            "topics": topics.summary(),
            # What the owner said that no agent has addressed, by kind.
            "inbox": dict(
                Counter(entry["kind"] for entry in Inbox(self.project).entries(every=True))
            ),
            # What was written in the store and not committed: it does not hold.
            "uncommitted": [path for _, path in Shared(self.project).changes()],
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
        summary = standing["topics"]
        opened = summary["open"]
        if opened:
            total = sum(opened.values())
            by_topic = ", ".join(f"{name}: {count}" for name, count in list(opened.items())[:5])
            more = ", …" if len(opened) > 5 else ""
            lines.append(
                f"nock: {total} new in Topics ({by_topic}{more}) — on"
                " `.nock/nock studio`, or with `/nock-triage`."
            )
        awaiting = summary["awaiting_you"]
        threads, rejected = awaiting["owner_wrote_last"], awaiting["rejected"]
        if threads or rejected:
            parts = [
                f"{count} {what}"
                for count, what in (
                    (len(threads), "thread(s) where the owner wrote last"),
                    (len(rejected), "rejected item(s) to rework"),
                )
                if count
            ]
            lines.append(
                f"nock: waiting on you in Topics — {', '.join(parts)}: `.nock/nock inbox`."
            )
            attached = awaiting.get("attachments", {})
            lines += [
                f"- answer in {ref}"
                + (f" (attached: {', '.join(attached[ref])})" if ref in attached else "")
                for ref in threads[:SHOWN]
            ]
            lines += [f"- rework {ref} (a new version)" for ref in rejected[:SHOWN]]
            if len(threads) > SHOWN or len(rejected) > SHOWN:
                lines.append("- and more — `.nock/nock inbox` has them all")
        if standing.get("uncommitted"):
            lines.append(
                f"nock: {len(standing['uncommitted'])} change(s) in .nock/shared/ don't hold and"
                " stay uncommitted — fix or remove them (`.nock/nock docs files`)."
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
