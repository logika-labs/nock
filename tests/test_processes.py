"""Running processes for an agent: supervised, bounded, condensed — and the
cache and the repeat note that save it re-running what has not changed."""

from __future__ import annotations

import fcntl
import os
import pty
import signal
import subprocess
import sys
import termios
import time
from pathlib import Path

from nock.condense import clean, excerpt
from nock.project import Project

from .conftest import git, nock, write_tool

TOOLS = '''\
import nock


@nock.command(cache="data/**")
def total(root, sh) -> str:
    """Add up the data, slowly."""
    sh("sleep 0.3")
    return str(sum(int(path.read_text()) for path in sorted((root / "data").glob("*.txt"))))


@nock.command
def failing(sh) -> None:
    """Fail through sh."""
    sh("echo one; echo two; ls definitely-missing")


@nock.command
def missing(sh) -> None:
    """Run a command that is not there."""
    sh(["definitely-not-a-program-xyz"])


@nock.command
def slow(sh, *, deadline: float = 0.5, silence: float = 10) -> None:
    """Outlive a bound."""
    sh("sleep 3", deadline=deadline, silence=silence)
'''


def test_condensing_drops_terminal_noise_and_folds_repeats(tmp_path: Path) -> None:
    raw = (
        "\x1b[1m\x1b[31mERROR\x1b[0m in "
        f"{tmp_path}/src/app.py\n"
        "Downloading 10%\rDownloading 55%\rDownloading 100%\n"
        "same\nsame\nsame\n\n\n\n"
        "item 1 of 9\nitem 2 of 9\nitem 3 of 9\nitem 4 of 9\n"
        "done\n"
    )
    assert clean(raw, tmp_path) == [
        "ERROR in src/app.py",
        "Downloading 100%",
        "same (×3)",
        "",
        "item 4 of 9 (×4 similar)",
        "done",
    ]


def test_an_excerpt_keeps_the_end_and_says_what_it_left_out() -> None:
    lines = [f"line {index}" for index in range(1000)]
    text, cut = excerpt(lines, 400)
    assert cut and text.startswith("line 0\n") and text.endswith("line 999")
    assert "lines omitted" in text and len(text) <= 440
    assert excerpt(["short"], 400) == ("short", False)


def test_run_supervises_any_command_and_passes_its_code_on(project: Project) -> None:
    script = project.root / "noisy.sh"
    script.write_text('for i in $(seq 1 300); do echo "step $i"; done\necho finished\nexit 3\n')
    result = nock(project.root, "run", "--", "bash", "noisy.sh")
    assert result.returncode == 3
    assert result.stdout == "step 300 (×300 similar)\nfinished\n"
    run = project.store.rows("SELECT * FROM runs")[0]
    assert run["exit_code"] == 3 and run["call"] is not None
    assert (project.logs / f"run-{run['id']}.log").read_text().count("step") == 300


def test_sh_turns_failures_into_exit_codes(project: Project) -> None:
    write_tool(project, "work", TOOLS)
    failing = nock(project.root, "failing")
    assert failing.returncode == 1
    assert failing.stdout.startswith("one\ntwo\nls: definitely-missing")
    assert "exited 1" in failing.stderr
    missing = nock(project.root, "missing")
    assert missing.returncode == 42 and "could not run" in missing.stderr
    assert nock(project.root, "slow").returncode == 54
    assert nock(project.root, "slow", "--deadline", "60", "--silence", "0.5").returncode == 55


def test_a_repeated_failure_says_so_and_whether_anything_changed(project: Project) -> None:
    write_tool(project, "work", TOOLS)
    first = nock(project.root, "failing")
    assert "same result" not in first.stderr
    second = nock(project.root, "failing")
    assert "same result as call 1" in second.stderr and "no file has changed since" in second.stderr
    (project.root / "touched.txt").write_text("x\n")
    third = nock(project.root, "failing")
    assert "same result as call 2" in third.stderr and "no file has changed" not in third.stderr


def test_a_cached_tool_replays_while_its_inputs_stand_still(project: Project) -> None:
    write_tool(project, "work", TOOLS)
    data = project.root / "data"
    data.mkdir()
    (data / "a.txt").write_text("2\n")
    (data / "b.txt").write_text("3\n")
    git(project.root, "add", "-A")
    git(project.root, "commit", "-qm", "data")
    assert nock(project.root, "total").stdout == "5\n"
    replay = nock(project.root, "total")
    assert replay.stdout == "5\n" and "cached" in replay.stderr
    (data / "b.txt").write_text("30\n")
    assert nock(project.root, "total").stdout == "32\n"
    fresh = nock(project.root, "total", "--fresh")
    assert fresh.stdout == "32\n" and "cached" not in fresh.stderr
    calls = project.store.rows("SELECT cached FROM calls WHERE tool = 'total' ORDER BY id")
    assert [row["cached"] for row in calls] == [0, 1, 0, 0]


