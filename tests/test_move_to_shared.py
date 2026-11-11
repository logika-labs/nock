"""The one-off move of a project's topics from the layout nock kept them in
before `.nock/shared/` (`scripts/move-to-shared.py`): decisions with their
versions, asset items joined to the decision their thread names or wrapped
in a "Review" decision, verdicts and preferences kept, attachments into
media, what sessions were told staying told, round records moved — one
commit, and nothing left of the old layout."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from nock.project import Project
from nock.shared import digest
from nock.topics import Topics

from .conftest import git

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "move-to-shared.py"
PICTURE = b"\x89PNG\r\n\x1a\n" + bytes(range(64))


def write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(value, bytes):
        path.write_bytes(value)
    else:
        path.write_text(value if isinstance(value, str) else json.dumps(value))


def stamp(moment: str, session: str = "maker", role: str = "interactive") -> dict[str, Any]:
    return {"moment": moment, "session": session, "role": role}


def item(slug: str, title: str, versions: list[dict[str, Any]], **fields: Any) -> dict[str, Any]:
    return {
        "slug": slug,
        "title": title,
        "description": fields.pop("description", ""),
        "aliases": [],
        "verdict": "open",
        "decided": None,
        "created": stamp("2026-01-01T00:00:00Z"),
        "updated": "2026-01-05T00:00:00Z",
        "thread": [],
        "versions": versions,
        **fields,
    }


def old_layout(project: Project) -> dict[str, Any]:
    """An earlier nock's topics, written as it wrote them."""
    topics = project.root / ".nock" / "topics"
    orders = topics / "orders"
    write(
        orders / "topic.json",
        {
            "name": "orders",
            "description": "Where orders are kept.",
            "state": "active",
            "status": "half done",
            "created": stamp("2026-01-01T00:00:00Z"),
            "updated": "2026-01-03T00:00:00Z",
            "thread": [
                {
                    "kind": "status",
                    "author": "agent",
                    "moment": "2026-01-01T00:00:01Z",
                    "text": "half done",
                    "state": "active",
                    "status": "half done",
                    "session": "maker",
                },
                {
                    "author": "owner",
                    "moment": "2026-01-02T00:00:00Z",
                    "text": "See this.",
                    "attachments": [
                        {
                            "name": "trace.png",
                            "type": "image",
                            "bytes": len(PICTURE),
                            "path": "attachments/20260102/trace.png",
                            "local": False,
                        }
                    ],
                },
            ],
        },
    )
    write(orders / "attachments" / "20260102" / "trace.png", PICTURE)
    # A decision in two versions, the first with the README it concerns.
    sqlite = item(
        "sqlite",
        "Orders live in SQLite",
        [
            {
                "version": 1,
                **stamp("2026-01-01T00:00:00Z"),
                "files": [
                    {"kind": "decision", "name": "decision.json"},
                    {"kind": "project", "path": "README.md", "type": "text", "local": False},
                ],
            },
            {
                "version": 2,
                **stamp("2026-01-02T00:00:00Z"),
                "files": [{"kind": "decision", "name": "decision.json"}],
            },
        ],
        verdict="accepted",
        decided=stamp("2026-01-03T00:00:00Z", "triage"),
        thread=[
            {"author": "owner", "moment": "2026-01-02T12:00:00Z", "text": "Why not Postgres?"},
            {
                "author": "agent",
                "moment": "2026-01-02T13:00:00Z",
                "text": "Screenshots: [orders/sqlite-shot]",
                "session": "maker",
            },
        ],
    )
    write(orders / "sqlite" / "item.json", sqlite)
    write(orders / "sqlite" / "1" / "decision.json", {"answer": "One file.", "alternatives": []})
    write(orders / "sqlite" / "1" / "project" / "README.md", "# demo\n")
    write(
        orders / "sqlite" / "2" / "decision.json", {"answer": "Still one file.", "alternatives": []}
    )
    # Its screenshot, an item of its own the owner rejected after accepting the decision.
    shot = item(
        "sqlite-shot",
        "The orders page",
        [
            {
                "version": 1,
                **stamp("2026-01-02T00:00:00Z"),
                "files": [{"kind": "derived", "name": "page.png", "type": "image", "local": False}],
            }
        ],
        verdict="rejected",
        decided=stamp("2026-01-04T00:00:00Z", "triage"),
    )
    write(orders / "sqlite-shot" / "item.json", shot)
    write(orders / "sqlite-shot" / "1" / "page.png", PICTURE)
    # An asset item no decision names: variants, one preferred, accepted.
    banner = item(
        "banner",
        "Banner",
        [
            {
                "version": 1,
                **stamp("2026-01-01T00:00:00Z"),
                "files": [
                    {"kind": "derived", "name": name, "type": "image", "local": False}
                    for name in ("a.svg", "b.svg")
                ],
            }
        ],
        description="Two takes on the banner",
        variants=True,
        preferred={"version": 1, "name": "b.svg"},
        verdict="accepted",
        decided=stamp("2026-01-03T00:00:00Z", "triage"),
    )
    write(orders / "banner" / "item.json", banner)
    for name in ("a", "b"):
        write(orders / "banner" / "1" / f"{name}.svg", f"<svg><title>{name}</title></svg>")
    write(topics / "map.md", "- [orders/sqlite] holds.\n")
    reflections = project.root / ".nock" / "reflections"
    write(reflections / "2026-01-01" / "record.json", {"summary": "First round."})
    write(reflections / "2026-01-01" / "report.md", "# Report\n")
    write(reflections / "logika" / "2026-01-02" / "record.json", {"summary": "Rules."})
    git(project.root, "add", "-A")
    git(project.root, "commit", "-qm", "An earlier nock's topics")
    return sqlite


