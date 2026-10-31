"""The primer, `.nock/context.md`, which CLAUDE.md imports so every session
reads it: what nock is for here and what to do with it — as the committed
settings have it, so `reminders = false` leaves only a word on what nock is,
and `consult.enabled = false` leaves out consulting."""

from __future__ import annotations

from pathlib import Path

from nock.configuration import Configuration
from nock.utils import write_atomic

PRIMER = "context.md"

INTRODUCTION = """\
## nock

This project uses nock to stay coherent across sessions, which matters as
much as getting each task done: you start knowing nothing of earlier
sessions, and nock keeps what they decided, what the owner said about it, and
the tools agents built.
"""

CONSULT = """\
- **Consult before you change code,** unless the task is really
  straightforward and unambiguous: `.nock/nock consult '{"intent": …,
  "context": …}'`. A fresh agent reads the project and tells you the
  decisions, tools and checks that bear on what you are about to do; do as
  it says, or record why not.
"""

DECIDE = """\
- **Record decisions as you make them:** `.nock/nock decide` (`--help` has
  the fields). A decision is a choice between ways that could each work, a
  deliberate simplification, your reading of something ambiguous, a todo
  you are leaving, or a question only the owner can settle when they are
  not there to ask; give the alternatives you weighed, for someone who knows
  what the system does but not how it is built. The owner reviews them
  later, so don't wait. When you do a todo, act on an answer or rework a
  rejected decision, edit it to say what you did.
- **Run noisy or long commands through `.nock/nock run -- COMMAND`,** and
  `.nock/nock check` before you finish. Exit codes: 1 fix the code, 42 fix
  the machine or the state, 50 and up retry or escalate.
"""

QUIET = """\
## nock

This project has nock (`.nock/nock`): a toolbox agents build for the project,
and the decisions they record for the owner to review. It stays quiet here:
use it when the human asks. `.nock/nock` lists the tools, `.nock/nock status`
says where things stand{consult}.
"""


def primer(configuration: Configuration) -> str:
    consulting = configuration.get("consult.enabled") is not False
    if configuration.get("reminders") is False:
        consult = (
            ", and `.nock/nock consult` has a fresh agent find the decisions and tools that"
            " bear on a task"
            if consulting
            else ""
        )
        return QUIET.format(consult=consult)
    return INTRODUCTION + "\n" + (CONSULT if consulting else "") + DECIDE


def refresh(directory: Path) -> bool:
    """Rewrite `directory/context.md` when the committed settings say
    otherwise; whether it changed. A machine's own `local/config.toml` never
    changes a committed file."""
    text = primer(Configuration([directory / "config.toml"]))
    path = directory / PRIMER
    if path.is_file() and path.read_text() == text:
        return False
    write_atomic(path, text)
    return True
