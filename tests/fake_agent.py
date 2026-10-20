"""A stand-in for `claude -p` in the seats nock dispatches: a real process that
does what a scripted session would — through nock's own CLI, in the directory
it was started in — and writes a transcript where Claude Code would. As the
elaborator it rewrites the question it was given, unless FAKE_ELABORATE is
`silent`; as the consultant it answers at once."""

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
        assert "# What it said" in prompt
        write_transcript(session, prompt)
        print(
            json.dumps({"type": "result", "result": "**The task, reframed** — as asked."}),
            flush=True,
        )
        return 0
    raise SystemExit(f"no seat for role {os.environ.get('NOCK_ROLE')!r}")


def elaborate(session: str, prompt: str) -> int:
    number = os.environ["NOCK_QUESTION"]
    assert f"question {number}" in prompt
    if os.environ.get("FAKE_ELABORATE") != "silent":
        rewritten = {
            "title": "Which database, now that we know the load",
            "context": "The load is 40 writes a second: SQLite holds it.",
            "options": ["SQLite", "Postgres"],
            "recommended": 1,
        }
        result = run(".nock/nock", "questions", "rewrite", number, json.dumps(rewritten))
        print(json.dumps({"type": "system", "message": result.stdout + result.stderr}), flush=True)
    write_transcript(session, prompt)
    print(json.dumps({"type": "result", "result": "elaborated"}), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
