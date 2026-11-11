"""Items' assets: a description under the title, variants with one preferred
before an asset is accepted (an item's `options` read as variants), views
served with nock's look; the Timeline, read from the topics, and the
notifications that are its events; Address now, for one thread; and search
ranked by the strongest match."""

from __future__ import annotations

import json
import urllib.request
from pathlib import Path
from typing import Any

import pytest

from nock.errors import ConflictError, UsageError
from nock.notify import ICON, Notifications, Reason, desktop_command
from nock.project import Project
from nock.timeline import Timeline
from nock.topics import Author, Topics

from . import store
from .test_chats import answered
from .test_chats import post as chat_post
from .test_topics import item_folder, judge, open_topic, page, post, submit

__all__ = ["page"]


def get(address: str, route: str) -> Any:
    with urllib.request.urlopen(f"{address}{route}") as response:
        return json.loads(response.read())


def fetch(address: str, route: str) -> bytes:
    with urllib.request.urlopen(f"{address}{route}") as response:
        return response.read()


def test_an_item_keeps_the_description_it_was_submitted_with(project: Project) -> None:
    ref = submit(
        project.root,
        {
            "title": "Banner",
            "description": "Three takes on the landing banner",
            "variants": True,
            "derived": [{"text": name, "name": f"{name}.md"} for name in "ab"],
        },
    )
    shown = store.shown(project.root, ref)
    assert shown["description"] == "Three takes on the landing banner"


def test_an_asset_with_variants_is_accepted_only_once_one_is_preferred(
    project: Project, page: str, tmp_path: Path
) -> None:
    paths = []
    for name in ("a.svg", "b.svg"):
        paths.append(tmp_path / name)
        paths[-1].write_text(f"<svg xmlns='http://www.w3.org/2000/svg'><title>{name}</title></svg>")
    open_topic(project.root)
    with pytest.raises(UsageError, match='"variants": true'):
        submit(
            project.root, {"title": "Favicon", "derived": [{"path": str(path)} for path in paths]}
        )
    ref = submit(
        project.root,
        {"title": "Favicon", "variants": True, "derived": [{"path": str(path)} for path in paths]},
    )
    single = submit(project.root, {"title": "Logo", "derived": [{"path": str(paths[0])}]})
    with pytest.raises(ConflictError, match="prefer one before accepting it"):
        judge(project.root, ref, "accepted")
    assert post(page, "judge", {"topic": "orders", "verdict": "accepted"}) == (
        200,
        {"judged": [single]},
    )
    assert post(page, "prefer", {"ref": ref, "version": 1, "name": "b.svg"})[0] == 200
    assert post(page, "judge", {"ref": ref, "verdict": "accepted"}) == (200, {"judged": [ref]})


def test_a_view_is_served_with_nock_s_look_and_the_item_s_files_named_for_it(
    project: Project, page: str, tmp_path: Path
) -> None:
    icon = tmp_path / "icon.svg"
    icon.write_text("<svg xmlns='http://www.w3.org/2000/svg'/>")
    view = "<!doctype html><html><head><title>Sizes</title></head><body><img src='icon.svg'></body></html>"
    ref = submit(
        project.root,
        {
            "title": "Favicon",
            "derived": [{"path": str(icon)}],
            "views": [{"text": view, "name": "sizes.html", "title": "At three sizes"}],
        },
    )
    (asset,) = store.shown(project.root, ref)["assets"]
    shown = asset["versions"][0]
    assert (
        shown["views"][0]["name"] == "sizes.html" and shown["views"][0]["title"] == "At three sizes"
    )
    slug = ref.split("/")[1]
    served = fetch(page, f"topics/view/orders/{slug}/favicon/1/sizes.html").decode()
    assert served.index('<link rel="stylesheet" href="/topics/view.css">') > served.index("<head>")
    given = json.loads(served.split("window.nock = ")[1].split(";</script>")[0])
    assert given["assets"] == [
        {
            "name": "icon.svg",
            "type": "image",
            "title": "Favicon",
            "address": "icon.svg",
            "preferred": False,
        }
    ]
    assert fetch(page, f"topics/view/orders/{slug}/favicon/1/icon.svg") == icon.read_bytes()
    assert b".grid" in fetch(page, "topics/view.css")
    with pytest.raises(UsageError, match="views lay out an asset's files"):
        submit(
            project.root,
            {
                "title": "D",
                "decision": {"answer": "Yes."},
                "views": [{"text": view, "name": "v.html"}],
            },
        )


