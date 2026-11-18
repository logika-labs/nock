"""Topics as agents write them and the owner meets them: decisions and
proposals, assets by version, the review and its blocks, the owner's notes,
their one chat, Accept and Reject, Done; what waits on whom, and what the
hooks and the views read of it. Real repositories, the store's own write path."""

from __future__ import annotations

import json

import pytest

from nock.errors import UsageError
from nock.project import Project
from nock.views import Views

from .conftest import git, nock
from .store import (
    asset,
    compose,
    draft,
    held,
    item_event,
    open_topic,
    propose,
    reply,
    settle,
    shared_root,
    state,
    submit,
    topics_in,
)


def test_a_decision_and_a_proposal_are_items_of_their_topic(project: Project) -> None:
    root = project.root
    submit(root)
    propose(root)
    topics = topics_in(root)
    decision, proposal = topics.items("orders")
    assert decision["status"] == "decision" and not decision["proposed"]
    assert proposal["status"] == "open" and proposal["takes"] == "a day"
    row = topics.row("orders")
    assert (row["decisions"], row["proposals"], row["open"]) == (1, 1, 1)
    assert row["for_owner"] == ["orders/archive"]
    log = git(root, "log", "--format=%s", "-3")
    assert "nock: orders/archive created" in log


def test_an_item_says_what_it_means_and_nothing_else(project: Project) -> None:
    root = project.root
    open_topic(root)
    folder = shared_root(root) / "orders" / "items" / "bare"
    draft(folder, {"kind": "created", "type": "decision", "title": "No meaning"})
    settled = settle(root)
    assert any("means" in problem for problem in settled.problems)
    folder2 = shared_root(root) / "orders" / "items" / "alts"
    draft(
        folder2,
        {"kind": "created", "type": "decision", "title": "T", "means": "M", "alternatives": []},
    )
    assert any("alternatives" in problem for problem in settle(root).problems)


def test_only_a_proposal_takes_a_verdict_and_only_an_accepted_one_is_carried_out(
    project: Project,
) -> None:
    root = project.root
    decision = submit(root)
    proposal = propose(root)
    topics = topics_in(root)
    with pytest.raises(UsageError, match="only a proposal"):
        topics.judge(decision, "accepted")
    refused = item_event(root, proposal, {"kind": "implemented", "means": "done early"})
    assert any("only a proposal the owner accepted" in p for p in refused.problems)
    for path in (shared_root(root) / "orders" / "items" / "archive" / "events").glob("new-*"):
        path.unlink()
    accepted = topics.judge(proposal, "accepted")
    assert accepted["status"] == "accepted"
    assert topics.row("orders")["for_agent"] == ["orders/archive"]
    done = item_event(
        root, proposal, {"kind": "implemented", "means": "A nightly job archives them."}
    )
    assert not done.problems
    carried = topics_in(root).item(proposal)
    assert carried["status"] == "decision" and carried["proposed"]
    assert carried["means"] == "A nightly job archives them."
    assert topics_in(root).row("orders")["for_agent"] == []


def test_a_rejected_proposal_is_dropped_but_kept_in_its_history(project: Project) -> None:
    root = project.root
    proposal = propose(root)
    rejected = topics_in(root).judge(proposal, "rejected")
    assert rejected["status"] == "rejected"
    assert rejected["history"][-1]["verdict"] == "rejected"
    row = topics_in(root).row("orders")
    assert row["for_owner"] == [] and row["proposals"] == 1


