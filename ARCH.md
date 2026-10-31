# Architecture

This document covers how nock is built: the repository, the layers, what
happens on each path through the code, and where a project plugs in. The
README covers what nock is for and how to use it.

## Constraints that shape everything

- **Vendored.** `nock init` copies `src/nock/` into a project's
  `.nock/core/nock/`, and the `.nock/nock` shim runs it with
  `PYTHONPATH=.nock/core python3 -m nock`. So the package must run on bare
  Python 3.12 with the standard library and nothing else. A project whose
  tools need its own packages names its interpreter (`environment.python`),
  and `environment.Environment` re-executes nock on it first thing — nock
  is still only the standard library there. That is why nock
  has its own template engine (`templates.py`) and its own JSON Schema subset
  (`schema.py`), and why `pyproject.toml` has no runtime dependencies.
- **One process per call.** Every `.nock/nock …` call is a fresh interpreter.
  Nothing is held in memory between calls: state is in SQLite and in files
  under `.nock/local/`, and caches are keyed on content.
- **Telemetry on the main checkout, code in the working tree.** An agent may
  work in a git worktree. Its calls must use that worktree's tools, but must
  record into the one database, and its decisions go to the main checkout. `Project` holds both places: `root` is
  the main checkout, and `here` is the working tree the call runs in.
- **nock eats its own cooking.** nock's own commands, checks and fixtures are
  registered with the same decorators a project uses. `builtin.py` and
  `fixtures.py` are effectively the first two modules of every toolbox.

## Repository

```
src/nock/
  __init__.py        the public API: decorators, error classes, Output, Problem, Block
  __main__.py        python -m nock → cli.main

  # the framework: from words typed to an exit code
  cli.py             the weaver: one invocation, end to end
  commands.py        function signature → argparse command; records, schemas, suggestions
  tools.py           the decorators, and the Registry that loads the toolbox
  fixtures.py        Scope (resolves fixtures by name) and nock's own fixtures: sh, root, git, …
  render.py          return value → text (CSV, key: value, …); caps; crash reports
  errors.py          the ExitCode taxonomy and the error class for each code
  processes.py       Supervisor: run a process with a deadline and a silence timeout; Output
  environment.py     Environment: the project's interpreter, PATH and dotenv, entered first
  condense.py        clean, fold and excerpt process output

  # telemetry
  store.py           the SQLite schema and a thin Store over it
  telemetry.py       Calls (start, finish, the repeated-failure note) and Cache
  sessions.py        Claude Code transcripts → sessions, prompts and events

  # the loop
  reflect.py         Reflection (due, start, finish, metrics), Rounds, and what each part reads:
                     Material (the toolbox), Knowledge (the map), Evidence (nock itself)
  logika.py          the `logika` topic: Ledger (logika.json read and counted), LogikaRound
                     (due, start, finish) and its Material
  decisions.py       Decisions (decide, edit, review, elaborate, what governs a file, the map's problems)
  web.py             the owner's page (`nock web`), a local server
  web.html           the page
  status.py          Standing: a round due, decisions waiting, rejected ones to rework, answered
                     questions, an unshared summary
  share.py           Sharing: a round's summary, held to naming nothing, sent on the owner's word
  consult.py         Consultant: a fresh agent finds the decisions and tools that bear on a task
  dispatch.py        Dispatcher: launch a headless `claude -p` session and ingest it
  hooks.py           `nock hook EVENT`: nock's own handlers, then the project's
  briefs/
    nock-reflect/    the `/nock-reflect` skill: SKILL.md (the lead) and its three parts'
                     briefs — process.md (includes _framework.md), knowledge.md, nock.md
    nock-reflect-logika/  the `/nock-reflect-logika` skill, installed in Logika projects only:
                     SKILL.md (the round, with the owner) and rules.md (from data to rules)
    nock-triage/     the `/nock-triage` skill: going through decisions with the owner
    elaborate.md     the brief of the agent that elaborates on a decision
    consult.md       the consultant's brief
    share.md         the brief of the agent that vets a summary before it is shared
    _framework.md    the framework on one page: `nock guide`, and part of the toolbox brief

  # the rest of the toolbox
  checks.py          Checks: command checks and @check functions → one Verdict
  generators.py      @generator files and catalogs; drift detection
  templates.py       the template engine used by catalogs and briefs
  schema.py          JSON Schema subset validation
  builtin.py         nock's own commands and checks, as tools

  # plumbing
  project.py         Project: the hub (places, configuration, git, registry, store, locks)
  configuration.py   defaults ⊕ .nock/config.toml ⊕ .nock/local/config.toml
  git.py             Git: one wrapper, typed errors
  setup.py           Installer (nock init) and Upgrader (three-way merge of the core)
  releases.py        the version, and releases on PyPI: their files, and the daily look for a newer one
  utils.py           time, atomic writes, JSON, slugs

tests/               real git repositories and processes; no mocks
  conftest.py        a fresh repository with nock installed, per test; the `nock()` runner
  fake_agent.py      the scripted stand-in for the dispatched agents (elaborator, consultant)
evals/               does reflection pay? real sessions, with and without a toolbox
```

