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
  topics, items, tools and checks that bear on what you are about to do; do
  as it says, or say why not.
"""

TOPICS = """\
- **Put your work before the owner in Topics:** find the topic for what you
  are doing (`.nock/nock topics list --query …`) or open one (`topics
  create`); a done one that comes back is revived, not made again. Into
  it, submit items bare (`items create`, `--help` has the fields): a
  decision when a later reader would ask "why" (a choice between real
  alternatives the owner hasn't made, a deliberate simplification, your
  reading of something ambiguous, a todo you leave; never the owner's own
  instruction or a routine detail), project files, or something you made to
  show part of the project (a screenshot, a page) with how to make it again.
  If it is the owner's call, submit the answer you would propose and carry
  on; the owner gives verdicts later, so don't wait.
- **Keep your topic's state and status current:** when you start work, set
  it active with a status (`.nock/nock topics update TOPIC '{"state":
  "active", "status": "…"}'`); update the status at each milestone ("waiting
  for the gate on main", "eval running, about 2 h"); set it `review` when
  you have finished and only the owner's verdicts remain, `done` or
  `abandoned` when the work is over. Work you dispatch is tracked the same way, in
  the topic it serves.
- **Check what awaits you** with `.nock/nock topics list` when you start and
  before you finish: threads where the owner wrote last, items they
  rejected (rework one as a new version: `items update REF --version`).
  When the owner is in the session, discuss with them here and leave at
  most a line in the thread; when they are away, or told you to work in the
  background, answer briefly in the thread (`--reply`), and say nothing if
  you just did what was asked and the new version shows it.
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
and the topics where they put their work before the owner. It stays quiet here:
use it when the human asks. `.nock/nock` lists the tools, `.nock/nock status`
says where things stand{consult}. When the human needs something nock lacks
or finds it broken, offer to send that to nock's makers with
`.nock/nock report`, only on their go-ahead.
"""


def primer(configuration: Configuration) -> str:
    consulting = configuration.get("consult.enabled") is not False
    if configuration.get("reminders") is False:
        consult = (
            ", and `.nock/nock consult` has a fresh agent find the items and tools that"
            " bear on a task"
            if consulting
            else ""
        )
        return QUIET.format(consult=consult)
    return INTRODUCTION + "\n" + (CONSULT if consulting else "") + TOPICS + REPORT


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
