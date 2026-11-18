"""Writers side by side on the store: what nock drafts is settled under the
store's lock, so another process's sweep never takes it as its own; the
owner's message sent again with its id is written once; a commit waits for
git's index lock, and one that cannot be made now is kept and made, as its
writer's, by the next settle."""

from __future__ import annotations

import json
import subprocess
import sys
import threading
import time

import pytest

from nock.errors import TimedOutError
from nock.fold import read_events
from nock.project import Project
from nock.shared import Shared
from nock.topics import Author

from .conftest import git, nock, post
from .store import submit, topics_in

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


def messages(project: Project, topic: str) -> list[dict[str, object]]:
    folder = Shared(project).topic_folder(topic) / "events"
    return [event for event in read_events(folder) if event["kind"] == "message"]


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


def test_what_nock_drafts_is_settled_under_the_stores_lock(project: Project) -> None:
    submit(project.root)
    topics = topics_in(project.root)
    with topics.drafting():
        topics.draft(Shared(project).topic_folder("orders"), {"kind": "message", "text": "Hi."})
        holder = subprocess.Popen(
            [
                sys.executable,
                "-c",
                "import sys; from pathlib import Path; from nock.project import Project\n"
                "with Project(Path(sys.argv[1])).lock('shared', patience=0.3): pass",
                str(project.root),
            ],
            stderr=subprocess.PIPE,
            text=True,
        )
        _, error = holder.communicate(timeout=10)
        assert holder.returncode != 0 and "TimedOutError" in error
        topics.settle(list(topics.drafted), Author.OWNER)
    (said,) = messages(project, "orders")
    assert said["by"]["author"] == "owner"  # type: ignore[index]


def test_the_owners_messages_stay_theirs_while_other_processes_sweep(
    project: Project, page: str
) -> None:
    refs = [submit(project.root, topic=f"area-{number}").split("/")[0] for number in range(4)]
    # An agent waits on its inbox: the owner's messages go to it, nobody is dispatched.
    (project.local / "inbox-listening.json").write_text(json.dumps({"waiter": time.time() + 600}))
    stop = threading.Event()
    sweeps: list[int] = []

    def sweeping() -> None:
        while not stop.is_set():
            sweeps.append(nock(project.root, "--version").returncode)

    sweepers = [threading.Thread(target=sweeping) for _ in range(2)]
    for sweeper in sweepers:
        sweeper.start()
    try:
        for number, ref in enumerate(refs):
            status, answer = post(page, "send", {"topic": ref, "text": f"Look at {number}."})
            assert status == 200, answer
            topics_in(project.root).write(
                ref, [{"kind": "message", "text": f"Looked at {number}."}], Author.AGENT
            )
    finally:
        stop.set()
        for sweeper in sweepers:
            sweeper.join()
    assert sweeps and not any(sweeps)
    for number, ref in enumerate(refs):
        owner, agent = messages(project, ref)
        assert (owner["text"], owner["by"]["author"]) == (f"Look at {number}.", "owner")  # type: ignore[index]
        # A sweep's writer has no role: this one is the call's own.
        assert (agent["by"]["author"], agent["by"].get("role")) == ("agent", "interactive")  # type: ignore[index, union-attr]
    assert git(project.root, "status", "--porcelain", "--", ".nock/shared") == ""


def test_the_owners_message_sent_again_with_its_id_is_written_once(
    project: Project, page: str
) -> None:
    submit(project.root)
    (project.local / "inbox-listening.json").write_text(json.dumps({"waiter": time.time() + 600}))
    body = {"topic": "orders", "text": "Why SQLite?", "id": "0a1b2c3d"}
    status, answer = post(page, "send", body)
    assert status == 200 and answer["message"]["id"] == "0a1b2c3d"
    assert post(page, "send", body)[0] == 200
    (said,) = messages(project, "orders")
    assert said["id"] == "0a1b2c3d" and said["by"]["author"] == "owner"  # type: ignore[index]
    status, answer = post(page, "send", {"topic": "orders", "text": "And?", "id": "nope"})
    assert status == 400 and "8 lowercase" in answer["error"]
    assert len(messages(project, "orders")) == 1


def test_a_commit_waits_for_another_process_holding_the_index_lock(project: Project) -> None:
    submit(project.root)
    lock = project.root / ".git" / "index.lock"
    lock.write_text("")
    threading.Timer(0.5, lock.unlink).start()
    topics_in(project.root).send("orders", "Done?", now=False)
    assert "message" in git(project.root, "log", "-1", "--format=%s")
    assert git(project.root, "status", "--porcelain", "--", ".nock/shared") == ""


def test_a_change_not_committed_now_is_committed_as_its_writers_by_the_next_settle(
    project: Project,
) -> None:
    submit(project.root)
    merging = project.root / ".git" / "MERGE_HEAD"
    merging.write_text(git(project.root, "rev-parse", "HEAD") + "\n")
    settled = topics_in(project.root).write(
        "orders", [{"kind": "message", "text": "Owner here."}], Author.OWNER
    )
    note = settled.note
    assert note and "mid-operation" in note and "next settle commits it" in note
    (said,) = messages(project, "orders")
    assert said["by"]["author"] == "owner"  # type: ignore[index]
    kept = json.loads((project.local / "uncommitted.json").read_text())
    assert kept[0]["by"]["author"] == "owner"
    # Still mid-merge: another settle leaves it kept, and finds no problem in it.
    assert not nock(project.root, "--version").stderr
    merging.unlink()
    result = nock(project.root, "--version")
    assert result.returncode == 0 and not result.stderr, result.stderr
    assert not (project.local / "uncommitted.json").exists()
    body = git(project.root, "log", "-1", "--format=%B")
    assert "message" in body and "Nock-On-Behalf: interactive" in body
    assert git(project.root, "status", "--porcelain", "--", ".nock/shared") == ""
    assert len(messages(project, "orders")) == 1


def test_a_stale_kept_change_whose_files_are_gone_is_dropped(project: Project) -> None:
    (project.local / "uncommitted.json").write_text(
        json.dumps([{"paths": ["topics/gone/events/x.json"], "by": {}, "subject": "gone"}])
    )
    submit(project.root)
    assert not (project.local / "uncommitted.json").exists()