## The layers

```
             ┌─────────────────────────────────────────────────────┐
  the loop   │ hooks.py  reflect.py  decisions.py  consult.py …     │
             ├─────────────────────────────────────────────────────┤
 telemetry   │ telemetry.py   sessions.py   store.py (nock.db)      │
             ├─────────────────────────────────────────────────────┤
 framework   │ cli.py ── commands.py  tools.py  fixtures.py         │
             │           render.py  errors.py  processes.py         │
             ├─────────────────────────────────────────────────────┤
  toolbox    │ builtin.py  checks.py  generators.py  .nock/tools/*  │
             ├─────────────────────────────────────────────────────┤
  plumbing   │ project.py  configuration.py  git.py  utils.py …     │
             └─────────────────────────────────────────────────────┘
```

The framework knows nothing about reflection. Reflection reads only what the
framework and the hooks recorded. A project's tools sit at the same level as
nock's built-ins.

## The life of a call

`.nock/nock failures --path tests` goes through `cli.Invocation.run`:

0. **Enter the environment.** `cli.main`, before anything else (hooks
   included), applies `[environment]`: it re-executes on
   `environment.python` when that is not the interpreter running (making it
   with `environment.setup` first if it is missing, except in a hook), puts
   `environment.path` first on PATH and sets the dotenv's variables.
1. **Discover.** `Project.discover()` finds `here` (`git rev-parse
   --show-toplevel`) and `root` (the main checkout). It then requires
   `.nock/` to exist.
2. **Load.** `Registry.load(project)` imports `nock.builtin` and
   `nock.fixtures`, then every `.nock/tools/*.py` (subdirectories such as
   `archive/` are skipped). Each decorator appends to a pending list, which the
   registry takes as it imports each module, so every tool knows its source
   file. A module that fails to import, or a name that clashes, goes into
   `registry.failures` with `file:line` and is printed on every call. The
   other tools keep working.
3. **Parse.** `cli.build()` turns the registry into an argparse tree, through
   `commands.Command.configure`. Each parameter is classified as a `Kind`:
   - a **fixture**, when its name is a known fixture; it is not on the
     command line;
   - a **record**, when its type is a TypedDict, a dataclass or a dict; it is
     one JSON argument;
   - an **argument**, when it is positional;
   - an **option**, when it is keyword-only;
   - **rest**, for `run -- COMMAND`.

   A parse error raises `UsageError`. Before that, `Group.suggest` or
   `unrecognized` adds a "did you mean". The refusal is still recorded as a
   call, so the material shows what agents tried.
4. **Cache.** If the tool has `cache=`, `telemetry.Cache.key` hashes:
   - the command's path and its arguments;
   - the bytes of the tool's source file;
   - the size and mtime of every file its globs match.

   On a hit, the stored result is replayed with a note, and step 5 is
   skipped.
5. **Execute.** `fixtures.Scope` resolves the function's fixture parameters
   by name, recursively, with cycle detection. A generator fixture is entered
   and its teardown is queued. The result becomes an `Outcome`:
   - an `Error` becomes its exit code, and its `value` is printed as
     evidence;
   - `Exit` passes a code through;
   - any other exception becomes 50, with `render.crash` showing the tool's
     own frames and the values in them;
   - `False` becomes 1.
