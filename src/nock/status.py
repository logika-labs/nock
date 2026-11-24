"""Where the project stands with nock, in one place: whether a reflection round
is due, a round summary not yet shared, a newer nock, and whether another
kind of round (a logika round, in a Logika project) is worth offering.
`nock status` prints it; a session the human starts begins with it, in a few
lines."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from nock.reflect import Reflection
from nock.releases import Updates
from nock.rounds import Protocol, protocols, skill_of
from nock.share import Sharing

if TYPE_CHECKING:
    from nock.project import Project


def offered(project: Project, every: list[Protocol]) -> dict[str, Any]:
    """The other namespaces' rounds that can run here and are adopted, each
    offered when one of its protocols is due: never run unasked."""
    found: dict[str, Any] = {}
    for protocol in every:
        namespace = protocol.manifest.namespace
        if namespace == "nock" or protocol.unavailable() or not protocol.adopted():
            continue
        skill = skill_of(namespace)
        offer = found.setdefault(
            namespace,
            {
                "due": None,
                "last": None,
                "title": f"{namespace} round",
                "skill_name": skill,
                "skill": (project.here / ".claude" / "skills" / skill / "SKILL.md").is_file(),
            },
        )
        offer["due"] = offer["due"] or protocol.due() or None
        last = protocol.since
        offer["last"] = max(filter(None, [offer["last"], last]), default=None)
    return found


class Standing:
    def __init__(self, project: Project) -> None:
        self.project = project

    def collect(self) -> dict[str, Any]:
        reflection = Reflection(self.project)
        window = reflection.window()
        every = protocols(self.project)
        own = [protocol for protocol in every if protocol.manifest.namespace == "nock"]
        why = next((reason for protocol in own if (reason := protocol.due())), "")
        return {
            "reflection": {
                "due": f"a reflection round is due ({why})" if why else None,
                "last": window.since,
                "sessions_since": len(window.sessions),
                "days_since": round(reflection.days(window), 1),
            },
            "unshared": Sharing(self.project).unshared(),
            "newer_nock": Updates(self.project).newer(),
            # The other kinds of round that can run here, each offered when due.
            "rounds": offered(self.project, every),
        }

    def lines(self, standing: dict[str, Any]) -> list[str]:
        """The standing, said in a few short lines; nothing when nothing calls."""
        lines = []
        due = standing["reflection"]["due"]
        if due:
            lines.append(f"nock: {due} — offer the human `/nock-reflect`; never start it unasked.")
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