def test_an_asset_is_versioned_and_a_project_file_is_linked_at_its_commit(
    project: Project,
) -> None:
    root = project.root
    open_topic(root)
    asset(root, "orders", "notes", "one\ntwo\n")
    asset(root, "orders", "notes", "one\nthree\n")
    topics = topics_in(root)
    notes = topics.asset("orders", "notes")
    assert [v["version"] for v in notes["versions"]] == [1, 2]
    assert topics.text_of("orders", "notes", 1) == "one\ntwo\n"
    assert topics.text_of("orders", "notes") == "one\nthree\n"
    folder = shared_root(root) / "orders" / "assets" / "readme"
    draft(folder, {"kind": "created", "title": "The README"})
    (folder / "versions" / "next").mkdir(parents=True)
    (folder / "versions" / "next" / "asset.json").write_text(
        json.dumps({"file": {"kind": "project", "path": "README.md"}})
    )
    held(root)
    linked = topics_in(root).asset("orders", "readme")["versions"][0]["file"]
    assert linked["path"] == "README.md" and len(linked["commit"]) == 40


def test_an_asset_version_holds_only_its_one_file(project: Project) -> None:
    root = project.root
    open_topic(root)
    folder = shared_root(root) / "orders" / "assets" / "two"
    draft(folder, {"kind": "created", "title": "Two"})
    version = folder / "versions" / "next"
    version.mkdir(parents=True)
    (version / "a.md").write_text("a")
    (version / "b.md").write_text("b")
    (version / "asset.json").write_text(json.dumps({"file": {"kind": "derived", "name": "a.md"}}))
    assert any("only the file" in problem for problem in settle(root).problems)


def test_a_review_is_checked_against_the_topic_it_shows(project: Project) -> None:
    root = project.root
    submit(root)
    asset(root, "orders", "notes")
    problems = compose(
        root,
        "orders",
        [
            {"kind": "item", "item": "nothing"},
            {"kind": "diff", "asset": "notes"},
            {"kind": "image", "asset": "missing"},
            {"kind": "html", "file": "absent.html"},
            {"kind": "chart", "chart": "pie", "labels": [], "series": []},
            {"kind": "text"},
        ],
    ).problems
    said = " ".join(problems)
    assert "no item 'nothing'" in said
    assert "a diff shows two versions" in said
    assert "no asset 'missing'" in said
    assert "html block's file" in said
    assert "pie" in said
    assert "text" in said
    assert topics_in(root).current_review("orders") is None


def test_a_review_tells_the_story_with_every_kind_of_block(project: Project) -> None:
    root = project.root
    submit(root)
    propose(root)
    asset(root, "orders", "schema", "create table a;\n", file_name="schema.sql")
    asset(root, "orders", "schema", "create table orders;\n", file_name="schema.sql")
    blocks = [
        {"kind": "text", "text": "Orders moved to **SQLite**."},
        {"kind": "item", "item": "sqlite", "id": "the-move"},
        {"kind": "diff", "asset": "schema", "from": 1, "to": 2},
        {"kind": "doc", "asset": "schema"},
        {"kind": "excerpt", "asset": "schema", "lines": [1, 1]},
        {"kind": "image", "asset": "schema"},
        {"kind": "table", "columns": ["a", "b"], "rows": [[1, 2]]},
        {
            "kind": "chart",
            "chart": "bar",
            "labels": ["x"],
            "series": [{"name": "n", "values": [1]}],
        },
        {"kind": "html", "file": "flow.html", "height": 200},
        {"kind": "item", "item": "archive"},
    ]
    settled = compose(root, "orders", blocks, files={"flow.html": "<p>flow</p>"})
    assert not settled.problems, settled.problems
    review = topics_in(root).current_review("orders")
    assert review is not None and review["version"] == 1
    assert [block["id"] for block in review["blocks"]][:3] == ["b1", "the-move", "b3"]
    assert (topics_in(root).html_block("orders", 1, "flow.html")).read_text() == "<p>flow</p>"
    assert topics_in(root).row("orders")["for_owner"] == ["orders/archive", "orders/review"]


