"""The studio on the store: each topic's decisions with their assets, files
reached through their asset, a preference posted for one asset; with an
agent waiting on `nock inbox`, the global chat and Address now go to it
instead of a dispatched agent; and a decision is folded again only once it
changed."""

from __future__ import annotations

import json
import time
import urllib.request
from pathlib import Path
from typing import Any

from nock.fold import Fold
from nock.inbox import Inbox
from nock.project import Project
from nock.topics import Author, Topics

from .store import DECISION, submit
from .test_chats import page

__all__ = ["page"]


def get(address: str, route: str) -> Any:
    with urllib.request.urlopen(f"{address}{route}") as response:
        return json.loads(response.read())


def post(address: str, route: str, body: dict[str, Any]) -> tuple[int, Any]:
    request = urllib.request.Request(
        f"{address}{route}", data=json.dumps(body).encode(), method="POST"
    )
    try:
        with urllib.request.urlopen(request) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read())


def listening(project: Project) -> None:
    Inbox(project, "orchestrator").listen(time.time() + 600)


def test_the_page_gets_decisions_with_their_assets_and_files_through_the_asset(
    project: Project, page: str, tmp_path: Path
) -> None:
    shot = tmp_path / "receipt.svg"
    shot.write_text("<svg xmlns='http://www.w3.org/2000/svg'/>")
    ref = submit(project.root, {**DECISION, "derived": [{"path": str(shot)}]})
    (topic,) = get(page, "topics")["topics"]
    (item,) = topic["items"]
    assert item["ref"] == ref and item["versions"][0]["decision"]["answer"]
    (asset,) = item["assets"]
    assert (
        asset["name"] == "orders-live-in-sqlite"
        and asset["versions"][0]["files"][0]["name"] == "receipt.svg"
    )
    slug = ref.split("/")[1]
    address = f"{page}topics/file/orders/{slug}/{asset['name']}/1/receipt.svg"
    with urllib.request.urlopen(address) as response:
        assert response.read() == shot.read_bytes()
        assert response.headers["Content-Type"].startswith("image/svg+xml")
    assert get(page, "topics")["listening"] == []


def test_a_preference_is_for_one_asset_of_the_decision(project: Project, page: str) -> None:
    ref = submit(
        project.root,
        {
            "title": "The banner",
            "variants": True,
            "derived": [{"text": name, "name": f"{name}.md"} for name in "ab"],
        },
    )
    asset = Topics(project).item(ref)["assets"][0]["name"]
    assert post(page, "topics/judge", {"ref": ref, "verdict": "accepted"})[0] == 400
    status, said = post(
        page, "topics/prefer", {"ref": ref, "asset": asset, "version": 1, "name": "b.md"}
    )
    assert status == 200 and said == {"preferred": {"version": 1, "name": "b.md"}}
    assert post(page, "topics/judge", {"ref": ref, "verdict": "accepted"})[0] == 200


def test_with_an_agent_listening_the_chat_and_address_now_go_to_its_inbox(
    project: Project, page: str, tmp_path: Path, monkeypatch: Any
) -> None:
    log = tmp_path / "asked.jsonl"
    monkeypatch.setenv("FAKE_LOG", str(log))
    ref = submit(project.root)
    Topics(project).reply(ref, "Why not Postgres?", Author.OWNER)
    listening(project)
    assert get(page, "topics")["listening"] == ["orchestrator"]
    status, chat = post(page, "chat/send", {"text": "Where do orders live?"})
    assert status == 200
    status, urged = post(page, "chat/address", {"ref": ref})
    assert status == 200 and urged == {"listening": True, "refs": [ref]}
    time.sleep(0.5)
    assert not log.exists(), "no agent was dispatched"
    kinds = [(entry["kind"], entry["ref"]) for entry in Inbox(project, "orchestrator").entries()]
    assert kinds == [("now", ref), ("chat", f"chat:{chat['id']}")]


def test_a_decision_is_folded_again_only_once_it_changed(project: Project) -> None:
    ref = submit(project.root)
    fold = Fold(project.root / ".nock" / "shared")
    topic, slug = ref.split("/")
    first = fold.item(topic, slug)
    assert first is not None
    first["title"] = "changed by a caller"
    again = fold.item(topic, slug)
    assert again is not None and again["title"] == DECISION["title"]
    Topics(project).reply(ref, "Noted.", Author.AGENT)
    assert [entry["text"] for entry in (fold.item(topic, slug) or {})["thread"]] == ["Noted."]
    assert json.dumps(fold.item(topic, slug))
