"""Review: what agents made for the owner, registered by key and numbered by
version, committed on the main checkout (a large file kept on the machine),
judged on the page or with `review judge`, made again from their recipe —
a command, or a dispatched agent — and listed at session start while the
owner's rejection or note waits on a new version."""

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from nock.hooks import HookRunner
from nock.project import Project
from nock.review import LARGE, Items
from nock.studio import Studio

from .conftest import git, nock

DRAFT: dict[str, Any] = {
    "key": "email/anomaly-report",
    "title": "The anomaly report email",
    "tags": ["Anomalies"],
    "text": "Three anomalies.\nOpen the queue.\n",
}


def add(directory: Path, draft: dict[str, Any] = DRAFT) -> dict[str, Any]:
    result = nock(directory, "review", "add", json.dumps(draft), "--json")
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads(result.stdout)


def judge(directory: Path, key: str, word: dict[str, Any]) -> dict[str, Any]:
    result = nock(directory, "review", "judge", key, json.dumps(word), "--json")
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads(result.stdout)


@pytest.fixture
def page(project: Project) -> Iterator[str]:
    server = Studio(project, 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server.address
    server.shutdown()
    server.server_close()


def post(address: str, route: str, body: dict[str, Any]) -> tuple[int, Any]:
    request = urllib.request.Request(
        f"{address}review/{route}",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read())


def test_an_item_registered_in_a_worktree_is_versioned_and_committed_on_the_main_checkout(
    project: Project, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    worktree = project.root.with_name("feature")
    git(project.root, "worktree", "add", "-q", "-b", "feature", str(worktree))
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "s1")
    first = add(worktree)
    assert first == {
        "key": "email/anomaly-report",
        "version": 1,
        "title": "The anomaly report email",
        "tags": ["anomalies"],
        "files": ["text.txt"],
    }
    assert not (worktree / ".nock" / "review").exists()
    folder = project.root / ".nock" / "review" / "email" / "anomaly-report" / "1"
    assert (folder / "text.txt").read_text() == DRAFT["text"]
    assert git(project.root, "log", "-1", "--format=%s") == (
        "Review item email/anomaly-report, version 1: The anomaly report email"
    )
    assert git(project.root, "status", "--porcelain") == ""

    (worktree / "shot.png").write_bytes(b"\x89PNG\r\n")
    (worktree / "page.html").write_text("<p>Three anomalies</p>")
    second = add(
        worktree,
        {"key": "email/anomaly-report", "files": ["shot.png", "page.html"], "note": "Darker."},
    )
    assert second["version"] == 2 and second["title"] == "The anomaly report email"
    assert second["tags"] == ["anomalies"] and second["files"] == ["shot.png", "page.html"]
    versions = json.loads(
        nock(project.root, "review", "show", "email/anomaly-report", "--json").stdout
    )
    assert [version["version"] for version in versions] == [1, 2]
    assert [item["kind"] for item in versions[1]["files"]] == ["image", "html"]
    assert Path(versions[1]["files"][0]["path"]).read_bytes() == b"\x89PNG\r\n"
    assert versions[1]["note"] == "Darker." and versions[1]["recorded"]["session"] == "s1"
    assert git(project.root, "status", "--porcelain") == ""


@pytest.mark.parametrize(
    ("draft", "problem"),
    [
        ({"key": "Email/Report", "title": "x", "text": "y"}, "is not a key"),
        ({"key": "email/2", "title": "x", "text": "y"}, "is not a key"),
        ({"key": "email/report", "text": "y"}, "`title` is missing"),
        ({"key": "email/report", "title": "x"}, "nothing to show"),
        ({"key": "email/report", "title": "x", "files": ["README.md.zip"]}, "no such file"),
        ({"key": "email/report", "title": "x", "files": ["README.md"]}, "not a kind of file"),
        ({"key": "email/report", "title": "x", "text": "y", "decision": 9}, "no decision 9"),
    ],
)
def test_an_item_must_have_a_key_a_title_and_something_to_show(
    project: Project, draft: dict[str, Any], problem: str
) -> None:
    if draft.get("files") == ["README.md"]:
        (project.root / "README.md").rename(project.root / "README.zip")
        draft = {**draft, "files": ["README.zip"]}
    result = nock(project.root, "review", "add", json.dumps(draft))
    assert result.returncode in (40, 44) and problem in result.stdout + result.stderr
    assert Items(project).keys() == []


def test_a_large_file_stays_on_the_machine_and_the_record_says_so(project: Project) -> None:
    video = project.root / "walkthrough.mp4"
    with video.open("wb") as file:
        file.truncate(LARGE + 1)
    added = add(
        project.root, {"key": "console/walkthrough", "title": "A walk", "files": [str(video)]}
    )
    [version] = Items(project).shown(added["key"])
    assert version["files"][0]["local"] is True
    kept = Path(version["files"][0]["path"])
    assert kept == project.local / "review" / "console" / "walkthrough" / "1" / "walkthrough.mp4"
    assert kept.stat().st_size == LARGE + 1
    committed = git(project.root, "show", "--name-only", "--format=", "HEAD").splitlines()
    assert committed == [".nock/review/console/walkthrough/1/version.json"]


def test_the_owner_judges_the_latest_version_and_lists_filter_by_it(project: Project) -> None:
    add(project.root)
    add(
        project.root,
        {"key": "console/queue", "title": "The queue", "tags": ["triage"], "text": "q"},
    )
    said = judge(
        project.root, "email/anomaly-report", {"verdict": "rejected", "feedback": "Calmer."}
    )
    assert said["verdict"] == "rejected" and said["feedback"] == "Calmer." and said["version"] == 1
    assert git(project.root, "log", "-1", "--format=%s") == (
        "Review item email/anomaly-report, version 1, rejected"
    )
    listed = json.loads(nock(project.root, "review", "list", "--json").stdout)
    assert listed["counts"] == {"unreviewed": 1, "approved": 0, "rejected": 1}
    rejected = nock(project.root, "review", "list", '{"verdict": "rejected"}', "--json")
    assert [row["key"] for row in json.loads(rejected.stdout)["items"]] == ["email/anomaly-report"]
    tagged = nock(project.root, "review", "list", '{"tag": "triage"}', "--json")
    assert [row["key"] for row in json.loads(tagged.stdout)["items"]] == ["console/queue"]
    prefixed = nock(project.root, "review", "list", '{"prefix": "email/"}', "--json")
    assert [row["key"] for row in json.loads(prefixed.stdout)["items"]] == ["email/anomaly-report"]

    second = add(project.root, {"key": "email/anomaly-report", "text": "Calmer now."})
    assert second["version"] == 2
    listed = json.loads(nock(project.root, "review", "list", "--json").stdout)
    assert listed["counts"] == {"unreviewed": 2, "approved": 0, "rejected": 0}
    nothing = nock(project.root, "review", "judge", "email/anomaly-report", "{}")
    assert nothing.returncode == 40


def test_a_project_s_fixed_tags_are_the_only_tags_an_item_takes(project: Project) -> None:
    config = project.root / ".nock" / "config.toml"
    config.write_text(config.read_text() + '\n[decisions]\ntags = ["pricing", "important"]\n')
    git(project.root, "commit", "-qam", "Fix the tags")
    outside = nock(project.root, "review", "add", json.dumps(DRAFT))
    assert outside.returncode == 40
    assert "anomalies: not in the project's tags (pricing)" in outside.stderr
    refused = nock(project.root, "review", "add", json.dumps({**DRAFT, "tags": ["important"]}))
    assert refused.returncode == 40
    assert add(project.root, {**DRAFT, "tags": ["Pricing"]})["tags"] == ["pricing"]
    assert add(project.root, {"key": DRAFT["key"], "text": "two"})["tags"] == ["pricing"]
    assert add(project.root, {"key": DRAFT["key"], "text": "three", "tags": []})["tags"] == []
    assert "Tags, the project's" in nock(project.root, "review", "add", "--help").stdout


def test_an_item_or_one_version_is_deleted_in_a_commit(project: Project) -> None:
    add(project.root)
    add(project.root, {"key": "email/anomaly-report", "text": "two"})
    result = nock(project.root, "review", "delete", "email/anomaly-report", "--version", "1")
    assert result.returncode == 0, result.stderr
    assert [item["version"] for item in Items(project).history("email/anomaly-report")] == [2]
    assert git(project.root, "log", "-1", "--format=%s") == (
        "Review item email/anomaly-report, version 1 deleted"
    )
    assert nock(project.root, "review", "delete", "email/anomaly-report").returncode == 0
    assert Items(project).keys() == []
    assert not (project.root / ".nock" / "review" / "email").exists()
    assert git(project.root, "status", "--porcelain") == ""
    assert nock(project.root, "review", "delete", "email/anomaly-report").returncode == 44


def test_the_page_serves_the_items_and_their_files_and_takes_the_owner_s_word(
    project: Project, page: str
) -> None:
    add(project.root)
    with urllib.request.urlopen(page) as response:
        shown = response.read().decode()
    assert '<a href="#review" data-tab-link="review">Review</a>' in shown
    with urllib.request.urlopen(f"{page}review") as response:
        listed = json.loads(response.read())
    assert [item["key"] for item in listed["items"]] == ["email/anomaly-report"]
    assert listed["tags"] == {"anomalies": 1} and listed["regenerating"] == {}
    address = f"{page}review/file/email/anomaly-report/1/text.txt"
    with urllib.request.urlopen(address) as response:
        assert response.read().decode() == DRAFT["text"]
        assert response.headers["Content-Type"] == "text/plain; charset=utf-8"
    ranged = urllib.request.Request(address, headers={"Range": "bytes=6-15"})
    with urllib.request.urlopen(ranged) as response:
        assert response.status == 206 and response.read() == b"anomalies."
        assert response.headers["Content-Range"] == f"bytes 6-15/{len(DRAFT['text'])}"
    for missing in ("review/file/email/anomaly-report/1/other.txt", "review/file/email/x/1/a.txt"):
        with pytest.raises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(f"{page}{missing}")
        assert error.value.code == 404

    status, error = post(page, "judge", {"key": "email/anomaly-report", "verdict": "maybe"})
    assert status == 400 and "not one of" in str(error["error"])
    status, version = post(
        page, "judge", {"key": "email/anomaly-report", "verdict": "approved", "feedback": "Good."}
    )
    assert status == 200 and version["verdict"] == "approved" and version["feedback"] == "Good."
    status, error = post(page, "regenerate", {"key": "email/anomaly-report"})
    assert status == 400 and "no recipe" in error["error"]
    status, _ = post(page, "nothing", {"key": "email/anomaly-report"})
    assert status == 404
    assert git(project.root, "status", "--porcelain") == ""


RECIPE = {
    "command": 'printf "made again: %s\\n" "$NOCK_REVIEW_FEEDBACK" > "$NOCK_REVIEW_OUTPUT/text.txt"'
}


def test_regenerating_runs_the_recipe_s_command_answering_the_note(project: Project) -> None:
    add(project.root, {**DRAFT, "recipe": RECIPE})
    judge(project.root, "email/anomaly-report", {"verdict": "rejected", "feedback": "warmer"})
    result = nock(project.root, "review", "regenerate", "email/anomaly-report", "--json")
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout) == {"key": "email/anomaly-report", "version": 2}
    latest = Items(project).latest("email/anomaly-report")
    assert latest["regenerated"] == {"from": 1, "feedback": "warmer"}
    assert latest["recipe"] == RECIPE and latest["verdict"] == "unreviewed"
    made = Items(project).file("email/anomaly-report", 2, "text.txt")
    assert made.read_text() == "made again: warmer\n"
    assert Items(project).running() == {}

    add(project.root, {"key": "email/anomaly-report", "text": "x", "recipe": {"command": "exit 3"}})
    failed = nock(project.root, "review", "regenerate", "email/anomaly-report")
    assert (
        failed.returncode == 1
        and "the recipe's command failed (exit 3)" in failed.stdout + failed.stderr
    )
    assert "failed (exit 3)" in Items(project).running()["email/anomaly-report"]["problem"]


