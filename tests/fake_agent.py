"""A stand-in for `claude -p` in the seats nock dispatches: a real process that
does what a scripted session would — through nock's own CLI, in the directory
it was started in — and writes a transcript where Claude Code would. It will
not start with its permissions bypassed, and, like Claude Code in `dontAsk`,
refuses and reports a call no allow rule covers (FAKE_TRY is one more call to
attempt). As the consultant it answers at once; as the studio's asker it
answers through `topics answer` (FAKE_ANSWER, or a stock one; FAKE_ANSWER
`slow` waits to be cancelled first); as the
sharer it reads the authors and hands back the vetted summary (FAKE_SHARE,
or a stock one; `nothing` hands back nothing). As the studio's answerer it
thinks, runs a search, and answers in the task's chat (FAKE_ANSWER_TEXT, or
what it heard), holding its answer until FAKE_GATE exists; it resumes only a
session whose transcript is there, as Claude Code does. As a round's
reflector it starts the round it was asked to run and says so. FAKE_LOG
collects what each was asked."""

from __future__ import annotations

import fnmatch
import json
import os
import re
import subprocess
import sys
import time
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
        elif rule == f"Bash({command})":
            return True
    return False


def writes(path: Path) -> bool:
    """Whether a `Write(/…/**)` rule lets the agent write this file."""
    for rule in ALLOWED:
        if rule.startswith("Write(//") and rule.endswith("/**)"):
            # Claude Code's absolute path: `//` and the path from the root.
            folder = Path("/" + rule[len("Write(//") : -len("/**)")])
            if path.resolve().is_relative_to(folder):
                return True
    return False


def act(step: list[str]) -> subprocess.CompletedProcess[str]:
    """One step of a scripted agent: `["write", PATH, TEXT]` writes a file
    (refused where no rule lets it), `["sh", COMMAND]` runs a shell command, or
    a nock command."""
    if step[0] == "write":
        path = Path(step[1])
        if not writes(path):
            DENIED.append({"tool_name": "Write", "tool_input": {"file_path": step[1]}})
            return subprocess.CompletedProcess(step, 1, "", "Permission denied")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(step[2])
        return subprocess.CompletedProcess(step, 0, "", "")
    if step[0] == "sh":
        if not allows(step[1]):
            DENIED.append({"tool_name": "Bash", "tool_input": {"command": step[1]}})
            return subprocess.CompletedProcess(step, 1, "", "Permission denied")
        return subprocess.run(["sh", "-c", step[1]], capture_output=True, text=True)
    return run(".nock/nock", *step)


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
    resumed = "--resume" in arguments
    session = arguments[arguments.index("--resume" if resumed else "--session-id") + 1]
    prompt = arguments[-1]
    if os.environ.get("FAKE_LOG"):
        with open(os.environ["FAKE_LOG"], "a") as log:
            said = {"role": os.environ.get("NOCK_ROLE"), "session": session, "resumed": resumed}
            log.write(json.dumps({**said, "prompt": prompt}) + "\n")
    if os.environ.get("FAKE_TRY"):
        run(*json.loads(os.environ["FAKE_TRY"]))
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
    if os.environ.get("NOCK_ROLE") == "answerer":
        return answer(session, prompt, resumed)
    if os.environ.get("NOCK_ROLE") == "reflector":
        return reflector(session, prompt)
    raise SystemExit(f"no seat for role {os.environ.get('NOCK_ROLE')!r}")


def consult(session: str, prompt: str) -> int:
    """Answer through `nock consult --submit` (FAKE_ADVICE, else a stock
    answer; FAKE_ANSWER for the owner's question from the studio's Ask), and
    once more, fixed, when the first is refused; FAKE_ADVICE=`silent` only
    answers in its last message, `nothing` gives no answer at all, and
    FAKE_ANSWER=`slow` takes a minute."""
    assert (
        "<question>" in prompt and "When each of the project's topics and items matters:" in prompt
    )
    write_transcript(session, prompt)
    given = os.environ.get("FAKE_ADVICE", "") or os.environ.get("FAKE_ANSWER", "")
    if given == "slow":
        time.sleep(60)
    if given == "nothing":
        finish("")
        return 0
    if given == "silent":
        finish("Nothing bears on it.")
        return 0
    advice = json.loads(given) if given else {"answer": "Nothing in nock bears on it."}
    result = run(".nock/nock", "consult", "--submit", json.dumps(advice))
    print(json.dumps({"type": "system", "message": result.stdout + result.stderr}), flush=True)
    if result.returncode != 0:
        fixed = {key: value for key, value in advice.items() if key in ("answer", "feedback")}
        result = run(".nock/nock", "consult", "--submit", json.dumps(fixed))
        print(json.dumps({"type": "system", "message": result.stdout + result.stderr}), flush=True)
    finish("submitted")
    return 0


def transcript_of(session: str) -> Path:
    return (
        Path(os.environ["CLAUDE_CONFIG_DIR"])
        / "projects"
        / re.sub(r"[^A-Za-z0-9]", "-", os.getcwd())
        / f"{session}.jsonl"
    )


def say(text: str) -> None:
    message = {"role": "assistant", "content": [{"type": "text", "text": text}]}
    print(json.dumps({"type": "assistant", "message": message}), flush=True)


def answer(session: str, prompt: str, resumed: bool) -> int:
    """Answer the owner's message in the task's chat: a message event."""
    if resumed and not transcript_of(session).is_file():
        print(f"No conversation found with session ID: {session}", file=sys.stderr, flush=True)
        return 1
    assert "# Answer now" in prompt and "<message>" in prompt
    topic = re.search(r"the task\s+`([a-z0-9-]+)`", prompt)
    assert topic, prompt[:400]
    heard = prompt.split("<message>\n", 1)[1].split("\n</message>", 1)[0]
    write_transcript(session, prompt)
    thinking = {"type": "thinking", "thinking": "The owner asked something; read the view."}
    print(json.dumps({"type": "assistant", "message": {"content": [thinking]}}), flush=True)
    tool = {
        "type": "tool_use",
        "id": "t1",
        "name": "Bash",
        "input": {"command": ".nock/nock search orders"},
    }
    print(json.dumps({"type": "assistant", "message": {"content": [tool]}}), flush=True)
    listed = run(".nock/nock", "search", "orders")
    result = {"type": "tool_result", "tool_use_id": "t1", "content": listed.stdout[:200]}
    print(json.dumps({"type": "user", "message": {"content": [result]}}), flush=True)
    gate = os.environ.get("FAKE_GATE")
    if gate:
        deadline = time.monotonic() + 30
        while not Path(gate).exists() and time.monotonic() < deadline:
            time.sleep(0.05)
    text = os.environ.get("FAKE_ANSWER_TEXT") or f"You said: {heard}"
    shared = Path(os.environ["FAKE_SHARED"]) if os.environ.get("FAKE_SHARED") else None
    folder = (shared or Path(".nock/shared")) / "topics" / topic.group(1) / "events"
    target = folder / f"reply-{session[:8]}.json"
    written = act(["write", str(target), json.dumps({"kind": "message", "text": text})])
    assert written.returncode == 0, "the answerer may write the store"
    say(text)
    finish(text)
    return 0


def reflector(session: str, prompt: str) -> int:
    found = re.search(r"\.nock/nock reflect ([a-z.]+)", prompt)
    assert found and "Run the" in prompt, prompt[:400]
    write_transcript(session, prompt)
    started = run(".nock/nock", "reflect", found.group(1))
    say(f"Started {found.group(1)}: exit {started.returncode}.")
    finish(f"Ran {found.group(1)}.")
    return 0 if started.returncode == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
