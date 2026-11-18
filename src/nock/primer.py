"""The primer, `.nock/context.md`, which CLAUDE.md imports so every Claude
Code session reads it, and which AGENTS.md holds between nock's markers for
the harnesses that read AGENTS.md and follow no import (Codex, Cursor): what
nock is for here and what to do with it — as the committed settings have it,
so `reminders = false` leaves only a word on what nock is."""

from __future__ import annotations

from pathlib import Path

from nock.configuration import Configuration
from nock.utils import write_atomic

PRIMER = "context.md"
AGENTS = "AGENTS.md"
MARK_START = "<!-- nock -->"
MARK_END = "<!-- /nock -->"

INTRODUCTION = """\
## nock

This project uses nock to stay coherent across sessions, which matters as
much as getting each task done: you start knowing nothing of earlier
sessions, and nock keeps what they decided, what the owner said about it, and
the tools agents built.
"""

MEMORY = """\
- **Read `.nock/shared/memory.md` first:** what nock has learned about this
  project and its owner, in short lines, each pointing to the files that hold
  the detail. Follow the lines that bear on your work. Tell the owner (or
  your orchestrator) what you learn that is worth remembering; reflection
  keeps the file.
"""

TOPICS = """\
- **Put your work before the owner in Topics** (tasks, to the owner): files
  you write in `.nock/shared/topics/` (`.nock/nock docs files` has each
  kind; nock fills in the rest and commits them). Find the topic for what
  you are doing (`.nock/nock search …`, then its view in
  `.nock/local/views/`) or open one; a done one that comes back is revived.
  Into it, as you go, short: a **decision** for what you decided and carried
  on with (a title, 1–3 lines on what it means for the owner, maybe why), a
  **proposal** for a todo you want done (the same, plus what it takes), and
  **assets** for files the owner should look at, versioned (before and
  after). Never the owner's own instruction or a routine detail. What only
  the owner can settle: propose it and carry on; don't wait.
- **Keep your topic's state and status current:** when you start work, set
  it active with a status (a `state` event, `{"kind": "state", "state":
  "active", "status": "…"}`); update the status at each milestone ("waiting
  for the gate on main", "benchmarks running, about 2 h"). When you have
  finished, compose its review if there is anything for the owner
  (`.nock/nock docs review`) and set it `review`; `done` or `abandoned`
  when the work is over. Work you dispatch is tracked the same way, in the
  topic it serves.
- **Check what awaits you** with `.nock/nock inbox` when you start and
  before you finish: the owner's messages and the notes they carry,
  proposals they accepted (carry them out, then mark them `implemented`) or
  rejected. When the owner is in the session, discuss with them here and
  leave at most a line in the chat; when they are away, answer in the
  topic's chat (a message event): a short summary, with blocks where
  something is better shown.
- **Run noisy or long commands through `.nock/nock run -- COMMAND`**
  (Claude Code asks about it as about the command itself), and
  `.nock/nock check` before you finish: the checks your changes can affect
  (`check --all` runs them all). Exit codes: 1 fix the code, 42
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
says where things stand, `.nock/shared/memory.md` what it has learned. When
the human needs something nock lacks or finds it broken, offer to send that to nock's makers with
`.nock/nock report`, only on their go-ahead.
"""


def primer(configuration: Configuration) -> str:
    if configuration.get("reminders") is False:
        return QUIET
    return INTRODUCTION + "\n" + MEMORY + TOPICS + REPORT


def with_section(text: str, section: str) -> str:
    """`text` with `section` between nock's markers, replacing an earlier one
    in place, or after everything else."""
    block = f"{MARK_START}\n{section.rstrip()}\n{MARK_END}\n"
    start, end = text.find(MARK_START), text.find(MARK_END)
    if 0 <= start < end:
        after = text[end + len(MARK_END) :].removeprefix("\n")
        return text[:start] + block + after
    return text.rstrip("\n") + "\n\n" + block if text.strip() else block


def refresh(directory: Path) -> list[Path]:
    """Rewrite `directory/context.md`, and the section of an AGENTS.md beside
    `directory` that holds one, when the committed settings say otherwise;
    the files it changed. A machine's own `local/config.toml` never changes a
    committed file."""
    text = primer(
        Configuration([directory / "config.toml", directory / "shared" / "settings.toml"])
    )
    changed = []
    path = directory / PRIMER
    if not (path.is_file() and path.read_text() == text):
        write_atomic(path, text)
        changed.append(path)
    agents = directory.parent / AGENTS
    held = agents.read_text() if agents.is_file() else ""
    if MARK_START in held and with_section(held, text) != held:
        write_atomic(agents, with_section(held, text))
        changed.append(agents)
    return changed
