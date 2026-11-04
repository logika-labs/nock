"""Decisions: what agents decided while they worked — the owner's calls among
them, tagged `important` — and what they think should be done later, one
committed file per decision in the main checkout's
`.nock/decisions/`, each with its reasoning, the alternatives that lost, the
files it governs (`touches`) and the decisions it overturns (`supersedes`).
The owner reviews them, on the page (`nock studio`) or in a session: accepts,
rejects, leaves a note, or has an agent elaborate. One that should never have
been recorded is deleted; git keeps it. `map.md` beside them says
how they bear on the work and on each other."""

from __future__ import annotations

import difflib
import fnmatch
import json
import os
import re
import subprocess
import sys
from collections import Counter
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Any, NotRequired, TypedDict

from nock.dispatch import Dispatcher
from nock.errors import Error, Failed, NotFoundError, UsageError
from nock.render import Problem
from nock.templates import Library
from nock.utils import now, read_json, write_json

if TYPE_CHECKING:
    from nock.project import Project

ROLE = "elaborator"
DECISION_VARIABLE = "NOCK_DECISION"
PACKAGE = Path(__file__).resolve().parent
BRIEFS = PACKAGE / "briefs"
# The git states in which a commit would land in the middle of someone's work.
BUSY_MARKERS = ("MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD", "rebase-merge", "rebase-apply")
MAP = "map.md"
# How the map cites a decision: `[D7]`.
CITATION = re.compile(r"\[D(\d+)\]")
# Tags every project has, unless it fixes its own vocabulary (`decisions.tags`);
# without one, agents add their own (a component, a subject).
TAGS = ("important", "technical", "product", "improvement")
# Tags nock's own workflows set, allowed beside any vocabulary: the owner's
# calls, and a logika round's decisions and instrumentation todos.
RESERVED = ("important", "logika", "instrumentation")
# What a decision says; changing any of it asks for a fresh review.
SUBSTANCE = ("title", "status", "summary", "evidence", "alternatives", "touches", "supersedes")
# How alike two titles must be, normalised, for `decide` to take the second for the first again.
SIMILAR = 0.9


class Status(StrEnum):
    DONE = "done"
    """Decided and carried out."""
    TODO = "todo"
    """Should be done, and is not yet."""


# A status earlier nocks wrote: a question for the owner, read now as a
# decision done and tagged important, its review kept.
QUESTION = "question"


class Review(StrEnum):
    UNREVIEWED = "unreviewed"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    """Done: rework it. Todo: do not do it."""


class Alternative(TypedDict):
    option: str
    why_not: str


class Draft(TypedDict):
    title: str
    """What was decided, as a statement: "The sweep requeues dead charges only";
    for the owner's call, the answer you propose and carry on with: "Refunds
    never exceed the charge"."""
    status: Status
    summary: str
    """Markdown, for someone who knows what the system does but not how it is built."""
    evidence: NotRequired[list[str]]
    """What you read, measured or found that bears on it, a line each."""
    alternatives: NotRequired[list[Alternative]]
    """What you seriously considered instead, and why not; none is a fine answer."""
    tags: NotRequired[list[str]]
    """important (only the owner can settle it: they accept or reject it), and
    the project's vocabulary (`decide --help` lists it); without one, technical,
    product, improvement and your own (a component, a subject)."""
    touches: NotRequired[list[str]]
    """The files it governs, as paths or globs: `src/pricing.py`, `migrations/**`."""
    supersedes: NotRequired[list[int]]
    """The decisions this one overturns."""


class Change(TypedDict):
    """An edit to a decision. `review`, `note` and `elaborate` are the owner's word."""

    number: int
    title: NotRequired[str]
    status: NotRequired[Status]
    summary: NotRequired[str]
    evidence: NotRequired[list[str]]
    alternatives: NotRequired[list[Alternative]]
    tags: NotRequired[list[str]]
    touches: NotRequired[list[str]]
    supersedes: NotRequired[list[int]]
    superseded_by: NotRequired[int | None]
    """The decision that overturns this one; null: it stands again."""
    review: NotRequired[Review]
    note: NotRequired[str | None]
    elaborate: NotRequired[bool]
    """Have an agent say more — answering the note, if there is one."""