def test_notes_wait_as_drafts_until_a_message_carries_them(project: Project) -> None:
    root = project.root
    submit(root)
    compose(root, "orders", [{"kind": "item", "item": "sqlite"}])
    topics = topics_in(root)
    first = topics.note("orders", {"item": "sqlite"}, "Why not Postgres?", identifier="0000000a")
    topics.note("orders", {"block": "b1", "review": 1, "quote": "SQLite"}, "Say more")
    edited = topics.note(
        "orders", {"item": "sqlite"}, "Why not Postgres, really?", replaces=first["id"]
    )
    topic = topics.topic("orders")
    assert [note["text"] for note in topics.unsent(topic)] == [
        "Why not Postgres, really?",
        "Say more",
    ]
    message = topics.send("orders", "", now=False)
    assert len(message["notes"]) == 2 and edited["id"] in message["notes"]
    topic = topics_in(root).topic("orders")
    assert topics_in(root).unsent(topic) == []
    carried = topics_in(root).carried(topic, message)
    assert carried[1]["target"] == 'block b1 (item) of review v1: "SQLite"'
    view = (root / ".nock" / "local" / "views" / "orders.md").read_text()
    assert "note on item sqlite: Why not Postgres, really?" in view


def test_an_agents_message_after_the_owners_answers_it_and_may_show_blocks(
    project: Project,
) -> None:
    root = project.root
    submit(root)
    topics = topics_in(root)
    said = topics.send("orders", "Is it backed up?", now=False)
    assert topics.comments()[0]["id"] == said["id"]
    answered = reply(
        root, "orders", "Nightly; see it.", blocks=[{"kind": "item", "item": "sqlite"}]
    )
    assert not answered.problems
    last = topics_in(root).topic("orders")["thread"][-1]
    assert last["answers"] == said["id"] and last["blocks"][0]["item"] == "sqlite"
    assert topics_in(root).comments() == []
    bad = reply(root, "orders", "x", blocks=[{"kind": "html", "file": "a.html"}])
    assert any("no html block" in problem for problem in bad.problems)


def test_done_counts_unnoted_decisions_as_fine_and_closes_what_waits_on_nobody(
    project: Project,
) -> None:
    root = project.root
    submit(root)
    compose(root, "orders", [{"kind": "item", "item": "sqlite"}])
    state(root, "orders", state="review", status="built")
    done = topics_in(root).done("orders")
    assert done == {"sent": False, "state": "done"}
    assert topics_in(root).reviewed(topics_in(root).topic("orders"))


def test_done_with_notes_sends_them_and_keeps_the_task_open(project: Project) -> None:
    root = project.root
    submit(root)
    compose(root, "orders", [{"kind": "item", "item": "sqlite"}])
    topics = topics_in(root)
    topics.note("orders", {"item": "sqlite"}, "Redo this")
    done = topics.done("orders")
    assert done["sent"] and done["state"] == "active"
    assert topics_in(root).row("orders")["for_agent"] == ["orders/chat"]


def test_a_closed_topic_takes_nothing_new_until_it_is_revived(project: Project) -> None:
    root = project.root
    open_topic(root)
    state(root, "orders", state="done")
    folder = shared_root(root) / "orders" / "items" / "late"
    draft(folder, {"kind": "created", "type": "decision", "title": "Late", "means": "m"})
    assert any("revive it first" in problem for problem in settle(root).problems)
    state(root, "orders", state="active", revived=True, note="the archive is back")
    held(root)
    topic = topics_in(root).topic("orders")
    assert topic["revived"]["note"] == "the archive is back"
    assert topics_in(root).row("orders")["description"] == "the archive is back"


def test_the_owner_hears_their_turn_and_the_agent_hears_the_owner(project: Project) -> None:
    root = project.root
    proposal = propose(root)
    rows = project.store.rows("SELECT reason, topic FROM notifications ORDER BY id")
    assert [(row["reason"], row["topic"]) for row in rows] == [("proposed", "orders")]
    topics = topics_in(root)
    topics.judge(proposal, "accepted")
    topics.send("orders", "and the receipts?", now=False)
    news = topics_in(root).news_for("agent-session")
    assert [entry["kind"] for entry in news] == ["message", "accepted"]
    assert topics_in(root).news_for("agent-session") == []
    assert topics_in(root).news_for("someone-else") == []


