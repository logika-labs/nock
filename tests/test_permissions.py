"""What nock's agents may do: each dispatched seat's exact permissions, the
refusal of anything else, reported rather than hung on; no code path that
bypasses Claude Code's permission checks; and the rules `nock init` writes
into a project."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from nock.asking import ROLE as ASKER
from nock.chats import ADDRESSER, CHATTER, NAMER
from nock.consult import ROLE as CONSULTANT
from nock.dispatch import ARGUMENT_LIMIT, BYPASS, SEATS, Dispatcher
from nock.project import Project
from nock.reflect import Reflection
from nock.share import ROLE as SHARER
from nock.topics import TIDIER

from .conftest import FAKE_AGENT, nock, write_tool
from .test_telemetry_and_reflection import RECORD, finish
from .test_topics import submit

ROOT = Path(__file__).resolve().parents[1]
READING = "Read,Grep,Glob,Bash"
EXPECTED = {
    CONSULTANT: [
        "Bash(.nock/nock topics list:*)",
        "Bash(.nock/nock topics show:*)",
        "Bash(.nock/nock items list:*)",
        "Bash(.nock/nock items show:*)",
        "Bash(.nock/nock docs:*)",
        "Bash(.nock/nock advise:*)",
    ],
    ASKER: [
        "Bash(.nock/nock topics list:*)",
        "Bash(.nock/nock topics show:*)",
        "Bash(.nock/nock items list:*)",
        "Bash(.nock/nock items show:*)",
        "Bash(.nock/nock topics answer:*)",
        "Bash(git log:*)",
        "Bash(git show:*)",
    ],
    SHARER: ["Bash(git log:*)"],
    CHATTER: [
        "Bash(.nock/nock topics list:*)",
        "Bash(.nock/nock topics show:*)",
        "Bash(.nock/nock items list:*)",
        "Bash(.nock/nock items show:*)",
        "Bash(.nock/nock docs:*)",
        "Bash(git log:*)",
        "Bash(git show:*)",
    ],
    NAMER: [],
    TIDIER: [
        "Bash(.nock/nock topics list:*)",
        "Bash(.nock/nock topics show:*)",
        "Bash(.nock/nock topics create:*)",
        "Bash(.nock/nock topics update:*)",
        "Bash(.nock/nock topics delete:*)",
        "Bash(.nock/nock items list:*)",
        "Bash(.nock/nock items show:*)",
        "Bash(.nock/nock items update:*)",
        "Bash(.nock/nock items judge:*)",
        "Bash(.nock/nock docs:*)",
        "Bash(git log:*)",
        "Bash(git show:*)",
    ],
    ADDRESSER: [
        "Bash(.nock/nock topics list:*)",
        "Bash(.nock/nock topics show:*)",
        "Bash(.nock/nock topics update:*)",
        "Bash(.nock/nock items list:*)",
        "Bash(.nock/nock items show:*)",
        "Bash(.nock/nock items update:*)",
        "Bash(.nock/nock items remake:*)",
        "Bash(.nock/nock docs:*)",
        "Bash(.nock/nock check:*)",
        "Bash(.nock/nock test:*)",
        "Edit(./**)",
        "Write(./**)",
        "Bash(git log:*)",
        "Bash(git show:*)",
        "Bash(git diff:*)",
        "Bash(git status:*)",
    ],
}
WRITING_GIT = ["--disallowedTools", "Bash(git * --ou*)"]
DENIED = {
    CONSULTANT: [],
    ASKER: WRITING_GIT,
    SHARER: WRITING_GIT,
    CHATTER: WRITING_GIT,
    NAMER: [],
    TIDIER: WRITING_GIT,
    ADDRESSER: WRITING_GIT,
}
# The namer has no tools at all, so no rules either; the addresser edits.
TOOLS: dict[str, str] = {NAMER: "", ADDRESSER: "Read,Grep,Glob,Bash,Edit,Write"}


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
        TOOLS.get(role, READING),
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
    brief = (
        "NOTHING TO SHARE: <question> <intent> When each of the project's topics and items matters:"
        " nock's studio # The conversation # Tidy up Work # Address my comments"
        " # Their message <message>\nhi\n</message>"
    )
    session = Dispatcher(project).launch(role, brief, project.root)
    assert session.exit_code == 0 and session.denied == []
    assert launched(arguments) == seat_flags(role, EXPECTED[role]) + DENIED[role]


def test_the_consultant_runs_with_its_rules_and_a_refusal_is_kept(
    project: Project, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    arguments = tmp_path / "arguments.json"
    monkeypatch.setenv("FAKE_ARGUMENTS", str(arguments))
    monkeypatch.setenv("FAKE_TRY", json.dumps(["rm", "-rf", "src"]))
    consultation = {"intent": "Move orders to Postgres.", "context": "SQLite is slow."}
    result = nock(project.root, "consult", json.dumps(consultation))
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Nothing in nock bears on it." in result.stdout
    assert launched(arguments)[-len(EXPECTED[CONSULTANT]) :] == EXPECTED[CONSULTANT]
    assert "--disallowedTools" not in launched(arguments)
    [kept] = (project.root / ".nock" / "local" / "consultations").glob("*.json")
    assert json.loads(kept.read_text())["denied"] == ["Bash: rm -rf src"]
    [log] = (project.root / ".nock" / "local" / "logs").glob("run-*.log")
    assert "nock: Claude Code refused Bash: rm -rf src" in log.read_text()


def test_a_consultant_refused_its_only_way_to_answer_says_what_was_refused(
    project: Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FAKE_ADVICE", "nothing")
    monkeypatch.setenv("FAKE_TRY", json.dumps([".nock/nock", "items", "create", "x", "{}"]))
    consultation = {"intent": "Move orders to Postgres.", "context": "SQLite is slow."}
    result = nock(project.root, "consult", json.dumps(consultation))
    assert "refused: Bash: .nock/nock items create x {}" in result.stdout + result.stderr


def test_an_asker_that_tried_more_than_its_seat_allows_says_so(
    project: Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    submit(project.root)
    monkeypatch.setenv("FAKE_TRY", json.dumps([".nock/nock", "run", "--", "curl", "example.com"]))
    result = nock(project.root, "topics", "ask", "Where do orders live?", "--json")
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout)["answer"] == "Nothing says so."
    [log] = (project.root / ".nock" / "local" / "logs").glob("run-*.log")
    assert "nock: Claude Code refused Bash: .nock/nock run -- curl example.com" in log.read_text()


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
    consultation = {"intent": "Move orders to Postgres.", "context": "SQLite is slow."}
    result = nock(project.root, "consult", json.dumps(consultation))
    assert result.returncode != 0
    assert "never bypasses them" in result.stdout + result.stderr
    assert project.store.rows("SELECT id FROM sessions") == []


def test_nothing_nock_ships_or_runs_passes_a_bypass_flag() -> None:
    """Only the refusal in dispatch.py names them."""
    pattern = re.compile("|".join(re.escape(flag) for flag in BYPASS))
    definition = (ROOT / "src" / "nock" / "dispatch.py").read_text()
    start = definition.index("BYPASS = (")
    end = definition.index(")", start)
    found = []
    for directory in ("src", "evals", "scripts", ".github"):
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
    assert {"Bash(.nock/nock)", "Bash(.nock/nock check:*)", "Bash(.nock/nock items create:*)"} <= {
        *allowed
    }
    assert all(rule.startswith("Bash(.nock/nock") for rule in allowed)
    assert permissions["ask"] == [
        "Bash(.nock/nock topics judge:*)",
        "Bash(.nock/nock items judge:*)",
        "Bash(.nock/nock share:*)",
        "Bash(.nock/nock report:*)",
        "Bash(.nock/nock init:*)",
        "Bash(.nock/nock upgrade:*)",
    ]
    assert nock(project.root, "check", "nock-wiring").returncode == 0


def test_the_blanket_rule_earlier_versions_wrote_is_flagged_and_taken_out(
    project: Project,
) -> None:
    settings = project.root / ".claude" / "settings.json"
    written = json.loads(settings.read_text())
    written["permissions"]["allow"] += ["Bash(.nock/nock:*)", "Bash(npm test:*)"]
    settings.write_text(json.dumps(written))
    stale = nock(project.root, "check", "nock-wiring")
    assert stale.returncode == 1 and "`.nock/nock run` take any command" in stale.stdout
    assert nock(project.root, "init").returncode == 0
    allowed = json.loads(settings.read_text())["permissions"]["allow"]
    assert "Bash(.nock/nock:*)" not in allowed and "Bash(npm test:*)" in allowed
    assert nock(project.root, "check", "nock-wiring").returncode == 0


def test_a_new_tool_asks_until_init_allows_it(project: Project) -> None:
    write_tool(project, "work", "import nock\n\n@nock.command\ndef ship():\n    '''Ship it.'''\n")
    unwired = nock(project.root, "check", "nock-wiring")
    assert unwired.returncode == 1 and "`.nock/nock ship` is not allowed yet" in unwired.stdout
    assert nock(project.root, "init").returncode == 0
    settings = json.loads((project.root / ".claude" / "settings.json").read_text())
    assert "Bash(.nock/nock ship:*)" in settings["permissions"]["allow"]
    assert nock(project.root, "check", "nock-wiring").returncode == 0


def test_a_round_s_parts_are_subagents_with_only_the_tools_they_need(project: Project) -> None:
    agents = project.root / ".claude" / "agents"
    tools = {
        path.stem: re.search(r"^tools: (.*)$", path.read_text(), re.MULTILINE)
        for path in agents.glob("*.md")
    }
    assert {name: found and found.group(1) for name, found in tools.items()} == {
        "nock-reflect-toolbox": "Read, Grep, Glob, Edit, Write, Bash",
        "nock-reflect-map": "Read, Grep, Glob, Edit, Bash",
        "nock-reflect-nock": "Read, Grep, Glob, Bash",
    }
    lead = nock(project.root, "docs", "reflection.lead").stdout
    assert all(f"`{name}`" in lead for name in tools)


@pytest.mark.parametrize("option", ["--output=leak.txt", "--outp=leak.txt", "--ou=leak.txt"])
@pytest.mark.parametrize("role", [ASKER, SHARER])
def test_git_that_would_write_a_file_is_refused(
    project: Project, role: str, option: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FAKE_TRY", json.dumps(["git", "log", "-p", option]))
    session = Dispatcher(project).launch(role, "NOTHING TO SHARE: <question>", project.root)
    assert session.denied == [f"Bash: git log -p {option}"]
    assert not (project.root / "leak.txt").exists()


def test_a_sharer_refused_its_way_says_what_was_refused(
    project: Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    started = Reflection(project).start()
    for path, text in zip(started["write"], ("# Report\n", "Early days.\n"), strict=True):
        (project.root / path).write_text(text)
    assert finish(project, RECORD).returncode == 0
    monkeypatch.setenv("FAKE_SHARE", "nothing")
    monkeypatch.setenv("FAKE_TRY", json.dumps(["curl", "https://example.com"]))
    result = nock(project.root, "share")
    assert result.returncode == 1
    assert "refused: Bash: curl https://example.com" in result.stdout + result.stderr