def test_the_timeline_is_read_from_the_topics_and_a_notification_is_one_of_its_events(
    project: Project, page: str
) -> None:
    open_topic(project.root, {**{"name": "orders", "description": "Orders."}, "status": "starting"})
    ref = submit(project.root)
    topics = Topics(project)
    topics.reply(ref, "Why not Postgres?", Author.OWNER)
    store.update_item(project.root, ref, reply="One file is enough.")
    store.update_topic(project.root, "orders", change={"state": "review", "status": "built"})
    events = Timeline(project).events()
    # Written within one second, the review and the answer may come in either order.
    kinds = [event["kind"] for event in events]
    assert sorted(kinds[:2]) == ["answered", "state"] and kinds[2:] == ["item", "topic"]
    answered_you = next(event for event in events if event["kind"] == "answered")
    assert answered_you["address"] == f"#topics/{ref}~chat"
    # Each says what happened, then a title, then a description.
    said = {event["kind"]: (event["phrase"], event["title"], event["preview"]) for event in events}
    assert said == {
        "answered": ("replied to you", "Why not Postgres?", "One file is enough."),
        "state": ("ready for your review", "built", "1 decision"),
        "item": (
            "decision for you",
            "Orders live in SQLite",
            "One file is enough for **orders** at today's load.",
        ),
        "topic": ("started", "Orders.", ""),
    }
    told = project.store.rows("SELECT event, address FROM notifications ORDER BY id")
    # The answer told the owner; the review, within the same five minutes, waits for the next window.
    assert told == [{"event": answered_you["key"], "address": answered_you["address"]}]
    listed = get(page, "timeline?filter=answers")
    assert [event["key"] for event in listed["events"]] == [answered_you["key"]]
    assert listed["counts"] == {"all": 4, "answers": 1, "review": 1, "topics": 2}
    assert get(page, "timeline?query=postgres%20sqlite")["events"][0]["ref"] == ref


def test_a_topic_s_status_changes_in_a_row_are_one_event_with_their_count(
    project: Project,
) -> None:
    open_topic(project.root, {"name": "orders", "description": "Orders. Kept in one file."})
    for status in ("one", "two", "three"):
        run(project.root, "topics", "update", "orders", json.dumps({"status": status}))
    submit(project.root)
    run(project.root, "topics", "update", "orders", json.dumps({"status": "four"}))
    # A second apart each, as an agent working writes them.
    folder = project.root / ".nock" / "topics" / "orders"
    topic = json.loads((folder / "topic.json").read_text())
    topic["created"]["moment"] = "2026-01-01T10:00:00Z"
    seconds = {"one": 1, "two": 2, "three": 3, "four": 5}
    for entry in topic["thread"]:
        entry["moment"] = f"2026-01-01T10:00:0{seconds.get(entry.get('status'), 0)}Z"
    (folder / "topic.json").write_text(json.dumps(topic))
    item_file = next(folder.glob("*/item.json"))
    item = json.loads(item_file.read_text())
    item["versions"][0]["moment"] = "2026-01-01T10:00:04Z"
    item_file.write_text(json.dumps(item))
    events = Timeline(project).events()
    shown = [(event["kind"], event["title"], event.get("count")) for event in events]
    assert shown == [
        ("status", "four", None),
        ("item", "Orders live in SQLite", None),
        ("status", "three", 3),
        ("topic", "Orders.", None),
    ]
    # The status it moved on from, before the three.
    assert events[2]["preview"] == "" and events[2]["muted"] is True
    assert events[0]["preview"] == "three"
    assert events[3]["preview"] == "Kept in one file."


