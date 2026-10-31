from __future__ import annotations

import io
import json
import re
import shutil
import subprocess
import threading
import tomllib
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from nock.hooks import HookRunner
from nock.project import Project
from nock.releases import NAME, VERSION, Updates, parsed
from nock.setup import PACKAGE, Installer, Upgrader, core_files

from .conftest import git, nock, write_tool


def test_init_is_idempotent_and_keeps_the_project_s_settings(repository: Path) -> None:
    settings = repository / ".claude" / "settings.json"
    settings.parent.mkdir()
    settings.write_text(
        json.dumps(
            {"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "mine"}]}]}, "model": "x"}
        )
    )
    (repository / "CLAUDE.md").write_text("# Rules\n\nBe kind.\n")
    Installer(repository).install()
    wired = json.loads(settings.read_text())
    assert wired["model"] == "x"
    commands = [hook["command"] for entry in wired["hooks"]["Stop"] for hook in entry["hooks"]]
    assert commands == ["mine", '"$CLAUDE_PROJECT_DIR"/.nock/nock hook Stop']
    started = [
        hook["command"] for entry in wired["hooks"]["SessionStart"] for hook in entry["hooks"]
    ]
    assert started == ['"$CLAUDE_PROJECT_DIR"/.nock/nock hook SessionStart']
    assert (repository / "CLAUDE.md").read_text() == "# Rules\n\nBe kind.\n\n@.nock/context.md\n"
    shutil.rmtree(repository / ".nock" / "core")
    Installer(repository).install()
    again = json.loads(settings.read_text())
    assert again == wired
    assert (repository / "CLAUDE.md").read_text().count("@.nock/context.md") == 1


def test_the_vendored_shim_runs_the_project_s_own_copy(project: Project) -> None:
    marker = project.root / ".nock" / "core" / "nock" / "builtin.py"
    marker.write_text(
        marker.read_text().replace('"""nock\'s documentation', '"""VENDORED nock\'s documentation')
    )
    result = subprocess.run(
        [str(project.root / ".nock" / "nock")],
        cwd=project.root,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "— VENDORED nock's documentation" in result.stdout


def test_upgrade_merges_upstream_into_a_locally_edited_core(
    project: Project, tmp_path: Path
) -> None:
    upstream = tmp_path / "upstream"
    shutil.copytree(
        PACKAGE, upstream / "src" / "nock", ignore=shutil.ignore_patterns("__pycache__")
    )
    (upstream / "pyproject.toml").write_text('version = "0.2.0"\n')
    git(upstream, "init", "-q", "-b", "main")
    git(upstream, "add", "-A")
    git(upstream, "commit", "-qm", "base")
    base = git(upstream, "rev-parse", "HEAD")
    core = project.root / ".nock" / "core"
    shutil.rmtree(core / "nock")
    shutil.copytree(upstream / "src" / "nock", core / "nock")
    (core / "VERSION.json").write_text(
        json.dumps({"version": "0.1.0", "source": str(upstream), "commit": base})
    )
    ours = core / "nock" / "utils.py"
    ours.write_text(ours.read_text() + "\n\ndef local_helper() -> int:\n    return 1\n")
    theirs = upstream / "src" / "nock" / "utils.py"
    theirs.write_text(
        '"""Upstream changed the docstring."""\n' + theirs.read_text().split("\n", 1)[1]
    )
    (upstream / "src" / "nock" / "new_module.py").write_text("VALUE = 2\n")
    git(upstream, "add", "-A")
    git(upstream, "commit", "-qm", "next")
    report = Upgrader(project).upgrade()
    assert not report.conflicts
    merged = ours.read_text()
    assert merged.startswith('"""Upstream changed the docstring."""') and "local_helper" in merged
    assert (core / "nock" / "new_module.py").read_text() == "VALUE = 2\n"
    assert json.loads((core / "VERSION.json").read_text())["version"] == "0.2.0"


class Index:
    """A stand-in for PyPI's JSON API: releases by version, each a wheel of
    the `nock` package."""

    def __init__(self) -> None:
        self.releases: dict[str, dict[str, bytes]] = {}
        self.asked = 0
        index = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                index.asked += 1
                parts = self.path.strip("/").split("/")
                if parts[-1].endswith(".whl"):
                    body = index.wheel(parts[-1].split("-")[1])
                elif parts == ["json"]:
                    body = json.dumps(index.release(max(index.releases, key=parsed))).encode()
                elif len(parts) == 2 and parts[0] in index.releases:
                    body = json.dumps(index.release(parts[0])).encode()
                else:
                    self.send_response(404)
                    self.end_headers()
                    return
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format: str, *arguments: object) -> None:
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"

    def release(self, version: str) -> dict[str, object]:
        wheel = f"{self.url}/files/nock-{version}-py3-none-any.whl"
        return {
            "info": {"version": version},
            "urls": [{"packagetype": "bdist_wheel", "url": wheel}],
        }

    def wheel(self, version: str) -> bytes:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            for name, content in self.releases[version].items():
                archive.writestr(f"nock/{name}", content)
            archive.writestr(f"nock-{version}.dist-info/METADATA", "Name: nock\n")
        return buffer.getvalue()


def use(project: Project, index: Index, check: bool) -> None:
    local = project.root / ".nock" / "local" / "config.toml"
    text = re.sub(r"\[upgrade\]\n(?:[^\[\n].*\n)*", "", local.read_text())
    local.write_text(text + f'[upgrade]\ncheck = {str(check).lower()}\nindex = "{index.url}"\n')


def test_upgrade_merges_the_latest_release_from_pypi_and_rewires(project: Project) -> None:
    index = Index()
    base = core_files(PACKAGE)
    index.releases[VERSION] = base
    theirs = dict(base)
    theirs["utils.py"] = (
        b'"""Upstream changed the docstring."""\n' + base["utils.py"].split(b"\n", 1)[1]
    )
    theirs["new_module.py"] = b"VALUE = 2\n"
    index.releases["9.0.0"] = theirs
    use(project, index, check=False)
    ours = project.root / ".nock" / "core" / "nock" / "utils.py"
    ours.write_text(ours.read_text() + "\n\ndef local_helper() -> int:\n    return 1\n")
    (project.root / ".claude" / "skills" / "nock-triage" / "SKILL.md").unlink()
    result = nock(project.root, "upgrade")
    assert result.returncode == 0, result.stdout + result.stderr
    merged = ours.read_text()
    assert merged.startswith('"""Upstream changed the docstring."""') and "local_helper" in merged
    assert (ours.parent / "new_module.py").read_text() == "VALUE = 2\n"
    version = json.loads((project.root / ".nock" / "core" / "VERSION.json").read_text())
    assert version == {"version": "9.0.0", "source": "pypi", "commit": None}
    assert (project.root / ".claude" / "skills" / "nock-triage" / "SKILL.md").is_file()
    index.server.shutdown()


def test_a_session_start_says_when_a_newer_nock_is_out_once_a_day(project: Project) -> None:
    index = Index()
    index.releases[VERSION] = {}
    use(project, index, check=True)
    start = HookRunner(project, {"session_id": "s1"}).handle("SessionStart")
    assert start is None or "is out" not in start.get("systemMessage", "")
    index.releases["9.0.0"] = {}
    asked = index.asked
    HookRunner(project, {"session_id": "s2"}).handle("SessionStart")
    assert index.asked == asked
    Updates(project).cache.unlink()
    start = HookRunner(project, {"session_id": "s3"}).handle("SessionStart")
    assert (
        start is not None
        and f"nock 9.0.0 is out (this project has {VERSION})" in start["systemMessage"]
    )
    assert json.loads(nock(project.root, "status", "--json").stdout)["newer_nock"] == "9.0.0"
    use(project, index, check=False)
    assert json.loads(nock(project.root, "status", "--json").stdout)["newer_nock"] is None
    index.server.shutdown()


def test_the_version_is_the_package_s() -> None:
    pyproject = tomllib.loads((Path(__file__).parents[1] / "pyproject.toml").read_text())
    assert pyproject["project"]["version"] == VERSION and pyproject["project"]["name"] == NAME


OWNER_TOOLS = '''\
import nock


@nock.command(confirm=True)
def deploy(host: str) -> str:
    """Deploy to a live box."""
    return f"deployed to {host}"


@nock.command(confirm=True, group="release")
def publish() -> None:
    """Publish the packages."""
'''


def test_a_command_that_needs_the_owner_s_word_is_asked_for_in_claude_code(
    project: Project,
) -> None:
    settings = project.root / ".claude" / "settings.json"
    write_tool(project, "owner", OWNER_TOOLS)
    unwired = nock(project.root, "check", "nock-wiring")
    assert unwired.returncode == 1
    assert "`deploy` needs the owner's word" in unwired.stdout
    assert nock(project.root, "init").returncode == 0
    permissions = json.loads(settings.read_text())["permissions"]
    assert permissions["ask"] == ["Bash(.nock/nock deploy:*)", "Bash(.nock/nock release publish:*)"]
    assert "Bash(.nock/nock:*)" in permissions["allow"]
    assert nock(project.root, "check", "nock-wiring").returncode == 0
    listed = nock(project.root).stdout
    assert "deploy HOST — Deploy to a live box (asks the owner)" in listed
    assert nock(project.root, "deploy", "box-1").stdout == "deployed to box-1\n"
    (project.root / ".nock" / "tools" / "owner.py").unlink()
    assert nock(project.root, "init").returncode == 0
    assert "ask" not in json.loads(settings.read_text())["permissions"]


def test_init_in_a_worktree_installs_there_and_leaves_the_main_checkout_alone(
    repository: Path,
) -> None:
    worktree = repository.with_name("feature")
    git(repository, "worktree", "add", "-q", "-b", "feature", str(worktree))
    Installer(worktree).install()
    assert (worktree / ".nock" / "nock").is_file()
    assert (worktree / ".claude" / "settings.json").is_file()
    assert "@.nock/context.md" in (worktree / "CLAUDE.md").read_text()
    assert not (repository / ".nock").exists()
    assert not (repository / ".claude").exists()
    assert git(repository, "status", "--porcelain") == ""
