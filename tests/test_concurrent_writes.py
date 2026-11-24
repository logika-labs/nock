"""Writers side by side: a lock another process holds is waited for with
patience; a commit in `.nock/shared/` waits for git's index lock, and is not
made while the main checkout is mid-merge."""

from __future__ import annotations

import subprocess
import sys
import threading
import time

import pytest

from nock.errors import TimedOutError
from nock.project import Project
from nock.shared import MEMORY, SHARED, commit

from .conftest import git

HOLDER = """
import sys
from pathlib import Path
from nock.project import Project
with Project(Path(sys.argv[1])).lock(sys.argv[2]):
    print("held", flush=True)
    sys.stdin.read()
"""


def held(project: Project, name: str) -> subprocess.Popen[str]:
    """Another process holding one of the project's locks until its stdin closes."""
    holder = subprocess.Popen(
        [sys.executable, "-c", HOLDER, str(project.root), name],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )
    assert holder.stdout is not None and holder.stdout.readline().strip() == "held"
    return holder


def test_a_lock_another_process_holds_is_waited_for_with_patience_then_refused(
    project: Project,
) -> None:
    holder = held(project, "shared")
    try:
        started = time.monotonic()
        with (
            pytest.raises(TimedOutError, match="nothing was written"),
            project.lock("shared", patience=0.2),
        ):
            pass
        assert time.monotonic() - started < 5
    finally:
        holder.communicate("")
    with project.lock("shared", patience=0.2), project.lock("shared"):
        pass  # free again, and taken again by the thread that holds it


def test_a_commit_waits_for_another_process_holding_the_index_lock(project: Project) -> None:
    memory = project.root / SHARED / MEMORY
    memory.write_text(memory.read_text() + "- tests: tests/, real git\n")
    lock = project.root / ".git" / "index.lock"
    lock.write_text("")
    threading.Timer(0.5, lock.unlink).start()
    made = commit(project, [str(SHARED / MEMORY)], "nock: the memory")
    assert made == git(project.root, "rev-parse", "HEAD")
    assert git(project.root, "log", "-1", "--format=%s") == "nock: the memory"
    assert git(project.root, "status", "--porcelain", "--", ".nock/shared") == ""


def test_nothing_is_committed_mid_merge_or_when_nothing_changed(project: Project) -> None:
    head = git(project.root, "rev-parse", "HEAD")
    assert commit(project, [str(SHARED / MEMORY)], "nock: the memory") is None
    memory = project.root / SHARED / MEMORY
    memory.write_text(memory.read_text() + "- tests: tests/\n")
    merging = project.root / ".git" / "MERGE_HEAD"
    merging.write_text(head + "\n")
    assert commit(project, [str(SHARED / MEMORY)], "nock: the memory") is None
    merging.unlink()
    assert commit(project, [str(SHARED / MEMORY)], "nock: the memory") is not None
    assert git(project.root, "rev-parse", "HEAD~1") == head
