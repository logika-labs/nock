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
- **Record a decision only when a later reader would ask "why":**
  `.nock/nock decide` (`--help` has the fields) for a choice between real
  alternatives the owner hasn't already made, a deliberate simplification,
  your reading of something ambiguous, or a todo you are leaving. Never for
  carrying out the owner's explicit instruction (the instruction is the
  record), a routine implementation detail, a change to an existing
  decision (edit it: `.nock/nock decisions edit`), or twice for the same
  thing. If it is the owner's call, record the answer you would propose,
  tag it `important`, and carry on; the owner reviews later, so don't
  wait. When you do a todo or rework a rejected decision, edit it to say
  what you did.{tags}
- **Show the owner what you made for them to look at** (a screenshot, a
  video, a PDF, a page, a text): `.nock/nock review add` (`--help` has the
  fields), under a stable key, with a recipe to make it again. When the
  owner rejects or notes one, make the next version.
- **A tag, on a decision or an item, names a topic** the owner would look
  at together (`pricing`, `emails`), or there is none: never the project's
  or product's name, nor a kind (`prompt`, `screenshot`) or what the key
  says; nock shows those.
- **Run noisy or long commands through `.nock/nock run -- COMMAND`**
  (Claude Code asks about it as about the command itself), and
  `.nock/nock check --changed` before you finish: the checks your changes
  can affect (plain `check` runs them all). Exit codes: 1 fix the code, 42
  fix the machine or the state, 50 and up retry or escalate.
"""

REPORT = """\
- **Tell nock's makers what nock lacks:** when the user needs something nock
  doesn't do, or something in nock is broken or confusing, tell them and
  offer to send it with `.nock/nock report "…"`. This channel matters to the
  makers: it is how nock learns what to fix. Send only on the user's
  go-ahead (then with `--yes`), never on your own, and never code or secrets
  unless they ask.
"""

QUIET = """\
## nock

This project has nock (`.nock/nock`): a toolbox agents build for the project,
and the decisions they record for the owner to review. It stays quiet here:
use it when the human asks. `.nock/nock` lists the tools, `.nock/nock status`
says where things stand{consult}. When the human needs something nock lacks
or finds it broken, offer to send that to nock's makers with
`.nock/nock report`, only on their go-ahead.
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
    fixed = [tag for tag in configuration.get("decisions.tags") or [] if tag != "important"]
    tags = f"\n  Tags: {', '.join(f'`{tag}`' for tag in fixed)} and `important`." if fixed else ""
    return INTRODUCTION + "\n" + (CONSULT if consulting else "") + DECIDE.format(tags=tags) + REPORT


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