6. **Render.** `render.render` picks the format by the result's shape. An
   `Output` from `sh` uses its own excerpt, which keeps the end. `--json`
   bypasses rendering. `render.capped` cuts to the configured characters or
   rows. The full text goes to `.nock/local/outputs/call-N.txt`, and its path
   is printed.
7. **Note a repeat.** On a non-zero exit, `Calls.repeat` looks for an earlier
   call within six hours that matches on all of: the command, the arguments,
   a digest of the full output, and `telemetry.tree_state`. The tree state is
   HEAD plus the size and mtime of dirty files. On a match, the call is noted
   ("same result as call N"), never refused.
8. **Record.** The `calls` row is started before execution, so a call that
   hangs still shows up. It is finished last, with the duration, the exit
   code, the bytes printed and in full, whether it was cached, the error, the
   fingerprint and the tree.

Stdout carries only the result. Notes and errors go to stderr, after stdout
is flushed, so a caller that pipes the output gets clean data.

`NOCK_UNRECORDED=1` turns step 8 off. The `nock-tools` check uses it when it
runs examples.

## Supervised processes

`processes.Supervisor` runs a command in its own process group:

- it streams the output to `.nock/local/logs/run-N.log` as it arrives, so the
  log survives a SIGKILL;
- it kills the group on the deadline (54) or after too long without output
  (55);
- it records a `runs` row.

The output goes through `condense.clean`:

- ANSI codes and control characters are stripped;
- of a line redrawn with `\r`, only the last version is kept;
- absolute paths are made relative;
- runs of blank lines are squeezed;
- identical consecutive lines are folded into `line (×N)`, and lines that
  differ only in digits into `(×N similar)`.

`Output.excerpt` keeps a quarter of its budget for the head and the rest for
the tail, and points at the log.

Streamed (`stream=True`), the output is also copied to stdout as it
arrives, the child reads the caller's stdin, and when that is a terminal
the child's process group is made its foreground (`tcsetpgrp`, as a shell
does for a job), so it can prompt and Ctrl-C reaches it. On an interrupt
from elsewhere it gets SIGINT and `INTERRUPT_GRACE` seconds, its output
still logged, before the group is killed.

The `sh` fixture wraps the Supervisor for tools. It drops git's location
variables (`GIT_DIR`, …), which git sets when it runs nock. It sets a quiet environment
(`NO_COLOR`, `TERM=dumb`, `PAGER=cat`). It then either raises, for a timeout,
a hang, a program that cannot start, or `CommandFailed` with the excerpt as
evidence, or it returns the `Output` when `check=False`.

## Telemetry

`store.Store` is one SQLite file, `.nock/local/nock.db`, with eight tables:

| table | written by | when |
|---|---|---|
| `calls` | `telemetry.Calls` | every call, including refusals |
| `runs` | `processes.Supervisor` | every supervised process |
| `sessions`, `prompts`, `events` | `sessions.Sessions.ingest` | at SessionEnd, at a round's start (`catch_up`), and after a dispatched session |
| `heard` | `decisions.Decisions.news_for` | when a session is told the owner's review of a decision it recorded |
| `shown` | `decisions.Decisions.reminders_for` | when a session is shown the decisions governing a file it edited |
| `nudged` | `hooks.HookRunner.session_start` | when a session start mentions a round's unshared summary |

Sessions are tied to calls through `CLAUDE_CODE_SESSION_ID`, which Claude Code
sets in its Bash tool and nock records on each call.

`sessions.Transcript` reads Claude Code's JSONL transcripts as best it can.
The format is internal, so a record that fits no known shape is skipped,
never a crash. Ingest replaces the session's rows, so it can be run again.
Sessions that nock dispatched carry `NOCK_ROLE`, are recorded with that role,
and are left out of the material, so reflection does not study itself.

`nock query` opens the database read-only (`mode=ro`).

Raw telemetry is never committed, because it is per-machine and does not
merge. What is shared is the reflection record (see below).

## The loop

### Hooks

