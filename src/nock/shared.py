"""`.nock/shared/`: what every clone and worktree of the project shares,
committed in the main checkout whichever worktree writes it — the memory,
the team's settings and the rounds' records — and the one way nock commits
there."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from nock.git import Git
from nock.render import Problem

if TYPE_CHECKING:
    from nock.project import Project

SHARED = Path(".nock") / "shared"
# What nock has learned about the project and its owner: short lines by
# subject, each pointing to the files with the detail; reflection keeps it.
MEMORY = "memory.md"
# The memory's size at most, in characters: every session reads it.
MEMORY_LIMIT = 8000
SETTINGS = "settings.toml"
# The git states in which a commit would land in the middle of someone's work.
BUSY_MARKERS = ("MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD", "rebase-merge", "rebase-apply")


def memory_path(project: Project) -> Path:
    return project.root / SHARED / MEMORY


def memory_problems(project: Project) -> list[Problem]:
    """The `nock-memory` check: the memory small enough to read every time."""
    path = memory_path(project)
    text = path.read_text() if path.is_file() else ""
    if len(text) <= MEMORY_LIMIT:
        return []
    return [
        Problem(
            f"the memory is {len(text):,} characters; at most {MEMORY_LIMIT:,}: prune"
            " and merge lines, the detail stays in the files they point to",
            str(SHARED / MEMORY),
        )
    ]


def commit(project: Project, paths: list[str], message: str) -> str | None:
    """Commit these paths (relative to the main checkout) alone there, under
    the `shared` lock; nothing when nothing changed, or when the main checkout
    is mid-merge or mid-rebase. The commit, or None."""
    with project.lock("shared"):
        git = Git(project.root)
        directory = Path(git("rev-parse", "--absolute-git-dir"))
        if any((directory / marker).exists() for marker in BUSY_MARKERS):
            return None
        tracked = set(git("ls-files", "-z", "--", *paths).split("\0"))
        wanted = [path for path in paths if (project.root / path).exists() or path in tracked]
        if not wanted:
            return None
        git.changing("add", "--all", "--", *wanted)
        if not git("diff", "--cached", "--name-only", "--", *wanted).strip():
            return None
        git.changing("commit", "--quiet", "--no-verify", "--only", "-m", message, "--", *wanted)
        return git.head()