class Batch(TypedDict):
    """Several changes at once, committed once: the edits, then the deletions."""

    edit: NotRequired[list[Change]]
    delete: NotRequired[list[int]]


class Filter(TypedDict):
    status: NotRequired[Status]
    review: NotRequired[Review]
    tag: NotRequired[str]
    path: NotRequired[str]
    """Only the decisions governing this file."""


def governs(pattern: str, path: str) -> bool:
    """Whether a `touches` entry covers a repository path: a glob, a file, or a directory."""
    directory = pattern.rstrip("/")
    return (
        fnmatch.fnmatchcase(path, pattern) or path == directory or path.startswith(f"{directory}/")
    )


def live(decision: dict[str, Any]) -> bool:
    """A decision that stands: not overturned by a later one."""
    return not decision.get("superseded_by")


def normalised(title: str) -> str:
    """A title as the duplicate guard compares it: lowercase words, nothing else."""
    return " ".join(re.sub(r"[\W_]+", " ", title.lower()).split())


def alike(left: str, right: str) -> bool:
    """Whether two titles say the same thing, near enough."""
    left, right = normalised(left), normalised(right)
    return left == right or difflib.SequenceMatcher(None, left, right).ratio() >= SIMILAR


def upgraded(decision: dict[str, Any]) -> dict[str, Any]:
    """A decision as this nock reads it: an earlier nock's question is a
    decision done and tagged important, reviewed as it was; saving it
    rewrites the file so."""
    if decision.get("status") == QUESTION:
        decision["status"] = str(Status.DONE)
        decision["tags"] = sorted({*decision.get("tags", []), "important"})
    return decision


def row(decision: dict[str, Any]) -> dict[str, Any]:
    """A decision in a line, as lists show it."""
    keys = ("number", "title", "status", "review", "tags")
    return {key: decision[key] for key in keys}