`nock init` writes `.claude/settings.json` entries that call
`.nock/nock hook <NativeEvent>`. `cli.main` handles `hook` before anything
else and hands it to `hooks.run`, which:

1. reads the payload from stdin and discovers the project from its `cwd`;
2. runs nock's own handlers:
   - **SessionStart** returns the project's tools, any load failures, and,
     for a session the human started, `status.Standing`'s lines: a round
     due, decisions waiting on review, rejected ones to rework, and — once
     per round (the `nudged` table) — an unshared summary. What calls for
     the human is said to them too, as `systemMessage`;
   - **UserPromptSubmit** tells the session the owner's reviews and notes on
     the decisions it recorded, once per change (the `heard` table);
   - **PostToolUse**, wired with an edit-tools matcher unless a project hook
     wants every tool, shows the standing decisions whose `touches` cover the
     edited file, the rejected first, once per session (the `shown` table);
   - **SessionEnd** ingests the transcript;
3. runs the project's `@nock.hook`s for the event, each in a fixture
   `Scope` with `payload`. Returned text is joined into `additionalContext`,
   and `Block` at `stop` becomes `{"decision": "block"}`;
4. **fails open**: any exception is printed to stderr, and the hook exits 0.
   A broken toolbox must never block the tool call that would fix it.

`setup.wired_events` wires the built-in events plus any event a project hook
listens to. Beside the blanket `Bash(.nock/nock:*)` allow, every
`confirm=True` command gets an `ask` rule (`Bash(.nock/nock PATH:*)`), which
Claude Code puts before `allow`, so an agent's call waits on the owner. The
`nock-wiring` check fails when a hook exists for an event that isn't wired,
or a `confirm` command has no ask rule.

### Decisions

`decisions.Decisions` keeps one JSON file per decision in the main
checkout's `.nock/decisions/` and commits each change there with
`git commit --only`, so a worktree's decision lands on the main branch at
once. It skips the commit, and says so, when the main checkout is mid-merge
or mid-rebase. `decide` and `edit` take the `Draft` and `Change` records;
`edit` is also the owner's review (`review`, `note`, `elaborate`), from the
page (`web.Server`, which accepts only those three) or from a session. A
change to a field in `SUBSTANCE` resets the review. A question
(`status: question`) is a decision whose review is the owner's answer;
`answered` lists those answered and not yet edited to done, for
`status.Standing`. "Elaborate" starts
`nock decisions elaborate N` as a detached process, which dispatches the
elaborator; the decision's `elaborating` flag holds until an edit changes
it, or the elaborator ends without one.

`citation_problems` is the `nock-map` check; `stale` (done decisions whose
files are gone) goes to the round's knowledge material instead, and
`unmatched` warns `decide` and `edit` of a `touches` entry that matches no
file. `nock init` writes an empty `map.md`.

`consult.Consultant` renders `briefs/consult.md` with the caller's intent
and context, and dispatches a read-only consultant in the caller's working
tree under `consult.deadline`. The session's last message is the answer the
caller prints.

### Dispatch

