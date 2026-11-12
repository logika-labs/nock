"""What a hook costs: it runs on every tool call, so it loads only the modules
its event needs, finds the repository without starting git, loads the
project's toolbox only when it has a hook for the event, and leaves nock's
bytecode cached even when the owner keeps Python from writing it."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from nock.git import Git, located
from nock.project import Project

from .conftest import git, nock, write_tool

# Runs the vendored nock as `python -m nock` does, then reports the nock
# modules it loaded and every process it started.
PROBE = """
import atexit, json, os, runpy, sys
started = []

def audit(event, arguments):
    if event == "subprocess.Popen":
        started.append([str(word) for word in arguments[1]])

def report():
    loaded = sorted(name for name in sys.modules if name == "nock" or name.startswith("nock."))
    with open(os.environ["PROBE_REPORT"], "w") as handle:
        json.dump({"modules": loaded, "started": started}, handle)

sys.addaudithook(audit)
atexit.register(report)
sys.argv = ["nock", *sys.argv[1:]]
runpy.run_module("nock", run_name="__main__", alter_sys=True)
"""
# What the hook after a `.nock/nock` command needs, and nothing more.
BEFORE_TOOL_MODULES = {
    "nock",
    "nock.callers",
    "nock.configuration",
    "nock.environment",
    "nock.errors",
    "nock.git",
    "nock.harnesses",
    "nock.hooks",
    "nock.project",
    "nock.store",
    "nock.utils",
}
# The prompt and edit hooks read Topics too, from the store.
TOPICS_MODULES = {
    "nock.notify",
    "nock.render",
    "nock.condense",
    "nock.topics",
    "nock.fold",
    "nock.records",
    "nock.schema",
    "nock.shared",
}
NEVER_IN_A_HOOK = {"nock.cli", "nock.builtin", "nock.tools", "nock.reflect", "nock.kinds"}


def probe(project: Project, event: str, payload: dict[str, Any]) -> dict[str, Any]:
    report = project.root / ".nock" / "local" / "probe.json"
    result = subprocess.run(
        [sys.executable, "-c", PROBE, "hook", event],
        cwd=project.root,
        input=json.dumps({"cwd": str(project.root), **payload}),
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "PYTHONPATH": str(project.root / ".nock" / "core"),
            "PROBE_REPORT": str(report),
        },
    )
    assert result.returncode == 0, result.stderr
    found = json.loads(report.read_text())
    report.unlink()
    return {**found, "stdout": result.stdout, "stderr": result.stderr}


def git_calls(found: dict[str, Any]) -> list[list[str]]:
    return [words for words in found["started"] if Path(words[0]).name == "git"]


PAYLOADS = {
    "PreToolUse": {
        "session_id": "s1",
        "tool_name": "Bash",
        "tool_input": {"command": ".nock/nock topics list"},
    },
    "PostToolUse": {
        "session_id": "s1",
        "tool_name": "Edit",
        "tool_input": {"file_path": "README.md"},
    },
    "UserPromptSubmit": {"session_id": "s1", "prompt": "go on"},
}


@pytest.mark.parametrize("event", list(PAYLOADS))
def test_a_hook_loads_only_what_its_event_needs_and_starts_no_more_than_one_git(
    project: Project, event: str
) -> None:
    nock(project.root, "hook", event, stdin=json.dumps(PAYLOADS[event]))
    found = probe(project, event, PAYLOADS[event])
    modules = set(found["modules"])
    allowed = BEFORE_TOOL_MODULES | (TOPICS_MODULES if event != "PreToolUse" else set())
    assert modules <= allowed, sorted(modules - allowed)
    assert not modules & NEVER_IN_A_HOOK
    assert len(git_calls(found)) <= 1, git_calls(found)
    assert found["stdout"] == ""


def test_the_toolbox_loads_for_a_hook_only_when_the_project_has_one_for_the_event(
    project: Project,
) -> None:
    payload = PAYLOADS["PreToolUse"]
    write_tool(
        project,
        "noting",
        "import nock\n\n@nock.hook('after-tool')\ndef noted(payload) -> str:\n    return 'edited'\n",
    )
    first = probe(project, "PreToolUse", payload)
    assert "nock.tools" in first["modules"]
    again = probe(project, "PreToolUse", payload)
    assert "nock.tools" not in again["modules"]
    edited = probe(project, "PostToolUse", PAYLOADS["PostToolUse"])
    assert "nock.tools" in edited["modules"]
    assert "edited" in json.loads(edited["stdout"])["hookSpecificOutput"]["additionalContext"]
    write_tool(
        project,
        "noting",
        "import nock\n\n@nock.hook('before-tool')\ndef noting(payload) -> str:\n    return 'about to run'\n",
    )
    changed = probe(project, "PreToolUse", payload)
    assert "nock.tools" in changed["modules"]
    context = json.loads(changed["stdout"])["hookSpecificOutput"]["additionalContext"]
    assert context == "about to run"


def test_the_repository_is_found_from_its_files_as_git_finds_it(
    repository: Path, tmp_path: Path
) -> None:
    (repository / "deep" / "er").mkdir(parents=True)
    worktree = tmp_path / "worktree"
    git(repository, "worktree", "add", "-q", "-b", "side", str(worktree))
    (worktree / "inside").mkdir()
    link = tmp_path / "link"
    link.symlink_to(repository)
    for directory in (repository, repository / "deep" / "er", worktree, worktree / "inside", link):
        directory = directory.resolve()
        toplevel = Path(git(directory, "rev-parse", "--show-toplevel"))
        common = git(directory, "rev-parse", "--path-format=absolute", "--git-common-dir")
        assert located(directory) == (toplevel, Path(common).parent), directory
        assert Git(directory).location() == (toplevel, Path(common).parent)
    assert located((repository / ".git").resolve()) is None
    os.environ["GIT_DIR"] = str(repository / ".git")
    try:
        assert located(repository.resolve()) is None
    finally:
        del os.environ["GIT_DIR"]


def test_nock_s_bytecode_is_cached_even_when_python_is_told_not_to_write_it(
    project: Project,
) -> None:
    write_tool(
        project, "plain", "import nock\n\n@nock.command\ndef plain() -> str:\n    return 'ok'\n"
    )
    core = project.root / ".nock" / "core" / "nock"
    environment = {**os.environ, "NOCK_PYTHON": sys.executable, "PYTHONDONTWRITEBYTECODE": "1"}
    for arguments in (["hook", "PreToolUse"], ["plain"]):
        subprocess.run(
            [str(project.root / ".nock" / "nock"), *arguments],
            cwd=project.root,
            input="{}",
            capture_output=True,
            text=True,
            env=environment,
            check=True,
        )
    tag = sys.implementation.cache_tag
    assert (core / "__pycache__" / f"hooks.{tag}.pyc").is_file()
    assert (core / "__pycache__" / f"cli.{tag}.pyc").is_file()
    assert not (project.root / ".nock" / "tools" / "__pycache__").exists()
    assert git(project.root, "status", "--porcelain") == ""