class Decisions:
    def __init__(self, project: Project) -> None:
        self.project = project

    @property
    def directory(self) -> Path:
        """The main checkout's, whichever worktree decides: the owner reviews there."""
        return self.project.root / ".nock" / "decisions"

    def path(self, number: int) -> Path:
        return self.directory / f"{number:04d}.json"

    def all(self) -> list[dict[str, Any]]:
        if not self.directory.is_dir():
            return []
        return [upgraded(read_json(path)) for path in sorted(self.directory.glob("[0-9]*.json"))]

    def get(self, number: int) -> dict[str, Any]:
        path = self.path(number)
        if not path.is_file():
            raise NotFoundError(f"no decision {number} — `.nock/nock decisions list` lists them")
        return upgraded(read_json(path))

    def save(self, decision: dict[str, Any]) -> None:
        decision["updated"] = now()
        write_json(self.path(decision["number"]), decision)

    def vocabulary(self) -> list[str]:
        """The project's fixed tags (`decisions.tags`), nock's own with them;
        empty when the project fixes none and any tag goes."""
        fixed = self.project.configuration.get("decisions.tags") or []
        if not fixed:
            return []
        return list(dict.fromkeys([*(str(tag).strip().lower() for tag in fixed), *RESERVED]))

    # --- deciding ---------------------------------------------------------------

    def decide(self, draft: Draft, force: bool = False) -> tuple[dict[str, Any], str | None]:
        """Record the decision under the next number, and commit it; the record,
        and why it is not committed when it could not be. A title a standing
        decision already has, or nearly, is refused unless forced."""
        with self.project.lock("decisions"):
            every = self.all()
            if not force:
                self.refuse_duplicate(draft, every)
            number = max((decision["number"] for decision in every), default=0) + 1
            decision: dict[str, Any] = {
                "number": number,
                "title": "",
                "status": str(Status.DONE),
                "review": str(Review.UNREVIEWED),
                "summary": "",
                "evidence": [],
                "alternatives": [],
                "tags": [],
                "touches": [],
                "supersedes": [],
                "superseded_by": None,
                "note": None,
                "reviewed": None,
                "elaborating": False,
                "recorded": {
                    "moment": now(),
                    "session": self.project.current_session(),
                    "role": self.project.current_role() or "interactive",
                },
            }
            self.apply(decision, dict(draft))
            self.save(decision)
            overturned = self.overturn(decision)
            message = f"Decision {number}: {decision['title']}"
            return decision, self.commit([number, *overturned], message)

    def refuse_duplicate(self, draft: Draft, every: list[dict[str, Any]]) -> None:
        """Fail when a standing decision, other than one the draft supersedes,
        has the draft's title or nearly."""
        overturned = set(draft.get("supersedes", []))
        for decision in every:
            if (
                live(decision)
                and decision["number"] not in overturned
                and alike(decision["title"], str(draft.get("title", "")))
            ):
                raise Failed(
                    f"decision {decision['number']} already says this: {decision['title']} — "
                    "edit it (`.nock/nock decisions edit`) rather than record it again; "
                    "`--force` only if this is really another decision",
                    {"duplicate_of": decision["number"], "title": decision["title"]},
                )

    def delete(self, number: int) -> str | None:
        """Remove a decision that should not have been recorded, and commit
        that; git keeps it."""
        with self.project.lock("decisions"):
            title = self.get(number)["title"]
            touched = self.remove(number)
            return self.commit(touched, f"Decision {number}, deleted: {title}")

    def remove(self, number: int) -> list[int]:
        """Remove a decision's file: what it superseded stands again, and what
        superseded it no longer names it; the decisions touched, uncommitted."""
        self.get(number)
        touched = [number]
        for other in self.all():
            if other["number"] == number:
                continue
            if other.get("superseded_by") == number:
                other["superseded_by"] = None
            elif number in other["supersedes"]:
                other["supersedes"] = [n for n in other["supersedes"] if n != number]
            else:
                continue
            self.save(other)
            touched.append(other["number"])
        self.path(number).unlink()
        return touched

    def batch(self, batch: Batch) -> tuple[list[dict[str, Any]], list[int], str | None]:
        """Apply the edits, then the deletions, and commit them once: the
        decisions edited, those deleted, and why it is not committed when it
        could not be. A refused change leaves every file as it was."""
        changes, deletions = batch.get("edit", []), batch.get("delete", [])
        if not changes and not deletions:
            raise UsageError("nothing to do: give `edit`, `delete` or both")
        with self.project.lock("decisions"):
            before = {path: path.read_bytes() for path in self.directory.glob("[0-9]*.json")}
            try:
                touched, edited = [], []
                for change in changes:
                    decision, numbers, _ = self.revise(change)
                    edited.append(decision)
                    touched += numbers
                for number in deletions:
                    touched += self.remove(number)
            except Error:
                for path in self.directory.glob("[0-9]*.json"):
                    if path not in before:
                        path.unlink()
                for path, content in before.items():
                    path.write_bytes(content)
                raise
            numbers = sorted(set(touched))
            message = f"Decisions {', '.join(map(str, numbers))}: " + ", ".join(
                part
                for part in (
                    f"{len(changes)} edited" if changes else "",
                    f"{len(deletions)} deleted" if deletions else "",
                )
                if part
            )
            return edited, sorted(set(deletions)), self.commit(numbers, message)

    def edit(self, change: Change) -> tuple[dict[str, Any], str | None]:
        """Change a decision, and commit it. A change to what it says asks for
        a fresh review (the owner's note stays); `review` and `note` record the
        owner's word."""
        with self.project.lock("decisions"):
            decision, touched, message = self.revise(change)
            return decision, self.commit(touched, message)

    def revise(self, change: Change) -> tuple[dict[str, Any], list[int], str]:
        """Change a decision, uncommitted: it, the decisions touched, and the commit message."""
        decision = self.get(change["number"])
        fields = {key: value for key, value in change.items() if key != "number"}
        substance = {key: fields[key] for key in SUBSTANCE if key in fields}
        changed = any(decision.get(key) != value for key, value in substance.items())
        self.apply(decision, fields)
        if changed:
            decision["elaborating"] = False
        if "review" in fields:
            decision["review"] = str(fields["review"])
            decision["reviewed"] = {
                "moment": now(),
                "session": self.project.current_session(),
            }
        elif changed:
            decision["review"] = str(Review.UNREVIEWED)
            decision["reviewed"] = None
        if "note" in fields:
            decision["note"] = str(fields["note"] or "").strip() or None
        if fields.get("elaborate"):
            decision["elaborating"] = True
        relinked = (
            self.relink(decision, change["superseded_by"]) if "superseded_by" in change else []
        )
        self.save(decision)
        overturned = self.overturn(decision)
        message = (
            f"Decision {decision['number']}, {self.said(fields, changed)}: {decision['title']}"
        )
        return decision, [decision["number"], *relinked, *overturned], message

    def relink(self, decision: dict[str, Any], successor: int | None) -> list[int]:
        """Set what supersedes a decision (None: nothing, it stands again),
        keeping the superseding decision's `supersedes` in step; the others touched."""
        number = decision["number"]
        if successor == number:
            raise UsageError(f"decision {number} cannot supersede itself")
        touched = []
        previous = decision.get("superseded_by")
        if previous and previous != successor and self.path(previous).is_file():
            earlier = self.get(previous)
            earlier["supersedes"] = [n for n in earlier["supersedes"] if n != number]
            self.save(earlier)
            touched.append(previous)
        if successor is not None and successor != previous:
            later = self.get(successor)
            later["supersedes"] = sorted({*later["supersedes"], number})
            self.save(later)
            touched.append(successor)
        decision["superseded_by"] = successor
        return touched

    def said(self, fields: dict[str, Any], changed: bool) -> str:
        """What an edit did, in a word or two, for its commit message."""
        if "review" in fields:
            return str(fields["review"])
        if fields.get("elaborate"):
            return "to elaborate"
        if "note" in fields and not changed:
            return "noted"
        return "edited"

    def apply(self, decision: dict[str, Any], fields: dict[str, Any]) -> None:
        """Fold a draft's or a change's fields into the decision, checked."""
        for key in ("title", "summary"):
            if key in fields:
                if not str(fields[key]).strip():
                    raise UsageError(f"`{key}` is empty")
                decision[key] = str(fields[key]).strip()
        if "status" in fields:
            decision["status"] = str(fields["status"])
        for key in ("evidence", "touches"):
            if key in fields:
                decision[key] = [item.strip() for item in fields[key] if item.strip()]
        if "alternatives" in fields:
            decision["alternatives"] = [dict(item) for item in fields["alternatives"]]
        if "tags" in fields:
            tags = sorted({tag.strip().lower() for tag in fields["tags"] if tag.strip()})
            vocabulary = self.vocabulary()
            outside = [tag for tag in tags if vocabulary and tag not in vocabulary]
            if outside:
                raise UsageError(
                    f"{', '.join(outside)}: not in the project's tags ({', '.join(vocabulary)}); "
                    "pick from them — the owner changes them in .nock/config.toml, `decisions.tags`"
                )
            decision["tags"] = tags
        if "supersedes" in fields:
            decision["supersedes"] = self.overturnable(fields["supersedes"], decision)

    def overturnable(self, numbers: list[int], decision: dict[str, Any]) -> list[int]:
        """Only a decision that stands can be superseded, and not by itself;
        one it already named that has since been deleted is dropped."""
        kept = []
        for earlier in numbers:
            if earlier == decision["number"]:
                raise UsageError(f"decision {earlier} cannot supersede itself")
            if earlier in decision.get("supersedes", []) and not self.path(earlier).is_file():
                continue
            kept.append(earlier)
            overturned = self.get(earlier)
            if overturned.get("superseded_by") not in (None, decision["number"]):
                raise UsageError(
                    f"decision {earlier} is already superseded by {overturned['superseded_by']}"
                )
        return sorted(set(kept))

    def overturn(self, decision: dict[str, Any]) -> list[int]:
        """Mark what a decision supersedes as superseded by it, and what it no
        longer supersedes as standing again."""
        marked = []
        for other in self.all():
            names = other["number"] in decision["supersedes"]
            if names and other.get("superseded_by") != decision["number"]:
                other["superseded_by"] = decision["number"]
            elif not names and other.get("superseded_by") == decision["number"]:
                other["superseded_by"] = None
            else:
                continue
            self.save(other)
            marked.append(other["number"])
        return marked

    def commit(self, numbers: list[int], message: str) -> str | None:
        """Commit these decisions' files in the main checkout — unless that would
        land in the middle of a merge or rebase there; then say so, and leave
        them written."""
        git = self.project.git
        git_directory = Path(git("rev-parse", "--absolute-git-dir"))
        busy = next((marker for marker in BUSY_MARKERS if (git_directory / marker).exists()), None)
        relative = [str(self.path(number).relative_to(self.project.root)) for number in numbers]
        if busy is not None:
            return f"not committed: the main checkout is mid-operation ({busy}); {', '.join(relative)} written"
        git("add", "--", *relative)
        git("commit", "--quiet", "--no-verify", "--only", "-m", message, "--", *relative)
        return None

    # --- reading ----------------------------------------------------------------

    def matching(self, filter: Filter) -> list[dict[str, Any]]:
        found = [decision for decision in self.all() if live(decision)]
        if "status" in filter:
            found = [decision for decision in found if decision["status"] == filter["status"]]
        if "review" in filter:
            found = [decision for decision in found if decision["review"] == filter["review"]]
        if "tag" in filter:
            tag = filter["tag"].lower()
            found = [decision for decision in found if tag in decision["tags"]]
        if "path" in filter:
            path = filter["path"]
            found = [
                decision
                for decision in found
                if any(governs(pattern, path) for pattern in decision["touches"])
            ]
        return found

    def counts(self) -> dict[str, dict[str, int]]:
        """The standing decisions, by status and review."""
        counts = {status: {review: 0 for review in map(str, Review)} for status in map(str, Status)}
        for decision in self.all():
            if live(decision):
                counts[decision["status"]][decision["review"]] += 1
        return counts

    def to_rework(self) -> list[dict[str, Any]]:
        """Done, and rejected: the owner wants it redone."""
        return self.matching({"status": Status.DONE, "review": Review.REJECTED})

    def important(self) -> list[dict[str, Any]]:
        """Tagged important and not yet reviewed: the owner's calls, which an
        agent proposed an answer to and carried on with."""
        return self.matching({"tag": "important", "review": Review.UNREVIEWED})

    def tags(self) -> dict[str, int]:
        """Every tag in use, the most used first; the fixed ones (the project's
        vocabulary, or nock's) always."""
        counted: Counter[str] = Counter({tag: 0 for tag in self.vocabulary() or TAGS})
        for decision in self.all():
            if live(decision):
                counted.update(decision["tags"])
        return dict(counted.most_common())

    # --- what the decisions govern ----------------------------------------------

    def reminders_for(self, session: str, path: str) -> list[dict[str, Any]]:
        """The standing decisions governing `path` this session has not been
        shown yet — the rejected first; showing them is recorded."""
        shown = {
            row["decision"]
            for row in self.project.store.rows(
                "SELECT decision FROM shown WHERE session = ?", (session,)
            )
        }
        found = [
            decision
            for decision in self.matching({"path": path})
            if decision["number"] not in shown
        ]
        for decision in found:
            self.project.store.insert("shown", {"session": session, "decision": decision["number"]})
        return sorted(found, key=lambda decision: decision["review"] != Review.REJECTED)

    def news_for(self, session: str) -> list[dict[str, Any]]:
        """The owner's reviews and notes on this session's decisions that it
        has not been told yet; telling it is recorded."""
        heard = {
            (row["decision"], row["updated"])
            for row in self.project.store.rows(
                "SELECT decision, updated FROM heard WHERE session = ?", (session,)
            )
        }
        news = [
            decision
            for decision in self.all()
            if decision["recorded"].get("session") == session
            and (decision["reviewed"] or decision["note"])
            and (decision["number"], decision["updated"]) not in heard
        ]
        for decision in news:
            self.project.store.insert(
                "heard",
                {
                    "session": session,
                    "decision": decision["number"],
                    "updated": decision["updated"],
                },
            )
        return news

    @property
    def map(self) -> Path:
        return self.directory / MAP

    def citation_problems(self) -> list[Problem]:
        """Every map citation of a decision that is missing or superseded."""
        if not self.map.is_file():
            return []
        decisions = {decision["number"]: decision for decision in self.all()}
        place = str(self.map.relative_to(self.project.root))
        problems = []
        for line, text in enumerate(self.map.read_text().splitlines(), start=1):
            for match in CITATION.finditer(text):
                number = int(match.group(1))
                cited = decisions.get(number)
                if cited is None:
                    problems.append(Problem(f"[D{number}] is no decision", place, line))
                elif cited.get("superseded_by"):
                    problems.append(
                        Problem(
                            f"[D{number}] is superseded by [D{cited['superseded_by']}]", place, line
                        )
                    )
        return problems

    def files(self) -> list[str]:
        """The working tree's files, tracked or not, but not ignored ones."""
        here = self.project.here
        listed = self.project.git("ls-files", "--cached", "--others", "--exclude-standard")
        return [file for file in listed.splitlines() if (here / file).exists()]

    def unmatched(self, decision: dict[str, Any], files: list[str] | None = None) -> list[str]:
        """The decision's `touches` entries that match no file."""
        files = self.files() if files is None else files
        return [
            pattern
            for pattern in decision["touches"]
            if not any(governs(pattern, file) for file in files)
        ]

    def stale(self) -> list[tuple[dict[str, Any], list[str]]]:
        """The standing done decisions governing files that are gone, and which."""
        files = self.files()
        found = [
            (decision, self.unmatched(decision, files))
            for decision in self.all()
            if live(decision) and decision["status"] == Status.DONE
        ]
        return [(decision, patterns) for decision, patterns in found if patterns]

    # --- elaborating ------------------------------------------------------------

    def elaborate(self, number: int) -> dict[str, Any]:
        """A headless agent says more about the decision, as the owner asked."""
        decision = self.get(number)
        brief = Library(self.project.code_path("briefs"), BRIEFS).render(
            "elaborate.md", decision=decision, rendered=json.dumps(decision, indent=2)
        )
        session = Dispatcher(self.project).launch(
            ROLE, brief, self.project.root, {DECISION_VARIABLE: str(number)}
        )
        decision = self.get(number)
        if decision["elaborating"]:
            decision["elaborating"] = False
            self.save(decision)
            self.commit([number], f"Decision {number}, not elaborated: {decision['title']}")
            return {
                "elaborated": False,
                "session": session.id,
                "problem": f"the session ended (exit {session.exit_code}) without editing the decision: {(session.result or '')[:400]}",
                **({"refused": session.denied} if session.denied else {}),
            }
        return {
            "elaborated": True,
            "session": session.id,
            **({"refused": session.denied} if session.denied else {}),
        }

    def elaborate_in_background(self, number: int) -> None:
        subprocess.Popen(
            [sys.executable, "-m", "nock", "decisions", "elaborate", str(number)],
            cwd=self.project.root,
            env={**os.environ, "PYTHONPATH": str(PACKAGE.parent)},
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