`dispatch.Dispatcher.launch` runs `claude -p --output-format stream-json
--session-id … --permission-mode bypassPermissions` (`agent.command`,
`agent.model`) for the sessions no human sits in: the elaborator and the
consultant and the sharer. (A reflection round's three parts are the
lead's own subagents, not dispatched.) It:

- runs under a Supervisor, with `agent.deadline` (or the caller's) and
  `agent.silence`;
- strips the parent session's variables, and sets `NOCK_ROLE`;
- ingests the transcript afterwards, with that role, so the reflection
  material leaves those sessions out.

### Reflection

A round is the `/nock-reflect` skill in an ordinary session. `nock init`
renders `briefs/nock-reflect/` into `.claude/skills/nock-reflect/`, the
toolbox brief with `!include("_framework.md")` bringing in the framework
guide.

1. **Start.** `nock reflect start` catches up on transcripts
   (`Sessions.catch_up`), names the round by date (`Rounds.new_name`, or the
   unfinished `Rounds.current`), computes `Reflection.metrics` for the
   window, and writes `round.json` and three material files in
   `.nock/local/reflections/DATE/`:
   - `process.md`, `reflect.Material`: the human's prompts, the commits and
     the areas they touch, the last round's `expect` lines beside each
     tool's numbers now and in its snapshot; then per-tool calls, failures by
     kind, duration, bytes, capping, caching and retire candidates below
     ½·log₁₀(total calls), unknown commands, Bash commands grouped by
     `shape()`, the files read most, the sessions;
   - `knowledge.md`, `reflect.Knowledge`: the decisions changed since the
     window opened, every standing one, the tags in use, the map;
   - `nock.md`, `reflect.Evidence`: the window's metrics beside every
     earlier round's, the first being the baseline.
2. **The parts.** The lead runs three subagents on them, and writes
   `report.md` and `share.md` in `.nock/reflections/DATE/`.
3. **Finish.** `nock reflect finish JSON` is checked against the `Record`
   TypedDict (summary, changes, verdicts, notes); requires both files; runs
   `ROUND_CHECKS` (`nock-tools`, `nock-generators`, `nock-map`,
   `nock-share`); writes `record.json` with the window, the metrics, the
   per-tool snapshot and `shared: null`; and commits `.nock/` (and the main
   checkout's decisions, from a worktree).

`Rounds` reads `.nock/reflections/*/record.json` (and the single-file records
of earlier versions). Rounds are directories named by date, so records from
different machines merge as plain files. The next round's window opens at
the latest one's `finished`.

`Reflection.due()` is the cheap check that SessionStart runs. A round is due
after `reflect.sessions` sessions or `reflect.days` days since the last
round, whichever comes first, given at least one session.

**The logika topic.** `reflect.Topic` names the rounds other than nock's
own; `Rounds(project, Topic.LOGIKA)` keeps them in
`.nock/reflections/logika/` (and `.nock/local/reflections/logika/`), where
nock's `*/record.json` never sees them. `logika.LogikaRound` is offered only
when `logika.json` is in the working tree and `logika` on PATH. Its `due`
— never run while the ledger declares events, or `reflect.logika.days`
after the last with commits to `logika.json` since — goes into
`status.Standing`, and the session start says it at most once a week
(`nudged` keys `logika:LAST:WEEK`). `start` writes `logika.md` from the
ledger, git and the decisions tagged `logika`; `finish` takes the same
`Record` (its `Change` kinds include validate, path, timeout, rule and
invariant, and `tested`), requires `report.md` and a parsing ledger, and
commits `.nock/` and `logika.json` through `reflect.commit`. The round
itself reads Logika's docs through the `logika` CLI rather than copying
them.

`share.Sharing` reads a round's `share.md`. Its `problems` — the
`nock-share` check — flag every line naming the repository's directory or
remotes, a tracked path or a file name (common ones aside), an author's
name or address, an email address or a link off nock.dev. `share`
dispatches the sharer (`briefs/share.md`) to vet the summary, scrubs its
answer the same way, and keeps it in the round's scratch directory, keyed
by the summary and the visibility, so a preview and the send that follows
vet once. It returns the text and where it would go; with `send`, it posts
it to `share.endpoint`, records `shared` in the round's record, and
commits.

## Extension points

Everything a project adds lives in `.nock/` and is committed:

| extension | where | registered by | used by |
|---|---|---|---|
| command (tool) | `.nock/tools/*.py` | `@nock.command` | `cli` |
| fixture | `.nock/tools/*.py` | `@nock.fixture` | `fixtures.Scope`, for any tool, check or hook |
| check | `.nock/tools/*.py` | `@nock.check` | `checks.Checks` |
| command check | `.nock/config.toml` | `[checks.NAME] command = …` (and `fix = …`) | `checks.Checks`, through the `sh` fixture |
| hook | `.nock/tools/*.py` | `@nock.hook(event)` | `hooks.HookRunner` |
| generated file | `.nock/tools/*.py` | `@nock.generator(path)` | `generators.Generators` |
| catalog | `.nock/generators/NAME/` | `nock gen new` | `generators.Catalog` |
| brief | `.nock/briefs/NAME.md` (elaborate, consult) | the file's presence | `templates.Library`, before the packaged briefs |
| skill | `.claude/skills/nock-reflect/`, `.claude/skills/nock-triage/`, `.claude/skills/nock-reflect-logika/` (Logika projects) | `nock init` | Claude Code; `nock init` rewrites them, and removes the retired `reflect` and `consolidate` |
| settings | `.nock/config.toml`, `.nock/local/config.toml` | — | `configuration.Configuration` |
| the core itself | `.nock/core/nock/` | edit it | kept by `nock upgrade`'s three-way merge |

Notes:

- **Names.** A tool's path is its function name with `_` → `-`, or `name=`,
  under `group=`. A clash with a built-in or another module is a load failure,
  not an override.
- **Fixtures** are found by parameter name. A project fixture can ask for
  other fixtures, nock's included. The names `project`, `payload` and `call`
  are supplied by the caller (`cli` or `hooks`), not by a function.
- **Checks** of one call run side by side, a thread per chain: checks that
  share a `chain` run one after another, in the order they are configured
  (they share a build lock or a cache). Calls take machine-wide slots
  (`checks.concurrency`, via file locks), so parallel sessions don't pile up
  test suites. A check's
  verdict is 1 (the code is wrong) or 42 (the machine is not ready). The
  first look names the cause.
- **Catalogs** are directories:
  - `schema.json`: the schema of one entry;
  - `entries.json`: the entries;
  - `outputs.toml`: which template renders which file;
  - `templates/`.

  Every write re-renders the bound files. `nock-generators` fails on drift.
- **The archive.** `.nock/tools/archive/` holds retired tools. It is not
  loaded, but it is kept, so a round can bring a tool back.
- **Pinned tools** (`@nock.command(pinned=True)`) are never retire
  candidates, for tools that are rarely used but vital.

## Install and upgrade

`setup.Installer.install`:

- copies the core and writes the shim, `.gitignore` (`local/`),
  `config.toml`, `context.md` and `tools/`;
- records the version, the source (`pypi` unless told otherwise) and, from a
  checkout, its commit in `.nock/core/VERSION.json`;
- imports `@.nock/context.md` into CLAUDE.md;
- wires `.claude/settings.json`: the hooks, the `Bash(.nock/nock:*)`
  permission and an `ask` rule per `confirm=True` command;
- writes the `/nock-reflect` and `/nock-triage` skills, and in a Logika
  project (`logika.json` at the root) `/nock-reflect-logika`.

It is idempotent, so running it again re-wires.

`setup.Upgrader.upgrade` fetches the source — the latest release on PyPI
(`releases.Releases`, which reads the wheel), or a git URL or a local
checkout — and does a per-file three-way merge with `git merge-file`:

- the base is the vendored release's files (or, from git, the vendored
  commit's);
- ours is the project's `.nock/core`;
- theirs is upstream.

Conflicts are left marked and reported. Without a findable base, it refuses
unless `--force` is given. `nock upgrade` then runs the upgraded core's
`nock init`, which rewrites the primer and the skills and re-wires the hooks.

`releases.Updates.newer` is what the session start and `nock status` say
about a newer release: it asks `upgrade.index` at most once a day, with a
two-second timeout, keeps the answer in `.nock/local/latest.json`, and is
silent on any failure.

`.github/workflows/release.yml` is the only workflow: a pushed tag `vX.Y.Z`
that matches the package's version is tested, built and published to PyPI
as `nock`, through trusted publishing. Nothing runs on other pushes.

## Tests and evals

- `tests/` runs the vendored `.nock/nock` in real temporary repositories,
  with real git and real processes. The dispatched agents are
  `tests/fake_agent.py`, configured as `agent.command`: it edits a
  decision as the elaborator (or stays silent) and answers as the
  consultant. There are no mocks.
- `evals/run.py` measures the whole loop with real Claude Code sessions:
  1. training tasks on a seeded shop project;
  2. one real `/nock-reflect` round, in a headless session;
  3. different test tasks of the same kinds, with and without the landed
     toolbox, each in a fresh clone.

  It reports the pass rate, cost, turns, time, tokens and tool use per kind.
  See `evals/README.md`.

The gates are `uv run pytest -n 4`, `uv run ruff check`,
`uv run ruff format` and `uv run basedpyright`. The conventions are in
`CLAUDE.md`.