def test_regenerating_dispatches_an_agent_with_the_instruction_note_and_version(
    project: Project, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    recipe = {"instruction": "Render the email template with the fixture."}
    add(project.root, {**DRAFT, "recipe": recipe})
    judge(project.root, "email/anomaly-report", {"feedback": "smaller headline"})
    arguments = tmp_path / "arguments.json"
    monkeypatch.setenv("FAKE_ARGUMENTS", str(arguments))
    result = nock(project.root, "review", "regenerate", "email/anomaly-report", "--json")
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout)["version"] == 2
    latest = Items(project).latest("email/anomaly-report")
    assert latest["regenerated"] == {"from": 1, "feedback": "smaller headline"}
    assert latest["note"] == "Answered the note." and latest["recorded"]["role"] == "regenerator"
    made = Items(project).file("email/anomaly-report", 2, "text.txt")
    assert made.read_text() == "made again: smaller headline\n"
    launched = json.loads(arguments.read_text())
    assert launched[launched.index("--tools") + 1] == "Read,Grep,Glob,Bash,Edit,Write"
    allowed = launched[launched.index("--allowedTools") + 1 : launched.index("--disallowedTools")]
    work = [rule for rule in allowed if rule.startswith("Write(")]
    assert len(work) == 1 and "/.nock/local/regenerations/" in work[0]
    assert "Bash(.nock/nock review add:*)" in allowed

    monkeypatch.setenv("FAKE_REGENERATE", "silent")
    failed = nock(project.root, "review", "regenerate", "email/anomaly-report")
    assert (
        failed.returncode == 1
        and "without registering a new version" in failed.stdout + failed.stderr
    )


