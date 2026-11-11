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

from nock.notify import ICON, Notifications, Reason, desktop_command
from nock.project import Project
from nock.timeline import Timeline
from nock.topics import Author, Topics

from .conftest import nock
from .test_chats import answered
from .test_chats import post as chat_post
from .test_topics import open_topic, page, post, run, submit

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
    shown = run(project.root, "items", "show", ref)
    assert shown["description"] == "Three takes on the landing banner"


def test_an_asset_with_variants_is_accepted_only_once_one_is_preferred(
    project: Project, page: str, tmp_path: Path
) -> None:
    paths = []
    for name in ("a.svg", "b.svg"):
        paths.append(tmp_path / name)
        paths[-1].write_text(f"<svg xmlns='http://www.w3.org/2000/svg'><title>{name}</title></svg>")
    open_topic(project.root)
    many = nock(
        project.root,
        "items",
        "create",
        "orders",
        json.dumps({"title": "Favicon", "derived": [{"path": str(path)} for path in paths]}),
    )
    assert many.returncode == 40 and '"variants": true' in many.stderr
    ref = submit(
        project.root,
        {"title": "Favicon", "variants": True, "derived": [{"path": str(path)} for path in paths]},
    )
    single = submit(project.root, {"title": "Logo", "derived": [{"path": str(paths[0])}]})
    refused = nock(project.root, "items", "judge", ref, '{"verdict": "accepted"}')
    assert refused.returncode != 0 and "prefer one before accepting it" in refused.stderr
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
    shown = run(project.root, "items", "show", ref)["versions"][0]
    assert (
        shown["views"][0]["name"] == "sizes.html" and shown["views"][0]["title"] == "At three sizes"
    )
    slug = ref.split("/")[1]
    served = fetch(page, f"topics/view/orders/{slug}/1/sizes.html").decode()
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
    assert fetch(page, f"topics/view/orders/{slug}/1/icon.svg") == icon.read_bytes()
    assert b".grid" in fetch(page, "topics/view.css")
    decided = nock(
        project.root,
        "items",
        "create",
        "orders",
        json.dumps(
            {
                "title": "D",
                "decision": {"answer": "Yes."},
                "views": [{"text": view, "name": "v.html"}],
            }
        ),
    )
    assert decided.returncode != 0 and "a decision has no views" in decided.stderr


def test_the_timeline_is_read_from_the_topics_and_a_notification_is_one_of_its_events(
    project: Project, page: str
) -> None:
    run(
        project.root,
        "topics",
        "create",
        json.dumps({**{"name": "orders", "description": "Orders."}, "status": "starting"}),
    )
    ref = submit(project.root)
    topics = Topics(project)
    topics.reply(ref, "Why not Postgres?", Author.OWNER)
    run(project.root, "items", "update", ref, "--reply", "One file is enough.")
    run(
        project.root,
        "topics",
        "update",
        "orders",
        json.dumps({"state": "review", "status": "built"}),
    )
    events = Timeline(project).events()
    # Written within one second, the review and the answer may come in either order.
    kinds = [event["kind"] for event in events]
    assert sorted(kinds[:2]) == ["answered", "state"] and kinds[2:] == ["item", "topic"]
    answered_you = next(event for event in events if event["kind"] == "answered")
    assert answered_you["address"] == f"#topics/{ref}~chat"
    assert answered_you["preview"] == "One file is enough."
    told = project.store.rows("SELECT event, address FROM notifications ORDER BY id")
    # The answer told the owner; the review, within the same five minutes, waits for the next window.
    assert told == [{"event": answered_you["key"], "address": answered_you["address"]}]
    listed = get(page, "timeline?filter=answers")
    assert [event["key"] for event in listed["events"]] == [answered_you["key"]]
    assert listed["counts"] == {"all": 4, "answers": 1, "review": 1, "topics": 2}
    assert get(page, "timeline?query=postgres%20sqlite")["events"][0]["ref"] == ref


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
    monkeypatch.setenv(
        "FAKE_ADDRESS", json.dumps([["items", "update", ref, "--reply", "One file is enough."]])
    )
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
    listed = run(project.root, "topics", "list", "--query", "nock cli docs")
    names = [row["name"] for row in listed["rows"]]
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
