"""Assets: what agents made for the owner to look at — screenshots, videos,
PDFs, HTML pages, text — each under a stable key (`email/anomaly-report`) and
numbered by version, the latest superseding the earlier ones. A version is a
directory in the main checkout's `.nock/assets/KEY/N/`, its record
(`asset.json`) beside its files, committed as decisions are; a file over
`LARGE` bytes stays under `.nock/local/assets/` instead, uncommitted, and the
record says so. The owner reviews the latest version (approved, rejected, a
note) on the page or with `assets review`, and may have it regenerated: the
recipe's command is run, or an agent is dispatched with its instruction, the
note and the current version, and what it makes is the next version."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import uuid
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Any, NotRequired, TypedDict

from nock.decisions import Decisions, committed
from nock.dispatch import SEATS, Dispatcher, Seat
from nock.errors import Error, Failed, NotFoundError, PreconditionError, UsageError
from nock.processes import Supervisor
from nock.templates import Library
from nock.utils import now, read_json, slug, write_json

if TYPE_CHECKING:
    from nock.project import Project

ROLE = "regenerator"
PACKAGE = Path(__file__).resolve().parent
BRIEFS = PACKAGE / "briefs"
RECORD = "asset.json"
# A file larger than this (most videos) is kept on this machine, uncommitted.
LARGE = 20 * 1024 * 1024
# A key: lowercase words joined by `/`, none of them only digits (a version's directory is).
SEGMENT = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
TEXT_FILE = "text.txt"
KINDS = {
    "image": (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".avif"),
    "video": (".mp4", ".webm", ".mov", ".m4v", ".ogv"),
    "pdf": (".pdf",),
    "html": (".html", ".htm"),
    "text": (".txt", ".md", ".json", ".log", ".csv", ".yaml", ".yml", ".toml", ".xml", ".diff"),
}
# What a regeneration's command and agent are told, in their environment.
KEY_VARIABLE = "NOCK_ASSET"
FROM_VARIABLE = "NOCK_ASSET_FROM"
FEEDBACK_VARIABLE = "NOCK_ASSET_FEEDBACK"
OUTPUT_VARIABLE = "NOCK_ASSET_OUTPUT"


class Review(StrEnum):
    UNREVIEWED = "unreviewed"
    APPROVED = "approved"
    REJECTED = "rejected"
    """Make it again, as the feedback says."""


class Recipe(TypedDict):
    """How to make the asset again: a command, an agent's instruction, or both."""

    command: NotRequired[str]
    """Run in the working tree by `sh -c`; it writes the new version's files
    into $NOCK_ASSET_OUTPUT, and may read the owner's note in $NOCK_ASSET_FEEDBACK."""
    instruction: NotRequired[str]
    """What an agent does to make it, told the owner's note and the current version."""


class Draft(TypedDict):
    key: str
    """Its stable identity, a path of lowercase words: `email/anomaly-report`.
    An existing key gets a new version."""
    title: NotRequired[str]
    """What it shows; required for a new key, otherwise the latest version's."""
    tags: NotRequired[list[str]]
    files: NotRequired[list[str]]
    """Paths to images, videos, PDFs, HTML or text files; or give `text`."""
    text: NotRequired[str]
    note: NotRequired[str]
    """What this version is, or what changed since the last, for the owner."""
    decision: NotRequired[int]
    """The decision it illustrates."""
    recipe: NotRequired[Recipe]
    """How to make it again; the latest version's when left out."""


class Word(TypedDict):
    """The owner's word on the latest version: a review, a note, or both."""

    review: NotRequired[Review]
    feedback: NotRequired[str | None]


class Filter(TypedDict):
    tag: NotRequired[str]
    review: NotRequired[Review]
    """The latest version's."""
    prefix: NotRequired[str]
    """Keys starting with this: `email/`."""