def test_regenerate_on_the_page_makes_the_next_version_in_the_background(
    project: Project, page: str
) -> None:
    add(project.root, {**DRAFT, "recipe": RECIPE})
    status, entry = post(page, "regenerate", {"key": "email/anomaly-report", "feedback": "bolder"})
    assert status == 200 and entry["from"] == 1 and entry["problem"] is None
    assert Items(project).latest("email/anomaly-report")["feedback"] == "bolder"
    deadline = time.monotonic() + 30
    while len(Items(project).versions("email/anomaly-report")) < 2:
        assert time.monotonic() < deadline, Items(project).running()
        time.sleep(0.1)
    while Items(project).running():
        assert time.monotonic() < deadline, Items(project).running()
        time.sleep(0.1)
    made = Items(project).file("email/anomaly-report", 2, "text.txt")
    assert made.read_text() == "made again: bolder\n"


def start(project: Project, session: str) -> dict[str, Any]:
    output = HookRunner(project, {"session_id": session}).handle("SessionStart")
    assert output is not None
    return output


def test_a_session_starts_with_the_items_to_make_again_until_a_new_version_comes(
    project: Project,
) -> None:
    add(project.root)
    begun = start(project, "s1")
    assert (
        "nock: review — 1 unreviewed: look at them on `.nock/nock studio`."
        in begun["systemMessage"]
    )
    judge(project.root, "email/anomaly-report", {"verdict": "rejected", "feedback": "Calmer."})
    context = start(project, "s2")["hookSpecificOutput"]["additionalContext"]
    assert (
        "- make again `email/anomaly-report` (version 1, rejected) The anomaly report email"
        " — the owner: Calmer." in context
    )
    standing = json.loads(nock(project.root, "status", "--json").stdout)
    assert standing["to_remake"] == [
        {
            "key": "email/anomaly-report",
            "version": 1,
            "title": "The anomaly report email",
            "verdict": "rejected",
            "feedback": "Calmer.",
        }
    ]
    add(project.root, {"key": "email/anomaly-report", "text": "Calmer now."})
    assert json.loads(nock(project.root, "status", "--json").stdout)["to_remake"] == []
    primer = (project.root / ".nock" / "context.md").read_text()
    assert "`.nock/nock review add`" in primer
