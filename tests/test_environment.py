"""The project's environment, which its tools run in: the interpreter that
can import the project's own packages, directories first on PATH, and the
variables of a dotenv file — while nock itself stays standard-library."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import venv
from pathlib import Path

from nock.project import Project

from .conftest import git, nock, write_tool

TOOLS = '''\
import os
import sys

import nock


@nock.command
def where(sh) -> dict:
    """Where the tool runs."""
    import projectlib  # only the project's interpreter has it

    return {
        "value": projectlib.VALUE,
        "prefix": sys.prefix,
        "token": os.environ.get("TOKEN"),
        "child": sh("echo $TOKEN; greet").text,
    }


@nock.command
def plain() -> str:
    """Needs nothing of the project."""
    return "ok"


@nock.hook("session-start")
def remind(payload):
    import projectlib

    return f"lib says {projectlib.VALUE}"
'''


def project_environment(project: Project) -> Path:
    """A virtual environment in the working tree, with a package only it has,
    and a `bin/` of the project's own commands."""
    environment = project.root / ".venv"
    venv.create(environment, with_pip=False, symlinks=True)
    site = next(environment.glob("lib/python3*/site-packages"))
    (site / "projectlib.py").write_text("VALUE = 'from the project'\n")
    bin_directory = project.root / "bin"
    bin_directory.mkdir()
    greet = bin_directory / "greet"
    greet.write_text("#!/bin/sh\necho hello from bin\n")
    greet.chmod(0o755)
    (project.root / ".gitignore").write_text(".venv/\n.env\n")
    return environment


def configure(project: Project, text: str) -> None:
    path = project.root / ".nock" / "config.toml"
    path.write_text(path.read_text() + "\n" + text)
    git(project.root, "add", "-A")
    git(project.root, "commit", "-qm", "configure")


ENVIRONMENT = '[environment]\npython = ".venv/bin/python"\npath = ["bin"]\ndotenv = ".env"\n'


def test_tools_run_on_the_project_s_interpreter_with_its_path_and_dotenv(
    project: Project,
) -> None:
    environment = project_environment(project)
    (project.root / ".env").write_text("# secrets\nexport TOKEN='s3cret'\nOTHER=1\n")
    write_tool(project, "where", TOOLS)
    configure(project, ENVIRONMENT)
    result = nock(project.root, "where", "--json")
    assert result.returncode == 0, result.stderr
    found = json.loads(result.stdout)
    assert found["value"] == "from the project"
    assert Path(found["prefix"]).resolve() == environment.resolve()
    assert found["token"] == "s3cret"
    assert found["child"] == "s3cret\nhello from bin"


def test_a_variable_already_set_wins_over_the_dotenv(project: Project) -> None:
    project_environment(project)
    (project.root / ".env").write_text("TOKEN=from-file\n")
    write_tool(project, "where", TOOLS)
    configure(project, ENVIRONMENT)
    result = subprocess.run(
        [str(project.root / ".nock" / "nock"), "where", "--json"],
        cwd=project.root,
        capture_output=True,
        text=True,
        env={**os.environ, "NOCK_PYTHON": sys.executable, "TOKEN": "mine"},
    )
    assert json.loads(result.stdout)["token"] == "mine"


def test_a_worktree_uses_its_own_interpreter_and_the_main_checkout_s_dotenv(
    project: Project,
) -> None:
    project_environment(project)
    (project.root / ".env").write_text("TOKEN=main\n")
    write_tool(project, "where", TOOLS)
    configure(project, ENVIRONMENT)
    worktree = project.root.with_name("feature")
    git(project.root, "worktree", "add", "-q", "-b", "feature", str(worktree))
    missing = nock(worktree, "plain")
    assert missing.returncode == 0 and missing.stdout == "ok\n"
    assert ".venv/bin/python (environment.python) is missing" in missing.stderr
    assert nock(worktree, "where").returncode == 50
    own = venv.EnvBuilder(with_pip=False, symlinks=True)
    own.create(worktree / ".venv")
    site = next((worktree / ".venv").glob("lib/python3*/site-packages"))
    (site / "projectlib.py").write_text("VALUE = 'the worktree'\n")
    result = nock(worktree, "where", "--json")
    assert result.returncode == 0, result.stderr
    found = json.loads(result.stdout)
    assert (found["value"], found["token"]) == ("the worktree", "main")


def test_hooks_run_in_the_project_s_environment_too(project: Project) -> None:
    project_environment(project)
    write_tool(project, "where", TOOLS)
    configure(project, ENVIRONMENT)
    payload = json.dumps({"session_id": "s1", "cwd": str(project.root), "source": "startup"})
    result = nock(project.root, "hook", "SessionStart", stdin=payload)
    assert result.returncode == 0
    context = json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"]
    assert "lib says from the project" in context


def test_children_of_sh_never_inherit_git_s_location(project: Project) -> None:
    write_tool(
        project,
        "gitenv",
        "import nock\n\n@nock.command\ndef gitenv(sh) -> str:\n"
        "    '''What git variables a child sees.'''\n"
        "    return sh('env | grep ^GIT_ | cut -d= -f1 | sort', check=False).text\n",
    )
    result = subprocess.run(
        [str(project.root / ".nock" / "nock"), "gitenv"],
        cwd=project.root,
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "NOCK_PYTHON": sys.executable,
            "GIT_DIR": str(project.root / ".git"),
            "GIT_INDEX_FILE": str(project.root / ".git" / "index"),
        },
    )
    assert result.returncode == 0, result.stderr
    assert "GIT_DIR" not in result.stdout and "GIT_INDEX_FILE" not in result.stdout


def test_a_missing_interpreter_is_set_up_first_when_the_project_says_how(
    project: Project,
) -> None:
    make = project.root / "make_environment.py"
    make.write_text(
        "import pathlib, venv\n"
        "venv.create('.venv', with_pip=False, symlinks=True)\n"
        "site = next(pathlib.Path('.venv').glob('lib/python3*/site-packages'))\n"
        "(site / 'projectlib.py').write_text(\"VALUE = 'set up'\\n\")\n"
        "print('made it')\n"
    )
    (project.root / ".gitignore").write_text(".venv/\n")
    write_tool(project, "where", TOOLS)
    configure(
        project,
        f'[environment]\npython = ".venv/bin/python"\nsetup = "{sys.executable} make_environment.py"\n',
    )
    nock(project.root, "hook", "SessionStart", stdin=json.dumps({"cwd": str(project.root)}))
    assert not (project.root / ".venv").exists()
    result = nock(project.root, "plain")
    assert result.returncode == 0, result.stderr
    assert result.stdout == "ok\n"
    assert "setting the project's environment up" in result.stderr and "made it" in result.stderr
    payload = json.dumps({"session_id": "s1", "cwd": str(project.root), "source": "startup"})
    hooked = nock(project.root, "hook", "SessionStart", stdin=payload)
    assert "lib says set up" in json.loads(hooked.stdout)["hookSpecificOutput"]["additionalContext"]
    again = nock(project.root, "plain")
    assert again.returncode == 0 and "setting" not in again.stderr


def test_hooks_never_wait_on_the_setup(project: Project) -> None:
    write_tool(project, "where", TOOLS)
    configure(project, '[environment]\npython = ".venv/bin/python"\nsetup = "sleep 30"\n')
    payload = json.dumps({"session_id": "s1", "cwd": str(project.root), "source": "startup"})
    result = nock(project.root, "hook", "SessionStart", stdin=payload)
    assert result.returncode == 0
    assert not (project.root / ".venv").exists()
    assert "run `sleep 30` first" in result.stderr
