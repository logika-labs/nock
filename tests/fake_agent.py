"""A stand-in for `claude -p` in the seats nock dispatches: a real process that
does what a scripted session would — through nock's own CLI, in the directory
it was started in — and writes a transcript where Claude Code would. As the
elaborator it deepens the decision it was given, unless FAKE_ELABORATE is
`silent`; as the consultant it answers at once; as the sharer it hands back
the vetted summary (FAKE_SHARE, or a stock one)."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path


def run(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(list(arguments), capture_output=True, text=True)


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
    session = arguments[arguments.index("--session-id") + 1]
    prompt = arguments[-1]
    if os.environ.get("NOCK_ROLE") == "elaborator":
        return elaborate(session, prompt)
    if os.environ.get("NOCK_ROLE") == "consultant":
        return consult(session, prompt)
    if os.environ.get("NOCK_ROLE") == "sharer":
        assert "NOTHING TO SHARE:" in prompt
        write_transcript(session, prompt)
        text = os.environ.get("FAKE_SHARE", "Early days, vetted.")
        print(json.dumps({"type": "result", "result": text}), flush=True)
        return 0
    raise SystemExit(f"no seat for role {os.environ.get('NOCK_ROLE')!r}")


def consult(session: str, prompt: str) -> int:
    """Advise through `nock advise` (FAKE_ADVICE, else a stock answer), and
    once more, fixed, when the first is refused; FAKE_ADVICE=`silent` only
    answers in its last message."""
    assert "<intent>" in prompt and "When each of the project's decisions matters:" in prompt
    write_transcript(session, prompt)
    given = os.environ.get("FAKE_ADVICE", "")
    if given == "silent":
        print(json.dumps({"type": "result", "result": "Nothing bears on it."}), flush=True)
        return 0
    advice = json.loads(given) if given else {"advice": "Nothing in nock bears on it."}
    result = run(".nock/nock", "advise", json.dumps(advice))
    print(json.dumps({"type": "system", "message": result.stdout + result.stderr}), flush=True)
    if result.returncode != 0:
        fixed = {key: value for key, value in advice.items() if key in ("advice", "feedback")}
        result = run(".nock/nock", "advise", json.dumps(fixed))
        print(json.dumps({"type": "system", "message": result.stdout + result.stderr}), flush=True)
    print(json.dumps({"type": "result", "result": "submitted"}), flush=True)
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
    print(json.dumps({"type": "result", "result": "elaborated"}), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