def check_key(key: str) -> str:
    key = key.strip().strip("/")
    segments = key.split("/")
    if not key or not all(SEGMENT.match(part) and not part.isdigit() for part in segments):
        raise UsageError(
            f"{key!r} is not a key: lowercase words of letters, digits, `.`, `_` and `-`,"
            " joined by `/`, none only digits — `email/anomaly-report`"
        )
    return key


def kind_of(name: str) -> str:
    suffix = Path(name).suffix.lower()
    for kind, suffixes in KINDS.items():
        if suffix in suffixes:
            return kind
    raise UsageError(
        f"{name}: not a kind of file the studio shows — "
        + "; ".join(f"{kind} ({', '.join(suffixes)})" for kind, suffixes in KINDS.items())
    )


def row(version: dict[str, Any], count: int) -> dict[str, Any]:
    """The latest version of an asset in a line, as lists show it."""
    return {
        "key": version["key"],
        "title": version["title"],
        "version": version["version"],
        "versions": count,
        "review": version["review"],
        "tags": version["tags"],
        "kinds": sorted({item["kind"] for item in version["files"]}),
    }


class Assets:
    def __init__(self, project: Project) -> None:
        self.project = project

    @property
    def directory(self) -> Path:
        """The main checkout's, whichever worktree registers: the owner reviews there."""
        return self.project.root / ".nock" / "assets"

    @property
    def large(self) -> Path:
        return self.project.local / "assets"

    @property
    def regenerations(self) -> Path:
        return self.project.local / "regenerations"

    def folder(self, key: str, version: int) -> Path:
        return self.directory / key / str(version)

    # --- reading ----------------------------------------------------------------

    def versions(self, key: str) -> list[dict[str, Any]]:
        """Every version of an asset, the earliest first; none for a key never registered."""
        place = self.directory / check_key(key)
        if not place.is_dir():
            return []
        found = [
            read_json(child / RECORD)
            for child in place.iterdir()
            if child.name.isdigit() and (child / RECORD).is_file()
        ]
        return sorted(found, key=lambda version: version["version"])

    def history(self, key: str) -> list[dict[str, Any]]:
        versions = self.versions(key)
        if not versions:
            raise NotFoundError(f"no asset {key} — `.nock/nock assets list` lists them")
        return versions

    def latest(self, key: str) -> dict[str, Any]:
        return self.history(key)[-1]

    def keys(self) -> list[str]:
        if not self.directory.is_dir():
            return []
        found = {
            str(path.parent.parent.relative_to(self.directory))
            for path in self.directory.rglob(RECORD)
            if path.parent.name.isdigit()
        }
        return sorted(found)

    def all(self) -> list[dict[str, Any]]:
        """Every asset with all its versions, the most recently registered first."""
        found = [{"key": key, "versions": self.versions(key)} for key in self.keys()]
        return sorted(
            found, key=lambda asset: asset["versions"][-1]["recorded"]["moment"], reverse=True
        )

    def matching(self, filter: Filter) -> list[dict[str, Any]]:
        found = self.all()
        if "prefix" in filter:
            found = [asset for asset in found if asset["key"].startswith(filter["prefix"])]
        if "tag" in filter:
            tag = filter["tag"].lower()
            found = [asset for asset in found if tag in asset["versions"][-1]["tags"]]
        if "review" in filter:
            found = [
                asset for asset in found if asset["versions"][-1]["review"] == filter["review"]
            ]
        return [row(asset["versions"][-1], len(asset["versions"])) for asset in found]

    def shown(self, key: str) -> list[dict[str, Any]]:
        """Every version, each file with where it is."""
        versions = self.history(key)
        for version in versions:
            for item in version["files"]:
                item["path"] = str(self.file(key, version["version"], item["name"]))
        return versions

    def file(self, key: str, version: int, name: str) -> Path:
        """Where one of a version's files is: only a file its record names."""
        record = next((item for item in self.history(key) if item["version"] == version), None)
        listed = record and next((item for item in record["files"] if item["name"] == name), None)
        if not listed:
            raise NotFoundError(f"asset {key} has no file {name} in version {version}")
        base = self.large if listed["local"] else self.directory
        return base / key / str(version) / name

    def counts(self) -> dict[str, int]:
        """The assets by their latest version's review."""
        counts = {review: 0 for review in map(str, Review)}
        for asset in self.all():
            counts[asset["versions"][-1]["review"]] += 1
        return counts

    def to_remake(self) -> list[dict[str, Any]]:
        """Latest versions the owner rejected, or left a note on without
        approving: someone should make the next version."""
        return [
            asset["versions"][-1]
            for asset in self.all()
            if asset["versions"][-1]["review"] == Review.REJECTED
            or (
                asset["versions"][-1]["review"] == Review.UNREVIEWED
                and asset["versions"][-1]["feedback"]
            )
        ]

    def tags(self) -> dict[str, int]:
        counted: dict[str, int] = {}
        for asset in self.all():
            for tag in asset["versions"][-1]["tags"]:
                counted[tag] = counted.get(tag, 0) + 1
        return dict(sorted(counted.items(), key=lambda item: (-item[1], item[0])))

    # --- registering ------------------------------------------------------------

    def add(
        self, draft: Draft, regenerated: dict[str, Any] | None = None
    ) -> tuple[dict[str, Any], str | None]:
        """Register the next version of an asset, and commit it; the record,
        and why it is not committed when it could not be."""
        key = check_key(draft["key"])
        sources = self.sources(draft)
        with self.project.lock("assets"):
            earlier = self.versions(key)
            previous = earlier[-1] if earlier else {}
            title = str(draft.get("title") or previous.get("title") or "").strip()
            if not title:
                raise UsageError(f"`title` is missing: {key} is a new asset")
            decision = draft.get("decision", previous.get("decision"))
            if decision is not None:
                Decisions(self.project).get(decision)
            given = dict(draft.get("recipe", previous.get("recipe") or {}))
            recipe = {
                field: str(value).strip() for field, value in given.items() if str(value).strip()
            }
            number = (previous.get("version") or 0) + 1
            folder = self.folder(key, number)
            files = []
            for name, source in sources:
                local = source.stat().st_size > LARGE if isinstance(source, Path) else False
                target = (self.large if local else self.directory) / key / str(number) / name
                target.parent.mkdir(parents=True, exist_ok=True)
                if isinstance(source, Path):
                    shutil.copyfile(source, target)
                else:
                    target.write_text(source)
                files.append(
                    {
                        "name": name,
                        "kind": kind_of(name),
                        "bytes": target.stat().st_size,
                        "local": local,
                    }
                )
            version: dict[str, Any] = {
                "key": key,
                "version": number,
                "title": title,
                "tags": sorted(
                    {
                        tag.strip().lower()
                        for tag in draft.get("tags", previous.get("tags", []))
                        if tag.strip()
                    }
                ),
                "files": files,
                "note": str(draft.get("note") or "").strip() or None,
                "decision": decision,
                "recipe": recipe or None,
                "regenerated": regenerated,
                "review": str(Review.UNREVIEWED),
                "feedback": None,
                "reviewed": None,
                "recorded": {
                    "moment": now(),
                    "session": self.project.current_session(),
                    "role": self.project.current_role() or "interactive",
                },
            }
            write_json(folder / RECORD, version)
            return version, self.commit([folder], f"Asset {key}, version {number}: {title}")

    def sources(self, draft: Draft) -> list[tuple[str, Path | str]]:
        """Each file's name and where it comes from (a path, or the text itself)."""
        found: list[tuple[str, Path | str]] = []
        if "text" in draft:
            if not draft["text"].strip():
                raise UsageError("`text` is empty")
            found.append((TEXT_FILE, draft["text"]))
        for given in draft.get("files", []):
            path = Path(given).expanduser()
            path = path if path.is_absolute() else Path.cwd() / path
            if not path.is_file():
                raise UsageError(f"{given}: no such file")
            kind_of(path.name)
            found.append((path.name, path))
        if not found:
            raise UsageError("nothing to show: give `files`, `text`, or both")
        names = [name for name, _ in found]
        doubled = sorted({name for name in names if names.count(name) > 1})
        if doubled:
            raise UsageError(f"two files named {', '.join(doubled)}: rename one")
        return found

    def review(self, key: str, word: Word) -> tuple[dict[str, Any], str | None]:
        """The owner's word on the latest version, committed."""
        if "review" not in word and "feedback" not in word:
            raise UsageError("nothing to say: give `review`, `feedback`, or both")
        with self.project.lock("assets"):
            version = self.latest(key)
            if "review" in word:
                version["review"] = str(word["review"])
                version["reviewed"] = {"moment": now(), "session": self.project.current_session()}
            if "feedback" in word:
                version["feedback"] = str(word["feedback"] or "").strip() or None
            folder = self.folder(version["key"], version["version"])
            write_json(folder / RECORD, version)
            said = str(word["review"]) if "review" in word else "noted"
            message = f"Asset {version['key']}, version {version['version']}, {said}"
            return version, self.commit([folder], message)

    def delete(self, key: str, version: int | None = None) -> tuple[list[int], str | None]:
        """Remove an asset, or one version of it, and commit that; git keeps it."""
        with self.project.lock("assets"):
            versions = [item["version"] for item in self.history(key)]
            doomed = versions if version is None else [version]
            if version is not None and version not in versions:
                raise NotFoundError(f"asset {key} has no version {version}")
            folders = [self.folder(key, number) for number in doomed]
            for number, folder in zip(doomed, folders, strict=True):
                shutil.rmtree(folder)
                shutil.rmtree(self.large / key / str(number), ignore_errors=True)
            self.prune(self.directory / key)
            what = "deleted" if version is None else f"version {version} deleted"
            return doomed, self.commit(folders, f"Asset {key}, {what}")

    def prune(self, place: Path) -> None:
        """Remove the empty directories a deleted key leaves."""
        while place != self.directory and place.is_dir() and not any(place.iterdir()):
            place.rmdir()
            place = place.parent

    def commit(self, folders: list[Path], message: str) -> str | None:
        paths = [str(folder.relative_to(self.project.root)) for folder in folders]
        return committed(self.project, paths, message)

    # --- regenerating -----------------------------------------------------------

    @property
    def state(self) -> Path:
        return self.regenerations / "state.json"

    def running(self) -> dict[str, Any]:
        """The regenerations under way or failed, by key; one whose process
        is gone without a word is said to have stopped."""
        if not self.state.is_file():
            return {}
        found: dict[str, Any] = read_json(self.state)
        for entry in found.values():
            if entry.get("problem") is None and not alive(entry.get("process")):
                entry["problem"] = "the regeneration stopped without a word"
        return found

    def mark(self, key: str, entry: dict[str, Any] | None) -> None:
        with self.project.lock("regenerations"):
            found = read_json(self.state) if self.state.is_file() else {}
            if entry is None:
                found.pop(key, None)
            else:
                found[key] = entry
            write_json(self.state, found)

    def recipe(self, key: str) -> tuple[dict[str, Any], dict[str, str]]:
        version = self.latest(key)
        recipe = version.get("recipe") or {}
        if not recipe:
            raise PreconditionError(
                f"asset {key} has no recipe: register a version with `recipe`"
                ' (`{"command": …}` or `{"instruction": …}`) to regenerate it'
            )
        return version, recipe

    def regenerate_in_background(self, key: str, feedback: str | None) -> dict[str, Any]:
        """Save the owner's note on the latest version, and start making the next."""
        self.recipe(key)
        if feedback is not None:
            self.review(key, {"feedback": feedback})
        version = self.latest(key)
        process = subprocess.Popen(
            [sys.executable, "-m", "nock", "assets", "regenerate", key],
            cwd=self.project.here,
            env={**os.environ, "PYTHONPATH": str(PACKAGE.parent)},
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        entry = {
            "since": now(),
            "from": version["version"],
            "process": process.pid,
            "problem": None,
        }
        self.mark(key, entry)
        return entry

    def regenerate(self, key: str) -> dict[str, Any]:
        """Make the next version from the recipe, taking the owner's note
        into account: the command alone is run here and its output
        registered; an instruction goes to an agent, which registers what it
        makes (and runs the command, if there is one, as it sees fit)."""
        version, recipe = self.recipe(key)
        key = version["key"]
        self.mark(
            key,
            {"since": now(), "from": version["version"], "process": os.getpid(), "problem": None},
        )
        work = self.regenerations / f"{slug(key)}-{version['version']}-{uuid.uuid4().hex[:8]}"
        output = work / "output"
        output.mkdir(parents=True)
        variables = {
            KEY_VARIABLE: key,
            FROM_VARIABLE: str(version["version"]),
            FEEDBACK_VARIABLE: version["feedback"] or "",
            OUTPUT_VARIABLE: str(output),
        }
        try:
            if recipe.get("instruction"):
                outcome = self.dispatch(version, recipe, output, variables)
            else:
                outcome = self.run(version, recipe["command"], output, variables)
        except Error as error:
            self.mark(key, {**self.running().get(key, {}), "problem": str(error)})
            raise
        self.mark(key, None)
        return outcome

    def run(
        self, version: dict[str, Any], command: str, output: Path, variables: dict[str, str]
    ) -> dict[str, Any]:
        result = Supervisor(
            self.project,
            ["sh", "-c", command],
            directory=self.project.here,
            environment={**os.environ, **variables},
        ).run()
        if not result.ok:
            raise Failed(
                f"the recipe's command failed (exit {result.code}); its log: {result.log}",
                {"output": result.lines[-20:]},
            )
        made = sorted(str(path) for path in output.iterdir() if path.is_file())
        if not made:
            raise Failed(f"the recipe's command wrote nothing into ${OUTPUT_VARIABLE} ({output})")
        regenerated = {"from": version["version"], "feedback": version["feedback"]}
        added, problem = self.add(Draft(key=version["key"], files=made), regenerated)
        return {
            "key": added["key"],
            "version": added["version"],
            **({"not_committed": problem} if problem else {}),
        }

    def dispatch(
        self,
        version: dict[str, Any],
        recipe: dict[str, str],
        output: Path,
        variables: dict[str, str],
    ) -> dict[str, Any]:
        key = version["key"]
        current = {
            **version,
            "files": [
                {**item, "path": str(self.file(key, version["version"], item["name"]))}
                for item in version["files"]
            ],
        }
        brief = Library(self.project.code_path("briefs"), BRIEFS).render(
            "regenerate.md",
            key=key,
            version=version,
            recipe=recipe,
            output=str(output),
            rendered=json.dumps(current, indent=2),
        )
        session = Dispatcher(self.project).launch(
            ROLE,
            brief,
            self.project.here,
            variables,
            seat=self.seat(recipe, output.parent),
        )
        latest = self.latest(key)
        refused = {"refused": session.denied} if session.denied else {}
        if latest["version"] == version["version"]:
            raise Failed(
                f"the agent ended (exit {session.exit_code}) without registering a new version"
                f" of {key}: {(session.result or '')[:400]}",
                {"session": session.id, **refused},
            )
        return {"key": key, "version": latest["version"], "session": session.id, **refused}

    def seat(self, recipe: dict[str, str], work: Path) -> Seat:
        """The regenerator's seat, and this regeneration's own: it writes in
        its work directory, and runs the recipe's command."""
        base = SEATS[ROLE]
        place = f"/{work.resolve()}/**"
        rules = [f"Read({place})", f"Edit({place})", f"Write({place})"]
        if recipe.get("command"):
            rules.append(f"Bash({recipe['command']}:*)")
        return Seat(base.tools, (*base.allowed, *rules), base.denied)


def alive(process: object) -> bool:
    if not isinstance(process, int):
        return False
    try:
        os.kill(process, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True