STREAMING = '''\
import nock


@nock.command
def serve(sh):
    """A server: it says it is ready, then answers its input, however long that takes."""
    return sh(
        "echo ready; read line; echo got $line; exit 3",
        check=False,
        stream=True,
        deadline=0,
        silence=0,
    )


@nock.command
def deploy(sh) -> None:
    """Steps whose output the owner watches; the second fails."""
    sh("echo step one", stream=True)
    sh("echo step two; exit 2", stream=True)
'''


def test_a_streamed_command_prints_as_it_goes_and_takes_the_caller_s_input(
    project: Project,
) -> None:
    write_tool(project, "serve", STREAMING)
    process = subprocess.Popen(
        [str(project.root / ".nock" / "nock"), "serve"],
        cwd=project.root,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env={**os.environ, "NOCK_PYTHON": sys.executable},
    )
    assert process.stdout is not None and process.stdin is not None
    assert process.stdout.readline() == "ready\n"
    assert process.poll() is None
    rest, _ = process.communicate("hello\n", timeout=30)
    assert rest == "got hello\n" and process.returncode == 3
    call = project.store.rows("SELECT exit_code, output_bytes FROM calls WHERE tool = 'serve'")[0]
    assert call["exit_code"] == 3 and call["output_bytes"] > 0


def test_a_streamed_failure_points_at_its_log_without_printing_it_again(project: Project) -> None:
    write_tool(project, "serve", STREAMING)
    result = nock(project.root, "deploy")
    assert result.returncode == 1
    assert result.stdout == "step one\nstep two\n"
    assert "`echo step two; exit 2` exited 2; its output is above (log: " in result.stderr
    assert "step two" not in result.stderr.replace("echo step two", "")


PROMPTING = '''\
import nock


@nock.command
def login(sh):
    """Asks on the terminal, as ssh and sudo do."""
    return sh(
        "printf 'name? ' >/dev/tty; read name </dev/tty; echo hello $name",
        check=False,
        stream=True,
    )
'''


def test_a_streamed_command_has_the_caller_s_terminal_to_prompt_on(project: Project) -> None:
    write_tool(project, "login", PROMPTING)
    descriptor, terminal = pty.openpty()
    process = subprocess.Popen(
        [str(project.root / ".nock" / "nock"), "login"],
        cwd=project.root,
        stdin=terminal,
        stdout=terminal,
        stderr=terminal,
        env={**os.environ, "NOCK_PYTHON": sys.executable},
        start_new_session=True,
        preexec_fn=lambda: fcntl.ioctl(0, termios.TIOCSCTTY, 0),
    )
    os.close(terminal)
    seen = b""
    deadline = time.monotonic() + 30
    while b"name? " not in seen and time.monotonic() < deadline:
        seen += os.read(descriptor, 1024)
    os.write(descriptor, b"ann\n")
    while time.monotonic() < deadline:
        try:
            chunk = os.read(descriptor, 1024)
        except OSError:
            break
        if not chunk:
            break
        seen += chunk
    status = process.wait(timeout=30)
    assert b"hello ann" in seen, seen
    assert status == 0


SERVER = '''\
import nock


@nock.command
def serve(sh):
    """A server that shuts down cleanly when asked."""
    return sh(
        "trap 'echo stopping; exit 0' INT; echo up; while :; do sleep 0.1; done",
        check=False,
        stream=True,
        deadline=0,
        silence=0,
    )
'''


def test_an_interrupted_server_is_asked_to_stop_before_it_is_killed(project: Project) -> None:
    write_tool(project, "serve", SERVER)
    process = subprocess.Popen(
        [str(project.root / ".nock" / "nock"), "serve"],
        cwd=project.root,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env={**os.environ, "NOCK_PYTHON": sys.executable},
    )
    assert process.stdout is not None
    assert process.stdout.readline() == "up\n"
    process.send_signal(signal.SIGTERM)
    process.wait(timeout=30)
    logs = sorted((project.root / ".nock" / "local" / "logs").glob("run-*.log"))
    assert "stopping" in logs[-1].read_text()
