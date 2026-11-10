"""Records a real Claude Code session with VHS: Claude Code runs in a tmux session in the demo
repository, VHS attaches to it and records, and this script types the prompts as a person would,
waits for each turn to end (the demo's Stop hook appends to a marks file) and detaches, which ends
the tape.

    python3 session.py SPEC.json OUT.mp4

SPEC: {"repository": "~/demo/tally", "prompts": ["…"], "width": 1680, "height": 860,
       "font_size": 20, "framerate": 15, "env": {"NAME": "value"}, "command": "claude …",
       "until_files": ["paths in the repository that must exist before the turn counts as over"]}
"""

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

# A tmux server of its own, so its options touch nobody else's tmux.
SOCKET = "nock-videos"
MARKS = Path.home() / "demo" / "marks" / "stop"
CONFIG = Path.home() / "demo" / "marks" / "tmux.conf"
THEME = {
    "name": "nock",
    "background": "#15131d",
    "foreground": "#f1eefa",
    "cursor": "#8fe9ff",
    "selection": "#3a3550",
    "black": "#15131d",
    "red": "#ff7a90",
    "green": "#9be8b4",
    "yellow": "#ffe27a",
    "blue": "#8fb8ff",
    "magenta": "#ff9ad5",
    "cyan": "#8fe9ff",
    "white": "#f1eefa",
    "brightBlack": "#6e6888",
    "brightRed": "#ff9aab",
    "brightGreen": "#b8f5d0",
    "brightYellow": "#fff2a0",
    "brightBlue": "#b9c8ff",
    "brightMagenta": "#ffb0d6",
    "brightCyan": "#bff3ff",
    "brightWhite": "#ffffff",
}


def tmux(*args: str) -> str:
    return subprocess.run(
        ["tmux", "-L", SOCKET, "-f", str(CONFIG), *args],
        capture_output=True,
        text=True,
        check=False,
    ).stdout


def screen(name: str) -> str:
    return tmux("capture-pane", "-p", "-t", name)


def wait_for(name: str, text: str, timeout: float) -> None:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if text in screen(name):
            return
        time.sleep(0.3)
    raise TimeoutError(f"{text!r} never showed:\n{screen(name)}")


def type_text(name: str, text: str) -> None:
    for char in text:
        tmux("send-keys", "-t", name, "-l", char)
        time.sleep(0.035 if char != " " else 0.06)


def stops() -> int:
    return len(MARKS.read_text().splitlines()) if MARKS.exists() else 0


def main(spec_path: str, out: str) -> int:
    spec = json.loads(Path(spec_path).read_text())
    repository = Path(spec["repository"]).expanduser()
    name = f"rec{os.getpid()}"
    env = {
        "PATH": f"{repository}/.venv/bin:{os.environ['PATH']}",
        "COLORTERM": "truecolor",
        **spec.get("env", {}),
    }
    exports = " ".join(f"{key}={json.dumps(value)}" for key, value in env.items())
    command = spec.get("command", "claude --setting-sources project,local")
    # Mouse and focus events on, so Claude Code has no tmux advice to print over the recording.
    CONFIG.parent.mkdir(parents=True, exist_ok=True)
    CONFIG.write_text(
        "set -g status off\nset -g window-size latest\nset -g mouse on\nset -s focus-events on\n"
        "set -g default-terminal tmux-256color\nset -as terminal-features ',*:RGB'\n"
    )
    tmux(
        "new-session",
        "-d",
        "-s",
        name,
        "-x",
        "160",
        "-y",
        "40",
        "-c",
        str(repository),
        f"env {exports} {command}",
    )
    end = time.monotonic() + 30
    while time.monotonic() < end:
        current = screen(name)
        if "trust this folder" in current:
            tmux("send-keys", "-t", name, "Down", "Enter")
        if "❯" in current and "trust this folder" not in current:
            break
        time.sleep(0.3)
    with tempfile.TemporaryDirectory() as scratch:
        tape = Path(scratch) / "session.tape"
        tape.write_text(
            "\n".join(
                [
                    f"Output {json.dumps(str(Path(out).resolve()))}",
                    "Set Shell zsh",
                    f"Set FontSize {spec.get('font_size', 20)}",
                    'Set FontFamily "IBM Plex Mono"',
                    f"Set Width {spec.get('width', 1680)}",
                    f"Set Height {spec.get('height', 860)}",
                    f"Set Framerate {spec.get('framerate', 15)}",
                    "Set Padding 24",
                    "Set CursorBlink false",
                    f"Set Theme {json.dumps(THEME)}",
                    "Set WaitTimeout 90m",
                    "Hide",
                    f"Type {json.dumps(f'tmux -L {SOCKET} attach -t {name}')}",
                    "Enter",
                    "Sleep 1.5s",
                    "Show",
                    "Wait+Screen@90m /detached \\(from session/",
                    "",
                ]
            )
        )
        recorder = subprocess.Popen(["vhs", "-q", str(tape)])
        end = time.monotonic() + 60
        while not tmux("list-clients", "-t", name).strip():
            if time.monotonic() > end:
                raise TimeoutError("VHS never attached")
            time.sleep(0.3)
        time.sleep(2.5)
        for prompt in spec["prompts"]:
            before = stops()
            type_text(name, prompt)
            time.sleep(0.6)
            tmux("send-keys", "-t", name, "Enter")
            end = time.monotonic() + spec.get("timeout", 3600)
            # A Stop hook can refuse a stop (nock does while a round is open), so a mark alone is not
            # the end: the turn is over once Claude Code has stopped working for a while after one.
            quiet = 0.0
            waiting_for = [repository / path for path in spec.get("until_files", [])]
            while stops() == before or quiet < 10 or not all(path.exists() for path in waiting_for):
                if time.monotonic() > end:
                    raise TimeoutError(f"the turn never ended:\n{screen(name)}")
                current = screen(name)
                busy = "esc to interrupt" in current or "background agent" in current
                quiet = 0.0 if busy else quiet + 1
                time.sleep(1)
            time.sleep(spec.get("linger", 3))
        Path(out).with_suffix(".txt").write_text(tmux("capture-pane", "-p", "-S", "-", "-t", name))
        tmux("detach-client", "-s", name)
        recorder.wait()
    # /exit, so the session ends as a person's would and nock's SessionEnd hook records it.
    type_text(name, "/exit")
    tmux("send-keys", "-t", name, "Enter")
    end = time.monotonic() + 30
    while (
        time.monotonic() < end
        and subprocess.run(
            ["tmux", "-L", SOCKET, "has-session", "-t", name], capture_output=True
        ).returncode
        == 0
    ):
        time.sleep(0.5)
    tmux("kill-session", "-t", name)
    return 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:]))
