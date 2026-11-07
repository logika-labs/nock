"""Topics and items: agents open a topic per piece of work and submit bare
items into it — decisions, project files, derived files — committed on the
main checkout whichever worktree writes; the owner gives verdicts and talks
in the threads, on the page or with `/nock-triage`; agents hear of it, find
what awaits them in `topics list`, and an earlier nock's decisions and review
items move into topics once."""

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
from nock.migration import Migration
from nock.project import Project
from nock.studio import PAGES, TABS, Studio
from nock.topics import Author, Topics

from .conftest import git, nock

TOPIC = {"name": "orders", "description": "Where orders are kept, for the checkout work."}
DECISION: dict[str, Any] = {
    "title": "Orders live in SQLite",
    "decision": {
        "answer": "One file is enough for **orders** at today's load.",
        "alternatives": [{"option": "Postgres", "why_not": "a server to run, for load we lack"}],
    },
}


def run(directory: Path, *arguments: str) -> Any:
    result = nock(directory, *arguments, "--json")
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads(result.stdout) if result.stdout.strip() else None


def open_topic(directory: Path, topic: dict[str, str] = TOPIC) -> str:
    return run(directory, "topics", "create", json.dumps(topic))["name"]


def submit(directory: Path, item: dict[str, Any] = DECISION, topic: str = "orders") -> str:
    main = Path(git(directory, "rev-parse", "--path-format=absolute", "--git-common-dir")).parent
    if not (main / ".nock" / "topics" / topic).is_dir():
        open_topic(directory, {**TOPIC, "name": topic})
    return run(directory, "items", "create", topic, json.dumps(item))["ref"]


def judge(directory: Path, ref: str, verdict: str, comment: str = "") -> Any:
    word = {"verdict": verdict, **({"comment": comment} if comment else {})}
    return run(directory, "items", "judge", ref, json.dumps(word))


def start(project: Project, session: str) -> dict[str, Any]:
    output = HookRunner(project, {"session_id": session}).handle("SessionStart")
    assert output is not None
    return output


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
        f"{address}topics/{route}",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read())


def test_an_item_submitted_in_a_worktree_is_committed_on_the_main_checkout(
    project: Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    worktree = project.root.with_name("feature")
    git(project.root, "worktree", "add", "-q", "-b", "feature", str(worktree))
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "s1")
    ref = submit(worktree)
    assert ref == "orders/orders-live-in-sqlite"
    assert not (worktree / ".nock" / "topics" / "orders").exists()
    folder = project.root / ".nock" / "topics" / "orders" / "orders-live-in-sqlite"
    decision = json.loads((folder / "1" / "decision.json").read_text())
    assert decision["status"] == "done" and decision["alternatives"][0]["option"] == "Postgres"
    assert git(project.root, "log", "-1", "--format=%s") == (
        "Item orders/orders-live-in-sqlite: Orders live in SQLite"
    )
    assert git(project.root, "status", "--porcelain") == ""
    shown = run(project.root, "items", "show", ref)
    assert shown["verdict"] == "open" and shown["versions"][0]["session"] == "s1"
    again = submit(worktree)
    assert again == "orders/orders-live-in-sqlite-2"


def test_an_item_holds_something_and_a_project_file_is_in_the_repository(
    project: Project, tmp_path: Path
) -> None:
    open_topic(project.root)
    empty = nock(project.root, "items", "create", "orders", '{"title": "Nothing"}')
    assert empty.returncode == 40 and "give `decision`, `files`, `derived`" in empty.stderr
    outside = tmp_path / "shot.png"
    outside.write_bytes(b"\x89PNG\r\n")
    wrong = nock(
        project.root,
        "items",
        "create",
        "orders",
        json.dumps({"title": "A", "files": [str(outside)]}),
    )
    assert wrong.returncode == 40 and "goes in `derived`" in wrong.stderr
    nowhere = nock(project.root, "items", "create", "nowhere", json.dumps(DECISION))
    assert nowhere.returncode == 44 and "no topic 'nowhere'" in nowhere.stderr


