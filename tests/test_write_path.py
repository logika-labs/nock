"""The write path: what an agent writes in `.nock/shared/` with its own tools
is settled by the hook after that tool call — committed alone with the
session's attribution, or refused in the same turn with what is wrong — and
anything written where no hook saw it is swept up by the next nock command
or hook; each topic's readable view is kept current."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from nock.hooks import HookRunner
from nock.project import Project

from .conftest import git, nock

SHARED = Path(".nock") / "shared"


def write(project: Project, relative: str, record: Any) -> Path:
    path = project.root / SHARED / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record))
    return path


def after_tool(project: Project, **payload: Any) -> dict[str, Any] | None:
    return HookRunner(
        project,
        {"session_id": "s1", "tool_name": "Bash", "tool_input": {"command": "cat > x"}, **payload},
    ).handle("PostToolUse")


def test_the_hook_after_a_tool_commits_what_it_wrote_with_its_session(project: Project) -> None:
    write(project, "topics/orders/events/a.json", {"kind": "created", "description": "Orders."})
    assert after_tool(project) is None
    body = git(project.root, "log", "-1", "--format=%B")
    assert "Nock-Session: s1" in body and "Nock-On-Behalf: interactive" in body
    assert git(project.root, "status", "--porcelain") == ""
    view = project.local / "views" / "orders.md"
    assert view.read_text().startswith("# orders\n\nactive")
    assert "[orders](orders.md)" in (project.local / "views" / "index.md").read_text()
    # A subagent's call is its own, its session the parent.
    write(project, "topics/orders/events/b.json", {"kind": "message", "text": "Done."})
    after_tool(project, agent_id="a7", agent_type="Explore")
    body = git(project.root, "log", "-1", "--format=%B")
    assert "Nock-Session: a7" in body and "Nock-Parent-Session: s1" in body
    assert "Nock-On-Behalf: agent" in body


def test_a_bad_edit_is_refused_in_the_same_turn_and_nothing_of_it_is_committed(
    project: Project,
) -> None:
    head = git(project.root, "rev-parse", "HEAD")
    write(project, "topics/orders/events/a.json", {"kind": "created"})
    refused = after_tool(project)
    assert refused is not None and refused["decision"] == "block"
    assert "'description' is a required property" in refused["reason"]
    assert git(project.root, "rev-parse", "HEAD") == head
    # The turn cannot end while it stays so; fixed, it lands.
    stop = HookRunner(project, {"session_id": "s1"}).handle("Stop")
    assert stop is not None and "description" in stop["reason"]
    write(project, "topics/orders/events/a.json", {"kind": "created", "description": "Orders."})
    assert after_tool(project) is None
    assert git(project.root, "rev-parse", "HEAD") != head


def test_what_no_hook_saw_is_swept_up_by_the_next_command_or_hook(project: Project) -> None:
    write(project, "topics/orders/events/a.json", {"kind": "created", "description": "Orders."})
    listed = nock(project.root, "search", "orders", "--json")
    assert listed.returncode == 0, listed.stderr
    assert "Nock-Session: unknown" in git(project.root, "log", "-1", "--format=%B")
    assert [topic["name"] for topic in json.loads(listed.stdout)["topics"]] == ["orders"]
    write(project, "topics/orders/events/b.json", {"kind": "message", "text": "Hello."})
    HookRunner(project, {"session_id": "s2"}).handle("SessionStart")
    assert git(project.root, "status", "--porcelain") == ""
    # What does not hold stays, named on the command's stderr.
    write(project, "topics/orders/events/c.json", {"kind": "nonsense"})
    shown = nock(project.root, "status")
    assert shown.returncode == 0 and "don't hold and stay uncommitted" in shown.stderr


def test_the_hook_after_a_tool_hears_shell_commands_too(project: Project) -> None:
    settings = json.loads((project.root / ".claude" / "settings.json").read_text())
    (entry,) = settings["hooks"]["PostToolUse"]
    assert entry["matcher"].split("|")[-1] == "Bash" and "Edit" in entry["matcher"]