def test_an_edited_file_shows_the_tasks_whose_assets_show_it(project: Project) -> None:
    root = project.root
    submit(root)
    asset(root, "orders", "shot", "png", file_name="shot.md", **{"from": ["src/*.py"]})
    found = topics_in(root).governing("s1", "src/app.py")
    assert found[0]["topic"] == "orders" and found[0]["decisions"][0]["slug"] == "sqlite"
    assert topics_in(root).governing("s1", "src/app.py") == []


def test_a_session_that_worked_in_a_topic_without_saying_where_it_stands_is_unstated(
    project: Project,
) -> None:
    root = project.root
    submit(root)
    assert topics_in(root).unstated("agent-session") == ["orders"]
    state(root, "orders", status="moving orders")
    assert topics_in(root).unstated("agent-session") == []


def test_search_finds_topics_and_items_and_the_views_hold_them_whole(project: Project) -> None:
    root = project.root
    submit(root)
    propose(root)
    asset(root, "orders", "notes", "x")
    compose(root, "orders", [{"kind": "text", "text": "Orders moved."}], summary="Moved")
    topics = topics_in(root)
    assert topics.search_topics("orders moved") == ["orders"]
    assert [found["ref"] for found in topics.search_items("archive")] == ["orders/archive"]
    Views(project).write()
    view = (root / ".nock" / "local" / "views" / "orders.md").read_text()
    for said in (
        "## Decisions",
        "## Proposals",
        "## Assets",
        "## Review, version 1",
        "Takes: a day",
    ):
        assert said in view
    index = (root / ".nock" / "local" / "views" / "index.md").read_text()
    assert "1 decisions, 1 proposals, 1 assets" in index


def test_the_memory_stays_small_and_cites_only_items_that_exist(project: Project) -> None:
    root = project.root
    submit(root)
    memory = root / ".nock" / "shared" / "memory.md"
    memory.write_text("- orders: [orders/sqlite]; gone: [orders/gone].\n")
    problems = topics_in(root).memory_problems()
    assert [problem.message for problem in problems] == ["[orders/gone] is no item"]
    memory.write_text("x" * 9000)
    assert "prune and merge" in str(topics_in(root).memory_problems()[0])
    topics_in(root).edit_memory("- orders: [orders/sqlite]\n")
    assert git(root, "status", "--porcelain", "--", ".nock/shared") == ""
    assert "memory.md" in git(root, "show", "--name-only", "--format=", "HEAD")


def test_a_plan_shows_progress_and_the_time_left(project: Project) -> None:
    root = project.root
    open_topic(root)
    steps = [{"title": "Schema", "estimate": 30}, {"title": "Move", "estimate": 60}]
    state_events = [
        {"kind": "plan", "steps": steps},
        {"kind": "step", "title": "Schema", "state": "started"},
        {"kind": "step", "title": "Schema", "state": "done"},
        {"kind": "step", "title": "Move", "state": "started"},
    ]
    for record in state_events:
        draft(shared_root(root) / "orders", record)
        held(root)
    found = topics_in(root).row("orders")["progress"]
    assert found["done"] == 1 and found["current"] == "Move"
    assert found["share"] == round(30 / 90, 3)
    assert found["steps"][0]["actual"] is not None and found["steps"][1]["actual"] is None
    # Done in no time: the pace makes what is left quick.
    assert found["left"] <= 60
    draft(
        shared_root(root) / "orders",
        {"kind": "plan", "steps": [*steps, {"title": "Check", "estimate": 10}]},
    )
    held(root)
    revised = topics_in(root).row("orders")["progress"]
    assert [step["title"] for step in revised["steps"]] == ["Schema", "Move", "Check"]
    assert revised["steps"][0]["done"]


def test_search_command_lists_topics_and_items(project: Project) -> None:
    root = project.root
    submit(root)
    done = nock(root, "search", "sqlite")
    assert done.returncode == 0, done.stderr
    assert "orders/sqlite" in done.stdout
