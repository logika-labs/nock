"""A stand-in for `claude -p` in the seats nock dispatches: a real process that
does what a scripted session would — through nock's own CLI, in the directory
it was started in — and writes a transcript where Claude Code would. It will
not start with its permissions bypassed, and, like Claude Code in `dontAsk`,
refuses and reports a call no allow rule covers (FAKE_TRY is one more call to
attempt). As the elaborator it deepens the decision it was given, unless
FAKE_ELABORATE is `silent`; as the consultant it answers at once; as the
sharer it reads the authors and hands back the vetted summary (FAKE_SHARE,
or a stock one; `nothing` hands back nothing); as an evaluation step's
agent it writes its brief to answer.txt, when its allow rules let it write."""

from __future__ import annotations

import fnmatch
import json
import os
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

BYPASS = (
    "--dangerously-skip-permissions",
    "--allow-dangerously-skip-permissions",
    "bypassPermissions",
)
# What Claude Code refused this session, as its `result` line reports it.
DENIED: list[dict[str, object]] = []
ALLOWED: list[str] = []
DENIED_RULES: list[str] = []


def flags(arguments: list[str]) -> list[str]:
    """The seat's allow rules, refusing a session that could bypass them;
    the command line goes to FAKE_ARGUMENTS for a test to read."""
    assert not any(argument in BYPASS for argument in arguments), arguments
    assert arguments[arguments.index("--permission-mode") + 1] == "dontAsk", arguments
    if os.environ.get("FAKE_ARGUMENTS"):
        Path(os.environ["FAKE_ARGUMENTS"]).write_text(json.dumps(arguments))
    return listed(arguments, "--allowedTools")


def listed(arguments: list[str], flag: str) -> list[str]:
    """The rules after `flag`, up to the next flag."""
    if flag not in arguments:
        return []
    start = arguments.index(flag) + 1
    end = next(index for index in range(start, len(arguments)) if arguments[index].startswith("--"))
    return arguments[start:end]


def allows(command: str) -> bool:
    """Claude Code's rules, as far as the fake needs them: a deny rule's `*`
    matches anything and wins; an allow rule is a prefix."""
    for rule in DENIED_RULES:
        if rule.startswith("Bash(") and fnmatch.fnmatchcase(command, rule[len("Bash(") : -1]):
            return False
    for rule in ALLOWED:
        if rule.startswith("Bash(") and rule.endswith(":*)"):
            prefix = rule[len("Bash(") : -len(":*)")]
            if command == prefix or command.startswith(prefix + " "):
                return True
    return False


def run(*arguments: str) -> subprocess.CompletedProcess[str]:
    """A Bash call: run when a rule allows it, refused (and reported) when not."""
    shown = " ".join(arguments)
    if not allows(shown):
        DENIED.append({"tool_name": "Bash", "tool_input": {"command": shown}})
        return subprocess.CompletedProcess(list(arguments), 1, "", "Permission denied")
    return subprocess.run(list(arguments), capture_output=True, text=True)


def finish(text: str) -> None:
    print(json.dumps({"type": "result", "result": text, "permission_denials": DENIED}), flush=True)


def write_transcript(session: str, prompt: str) -> None:
    root = (
        Path(os.environ["CLAUDE_CONFIG_DIR"])
        / "projects"
        / re.sub(r"[^A-Za-z0-9]", "-", os.getcwd())
    )
    root.mkdir(parents=True, exist_ok=True)
    moment = datetime.now(UTC).isoformat()
    records = [
        {
            "type": "user",
            "timestamp": moment,
            "cwd": os.getcwd(),
            "message": {"role": "user", "content": prompt[:200]},
        },
        {
            "type": "assistant",
            "timestamp": moment,
            "message": {
                "id": "m1",
                "model": "claude-test",
                "usage": {"input_tokens": 10, "output_tokens": 5},
                "content": [],
            },
        },
    ]
    (root / f"{session}.jsonl").write_text(
        "\n".join(json.dumps(record) for record in records) + "\n"
    )


def main() -> int:
    arguments = sys.argv[1:]
    ALLOWED.extend(flags(arguments))
    DENIED_RULES.extend(listed(arguments, "--disallowedTools"))
    session = arguments[arguments.index("--session-id") + 1]
    prompt = arguments[-1]
    if os.environ.get("FAKE_TRY"):
        run(*json.loads(os.environ["FAKE_TRY"]))
    if os.environ.get("NOCK_ROLE") == "elaborator":
        return elaborate(session, prompt)
    if os.environ.get("NOCK_ROLE") == "consultant":
        return consult(session, prompt)
    if os.environ.get("NOCK_ROLE") == "sharer":
        assert "NOTHING TO SHARE:" in prompt
        authors = run("git", "log", "--format=%an %ae")
        assert authors.returncode == 0, authors.stderr
        write_transcript(session, prompt)
        text = os.environ.get("FAKE_SHARE", "Early days, vetted.")
        finish("" if text == "nothing" else text)
        return 0
    if os.environ.get("NOCK_ROLE") == "evaluated":
        write_transcript(session, prompt)
        if "Write" in ALLOWED:
            Path("answer.txt").write_text(prompt)
        else:
            DENIED.append({"tool_name": "Write", "tool_input": {"file_path": "answer.txt"}})
        finish("answered")
        return 0
    raise SystemExit(f"no seat for role {os.environ.get('NOCK_ROLE')!r}")


def consult(session: str, prompt: str) -> int:
    """Advise through `nock advise` (FAKE_ADVICE, else a stock answer), and
    once more, fixed, when the first is refused; FAKE_ADVICE=`silent` only
    answers in its last message, and `nothing` gives no answer at all."""
    assert "<intent>" in prompt and "When each of the project's decisions matters:" in prompt
    write_transcript(session, prompt)
    given = os.environ.get("FAKE_ADVICE", "")
    if given == "nothing":
        finish("")
        return 0
    if given == "silent":
        finish("Nothing bears on it.")
        return 0
    advice = json.loads(given) if given else {"advice": "Nothing in nock bears on it."}
    result = run(".nock/nock", "advise", json.dumps(advice))
    print(json.dumps({"type": "system", "message": result.stdout + result.stderr}), flush=True)
    if result.returncode != 0:
        fixed = {key: value for key, value in advice.items() if key in ("advice", "feedback")}
        result = run(".nock/nock", "advise", json.dumps(fixed))
        print(json.dumps({"type": "system", "message": result.stdout + result.stderr}), flush=True)
    finish("submitted")
    return 0


def elaborate(session: str, prompt: str) -> int:
    number = os.environ["NOCK_DECISION"]
    assert f"decision {number}" in prompt
    if os.environ.get("FAKE_ELABORATE") != "silent":
        change = {
            "number": int(number),
            "summary": "SQLite holds the load: 40 writes a second.",
            "evidence": ["the busiest hour wrote 40 rows a second"],
        }
        result = run(".nock/nock", "decisions", "edit", json.dumps(change))
        print(json.dumps({"type": "system", "message": result.stdout + result.stderr}), flush=True)
    write_transcript(session, prompt)
    finish("elaborated")
    return 0


if __name__ == "__main__":
    sys.exit(main())