def test_a_new_version_copies_project_files_as_they_are_now_and_reopens_the_item(
    project: Project, tmp_path: Path
) -> None:
    shot = tmp_path / "email.png"
    shot.write_bytes(b"\x89PNG one")
    item = {
        "title": "The lapsed payment email",
        "files": ["README.md"],
        "derived": [
            {
                "path": str(shot),
                "from": ["README.md"],
                "when": "the payment lapsed",
                "recipe": {"command": "make email"},
            }
        ],
    }
    ref = submit(project.root, item)
    judge(project.root, ref, "rejected", "Bolder subject line.")
    refused = nock(project.root, "items", "update", ref, '{"title": "Bolder"}')
    assert refused.returncode == 49 and "--version" in refused.stderr
    (project.root / "README.md").write_text("# demo, changed\n")
    git(project.root, "commit", "-qam", "Change the README")
    updated = run(project.root, "items", "update", ref, "--version", "{}")
    assert updated == {"ref": ref, "verdict": "open", "versions": 2}
    shown = run(project.root, "items", "show", ref)
    first, second = (version["files"] for version in shown["versions"])
    assert Path(first[0]["where"]).read_text() == "# demo\n"
    assert Path(second[0]["where"]).read_text() == "# demo, changed\n"
    assert second[1]["name"] == "email.png" and second[1]["when"] == "the payment lapsed"
    assert Path(second[1]["where"]).read_bytes() == b"\x89PNG one"
    assert shown["thread"][0] == {
        **shown["thread"][0],
        "author": "owner",
        "text": "Bolder subject line.",
        "verdict": "rejected",
    }
    run(project.root, "items", "update", ref, '{"title": "The lapsed payment email, bolder"}')
    assert run(project.root, "items", "show", ref)["versions"][-1]["version"] == 2


def test_only_an_open_item_the_owner_has_not_written_on_is_deleted(project: Project) -> None:
    ref = submit(project.root)
    keep = submit(project.root, {**DECISION, "title": "Orders are never deleted"})
    run(project.root, "items", "update", keep, "--reply", "Why not archive them?")
    judge(project.root, keep, "accepted")
    refused = nock(project.root, "items", "delete", keep)
    assert refused.returncode == 43 and "the owner's word" in refused.stderr
    run(project.root, "items", "delete", ref)
    assert not (project.root / ".nock" / "topics" / "orders" / "orders-live-in-sqlite").exists()
    not_empty = nock(project.root, "topics", "delete", "orders")
    assert not_empty.returncode == 49 and "holds items" in not_empty.stderr
    open_topic(project.root, {"name": "spare", "description": "Nothing yet."})
    run(project.root, "topics", "delete", "spare")
    assert git(project.root, "status", "--porcelain") == ""


