"""Where the project stands with nock, in one place: whether a reflection round
is due, the open items by topic (new to the owner), what waits on an agent in
the topics (threads where the owner wrote last, items they rejected), a round
summary not yet shared, a newer nock, and whether another kind of round (a
logika round, in a Logika project) is worth offering. `nock status` prints
it, with its nudges for the session asking (`nudges`); a session the human
starts begins with the standing alone."""

from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING, Any

from nock.generators import Generators
from nock.inbox import Inbox
from nock.reflect import Reflection
from nock.releases import Updates
from nock.rounds import Protocol, protocols, skill_of
from nock.sessions import Sessions
from nock.share import Sharing
from nock.shared import Shared
from nock.topics import Topics

if TYPE_CHECKING:
    from nock.project import Project


# The most items of a kind the session start lists; `nock status` has them all.
SHOWN = 3
# Claude Code's tools that change a file.
EDITING = ("Edit", "MultiEdit", "Write", "NotebookEdit")
# How many commits since the session last recorded anything ask it to record.
UNRECORDED_COMMITS = 3


def consult_nudge(project: Project, session: str | None) -> str:
    """Files this session changed, and no `nock consult` run in it."""
    if not session:
        return ""
    Sessions(project).catch_up()
    placeholders = ", ".join("?" for _ in EDITING)
    edited = {
        row["input"]
        for row in project.store.rows(
            f"SELECT input FROM events WHERE session = ? AND tool IN ({placeholders})",
            (session, *EDITING),
        )
        if row["input"]
    }
    consulted = project.store.rows(
        "SELECT 1 FROM calls WHERE session = ? AND tool = 'consult' LIMIT 1", (session,)
    )
    if not edited or consulted:
        return ""
    return (
        f"nock: this session changed {len(edited)} file(s) and consulted on none —"
        ' `.nock/nock consult "what you are about to do"` when unsure, or touching something'
        " with history."
    )


def record_nudge(project: Project, session: str | None) -> str:
    """Commits since this session's last write to the topics (the last commit
    nock made for it, by its `Nock-Session` trailer), none of them nock's own;
    nothing for a session that wrote nothing yet."""
    if not session:
        return ""
    last = project.git(
        "log", "-1", "--format=%H", "--fixed-strings", f"--grep=Nock-Session: {session}",
        "HEAD", check=False,
    ).strip()  # fmt: skip
    if not last:
        return ""
    subjects = project.git("log", "--format=%s", f"{last}..HEAD", check=False)
    commits = [line for line in subjects.splitlines() if line and not line.startswith("nock:")]
    if len(commits) < UNRECORDED_COMMITS:
        return ""
    return (
        f"nock: {len(commits)} commit(s) since this session last recorded anything in Topics —"
        " a choice a later reader would ask about is a decision to record, and what you made"
        " to show the work an asset of it (`.nock/nock docs topics.items`)."
    )


def gen_nudge(project: Project) -> str:
    """Generated files edited by hand: out of step with their generator."""
    drifted = Generators(project).drifted(project.here)
    if not drifted:
        return ""
    return (
        f"nock: {', '.join(drifted[:SHOWN])} {'is' if len(drifted) == 1 else 'are'} generated"
        " and out of step with the generator — the change belongs in the generator;"
        " `.nock/nock gen` writes them again."
    )


def nudges(project: Project, session: str | None) -> list[str]:
    """What the session asking `nock status` might do next, each when it applies."""
    found = [consult_nudge(project, session), record_nudge(project, session), gen_nudge(project)]
    return [text for text in found if text]


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

    def collect(self, nudging: bool = False) -> dict[str, Any]:
        reflection = Reflection(self.project)
        window = reflection.window()
        topics = Topics(self.project)
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
            # What the session asking might do next: only `nock status` asks.
            **({"nudges": nudges(self.project, self.project.current_session())} if nudging else {}),
            # The other kinds of round that can run here, each offered when due.
            "rounds": offered(self.project, every),
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
        lines += standing.get("nudges") or []
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
