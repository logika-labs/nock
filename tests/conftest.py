"""Real repositories, real processes, real SQLite: a project is a fresh git
repository with nock installed into it, and the reflecting agent is a scripted
stand-in process."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

from nock.prices import Prices
from nock.project import Project
from nock.setup import Installer

FAKE_AGENT = Path(__file__).with_name("fake_agent.py")
# A copy of a few entries of LiteLLM's price table, so no test reaches the network.
PRICES = Path(__file__).with_name("prices.json")


def git(directory: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", *arguments], cwd=directory, check=True, capture_output=True, text=True
    ).stdout.strip()


@pytest.fixture(autouse=True)
def isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """No Claude Code session, nock seat, git identity or display leaks in from outside."""
    for name in list(os.environ):
        if name.startswith(("CLAUDE", "NOCK_", "GIT_")):
            monkeypatch.delenv(name)
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude"))
    monkeypatch.setenv("GIT_AUTHOR_NAME", "Test")
    monkeypatch.setenv("GIT_AUTHOR_EMAIL", "test@example.com")
    monkeypatch.setenv("GIT_COMMITTER_NAME", "Test")
    monkeypatch.setenv("GIT_COMMITTER_EMAIL", "test@example.com")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(tmp_path / "gitconfig"))
    # No display: a test never shows the owner a desktop notification.
    monkeypatch.setenv("CI", "1")
    # Only Claude Code, unless a test puts another harness's command on PATH.
    harnesses = ("codex", "cursor", "cursor-agent")
    monkeypatch.setenv(
        "PATH",
        os.pathsep.join(
            directory
            for directory in os.environ.get("PATH", "").split(os.pathsep)
            if not any((Path(directory) / name).exists() for name in harnesses)
        ),
    )
    yield


@pytest.fixture
def repository(tmp_path: Path) -> Path:
    root = tmp_path / "repository"
    root.mkdir()
    git(root, "init", "-q", "-b", "main")
    (root / "README.md").write_text("# demo\n")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "init")
    return root


@pytest.fixture
def project(repository: Path, monkeypatch: pytest.MonkeyPatch) -> Project:
    """A repository with nock installed and committed, the agent a stand-in."""
    Installer(repository).install()
    local = repository / ".nock" / "local"
    local.mkdir(exist_ok=True)
    (local / "config.toml").write_text(
        f'[agent]\ncommand = ["{sys.executable}", "{FAKE_AGENT}"]\n[upgrade]\ncheck = false\n'
    )
    git(repository, "add", "-A")
    git(repository, "commit", "-q", "-m", "Add nock")
    monkeypatch.chdir(repository)
    project = Project.discover(repository)
    Prices(project, PRICES.as_uri()).table()
    return project


def nock(
    directory: Path, *arguments: str, stdin: str | None = None
) -> subprocess.CompletedProcess[str]:
    """The CLI, run as an agent runs it: the project's vendored copy."""
    return subprocess.run(
        [str(directory / ".nock" / "nock"), *arguments],
        cwd=directory,
        capture_output=True,
        text=True,
        input=stdin,
        env={**os.environ, "NOCK_PYTHON": sys.executable},
    )


def write_tool(project: Project, name: str, source: str) -> None:
    """A module in the project's `.nock/tools/`, committed."""
    path = project.root / ".nock" / "tools" / f"{name}.py"
    path.write_text(source)
    git(project.root, "add", "-A")
    git(project.root, "commit", "-qm", f"Add tool {name}")


def own_protocol(project: Project, name: str, due: dict[str, object]) -> None:
    """A project's own copy of a shipped protocol in `.nock/rounds/`, its due
    rules changed: how a project sets when a round is due."""
    namespace, protocol = name.split(".")
    shipped = project.root / ".nock" / "core" / "nock" / "rounds" / namespace / protocol
    target = project.root / ".nock" / "rounds" / namespace / protocol
    shutil.copytree(shipped, target, dirs_exist_ok=True)
    manifest = target / "round.toml"
    text = manifest.read_text()
    head, _, rest = text.partition("[due]\n")
    rules, _, tail = rest.partition("\n\n")
    kept = {line.split(" = ")[0]: line for line in rules.splitlines() if " = " in line}
    for key, value in due.items():
        kept[key] = f"{key} = {json.dumps(value)}"
    manifest.write_text(head + "[due]\n" + "\n".join(kept.values()) + "\n\n" + tail)
