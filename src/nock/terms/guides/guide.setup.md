---
term: guide.setup
aliases: [guide.install, guide.installing, guide.getting-started, guide.upgrading, guide.settings, guide.config, guide.configuration, guide.permissions, guide.agents]
description: Install nock in a repository, make your tests its gate, keep it upgraded, and every setting
---

# Setting up

## Install

Inside the repository you want it in:

```sh
uvx nock init
```

(Or `pipx run nock init`; from a checkout of nock, `uv run --project
~/path/to/nock nock init`.) It:

- vendors nock into `.nock/core/` and writes the `.nock/nock` shim (a core
  already vendored is kept, since `nock upgrade` is what changes it);
- writes `.nock/config.toml` and an empty `.nock/tools/`;
- writes the primer, `.nock/context.md`, and imports it into CLAUDE.md;
- wires Claude Code's hooks;
- allows each `.nock/nock` command in Claude Code's permissions, one rule per
  command (more on that [below](#what-nocks-agents-may-do));
- installs the skills, and the subagents a round's parts run as. Each is its
  trigger and one line, "Run `.nock/nock docs TERM` and do what it says.", so
  the text it follows always matches the vendored core.

Commit the result. From then on every session in the repository starts with
the toolbox listed, and is recorded when it ends. nock speaks up unasked only a
little, and shares a usage report only if you say yes when it asks.

## Your tests as the gate

Make your test suite and linters the gate that tools and reflection rounds must
pass, by adding them as checks:

```toml
# .nock/config.toml
[checks.test]
command = "pytest -q"

[checks.lint]
command = "ruff check"
```

Checks run side by side. Those that must not, because they share a build, a
lock or a cache, share a `chain` and run one after another in the order written:

```toml
[checks.clippy]
command = "cargo clippy -- -D warnings"
chain = "rust"

[checks.cargo-test]
command = "cargo test"
chain = "rust"
```

`nock check` runs the checks the branch's changes can affect, `nock check
rust` a chain, `nock check cargo-test` one check of it, and `--all` every one.
A check's `fix` is the command that fixes what it finds, run first with `--fix`.

## Quiet

`reminders = false` keeps nock silent unless asked: no toolbox or standing at
a session's start, no verdicts at a prompt, no items after an edit, and a
primer that only says what nock is. Every session is still recorded, and `nock
status` still answers. Set it in `.nock/local/config.toml` to quiet only your
own machine.

## Upgrading

`.nock/nock upgrade` merges the latest release from PyPI into the vendored
core, keeping any local edits to it (a three-way merge against the release you
have), and re-wires the project with the merged core's primer, hooks and
skills.

nock also upgrades itself. Once a day at most, a session you start asks PyPI
whether a newer nock is out and, when the core came from PyPI, runs that upgrade
with `--only-clean`: a clean merge applies, and the session says so in one line
(the changes are yours to commit); a merge that would conflict with your edits
changes nothing, and the session says the release is out, for you to run
`.nock/nock upgrade` and resolve. `upgrade.auto = false` leaves only the word;
`upgrade.check = false` turns both off.

## Settings

`.nock/config.toml` is committed. `.nock/local/config.toml` overrides it on one
machine.

| key | default | is |
|---|---|---|
| `branch` | `main` | the main branch, which `changed` diffs against |
| `reminders` | true | whether nock speaks up unasked; false: silent unless asked |
| `notifications` | true | whether nock tells you when a topic is your turn again (moved to review, an agent answered you, a rejected item reworked): on the desktop, or in the studio while it is open; once per topic per five minutes, and never without a display (CI, a headless agent). On macOS a click opens the topic with `terminal-notifier` installed (`brew install terminal-notifier`); without it, the notification names the address |
| `output.characters`, `output.rows` | 8000, 60 | the cap on what a call prints |
| `run.deadline`, `run.silence` | 3600, 900 | seconds before a supervised process is stopped |
| `checks.NAME.command`, `fix`, `chain`, `directory`, `deadline`, `silence`, `failure_codes` | — | a command that is a check; the command that fixes what it finds; its chain; where it runs and its bounds; the exit codes that mean the code is wrong (`[1]`) |
| `checks.concurrency` | 2 | checks run at once, machine-wide |
| `reflect.sessions`, `reflect.days` | 15, 7 | when a round is due, whichever comes first |
| `reflect.logika.days` | 30 | in a Logika project, days after a logika round before the next is offered |
| `agent.command`, `agent.model`, `agent.deadline` | `claude`, —, 1800 | the headless agent nock dispatches (consult, Ask, share, the studio's chat and Tidy up); it may not bypass or set permissions |
| `permissions.confirm` | `ask` | `ask`: you approve each call of a `confirm=True` command, even in bypass mode; `allow`: the agent runs it only when your request calls for it |
| `studio.port` | 8765 | the port `nock studio` serves on, and the one a notification links to while no studio runs |
| `studio.transcribe_url`, `transcribe_model`, `transcribe_key_variable` | —, `whisper-1`, — | the Whisper server the studio's recorder sends what you say to (OpenAI's `/v1/audio/transcriptions` form: OpenAI, whisper.cpp's server, faster-whisper-server), the model, and the name of the environment variable holding its key (never the key); set in the studio's settings too |
| `consult.enabled`, `consult.deadline` | true, 600 | whether the consultant runs and the primer asks for it; seconds a consultation may take |
| `upgrade.check`, `upgrade.auto`, `upgrade.index` | true, true, PyPI's `nock` | whether a session start looks for a newer nock; whether it upgrades by itself when the merge is clean; where releases are looked up |
| `share` | — (unanswered) | your answer on the weekly usage report: unset or false sends nothing |
| `endpoints.reflections`, `endpoints.usage`, `endpoints.reports` | `https://api.nock.dev/…` | where a summary, the usage reports and `nock report` go |
| `environment.python`, `setup`, `path`, `dotenv` | —, —, `[]`, — | what tools run in: the project's interpreter and how to make it, PATH entries, a dotenv file |
| `pricing.fetch`, `pricing.table` | true, LiteLLM's table on GitHub | whether nock fetches the public price table (at most daily), and from where |
| `pricing."PREFIX"` | — | dollars per million tokens, `{input, output, cache_read, cache_write}`, for models whose name starts with PREFIX |
| `eval.cache` | — | a directory outside git for the evaluations' caches |

## What nock's agents may do

nock never bypasses Claude Code's permission checks: no code path passes Claude
Code a flag that skips them, and nock refuses an `agent.command` that does. A
test holds the package to it.

**In your sessions,** the rules `nock init` writes into
`.claude/settings.json` are all there is, one per command, nothing that runs
arbitrary shell:

- `allow`: `.nock/nock` and each command of the toolbox, nock's and the
  project's, which read, record in `.nock/`, or run the project's own committed
  tools and checks;
- `ask`: every `confirm=True` command: the project's own, and nock's `init`
  (it rewrites these rules), `upgrade` (it fetches and merges code; the clean
  upgrade a session start runs by itself is the exception, which
  `upgrade.auto = false` turns off), `share` and `report` (they send something
  out). Claude Code asks about these even in bypass mode, unless
  `permissions.confirm = "allow"`;
- no rule for `run`, which runs any command: Claude Code asks about it as it
  would about the command itself.

Re-running `nock init` replaces nock's own rules and keeps everyone else's.

**The agents nock dispatches** (`claude -p`, no one in the session) run in
`dontAsk`: each seat has the tools and allow rules its brief needs and nothing
else, and anything else is refused, never prompted, so a run can't hang on a
question. The project's Claude Code settings aren't loaded, so its allow rules
never widen a seat; your user-level settings still apply.

| seat | may |
|---|---|
| consultant | read; list and show topics and items, `docs`, submit its advice |
| asker (Ask) | read; list and show topics and items, submit its answer; `git log`, `git show` |
| sharer | read; `git log` |
| chatter (the chat) | read; list and show topics and items, `docs`; `git log`, `git show` |
| addresser (Address my comments) | read, and edit files inside the project; list, show and update topics and items, `docs`, `check`, `test`; `git log`, `show`, `diff`, `status` |
| tidier (Tidy up) | read; list, show, create, update and delete topics, update items, drop items; `docs`; `git log`, `git show` |

None but the addresser can edit a file, and none can reach the network. What
Claude Code refused comes back with the session, in its record or log.

**A round's parts** are subagents of the session running the round, narrowed by
the subagent types nock installs: the toolbox part reads, edits and runs
commands, kept to `.nock/` by its brief; the map part reads and edits the map;
the nock part and the logika round's parts only read and run commands.
