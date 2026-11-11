"""A stand-in for `claude -p` in the seats nock dispatches: a real process that
does what a scripted session would — through nock's own CLI, in the directory
it was started in — and writes a transcript where Claude Code would. It will
not start with its permissions bypassed, and, like Claude Code in `dontAsk`,
refuses and reports a call no allow rule covers (FAKE_TRY is one more call to
attempt). As the consultant it answers at once; as the studio's asker it
answers through `topics answer` (FAKE_ANSWER, or a stock one; FAKE_ANSWER
`slow` waits to be cancelled first); as the
sharer it reads the authors and hands back the vetted summary (FAKE_SHARE,
or a stock one; `nothing` hands back nothing). As the studio's chat it streams its answer word by word (FAKE_CHAT, or what
it heard), holding half of it until FAKE_CHAT_GATE exists, and resumes only
a session whose transcript is there, as Claude Code does; as the namer it
names the chat (FAKE_NAME); as Tidy up it runs the nock commands FAKE_TIDY
lists and sums up (FAKE_TIDY_SUMMARY). FAKE_LOG collects what each was
asked."""

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
    if os.environ.get("NOCK_ROLE") == "asker":
        return answer(session, prompt)
    if os.environ.get("NOCK_ROLE") == "sharer":
        assert "NOTHING TO SHARE:" in prompt
        authors = run("git", "log", "--format=%an %ae")
        assert authors.returncode == 0, authors.stderr
        write_transcript(session, prompt)
        text = os.environ.get("FAKE_SHARE", "Early days, vetted.")
        finish("" if text == "nothing" else text)
        return 0
    if os.environ.get("NOCK_ROLE") == "chatter":
        return chat(session, prompt, resumed)
    if os.environ.get("NOCK_ROLE") == "namer":
        assert "# The conversation" in prompt and "--tools" in arguments
        named = {"title": "Where orders live", "summary": "The owner asked; SQLite."}
        finish(os.environ.get("FAKE_NAME") or json.dumps(named))
        return 0
    if os.environ.get("NOCK_ROLE") == "tidier":
        return tidy(session, prompt)
    if os.environ.get("NOCK_ROLE") == "addresser":
        return address(session, prompt)
    raise SystemExit(f"no seat for role {os.environ.get('NOCK_ROLE')!r}")


def consult(session: str, prompt: str) -> int:
    """Advise through `nock advise` (FAKE_ADVICE, else a stock answer), and
    once more, fixed, when the first is refused; FAKE_ADVICE=`silent` only
    answers in its last message, and `nothing` gives no answer at all."""
    assert "<intent>" in prompt and "When each of the project's topics and items matters:" in prompt
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


def answer(session: str, prompt: str) -> int:
    assert "<question>" in prompt
    write_transcript(session, prompt)
    given = os.environ.get("FAKE_ANSWER", "")
    if given == "slow":
        time.sleep(60)
    said = json.loads(given) if given and given != "slow" else {"answer": "Nothing says so."}
    result = run(".nock/nock", "topics", "answer", json.dumps(said))
    print(json.dumps({"type": "system", "message": result.stdout + result.stderr}), flush=True)
    finish("answered")
    return 0


def transcript_of(session: str) -> Path:
    return (
        Path(os.environ["CLAUDE_CONFIG_DIR"])
        / "projects"
        / re.sub(r"[^A-Za-z0-9]", "-", os.getcwd())
        / f"{session}.jsonl"
    )


def say(text: str) -> None:
    """An assistant message, word by word as `--include-partial-messages`
    streams it, then whole; half of it held until FAKE_CHAT_GATE exists."""
    words = text.split(" ")
    gate = os.environ.get("FAKE_CHAT_GATE")
    for index, word in enumerate(words):
        if gate and index == len(words) // 2:
            deadline = time.monotonic() + 30
            while not Path(gate).exists() and time.monotonic() < deadline:
                time.sleep(0.05)
        delta = {"type": "text_delta", "text": word if index == 0 else f" {word}"}
        event = {"type": "content_block_delta", "index": 0, "delta": delta}
        print(json.dumps({"type": "stream_event", "event": event}), flush=True)
    message = {"role": "assistant", "content": [{"type": "text", "text": text}]}
    print(json.dumps({"type": "assistant", "message": message}), flush=True)


def chat(session: str, prompt: str, resumed: bool) -> int:
    if resumed and not transcript_of(session).is_file():
        print(f"No conversation found with session ID: {session}", file=sys.stderr, flush=True)
        return 1
    if resumed:
        heard = prompt
    else:
        assert "# Their message" in prompt and "nock's studio" in prompt
        heard = prompt.split("<message>\n", 1)[1].split("\n</message>", 1)[0]
        write_transcript(session, prompt)
    tool = {"type": "tool_use", "name": "Bash", "input": {"command": ".nock/nock topics list"}}
    print(json.dumps({"type": "assistant", "message": {"content": [tool]}}), flush=True)
    listed = run(".nock/nock", "topics", "list")
    assert listed.returncode == 0, listed.stderr
    text = os.environ.get("FAKE_CHAT") or f"You said: {heard}"
    say(text)
    finish(text)
    return 0


def tidy(session: str, prompt: str) -> int:
    assert "# Tidy up the topics" in prompt
    write_transcript(session, prompt)
    say("Reading the topics first.")
    for command in json.loads(os.environ.get("FAKE_TIDY") or "[]"):
        tool = {"type": "tool_use", "name": "Bash", "input": {"command": " ".join(command)}}
        print(json.dumps({"type": "assistant", "message": {"content": [tool]}}), flush=True)
        result = run(".nock/nock", *command)
        print(json.dumps({"type": "system", "message": result.stdout + result.stderr}), flush=True)
    summary = os.environ.get("FAKE_TIDY_SUMMARY") or "Moved one item\n\n- orders: first"
    say(summary)
    finish(summary)
    return 0


def address(session: str, prompt: str) -> int:
    """Answer the owner's comments through nock (FAKE_ADDRESS: the commands)."""
    assert "# Address my comments" in prompt and "<message>" in prompt
    write_transcript(session, prompt)
    say("Reading each thread first.")
    for command in json.loads(os.environ.get("FAKE_ADDRESS") or "[]"):
        tool = {"type": "tool_use", "name": "Bash", "input": {"command": " ".join(command)}}
        print(json.dumps({"type": "assistant", "message": {"content": [tool]}}), flush=True)
        result = run(".nock/nock", *command)
        assert result.returncode == 0, result.stdout + result.stderr
    summary = "Answered every comment."
    say(summary)
    finish(summary)
    return 0


if __name__ == "__main__":
    sys.exit(main())