def test_an_asset_s_event_carries_the_face_of_each_of_its_pictures(
    project: Project, tmp_path: Path
) -> None:
    paths = []
    for name in ("a.svg", "b.svg"):
        paths.append(tmp_path / name)
        paths[-1].write_text(f"<svg xmlns='http://www.w3.org/2000/svg'><title>{name}</title></svg>")
    open_topic(project.root)
    pictures = submit(
        project.root,
        {
            "title": "Favicon",
            "variants": True,
            "derived": [{"path": str(path)} for path in paths],
        },
    )
    text = submit(project.root, {"title": "Notes", "derived": [{"text": "x", "name": "x.md"}]})
    events = {event.get("ref"): event for event in Timeline(project).events()}
    assert events[pictures]["faces"] == [
        {"file": "a.svg", "type": "image", "asset": "favicon", "version": 1},
        {"file": "b.svg", "type": "image", "asset": "favicon", "version": 1},
    ]
    assert "faces" not in events[text]


def test_the_notifications_show_nock_s_logo(project: Project, page: str) -> None:
    command = desktop_command("nock", "text", "http://x/#topics/a", "a", "linux")
    assert command is None or f"--icon={ICON}" in command
    assert ICON.is_file() and fetch(page, "icon.png") == ICON.read_bytes()
    assert Notifications(project).tell("orders", Reason.REVIEW, [], event=None) is not None


def test_address_now_answers_the_comment_in_one_thread(
    project: Project, page: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ref = submit(project.root)
    other = submit(project.root, {"title": "Refunds are capped", "decision": {"answer": "Yes."}})
    topics = Topics(project)
    topics.reply(ref, "Why not Postgres?", Author.OWNER)
    topics.reply(other, "And the cap?", Author.OWNER)
    said = {"kind": "message", "text": "One file is enough."}
    reply = ["write", str(item_folder(project, ref) / "events" / "a.json"), json.dumps(said)]
    monkeypatch.setenv("FAKE_ADDRESS", json.dumps([reply]))
    status, started = chat_post(page, "address", {"ref": ref})
    assert status == 200 and started["title"] == "Address now" and started["refs"] == [ref]
    assert started["messages"][0]["text"].startswith("Address my comment:")
    assert other not in started["messages"][0]["text"]
    answered(page, started["id"])
    assert topics.item(ref)["thread"][-1]["author"] == "agent"
    assert topics.item(other)["thread"][-1]["author"] == "owner"
    assert chat_post(page, "address", {"ref": ref})[0] == 400


def test_search_ranks_what_holds_every_word_first_then_all_but_one_and_so_on(
    project: Project, page: str
) -> None:
    """Searching "nock cli docs": the topics holding all three come first, more
    occurrences higher; then those holding two; then one. A word is found where
    a word starts: "cli" is not in "decline"."""
    for name, description in [
        ("partial", "The nock site, its pages declined."),
        ("complete", "nock's CLI docs: every command."),
        ("twice", "nock CLI docs, the CLI reference, and the docs index."),
        ("pair", "nock docs, the essays."),
    ]:
        open_topic(project.root, {"name": name, "description": description})
    names = Topics(project).search_topics("nock cli docs")
    assert names == ["twice", "complete", "pair", "partial"]
    found = get(page, "topics/search/nock%20cli%20docs")
    # Shown whole, only the topics holding every word; the strongest first.
    assert found["topics"] == ["complete", "twice"]
    assert found["order"] == ["twice", "complete"]


def test_the_studio_s_menu_says_nock_and_its_settings_fold_by_group(page: str) -> None:
    shell = fetch(page, "").decode()
    assert '<h1 id="title">nock</h1>' in shell
    assert ">Topics</a>" in shell and ">Timeline</a>" in shell
    assert shell.count('<details class="group"') == 3
    for group in ("Sharing", "Notifications", "Transcription"):
        assert f"<span>{group}</span>" in shell or f">{group}</span>" in shell