def test_an_item_moves_to_another_topic_whatever_its_verdict_and_its_old_refs_resolve(
    project: Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    ref = submit(project.root, {**DECISION, "derived": [{"text": "big", "name": "big.txt"}]})
    item = project.root / ".nock" / "topics" / "orders" / "orders-live-in-sqlite" / "item.json"
    record = json.loads(item.read_text())
    item.write_text(json.dumps({**record, "aliases": ["7"]}))
    git(project.root, "commit", "-qam", "An earlier decision's number")
    run(project.root, "items", "update", ref, "--reply", "Why not Postgres?")
    judge(project.root, ref, "accepted")
    open_topic(project.root, {"name": "storage", "description": "Where data is kept."})
    taken = submit(project.root, DECISION, topic="storage")
    assert taken == "storage/orders-live-in-sqlite"
    (project.root / ".nock" / "topics" / "map.md").write_text(f"- [{ref}] and [D7] hold.\n")
    git(project.root, "add", "-A")
    git(project.root, "commit", "-qm", "The map")
    topics = Topics(project)
    monkeypatch.setattr("nock.topics.LARGE", 2)
    topics.update_item(ref, None, version={"derived": [{"text": "bigger", "name": "big.txt"}]})
    large = project.local / "topics" / "orders" / "orders-live-in-sqlite" / "2" / "big.txt"
    assert large.is_file()
    moved = run(project.root, "items", "update", ref, json.dumps({"topic": "storage"}))
    assert moved["ref"] == "storage/orders-live-in-sqlite-2"
    record = topics.item(moved["ref"])
    assert record["verdict"] == "open" and record["thread"][0]["text"] == "Why not Postgres?"
    assert [version["version"] for version in record["versions"]] == [1, 2]
    assert record["aliases"] == ["7", ref]
    assert topics.item("7")["ref"] == topics.item("D7")["ref"] == topics.item(ref)["ref"]
    assert topics.item("storage/7")["ref"] == moved["ref"]
    assert (
        project.local / "topics" / "storage" / "orders-live-in-sqlite-2" / "2" / "big.txt"
    ).is_file()
    assert topics.file("storage", "orders-live-in-sqlite-2", 1, "big.txt").read_text() == "big"
    assert topics.citation_problems() == []
    assert not (project.root / ".nock" / "topics" / "orders" / "orders-live-in-sqlite").exists()
    assert git(project.root, "status", "--porcelain") == ""
    judge(project.root, moved["ref"], "accepted")
    again = run(project.root, "items", "update", moved["ref"], json.dumps({"topic": "orders"}))
    assert again["ref"] == "orders/orders-live-in-sqlite-2" and again["verdict"] == "accepted"
    assert topics.item(ref)["aliases"] == ["7", ref, "storage/orders-live-in-sqlite-2"]
    refused = nock(project.root, "items", "update", ref, json.dumps({"topic": "nowhere"}))
    assert refused.returncode != 0 and "no topic 'nowhere'" in refused.stderr


def test_list_summarises_what_is_open_and_what_awaits_an_agent_unless_full(
    project: Project, page: str
) -> None:
    for number in range(20):
        submit(project.root, {**DECISION, "title": f"Decision number {number}"})
    asked = submit(
        project.root,
        {"title": "Pricing is per seat", "decision": {"answer": "Per seat, monthly."}},
        topic="pricing",
    )
    post(page, "reply", {"ref": asked, "text": "Why not per project?"})
    rejected = submit(project.root, {**DECISION, "title": "Refunds are manual"}, topic="pricing")
    post(page, "judge", {"ref": rejected, "verdict": "rejected"})
    listed = run(project.root, "items", "list")
    assert listed["summary"] == {
        "open": {"orders": 20, "pricing": 1},
        "awaiting_you": {"owner_wrote_last": [asked], "rejected": [rejected]},
    }
    assert len(listed["rows"]) == 15 and "--full" in listed["more"]
    full = run(project.root, "items", "list", "--full")
    assert "summary" not in full and len(full["rows"]) == 22
    topics = run(project.root, "topics", "list", "--full")["rows"]
    assert [row["name"] for row in topics] == ["pricing", "orders"]
    assert topics[0]["open"] == 1 and topics[0]["rejected"] == 1
    found = run(project.root, "items", "list", "--query", "per project seat", "--full")["rows"]
    assert found[0]["ref"] == asked
    assert run(project.root, "topics", "list", "--query", "seat", "--full")["rows"][0]["name"] == (
        "pricing"
    )


def test_a_finished_topic_comes_back_revived_its_note_its_description(project: Project) -> None:
    ref = submit(project.root)
    judge(project.root, ref, "accepted")
    again = nock(project.root, "items", "create", "orders", json.dumps(DECISION))
    assert again.returncode == 49 and "--revive" in again.stderr
    made = nock(project.root, "topics", "create", json.dumps(TOPIC))
    assert made.returncode == 49 and "revive it" in made.stderr
    run(project.root, "topics", "update", "orders", "--revive", "Orders move to a second region.")
    later = submit(project.root, {**DECISION, "title": "Orders replicate to the second region"})
    shown = run(project.root, "topics", "show", "orders")
    assert shown["description"] == "Orders move to a second region."
    assert [item["ref"] for item in shown["items"]] == [later, ref]
    assert shown["thread"][0]["kind"] == "revival"


def test_the_owner_judges_on_the_page_and_the_submitting_session_hears_once(
    project: Project, page: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "s1")
    ref = submit(project.root)
    other = submit(project.root, {**DECISION, "title": "Orders are kept a year"})
    with urllib.request.urlopen(page) as response:
        shown = response.read().decode()
    assert '<a href="#topics" data-tab-link="topics">Topics</a>' in shown
    assert "<!-- nock:" not in shown
    with urllib.request.urlopen(f"{page}topics") as response:
        listed = json.loads(response.read())
    (topic,) = listed["topics"]
    assert topic["counts"] == {"open": 2, "accepted": 0, "rejected": 0}
    assert topic["items"][1]["versions"][0]["decision"]["answer"].startswith("One file")
    status, _ = post(page, "judge", {"ref": ref, "verdict": "maybe"})
    assert status == 400
    # A verdict on the page takes no comment: the words go through the chat.
    status, _ = post(page, "judge", {"ref": ref, "verdict": "rejected", "comment": "Postgres."})
    assert status == 400
    post(page, "reply", {"ref": ref, "text": "Postgres."})
    status, _ = post(page, "judge", {"ref": ref, "verdict": "rejected"})
    assert status == 200
    assert git(project.root, "status", "--porcelain") == ""

    prompt = HookRunner(project, {"session_id": "s1"}).handle("UserPromptSubmit")
    assert prompt is not None
    told = prompt["hookSpecificOutput"]["additionalContext"]
    assert f"[{ref}] Orders live in SQLite — rejected: Postgres." in told
    assert HookRunner(project, {"session_id": "s1"}).handle("UserPromptSubmit") is None
    assert HookRunner(project, {"session_id": "s2"}).handle("UserPromptSubmit") is None

    status, judged = post(page, "judge", {"topic": "orders", "verdict": "accepted"})
    assert status == 200 and judged["judged"] == [other]
    post(page, "reply", {"topic": "orders", "text": "All good otherwise."})
    assert Topics(project).topic("orders")["thread"][-1]["author"] == "owner"


def chat_of(address: str, ref: str) -> dict[str, Any]:
    with urllib.request.urlopen(f"{address}topics") as response:
        listed = json.loads(response.read())
    items = [item for topic in listed["topics"] for item in topic["items"]]
    return next(item["chat"] for item in items if item["ref"] == ref)


def test_the_owner_s_message_waits_for_the_agent_s_one_answer_and_is_withdrawn_until_then(
    project: Project, page: str
) -> None:
    ref = submit(project.root)
    assert chat_of(page, ref) == {"pending": False, "unseen": 0, "answered": False}
    post(page, "reply", {"ref": ref, "text": "Why not Postgres?"})
    assert chat_of(page, ref)["pending"] is True
    status, refused = post(page, "reply", {"ref": ref, "text": "And MySQL?"})
    assert status == 400 and "withdraw it" in refused["error"]
    status, taken = post(page, "withdraw", {"ref": ref})
    assert status == 200 and taken == {"text": "Why not Postgres?"}
    assert Topics(project).item(ref)["thread"] == []
    status, nothing = post(page, "withdraw", {"ref": ref})
    assert status == 400 and "nothing to withdraw" in nothing["error"]
    post(page, "reply", {"ref": ref, "text": "Why not Postgres, then?"})
    answered = run(project.root, "items", "update", ref, "--reply", "A server to run.")
    asked = Topics(project).item(ref)["thread"][0]["moment"]
    assert answered["answered"] == asked
    assert chat_of(page, ref) == {"pending": False, "unseen": 1, "answered": True}
    assert "answered" not in run(project.root, "items", "update", ref, "--reply", "And backups.")
    assert chat_of(page, ref)["unseen"] == 2
    status, _ = post(page, "seen", {"ref": ref})
    assert status == 200 and chat_of(page, ref)["unseen"] == 0
    # A verdict given after the owner's message is the answer: the chat opens again.
    post(page, "reply", {"ref": ref, "text": "Hm."})
    post(page, "judge", {"ref": ref, "verdict": "rejected"})
    assert chat_of(page, ref)["pending"] is False
    status, _ = post(page, "reply", {"ref": ref, "text": "Postgres, please."})
    assert status == 200
    # A topic's chat is the same.
    post(page, "reply", {"topic": "orders", "text": "Is this all?"})
    status, _ = post(page, "reply", {"topic": "orders", "text": "Hello?"})
    assert status == 400
    assert run(project.root, "topics", "update", "orders", "--reply", "Yes.")["answered"]
    status, _ = post(page, "seen", {"topic": "nowhere"})
    assert status == 404


def test_a_session_starts_with_what_is_new_in_topics_and_what_awaits_it_once_a_day(
    project: Project, page: str
) -> None:
    ref = submit(project.root)
    submit(project.root, {**DECISION, "title": "Emails go out at nine"}, topic="emails")
    submit(project.root, {**DECISION, "title": "Emails are plain text"}, topic="emails")
    begun = start(project, "s1")
    context = begun["hookSpecificOutput"]["additionalContext"]
    assert "nock: 3 new in Topics (emails: 2, orders: 1)" in context
    assert "3 new in Topics" in begun["systemMessage"]
    assert HookRunner(project, {"session_id": "s2"}).handle("SessionStart") is None
    post(page, "reply", {"ref": ref, "text": "Postgres."})
    post(page, "judge", {"ref": ref, "verdict": "rejected"})
    context = start(project, "s3")["hookSpecificOutput"]["additionalContext"]
    assert f"- rework {ref} (`--version`)" in context
    assert HookRunner(project, {"session_id": "s4"}).handle("SessionStart") is None
    standing = run(project.root, "status")
    assert standing["topics"]["awaiting_you"]["rejected"] == [ref]


def test_an_edit_to_a_file_an_item_holds_shows_the_item_once(project: Project) -> None:
    ref = submit(project.root, {"title": "The README's first line", "files": ["README.md"]})
    payload = {"session_id": "s1", "tool_input": {"file_path": str(project.root / "README.md")}}
    output = HookRunner(project, payload).handle("PostToolUse")
    assert output is not None
    assert (
        f"- [{ref}] (open) The README's first line"
        in output["hookSpecificOutput"]["additionalContext"]
    )
    assert HookRunner(project, payload).handle("PostToolUse") is None


def test_the_map_check_holds_its_citations(project: Project) -> None:
    ref = submit(project.root)
    (project.root / ".nock" / "topics" / "map.md").write_text(
        f"- [{ref}] holds; [orders/gone] not.\n"
    )
    result = nock(project.root, "check", "nock-map")
    assert result.returncode == 1 and "[orders/gone] is no item" in result.stdout + result.stderr
    assert f"[{ref}]" not in (result.stdout + result.stderr).replace("[orders/gone]", "")


def test_every_studio_tab_has_its_panel_and_its_routes_only(page: str) -> None:
    assert [tab.name for tab in TABS] == ["topics", "evals"]
    for tab in TABS:
        assert f'studio.register("{tab.name}"' in (PAGES / f"{tab.name}.html").read_text()
    for path in ("nothing", "decisions", "review", "topics/extra", "topics/file/a/b/1/c"):
        with pytest.raises(urllib.error.HTTPError) as missing:
            urllib.request.urlopen(f"{page}{path}")
        assert missing.value.code == 404
    status, _ = post(page, "nothing", {})
    assert status == 404


def test_a_version_s_files_are_served_as_they_are(
    project: Project, page: str, tmp_path: Path
) -> None:
    (project.root / "docs").mkdir()
    (project.root / "docs" / "guide.md").write_text("# Guide\n")
    git(project.root, "add", "-A")
    git(project.root, "commit", "-qm", "A guide")
    ref = submit(project.root, {"title": "The guide", "files": ["docs/guide.md"]})
    slug = ref.split("/")[1]
    with urllib.request.urlopen(f"{page}topics/file/orders/{slug}/1/docs/guide.md") as response:
        assert response.read() == b"# Guide\n"


def test_the_owner_asks_and_the_answer_names_items_that_exist(
    project: Project, page: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    ref = submit(project.root)
    monkeypatch.setenv(
        "FAKE_ANSWER", json.dumps({"answer": "In SQLite.", "items": ["orders/nope"]})
    )
    # Its answer refused, the agent's last message is what it said.
    fallen = run(project.root, "topics", "ask", "Where do orders live?")
    assert fallen["answer"] == "answered" and fallen["items"] == []
    monkeypatch.setenv("FAKE_ANSWER", json.dumps({"answer": "In **SQLite**.", "items": [ref]}))
    status, started = post(page, "ask", {"question": "Where do orders live?"})
    assert status == 200 and started["running"] is True
    status, error = post(page, "ask", {"question": "And refunds?"})
    assert status == 400 and "being answered" in error["error"]
    deadline = time.monotonic() + 60
    while True:
        with urllib.request.urlopen(f"{page}topics") as response:
            asked = json.loads(response.read())["ask"]
        if not asked["running"]:
            break
        assert time.monotonic() < deadline
        time.sleep(0.2)
    assert asked["answer"] == "In **SQLite**." and asked["items"] == [ref]


def test_an_ask_is_cancelled(project: Project, page: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FAKE_ANSWER", "slow")
    post(page, "ask", {"question": "Anything?"})
    status, cancelled = post(page, "ask/cancel", {})
    assert status == 200 and cancelled["problem"] == "cancelled" and not cancelled["running"]


def test_only_an_asked_agent_submits_an_answer(project: Project) -> None:
    result = nock(project.root, "topics", "answer", json.dumps({"answer": "Yes."}))
    assert result.returncode == 43 and "only an agent the studio's Ask dispatched" in result.stderr


def test_an_earlier_nock_s_decisions_and_review_items_move_into_topics_once(
    project: Project,
) -> None:
    decisions = project.root / ".nock" / "decisions"
    decisions.mkdir(parents=True, exist_ok=True)
    recorded = {"moment": "2026-01-01T00:00:00Z", "session": "s1", "role": "interactive"}
    base = {
        "status": "done",
        "evidence": [],
        "alternatives": [],
        "touches": [],
        "supersedes": [],
        "superseded_by": None,
        "note": None,
        "reviewed": None,
        "elaborating": False,
        "recorded": recorded,
        "updated": "2026-01-02T00:00:00Z",
    }
    (decisions / "0007.json").write_text(
        json.dumps(
            {
                **base,
                "number": 7,
                "title": "Orders live in SQLite",
                "review": "accepted",
                "summary": "One file.",
                "tags": ["important", "storage", "core"],
                "touches": ["README.md"],
                "note": "Fine for now.",
                "reviewed": {"moment": "2026-01-03T00:00:00Z", "session": "s9"},
            }
        )
    )
    (decisions / "0008.json").write_text(
        json.dumps(
            {
                **base,
                "number": 8,
                "title": "Keep it short",
                "review": "unreviewed",
                "summary": "Yes.",
                "tags": [],
            }
        )
    )
    (decisions / "map.md").write_text("- [D7] holds.\n")
    version = project.root / ".nock" / "review" / "email" / "report" / "1"
    version.mkdir(parents=True)
    (version / "text.txt").write_text("Three anomalies.\n")
    (version / "version.json").write_text(
        json.dumps(
            {
                "key": "email/report",
                "version": 1,
                "title": "The report email",
                "tags": ["emails"],
                "files": [{"name": "text.txt", "kind": "text", "bytes": 17, "local": False}],
                "note": "The first cut.",
                "decision": 7,
                "recipe": {"command": "make report"},
                "regenerated": None,
                "verdict": "rejected",
                "feedback": "Shorter.",
                "reviewed": {"moment": "2026-01-04T00:00:00Z", "session": None},
                "recorded": recorded,
            }
        )
    )
    git(project.root, "add", "-A")
    git(project.root, "commit", "-qm", "An earlier nock's records")
    outcome = Migration(project).run()
    assert outcome["topics"] == {"emails": 1, "general": 1, "storage": 1}
    topics = Topics(project)
    seven = topics.item("7")
    assert seven["ref"] == "storage/orders-live-in-sqlite" and seven["verdict"] == "accepted"
    assert seven["thread"][0]["author"] == "owner" and seven["thread"][0]["text"] == "Fine for now."
    answer = topics.decision(seven, seven["versions"][0])
    assert answer is not None and "Applies to `README.md`." in answer["answer"]
    assert topics.item("general/keep-it-short")["verdict"] == "open"
    report = topics.item("emails/email-report")
    assert report["verdict"] == "rejected" and report["versions"][0]["files"][0]["recipe"] == {
        "command": "make report"
    }
    assert [entry["text"] for entry in report["thread"]] == [
        "Version 1: The first cut.",
        "Version 1 illustrates [storage/orders-live-in-sqlite].",
        "On version 1: Shorter.",
    ]
    assert not decisions.exists() and not (project.root / ".nock" / "review").exists()
    assert (project.root / ".nock" / "topics" / "map.md").read_text() == "- [D7] holds.\n"
    assert topics.citation_problems() == []
    assert git(project.root, "status", "--porcelain") == ""
    assert Migration(project).run() == {"migrated": False}
    assert outcome["marked_told"] == 2
    assert HookRunner(project, {"session_id": "s1"}).handle("UserPromptSubmit") is None
    topics.reply("7", "Revisit at scale.", Author.OWNER)
    prompt = HookRunner(project, {"session_id": "s1"}).handle("UserPromptSubmit")
    assert prompt is not None
    told = prompt["hookSpecificOutput"]["additionalContext"]
    assert "[storage/orders-live-in-sqlite]" in told and "emails/email-report" not in told


def test_a_project_migrated_before_marks_what_the_owner_said_as_told_once(
    project: Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "s1")
    ref = submit(project.root)
    judge(project.root, ref, "accepted", "Fine.")
    assert run(project.root, "topics", "migrate", "--mark-seen") == {
        "migrated": False,
        "marked_told": 1,
    }
    assert run(project.root, "topics", "migrate", "--mark-seen")["marked_told"] == 0
    assert HookRunner(project, {"session_id": "s1"}).handle("UserPromptSubmit") is None


def test_a_task_keeps_its_state_and_is_accepted_when_done(
    project: Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "orchestrator")
    task = {
        "title": "Build the topics",
        "task": {"brief": "Topics replace decisions.", "branch": "topics"},
    }
    ref = submit(project.root, task)
    mixed = nock(
        project.root, "items", "create", "orders", json.dumps({**task, "files": ["README.md"]})
    )
    assert mixed.returncode == 40 and "a task holds nothing else" in mixed.stderr
    shown = run(project.root, "items", "show", ref)
    assert shown["task"]["state"] == "queued" and shown["task"]["started"] is None
    vague = nock(project.root, "items", "update", ref, '{"state": "waiting"}')
    assert vague.returncode == 40 and "waiting_on" in vague.stderr
    run(project.root, "items", "update", ref, '{"state": "waiting", "waiting_on": "owner"}')
    run(project.root, "items", "update", ref, '{"state": "running"}')
    before = run(project.root, "items", "show", ref)["task"]
    assert before["started"] and before["waiting_on"] is None
    run(project.root, "items", "update", ref, "--reply", "Half the tests pass.")
    assert run(project.root, "items", "show", ref)["task"]["heard"] >= before["heard"]
    listed = run(project.root, "items", "list")
    assert listed["summary"]["open"] == {}
    assert listed["rows"][0]["state"] == "running" and listed["rows"][0]["kinds"] == ["task"]
    other = submit(project.root, {"title": "Ship it", "task": {"brief": "Release."}})
    no_version = nock(project.root, "items", "update", ref, "--version", "{}")
    assert no_version.returncode == 40
    done = run(
        project.root, "items", "update", ref, '{"state": "done"}', "--reply", "Merged as abc123."
    )
    assert done["verdict"] == "accepted"
    assert HookRunner(project, {"session_id": "orchestrator"}).handle("UserPromptSubmit") is None
    run(project.root, "items", "update", other, '{"state": "failed"}')
    failing = run(project.root, "items", "list")
    assert failing["summary"]["open"] == {"orders": 1}
    assert run(project.root, "items", "show", other)["verdict"] == "open"
