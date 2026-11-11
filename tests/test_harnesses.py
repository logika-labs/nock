"""The agent harnesses `nock init` wires: Claude Code always, Codex and Cursor
where the repository or PATH has them, each with its own skills, hooks and
instructions; what init prints; and the hooks answering in each harness's
format."""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

import pytest

from nock.harnesses import Harness
from nock.hooks import HookRunner
from nock.primer import MARK_END, MARK_START
from nock.project import Project
from nock.setup import Installer

from .conftest import git, nock
from .test_topics import submit

CODEX_COMMAND = '"$(git rev-parse --show-toplevel)"/.nock/nock hook {event} codex'
CURSOR_COMMAND = '"$(git rev-parse --show-toplevel)"/.nock/nock hook {event} cursor'


def hooks_of(path: Path) -> dict[str, list[str]]:
    """Each event's commands in a hooks file, Cursor's or the others'."""
    hooks = json.loads(path.read_text())["hooks"]
    return {
        event: [
            command
            for entry in entries
            for command in (
                [hook["command"] for hook in entry["hooks"]]
                if "hooks" in entry
                else [entry["command"]]
            )
        ]
        for event, entries in hooks.items()
    }


def on_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, command: str) -> None:
    directory = tmp_path / "bin"
    directory.mkdir(exist_ok=True)
    (directory / command).write_text("#!/bin/sh\n")
    (directory / command).chmod(0o755)
    monkeypatch.setenv("PATH", f"{directory}{os.pathsep}{os.environ['PATH']}")


def test_only_claude_code_is_wired_where_no_other_harness_is_found(repository: Path) -> None:
    said = Installer(repository).install()
    assert said[0] == "Found agent harnesses: Claude Code."
    assert said[1:3] == ["", "Added:"]
    listed = {line.split()[0] for line in said if line.startswith("  ")}
    assert {
        ".nock/core/",
        ".nock/nock",
        ".nock/context.md",
        "CLAUDE.md",
        ".claude/settings.json",
        ".claude/skills/nock-work/SKILL.md",
        ".claude/agents/nock-toolbox.md",
    } <= listed
    assert not any(path.startswith((".agents", ".codex", ".cursor", "AGENTS")) for path in listed)
    assert "(updated)" not in "\n".join(said), "everything is new"
    assert said[-1].startswith("Next: commit what nock changed")
    for absent in (".agents", ".codex", ".cursor", "AGENTS.md"):
        assert not (repository / absent).exists(), absent
    again = Installer(repository).install()
    assert again[0] == "Found agent harnesses: Claude Code."
    assert again[-2:] == ["", "Nothing changed: nock is set up and wired already."]


def test_codex_found_by_its_directory_gets_its_skill_hooks_and_the_agents_md_section(
    repository: Path,
) -> None:
    (repository / ".codex").mkdir()
    said = Installer(repository).install()
    assert said[0] == "Found agent harnesses: Claude Code, Codex."
    printed = "\n".join(said)
    for path in (".agents/skills/nock-work/SKILL.md", ".codex/hooks.json", "AGENTS.md"):
        assert f"  {path}" in printed, path
    assert "Codex runs a project's hooks once you trust them: `/hooks` in Codex." in printed
    work = (repository / ".claude" / "skills" / "nock-work" / "SKILL.md").read_text()
    assert (repository / ".agents" / "skills" / "nock-work" / "SKILL.md").read_text() == work
    assert not (repository / ".agents" / "skills" / "nock-triage").exists()
    assert hooks_of(repository / ".codex" / "hooks.json") == {
        event: [CODEX_COMMAND.format(event=event)]
        for event in ("PostToolUse", "SessionStart", "Stop", "UserPromptSubmit")
    }
    stop = json.loads((repository / ".codex" / "hooks.json").read_text())["hooks"]["Stop"]
    assert stop == [
        {
            "hooks": [
                {"type": "command", "command": CODEX_COMMAND.format(event="Stop"), "timeout": 300}
            ]
        }
    ]
    primer = (repository / ".nock" / "context.md").read_text()
    assert (
        repository / "AGENTS.md"
    ).read_text() == f"{MARK_START}\n{primer.rstrip()}\n{MARK_END}\n"
    assert (repository / "CLAUDE.md").read_text() == "@.nock/context.md\n"
    assert not (repository / ".cursor").exists()


