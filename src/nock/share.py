"""Sharing a round's summary with nock's makers: the abstract one the round
wrote (`share.md`), vetted by a fresh agent that reads the project to learn
what would identify it and rewrites whatever does, then held to a mechanical
scrub — and sent only when the owner says so, to nock's makers alone."""

from __future__ import annotations

import hashlib
import json
import re
import urllib.error
import urllib.request
from pathlib import Path
from typing import TYPE_CHECKING, Any, NotRequired, TypedDict

from nock.dispatch import Dispatcher
from nock.errors import ExternalError, Failed, NotFoundError, PolicyError
from nock.git import GitError
from nock.reflect import SHARE, Reflection, commit
from nock.render import Problem
from nock.templates import Library
from nock.usage import shares
from nock.utils import now, read_json, write_json

if TYPE_CHECKING:
    from nock.project import Project

ROLE = "sharer"
BRIEFS = Path(__file__).resolve().parent / "briefs"
# How the vetting agent says the summary cannot be shared at all.
NOTHING = "NOTHING TO SHARE:"
EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
URL = re.compile(r"https?://[^\s)>\]]+")
# Files every project has: naming one says nothing about this one.
COMMON_FILES = {
    "README.md", "CLAUDE.md", "AGENTS.md", "CHANGELOG.md", "LICENSE", "Makefile",
    "pyproject.toml", "package.json", "requirements.txt", "setup.py", ".gitignore",
    "config.toml", "settings.json", "map.md", "SKILL.md",
}  # fmt: skip


class Request(TypedDict):
    round: NotRequired[str]
    """The round's date, as its directory is named; the default is the latest."""
    send: NotRequired[bool]
    """Send it. Only on the owner's word; without it, see what would be sent."""
    again: NotRequired[bool]
    """Vet it afresh, even though the summary has not changed since it was."""


class Sharing:
    def __init__(self, project: Project) -> None:
        self.project = project
        self.reflection = Reflection(project)

    def round(self, name: str | None) -> dict[str, Any]:
        rounds = [record for record in self.reflection.rounds.all() if record.get("metrics")]
        if name is not None:
            rounds = [record for record in rounds if record["round"] == name]
        if not rounds:
            raise NotFoundError(f"no finished round{f' {name}' if name else ''} to share")
        return rounds[-1]

    def text(self, name: str) -> str:
        return (self.reflection.rounds.directory / name / SHARE).read_text().strip()

    def vetted(self, name: str, again: bool) -> str:
        """The summary as it would be sent: vetted by an agent — again only
        when the summary changed, or when asked — and scrubbed."""
        text = self.text(name)
        fingerprint = hashlib.sha256(text.encode()).hexdigest()
        kept = self.reflection.rounds.scratch / name / "outgoing.json"
        if not again and kept.is_file() and read_json(kept).get("fingerprint") == fingerprint:
            return read_json(kept)["text"]
        brief = Library(self.project.code_path("briefs"), BRIEFS).render("share.md", text=text)
        session = Dispatcher(self.project).launch(ROLE, brief, self.project.here)
        result = (session.result or "").strip()
        if session.exit_code != 0 or not result:
            raise Failed(
                f"the vetting agent gave no text (exit {session.exit_code}; log: {session.log})",
                [f"refused: {line}" for line in session.denied],
            )
        if result.startswith(NOTHING):
            raise Failed(
                f"the vetting agent found nothing that can be shared — {result.removeprefix(NOTHING).strip()}"
            )
        problems = self.problems_in(result, "the vetted summary")
        if problems:
            raise Failed("the vetted summary still names the project", problems)
        write_json(
            kept,
            {
                "fingerprint": fingerprint,
                "text": result,
                "session": session.id,
                "denied": session.denied,
            },
        )
        return result

    def share(self, request: Request) -> dict[str, Any]:
        if request.get("send") and not shares(self.project):
            raise PolicyError(
                "`share` is false here, so nock sends nothing — set `share = true` in"
                " .nock/config.toml to send the summary"
            )
        record = self.round(request.get("round"))
        name = record["round"]
        text = self.vetted(name, bool(request.get("again")))
        endpoint = str(self.project.configuration.get("endpoints.reflections"))
        if not request.get("send"):
            return {"round": name, "to": endpoint, "shared": record.get("shared"), "text": text}
        body = json.dumps({"summary": text, "round": name}).encode()
        post = urllib.request.Request(
            endpoint, data=body, headers={"Content-Type": "application/json"}, method="POST"
        )
        try:
            with urllib.request.urlopen(post, timeout=30) as response:
                answer = json.loads(response.read() or b"{}")
        except (urllib.error.URLError, TimeoutError, ValueError) as error:
            raise ExternalError(f"could not reach {endpoint}: {error}") from error
        shared = {"moment": now(), "id": answer.get("id")}
        self.reflection.record_shared(name, shared)
        commit(self.project, f"Reflection round {name}: shared")
        return {"round": name, **shared}

    # --- what the summary may not say -------------------------------------------

    def identifiers(self) -> tuple[set[str], set[str]]:
        """What names this project: its directory and remotes, the paths and
        file names in it (matched in any case), and its authors (as written)."""
        git = self.project.git
        loose = {self.project.root.name}
        exact: set[str] = set()
        try:
            for url in git("remote", "-v").split():
                loose.update(
                    part for part in re.split(r"[/:@]", url.removesuffix(".git"))[-2:] if part
                )
            files = git("ls-files").splitlines()
            authors = git("log", "--max-count=500", "--format=%an%n%ae").splitlines()
        except GitError:
            files, authors = [], []
        for file in files:
            if file.startswith(".nock/") or file.startswith(".claude/"):
                continue
            name = file.rsplit("/", 1)[-1]
            if "/" in file:
                loose.add(file)
            if "." in name.strip(".") and name not in COMMON_FILES:
                loose.add(name)
        exact.update(author for author in authors if author.strip())
        loose -= {"nock", "origin", "fetch", "push", "github.com", "gitlab.com"}
        return {token for token in loose if len(token) > 2}, exact

    def problems(self, name: str) -> list[Problem]:
        """Every line of a round's summary that names the project, someone in
        it, an address or a link."""
        path = self.reflection.rounds.directory / name / SHARE
        if not path.is_file():
            return []
        return self.problems_in(path.read_text(), str(path.relative_to(self.project.here)))

    def problems_in(self, text: str, place: str) -> list[Problem]:
        loose, exact = self.identifiers()
        found = []
        for line, content in enumerate(text.splitlines(), start=1):
            said: list[str] = EMAIL.findall(content)
            said += [url for url in URL.findall(content) if "nock.dev" not in url]
            said += [
                token
                for token in loose
                if re.search(rf"(?<![\w.-]){re.escape(token)}(?![\w-])", content, re.IGNORECASE)
            ]
            said += [token for token in exact if re.search(rf"\b{re.escape(token)}\b", content)]
            found += [
                Problem(f"names `{token}` — say it abstractly", place, line)
                for token in sorted(set(said))
            ]
        return found

    def unshared(self) -> str | None:
        """The latest round, when its summary has not been shared."""
        records = [record for record in self.reflection.rounds.all() if record.get("metrics")]
        if records and not records[-1].get("shared"):
            return records[-1]["round"]
        return None
