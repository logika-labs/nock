"""What nock's agents may do: each dispatched seat's exact permissions, the
refusal of anything else, reported rather than hung on; no code path that
bypasses Claude Code's permission checks; and the rules `nock init` writes
into a project."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from nock.dispatch import ARGUMENT_LIMIT, BYPASS, SEATS, Dispatcher
from nock.errors import PolicyError
from nock.project import Project
from nock.rounds import named
from nock.share import ROLE as SHARER

from .conftest import FAKE_AGENT, nock, write_tool
from .test_telemetry_and_reflection import RECORD
from .test_telemetry_and_reflection import submit as submit_round

ROOT = Path(__file__).resolve().parents[1]
READING = "Read,Grep,Glob,Bash"
GIT = ["Bash(git log:*)", "Bash(git show:*)"]
EXPECTED = {SHARER: ["Bash(git log:*)"]}
WRITING_GIT = ["--disallowedTools", "Bash(git * --ou*)"]
DENIED = {SHARER: WRITING_GIT}


def seat_flags(role: str, allowed: list[str]) -> list[str]:
    return [
        "-p",
        "--output-format",
        "stream-json",
        "--verbose",
        "--permission-mode",
        "dontAsk",
        "--setting-sources",
        "user",
        "--strict-mcp-config",
        "--tools",
        READING,
        *(["--allowedTools", *allowed] if allowed else []),
    ]


def launched(path: Path) -> list[str]:
    """The command line the fake agent was started with, after the agent itself."""
    arguments = json.loads(path.read_text())
    return arguments[: arguments.index("--session-id")]


def test_every_seat_is_one_nock_knows() -> None:
    assert set(SEATS) == set(EXPECTED)


@pytest.mark.parametrize("role", sorted(EXPECTED))
def test_each_seat_gets_exactly_its_tools_and_rules(
    project: Project, role: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    arguments = tmp_path / "arguments.json"
    monkeypatch.setenv("FAKE_ARGUMENTS", str(arguments))
    brief = "NOTHING TO SHARE: or the summary, vetted"
    session = Dispatcher(project).launch(role, brief, project.root)
    assert session.exit_code == 0 and session.denied == []
    assert launched(arguments) == seat_flags(role, EXPECTED[role]) + DENIED[role]


def test_a_refusal_is_kept_with_the_session_and_in_its_log(
    project: Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FAKE_TRY", json.dumps([".nock/nock", "run", "--", "curl", "example.com"]))
    session = Dispatcher(project).launch(SHARER, "NOTHING TO SHARE: or the summary", project.root)
    assert session.exit_code == 0
    assert session.denied == ["Bash: .nock/nock run -- curl example.com"]
    assert "nock: Claude Code refused Bash: .nock/nock run -- curl example.com" in (
        session.log.read_text()
    )


def test_a_long_brief_is_readable_and_nothing_else_outside(project: Project) -> None:
    prompt, allowed = Dispatcher(project).carried("s1", "x" * (ARGUMENT_LIMIT + 1))
    path = project.local / "briefs" / "s1.md"
    assert str(path) in prompt and allowed == (f"Read(/{path.resolve()})",)
    assert Dispatcher(project).carried("s2", "short") == ("short", ())


@pytest.mark.parametrize(
    "flag", ["--dangerously-skip-permissions", "--permission-mode=bypassPermissions", "--tools"]
)
def test_an_agent_command_that_sets_permissions_itself_is_refused(
    project: Project, flag: str
) -> None:
    local = project.root / ".nock" / "local" / "config.toml"
    local.write_text(local.read_text().replace(f'"{FAKE_AGENT}"]', f'"{FAKE_AGENT}", "{flag}"]', 1))
    with pytest.raises(PolicyError, match="never bypasses them"):
        Dispatcher(Project.discover(project.root)).launch(SHARER, "NOTHING TO SHARE:", project.root)
    assert project.store.rows("SELECT id FROM sessions") == []


def test_nothing_nock_ships_or_runs_passes_a_bypass_flag() -> None:
    """Only the refusal in dispatch.py names them."""
    pattern = re.compile("|".join(re.escape(flag) for flag in BYPASS))
    definition = (ROOT / "src" / "nock" / "dispatch.py").read_text()
    start = definition.index("BYPASS = (")
    end = definition.index(")", start)
    found = []
    for directory in ("src", "scripts", ".github"):
        for path in sorted((ROOT / directory).rglob("*")):
            if not path.is_file() or path.suffix not in (".py", ".md", ".toml", ".json", ".yml"):
                continue
            text = path.read_text()
            if path.name == "dispatch.py" and path.parent.name == "nock":
                text = text[:start] + text[end:]
            found += [f"{path.relative_to(ROOT)}: {match}" for match in pattern.findall(text)]
    assert found == []


def test_init_allows_each_command_but_run_and_asks_for_the_owner_s(project: Project) -> None:
    permissions = json.loads((project.root / ".claude" / "settings.json").read_text())[
        "permissions"
    ]
    allowed = permissions["allow"]
    assert "Bash(.nock/nock:*)" not in allowed
    assert not [rule for rule in allowed if "nock run" in rule]
    assert {"Bash(.nock/nock)", "Bash(.nock/nock check:*)", "Bash(.nock/nock docs:*)"} <= {*allowed}
    assert all(rule.startswith("Bash(.nock/nock") for rule in allowed)
    assert permissions["ask"] == [
        "Bash(.nock/nock share:*)",
        "Bash(.nock/nock report:*)",
        "Bash(.nock/nock init:*)",
        "Bash(.nock/nock upgrade:*)",
    ]
    assert nock(project.root, "check", "nock-wiring").returncode == 0


def test_a_new_tool_asks_until_init_allows_it(project: Project) -> None:
    write_tool(project, "work", "import nock\n\n@nock.command\ndef ship():\n    '''Ship it.'''\n")
    unwired = nock(project.root, "check", "nock-wiring")
    assert unwired.returncode == 1 and "`.nock/nock ship` is not allowed yet" in unwired.stdout
    assert nock(project.root, "init").returncode == 0
    settings = json.loads((project.root / ".claude" / "settings.json").read_text())
    assert "Bash(.nock/nock ship:*)" in settings["permissions"]["allow"]
    assert nock(project.root, "check", "nock-wiring").returncode == 0


def test_a_subround_s_parts_are_subagents_with_only_the_tools_they_need(project: Project) -> None:
    agents = project.root / ".claude" / "agents"
    tools = {
        path.stem: re.search(r"^tools: (.*)$", path.read_text(), re.MULTILINE)
        for path in agents.glob("*.md")
    }
    assert {name: found and found.group(1) for name, found in tools.items()} == {
        "nock-toolbox": "Read, Grep, Glob, Edit, Write, Bash",
        "nock-fit": "Read, Grep, Glob, Bash",
        # Every subround that can run here is on: the audits' agents too.
        "audit-security": "Read, Grep, Glob, Bash",
        "audit-tests-package": "Read, Grep, Glob, Bash",
        "audit-tests-promises": "Read, Grep, Glob, Bash",
    }
    for name in ("nock.fit", "nock.toolbox"):
        begun = json.loads(nock(project.root, "reflect", name, "--json").stdout)
        (agent,) = begun["agents"]
        brief = nock(project.root, "docs", name).stdout
        assert agent["type"] in tools and f"`{agent['type']}`" in brief


@pytest.mark.parametrize("option", ["--output=leak.txt", "--outp=leak.txt", "--ou=leak.txt"])
@pytest.mark.parametrize("role", [SHARER])
def test_git_that_would_write_a_file_is_refused(
    project: Project, role: str, option: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FAKE_TRY", json.dumps(["git", "log", "-p", option]))
    brief = "NOTHING TO SHARE: or the summary, vetted"
    session = Dispatcher(project).launch(role, brief, project.root)
    assert session.denied == [f"Bash: git log -p {option}"]
    assert not (project.root / "leak.txt").exists()


def test_a_sharer_refused_its_way_says_what_was_refused(
    project: Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    (fit,) = named(project, "nock.fit")
    started = fit.start()
    for path, text in zip(started["write"], ("# Report\n", "Early days.\n"), strict=True):
        Path(path).write_text(text)
    assert submit_round(project, RECORD).returncode == 0
    monkeypatch.setenv("FAKE_SHARE", "nothing")
    monkeypatch.setenv("FAKE_TRY", json.dumps(["curl", "https://example.com"]))
    result = nock(project.root, "share")
    assert result.returncode == 1
    assert "refused: Bash: curl https://example.com" in result.stdout + result.stderr
