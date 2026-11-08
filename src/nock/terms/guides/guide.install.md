---
term: guide.install
aliases: [guide.installing, guide.getting-started, guide.upgrading]
description: Install nock in a repository, commit it, keep it upgraded, and make your tests its checks
---

# Install

Inside the repository you want it in:

```sh
uvx nock init
```

(Or `pipx run nock init`; from a checkout of nock, `uv run --project
~/path/to/nock nock init`.)

`nock init`:

- vendors nock into `.nock/core/` (only when there is none: a core already
  vendored is kept, and says so, since `nock upgrade` is what changes it) and
  writes the `.nock/nock` shim;
- writes `.nock/config.toml` and an empty `.nock/tools/`;
- writes the primer `.nock/context.md`, and imports it into CLAUDE.md;
- wires Claude Code's hooks;
- allows each `.nock/nock` command in Claude Code's permissions, one rule
  per command, except `run` (it runs any command, so Claude Code treats it
  as that command) and the commands that need the owner's word, which Claude
  Code asks about (see [What nock's agents may do](#what-nocks-agents-may-do));
- installs the skills, and the subagents a round's parts run as. Each is
  its trigger and one line, "Run `.nock/nock docs TERM` and do what it
  says.": the text it follows is in nock's docs, so it always matches the
  vendored core, and an upgrade never rewrites a skill.

Commit the result. From then on, every agent session in the repository starts
with the project's tools listed, and is recorded when it ends. nock speaks up
unasked only a little, and `reminders = false` silences it (see [The first
session](#the-first-session)); it shares a usage report only if you say yes when it
asks (see [What nock shares](#what-nock-shares)).

## Upgrading

To upgrade, `.nock/nock upgrade`. It merges the latest release from PyPI into
the vendored core, keeping any local edits to it (a three-way merge against
the release you have), and re-wires the project: primer, hooks and skills,
rewritten by the core just merged (its `nock init`, with `NOCK_SOURCE` left
out).
nock also upgrades itself: once a day at most, a session you start asks PyPI
whether a newer nock is out and, when it is and the core came from PyPI,
runs that upgrade with `--only-clean`. A clean merge applies by itself and
the session says so in one line (the changes to `.nock/` and `.claude/` are
yours to commit); a merge that would conflict with your edits to the core
changes nothing, and the session says the release is out, for you to run
`.nock/nock upgrade` and resolve. `upgrade.auto = false` leaves only that
word; `upgrade.check = false` turns both off. Once a day at most, too,
nock fetches LiteLLM's public price table from GitHub (`pricing.table`), a
plain GET that sends nothing about the project, to cost sessions at API
prices; `pricing.fetch = false` turns that off.

## Your tests as the gate

To make your test suite and linters the gate that tools and reflection rounds
must pass, add them as checks:

```toml
# .nock/config.toml
[checks.test]
command = "pytest -q"

[checks.lint]
command = "ruff check"
```

Checks run side by side. Those that must not — they share a build, a lock
or a cache — share a `chain`, and run one after another in the order they
are written:

```toml
[checks.clippy]
command = "cargo clippy -- -D warnings"
chain = "rust"

[checks.cargo-test]
command = "cargo test"
chain = "rust"
```

`nock check rust` runs a chain; `nock check cargo-test` one check of it.
