"""Sharing a round's summary with nock's makers: the abstract one the round
wrote (`share.md`), held to saying nothing that names the project, sent only
when the owner says so — privately (only nock's makers read it) or publicly
(posted on nock.dev, for discussion)."""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from enum import StrEnum
from typing import TYPE_CHECKING, Any, NotRequired, TypedDict

from nock.errors import ExternalError, NotFoundError
from nock.git import GitError
from nock.reflect import SHARE, Reflection
from nock.render import Problem
from nock.utils import now

if TYPE_CHECKING:
    from nock.project import Project

EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
URL = re.compile(r"https?://[^\s)>\]]+")
# Files every project has: naming one says nothing about this one.
COMMON_FILES = {
    "README.md", "CLAUDE.md", "AGENTS.md", "CHANGELOG.md", "LICENSE", "Makefile",
    "pyproject.toml", "package.json", "requirements.txt", "setup.py", ".gitignore",
    "config.toml", "settings.json", "map.md", "SKILL.md",
}  # fmt: skip


class Visibility(StrEnum):
    PRIVATE = "private"
    """Only nock's makers read it."""
    PUBLIC = "public"
    """Posted on nock.dev, where others can discuss it."""


class Request(TypedDict):
    visibility: Visibility
    round: NotRequired[str]
    """The round's date, as its directory is named; the default is the latest."""
    send: NotRequired[bool]
    """Send it. Only on the owner's word; without it, see what would be sent."""


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

    def share(self, request: Request) -> dict[str, Any]:
        record = self.round(request.get("round"))
        name = record["round"]
        text = self.text(name)
        endpoint = str(self.project.configuration.get("share.endpoint"))
        if not request.get("send"):
            return {
                "round": name,
                "to": endpoint,
                "visibility": str(request["visibility"]),
                "shared": record.get("shared"),
                "text": text,
            }
        body = json.dumps(
            {"summary": text, "visibility": str(request["visibility"]), "round": name}
        ).encode()
        post = urllib.request.Request(
            endpoint, data=body, headers={"Content-Type": "application/json"}, method="POST"
        )
        try:
            with urllib.request.urlopen(post, timeout=30) as response:
                answer = json.loads(response.read() or b"{}")
        except (urllib.error.URLError, TimeoutError, ValueError) as error:
            raise ExternalError(f"could not reach {endpoint}: {error}") from error
        shared = {
            "moment": now(),
            "visibility": str(request["visibility"]),
            "url": answer.get("url"),
        }
        self.reflection.record_shared(name, shared)
        self.reflection.commit(f"Reflection round {name}: shared, {request['visibility']}")
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
        loose, exact = self.identifiers()
        place = str(path.relative_to(self.project.here))
        found = []
        for line, text in enumerate(path.read_text().splitlines(), start=1):
            said: list[str] = EMAIL.findall(text)
            said += [url for url in URL.findall(text) if "nock.dev" not in url]
            said += [
                token
                for token in loose
                if re.search(rf"(?<![\w.-]){re.escape(token)}(?![\w-])", text, re.IGNORECASE)
            ]
            said += [token for token in exact if re.search(rf"\b{re.escape(token)}\b", text)]
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