def test_cursor_found_on_path_gets_hooks_and_the_section_but_no_copy_of_a_skill(
    repository: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    on_path(tmp_path, monkeypatch, "cursor-agent")
    (repository / "AGENTS.md").write_text("# Rules\n\nBe kind.\n")
    said = Installer(repository).install()
    assert said[0] == "Found agent harnesses: Claude Code, Cursor."
    wired = json.loads((repository / ".cursor" / "hooks.json").read_text())
    assert wired == {
        "version": 1,
        "hooks": {
            event: [{"command": CURSOR_COMMAND.format(event=native), "timeout": 300}]
            for event, native in (("sessionStart", "SessionStart"), ("stop", "Stop"))
        },
    }
    assert not (repository / ".cursor" / "skills").exists()
    assert not (repository / ".agents").exists(), "Cursor reads .claude/skills"
    agents = (repository / "AGENTS.md").read_text()
    assert agents.startswith(f"# Rules\n\nBe kind.\n\n{MARK_START}\n## nock\n")
    assert agents.endswith(f"{MARK_END}\n")
    assert "  AGENTS.md" in "\n".join(said) and "(updated)" in "\n".join(said)
    assert "`/hooks` in Codex" not in "\n".join(said)


def test_hooks_files_keep_everyone_else_s_entries_and_replace_nock_s(repository: Path) -> None:
    codex = repository / ".codex" / "hooks.json"
    codex.parent.mkdir()
    mine = {"hooks": [{"type": "command", "command": "./mine.sh"}]}
    stale = {"hooks": [{"type": "command", "command": ".nock/nock hook PreToolUse codex"}]}
    codex.write_text(json.dumps({"model": "x", "hooks": {"Stop": [mine], "PreToolUse": [stale]}}))
    Installer(repository).install()
    wired = json.loads(codex.read_text())
    assert wired["model"] == "x"
    assert "PreToolUse" not in wired["hooks"], "nock's stale entry is gone, and with it the event"
    assert hooks_of(codex)["Stop"] == ["./mine.sh", CODEX_COMMAND.format(event="Stop")]
    before = codex.read_text()
    again = "\n".join(Installer(repository).install())
    assert codex.read_text() == before and ".codex/hooks.json" not in again


def test_a_project_hook_is_wired_into_codex_but_not_into_cursor(
    repository: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (repository / ".codex").mkdir()
    (repository / ".cursor").mkdir()
    Installer(repository).install()
    tool = repository / ".nock" / "tools" / "guard.py"
    tool.write_text(
        "import nock\n\n\n@nock.hook('after-tool')\ndef guard(payload):\n    return 'seen'\n"
    )
    Installer(repository).install()
    assert hooks_of(repository / ".codex" / "hooks.json")["PostToolUse"] == [
        CODEX_COMMAND.format(event="PostToolUse")
    ]
    assert set(hooks_of(repository / ".cursor" / "hooks.json")) == {"sessionStart", "stop"}


def test_a_skill_copy_no_harness_found_reads_is_taken_out_unless_edited(repository: Path) -> None:
    (repository / ".codex").mkdir()
    Installer(repository).install()
    skill = repository / ".agents" / "skills" / "nock-work" / "SKILL.md"
    assert skill.is_file()
    shutil.rmtree(repository / ".codex")
    said = "\n".join(Installer(repository).install())
    assert not (repository / ".agents").exists()
    assert ".agents/skills/nock-work/SKILL.md" in said and "(removed)" in said
    skill.parent.mkdir(parents=True)
    skill.write_text("our own version\n")
    Installer(repository).install()
    assert skill.read_text() == "our own version\n"


def test_a_claude_md_importing_agents_md_reads_the_primer_once(repository: Path) -> None:
    (repository / "CLAUDE.md").write_text("@AGENTS.md\n\n@.nock/context.md\n")
    (repository / ".codex").mkdir()
    said = "\n".join(Installer(repository).install())
    assert (repository / "CLAUDE.md").read_text() == "@AGENTS.md\n"
    assert "imports AGENTS.md, which holds the primer" in said
    assert MARK_START in (repository / "AGENTS.md").read_text()
    shutil.rmtree(repository / ".codex")
    Installer(repository).install()
    assert (repository / "CLAUDE.md").read_text() == "@AGENTS.md\n", "AGENTS.md still holds it"


def test_the_agents_md_section_follows_the_committed_settings(repository: Path) -> None:
    (repository / ".codex").mkdir()
    Installer(repository).install()
    agents = repository / "AGENTS.md"
    agents.write_text(agents.read_text() + "\n## Ours\n\nKept.\n")
    config = repository / ".nock" / "shared" / "settings.toml"
    config.write_text(config.read_text().replace("reminders = true", "reminders = false"))
    git(repository, "add", "-A")
    git(repository, "commit", "-qm", "Quiet nock")
    HookRunner(Project.discover(repository), {"session_id": "s1"}, Harness.CODEX).handle(
        "SessionStart"
    )
    text = agents.read_text()
    assert "It stays quiet here" in text and "Consult before you change code" not in text
    assert text.endswith(f"{MARK_END}\n\n## Ours\n\nKept.\n")
    assert text.count(MARK_START) == 1


def test_codex_hears_claude_code_s_format_and_cursor_its_own(
    project: Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    tool = project.root / ".nock" / "tools" / "hello.py"
    tool.write_text("import nock\n\n\n@nock.command()\ndef hello() -> str:\n    return 'hi'\n")
    payload = json.dumps({"session_id": "x1", "cwd": str(project.root)})
    codex = nock(project.root, "hook", "SessionStart", "codex", stdin=payload)
    told = json.loads(codex.stdout)["hookSpecificOutput"]
    assert told["hookEventName"] == "SessionStart" and "hello" in told["additionalContext"]
    cursor = nock(
        project.root,
        "hook",
        "SessionStart",
        "cursor",
        stdin=json.dumps({"conversation_id": "c1", "workspace_roots": [str(project.root)]}),
    )
    assert "hello" in json.loads(cursor.stdout)["additional_context"]
    unknown = nock(project.root, "hook", "SessionStart", "emacs", stdin=payload)
    assert unknown.returncode == 0 and "unknown harness 'emacs'" in unknown.stderr

    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "c2")
    submit(project.root)
    stop = {"conversation_id": "c2", "workspace_roots": [str(project.root)], "loop_count": 1}
    assert HookRunner(project, stop, Harness.CURSOR).handle("Stop") is None
    asked = HookRunner(project, {**stop, "loop_count": 0}, Harness.CURSOR).handle("Stop")
    assert asked is not None and set(asked) == {"followup_message"}
    assert "orders" in asked["followup_message"]