def script_module() -> Any:
    spec = importlib.util.spec_from_file_location("move_to_shared", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def move(project: Project, *arguments: str) -> dict[str, Any]:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), str(project.root), "--nock", str(ROOT / "src"), *arguments],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_the_old_layout_moves_into_the_store_once_in_one_commit(project: Project) -> None:
    sqlite = old_layout(project)
    # What a session was told of the owner's word, in the old layout's terms.
    project.store.insert(
        "told",
        {
            "session": "maker",
            "item": "orders/sqlite",
            "updated": script_module().legacy_word(sqlite),
        },
    )
    head = git(project.root, "rev-parse", "HEAD")
    assert move(project, "--dry-run") == {"topics": 1, "items": 3, "versions": 4, "rounds": 2}
    assert git(project.root, "rev-parse", "HEAD") == head
    moved = move(project)
    assert moved["topics"] == 1 and moved["items"] == 2 and moved["rounds"] == 2
    assert git(project.root, "rev-list", "--count", f"{head}..HEAD") == "1"
    assert git(project.root, "status", "--porcelain") == ""
    assert not (project.root / ".nock" / "topics").exists()
    assert not (project.root / ".nock" / "reflections").exists()
    topics = Topics(project)
    topic = topics.topic("orders")
    assert topic["state"] == "active" and topic["status"] == "half done"
    (said,) = [entry for entry in topic["thread"] if entry.get("attachments")]
    (trace,) = said["attachments"]
    assert said["author"] == "owner" and trace["sha256"] == digest(PICTURE)
    assert topics.where(trace, "orders").read_bytes() == PICTURE
    # The decision, its versions, its README linked at the commit that made it,
    # and the screenshot its thread names as one of its assets.
    decision = topics.item("orders/sqlite")
    assert [version["version"] for version in decision["versions"]] == [1, 2]
    assert topics.decision(decision, decision["versions"][1]) == {
        "answer": "Still one file.",
        "alternatives": [],
    }
    assets = {asset["name"]: asset for asset in decision["assets"]}
    assert set(assets) == {"readme-md", "sqlite-shot"}
    (readme,) = assets["readme-md"]["versions"][0]["files"]
    assert readme["commit"] == head and "sha256" not in readme
    (page,) = assets["sqlite-shot"]["versions"][0]["files"]
    assert page["sha256"] == digest(PICTURE)
    assert decision["created"]["session"] == "maker" and "orders/sqlite-shot" in decision["aliases"]
    assert topics.item("orders/sqlite-shot")["ref"] == "orders/sqlite"
    # The owner rejected the screenshot after accepting the decision: rework it.
    assert decision["verdict"] == "rejected"
    # An asset item no decision names: a "Review" decision holding it, its pick kept.
    banner = topics.item("orders/banner")
    assert banner["title"] == "Review: Banner" and banner["verdict"] == "accepted"
    (asset,) = banner["assets"]
    assert asset["variants"] is True and asset["preferred"] == {"version": 1, "name": "b.svg"}
    assert topics.map.read_text() == "- [orders/sqlite] holds.\n"
    assert topics.citation_problems() == []
    # What the maker was told stays told; what it never was is news to it.
    assert [news["ref"] for news in topics.news_for("maker")] == ["orders/banner"]
    rounds = project.root / ".nock" / "shared" / "rounds"
    for name in ("nock.toolbox", "nock.map", "nock.fit"):
        record = json.loads((rounds / name / "2026-01-01" / "record.json").read_text())
        assert record == {"summary": "First round.", "protocol": name}
        assert (rounds / name / "2026-01-01" / "report.md").is_file()
    for name in ("logika.rules", "logika.analytics"):
        assert (rounds / name / "2026-01-02" / "record.json").is_file()
    assert move(project) == {"moved": False, "why": "no .nock/topics/ to move"}
