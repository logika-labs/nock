"""What the evals' real Claude Code sessions may do. They work as an engineer
would on a throwaway copy of a project: read anything, edit inside it, run
Python, git, SQLite and nock. Nothing else is allowed, and in `dontAsk` it is
refused rather than prompted for, since nobody is there to answer. Python is
any code already, so nock's `run` grants nothing more here."""

from __future__ import annotations

ENGINEER = [
    "--permission-mode",
    "dontAsk",
    "--allowedTools",
    "Read",
    "Edit(./**)",
    "Agent",
    "Skill",
    "Bash(python3:*)",
    "Bash(python:*)",
    "Bash(git:*)",
    "Bash(sqlite3:*)",
    "Bash(.nock/nock:*)",
]
# A scripted owner only answers: no tools at all.
ANSWERING = ["--permission-mode", "dontAsk", "--tools", ""]
