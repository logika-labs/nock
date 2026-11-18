# Architecture

This document covers how nock is built: the repository, the layers, what
happens on each path through the code, and where a project plugs in. The
guides (`src/nock/terms/guides/`, nock.dev's docs) cover what nock is for and how to use it.

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
  record into the one database, and its topics go to the main checkout. `Project` holds both places: `root` is
  the main checkout, and `here` is the working tree the call runs in.
- **nock eats its own cooking.** nock's own commands, checks and fixtures are
  registered with the same decorators a project uses. `builtin.py` and
  `fixtures.py` are effectively the first two modules of every toolbox.

## Repository

```
src/nock/
  __init__.py        the public API: decorators, error classes, Output, Problem, Block
  __main__.py        python -m nock → hooks.main for `hook`, else cli.main; then utils.cache_bytecode

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
  sessions.py        Claude Code transcripts → sessions, prompts and events, read on as they grow
  callers.py         Callers: which of a session's agents runs a nock command (the before-tool hook's notes)
  prices.py          Prices: LiteLLM's public table, cached daily, for API-equivalent cost

  # the loop
  rounds.py          the registry of protocols (shipped, then `.nock/rounds/`), Protocol: whether
                     it can run and is adopted, when it is due, its materials, a round started,
                     picked up, left open and submitted; the round's commit
  rounds/            the shipped protocols, a folder each: nock/toolbox, nock/map, nock/fit,
                     logika/rules, logika/analytics, logika/instrument, audit/performance,
                     audit/security,
                     audit/tests, fuzz/api, fuzz/ui (round.toml, lead.md, agents/, material.py)
  reflect.py         Rounds (a protocol's records and scratch), the Record schema, Reflection
                     (nock's window and its metrics, over nock.fit's rounds), and the material
                     builders: Material (the toolbox), Knowledge (the memory, for fit),
                     Evidence (fit)
  logika.py          Ledger (logika.json read and counted), Logika (where its rounds can run,
                     the ledger's problems), Map (`logika map --json`'s open items),
                     and its rounds' material: Material, Analytics, Instrument
  records.py         the file kinds of `.nock/shared/`: each event's schema by where it lives
                     (topic, item, asset, review), asset.json, review.json and its blocks,
                     event file names
  shared.py          Shared, the store: its root, media, memory and committer; `settle`, the
                     write path (validate, complete, commit with trailers) every writer goes through
  fold.py            Fold: the store's events read as topics (their chat, notes, plan, reviews
                     done), items (decisions and proposals), assets by version, the review
  topics.py          Topics: read from the fold and written as events; where files are
                     (`located`: the one layer reading them); what waits on the owner and on
                     agents; the owner's notes, Send, Accept/Reject, Done; a plan's progress;
                     search; what the hooks read (news, an edited file's tasks, unstated
                     topics); the memory and its check; `heard`, what every settle does after
  timeline.py        Timeline: what happened in the topics, read from them as events, newest
                     first; the notifications are these events
  inbox.py           Inbox: what the owner said that waits on an agent, by priority; each
                     reader's shown entries (`inbox_shown`); `wait`, settling a batch
  views.py           Views: each topic folded into markdown in `.nock/local/views/`
  runs.py            Runs: the headless sessions the studio starts on the owner's click — an
                     answer now in a task's chat (resuming its session), a round run whole —
                     each turn's stream kept beside it; `.nock/local/runs/`
  studio.py          the owner's page (`nock studio`): a local server, `Api` the page's JSON;
                     `code_moment`, so a studio older than its code offers to restart
                     in place (`POST /restart`, a re-exec on the same port)
  pages/             studio.html, the shell (the band, the menu, the settings with the
                     notifications, the toasts); studio.css, its look; topics.html with
                     topics.css and chat.css, the Topics tab (each topic opening in place on
                     its review, its items, assets and chat; the filters and the round due);
                     timeline.html with timeline.css, the Timeline; view.css, the look an html
                     block is served with; icon.png, nock's logo, shown with every notification
  status.py          Standing: a round due, what waits on the owner and on agents, an
                     unshared summary; `nock status`'s nudges (record, gen)
  share.py           Sharing: a round's summary, held to naming nothing, sent on the owner's word
  usage.py           Usage: the report shared with nock's makers on the owner's yes (`share`),
                     the question asked once, the project's random id, the weekly send
  reports.py         Reports: what the user writes to nock's makers (`nock report`), shown and
                     asked on a terminal, sent with no terminal only with `--yes`
  dispatch.py        Dispatcher: launch a headless `claude -p` session in a seat and ingest it
  hooks.py           `nock hook EVENT [HARNESS]`: nock's own handlers, then the project's
  harnesses.py       Harness: Claude Code, Codex, Cursor; which are found, and each one's
                     skills directory, hooks file and events
  primer.py          the primer `.nock/context.md`, as the committed settings have it, and
                     its copy between nock's markers in AGENTS.md
  docs.py            Docs: the terms of `nock docs`, parsed and validated; the closest to a miss
  terms/             one article per term (`tools.caching.md`): front matter term, aliases,
                     description; at most 500 characters. The briefs point at the terms
    briefs/          the long texts the installed skills and subagents follow: the
                     rounds' agents reflection.toolbox, .nock (fit's); the logika
                     rounds' lead reflection.logika.lead and agents .rules, .analytics;
                     the audits' agents reflection.security, .tests (its package agent), .tests.promises;
                     topics.triage; work and work.subagent (the orchestrator, and what it
                     dispatches); review (composing a task's review)
    guides/          the documentation for people: a few long essays (guide.why, guide.review, …)
                     and the reference (guide.commands), nock.dev's docs built from them; at most
                     16,000 characters, printed whole
  briefs/
    nock-triage/     the `/nock-triage` skill, a pointer to `topics.triage`
    nock-work/       the `/nock-work` skill, a pointer to `work`, in `.agents/skills/` too
                     where Codex is found
    share.md         the brief of the agent that vets a summary before it is shared
    answer.md        the answerer's brief: the owner's message and its notes, answered now
    round.md         the reflector's brief: run the round whole, its result a task

  # the rest of the toolbox
  checks.py          Checks: command checks and @check functions → one Verdict;
                     those the branch's changes can affect (`check`), or all (`--all`)
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
  fake_agent.py      the scripted stand-in for the dispatched agents (sharer, the studio's
                     answerer and reflector)
scripts/release.py   cut a release: checks, asks, then tags vVERSION and pushes it (standard library)
web/                 nock.dev, never vendored or packaged: layout.html, home.html, legal/, site/
                     (style, fonts, the built pages), build.py (the docs pages from the
                     terms and guides), deploy.py (to Logika's box)
server/              api.nock.dev, where `nock share`, the usage reports and `nock report` post: a
                     distribution of
                     its own (`nock-api`, Python 3.14, FastAPI, Postgres), never vendored or
                     published, with its own lock, tests and deploy (server/README.md)
```

## The layers

```
             ┌─────────────────────────────────────────────────────┐
  the loop   │ hooks.py  reflect.py  topics.py  runs.py …        │
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

0. **Enter the environment.** `environment.enter`, before anything else
   (`cli.main`, and `hooks.main` for a hook), applies `[environment]`: it
   re-executes on `environment.python` when that is not the interpreter
   running (another name for the same file in the same directory, a venv's
   `python` and `python3`, is the same interpreter; making it with
   `environment.setup` first if it is missing, except in a hook), puts
   `environment.path` first on PATH and sets the dotenv's variables.
1. **Discover.** `Project.discover()` finds `here` (the working tree) and
   `root` (the main checkout) with `Git.location`: from the `.git` directory
   or file and its `commondir` (`git.located`), without starting git, unless
   something could make git answer otherwise (a `GIT_DIR`-like variable, a
   `core.worktree`, a bare repository, another owner, a filesystem crossed,
   a directory inside `.git`), when one `git rev-parse` answers. It then
   requires `.nock/` to exist.
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

`NOCK_UNRECORDED=1` turns step 8 off. Every call sets it in its own
environment once its row is started, so whatever it spawns — a check's suite,
`run`'s command, a test that runs `.nock/nock`, the `nock-tools` check's
examples (never a `confirm=True` tool's, which it only parses) — calls nock unrecorded; a refusal (`record_refusal`) honours it too.
`Dispatcher.environment` removes it, so the agents nock dispatches are
recorded as agents.

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

`store.Store` is one SQLite file, `.nock/local/nock.db`, with nine tables:

| table | written by | when |
|---|---|---|
| `calls` | `telemetry.Calls` | every call, including refusals |
| `runs` | `processes.Supervisor` | every supervised process |
| `sessions`, `prompts`, `events`, `transcripts` | `sessions.Sessions.ingest` | at SessionEnd, after a dispatched session, and whenever telemetry is read (`catch_up`: a window, `usage`, `query`, `sessions`) |
| `told` | `topics.Topics.news_for` | when a session is told what the owner said in a topic it worked in, by the event's id |
| `shown_items` | `topics.Topics.governing` | when a session is shown the items about a file it edited |
| `nudged` | `hooks.HookRunner.standing` | when a session start says the day's standing, a round's unshared summary, or a logika round's offer |

Sessions are tied to calls through `CLAUDE_CODE_SESSION_ID`, which Claude Code
sets in its Bash tool and nock records on each call.

`sessions.Transcript` reads Claude Code's JSONL transcripts as best it can.
The format is internal, so a record that fits no known shape is skipped,
never a crash. Ingest is incremental: the `transcripts` row keeps the byte
offset read to (the end of the last whole line) and, as JSON, what reading on
needs — the totals, tokens by model, the message ids already counted, the tool
calls still waiting for their results (with their `events` rowids, which a
later read fills in). One transaction, under the `transcripts` lock, writes
the new rows and the state, so a growing transcript read many times counts
each thing once; a file that shrank or moved is read again from the start,
replacing the session's rows. `catch_up` stats each transcript and reads only
those whose size moved.

The role is the one nock dispatched it as (`NOCK_ROLE`, noted in
`.nock/local/dispatched/`), else `headless` when the transcript's
`entrypoint` starts with `sdk` (`claude -p`, the Agent SDK), else
`interactive`. Only interactive sessions are the window (`Sessions.since`),
so reflection studies neither itself nor scripted runs. `Project.current_role`
reads `CLAUDE_CODE_ENTRYPOINT` the same way, so a headless session start hears
no standing and its end sends no report.

`prices.Prices` costs a session's tokens by model and kind at LiteLLM's public
table (`prices.TABLE`; a test passes its own), fetched at most daily with a
three-second timeout and cached, reduced, in `.nock/local/prices.json` (a
failed fetch is tried again after an hour). A `cost-state` record's
total wins. An unpriced session's cost is NULL; `catch_up` prices those again
once prices can be had, and a window's `spend` sums the priced and counts the
rest.

`nock query` opens the database read-only (`mode=ro`).

Raw telemetry is never committed, because it is per-machine and does not
merge. What is shared is the reflection record (see below).

## Documentation for agents

`nock docs` serves `terms/`, one Markdown file per term, named by it
(`tools.caching.md`). Its front matter holds `term`, `aliases` and a
one-line `description` (at most 100 characters); the article is at most 500,
but for the briefs in `terms/briefs/` and the guides in `terms/guides/`,
which may run to 16,000 and are printed whole (`docs.Article`, which the
output cap passes through). A guide (`guide.review`, a child of `guide`) is a
page of the documentation for people, an essay or the reference: it opens with its `# ` title, and
nock.dev's docs are built from the guides and the terms (`web/build.py`), so
the site, `nock docs` and the README's overview share one source. A short
term is what an agent needs at a glance; its guide, everything.
A dotted term is the child of the term before its last dot, and its parent's
article ends by listing it. `docs.Docs` reads them all on each call, sorted
parents first; `problems` finds a name taken twice or a child without its
parent, and the tests hold every file to the rules. A miss answers the three
closest: names it nearly spells (`difflib`), then the articles that mention
it most, then the most alike names. The briefs name the terms their agents
read (`.nock/nock docs TERM …`), and a test holds each name to a term. A new
area is a new root term with its children, such as `topics.*`.

Every skill and subagent nock installs is its front matter (the trigger)
and one line, "Run `.nock/nock docs TERM` and do what it says.": the text
it follows is a brief term, so it always matches the vendored core, and an
upgrade changes what a skill says without rewriting the skill.

## The loop

### Hooks

`nock init` writes entries into each found harness's hooks file that call
`.nock/nock hook <NativeEvent> [HARNESS]`, the event by Claude Code's name:
`.claude/settings.json` (`"$CLAUDE_PROJECT_DIR"/.nock/nock hook EVENT`),
`.codex/hooks.json` and `.cursor/hooks.json` (`"$(git rev-parse
--show-toplevel)"/.nock/nock hook EVENT codex|cursor`, since neither names
the project directory, with a 300-second timeout, past the upgrade a session
start may run). `python -m nock hook` goes to `hooks.main` without loading
the rest of the CLI (`__main__.py`), which enters the environment and hands
it to `hooks.run`. A hook runs on every tool call, so each handler imports
what only it needs inside itself (the package's public names load on first
use too, `nock.__getattr__`), and nock's own bytecode is written even under
`PYTHONDONTWRITEBYTECODE` (`utils.cache_bytecode`, at exit and before a
re-execution; the project's modules are left as the variable says).
`hooks.run`:

1. reads the payload from stdin, in Claude Code's words (`hooks.normalized`:
   Cursor's `conversation_id` is the session, its first `workspace_roots`
   the directory, a `loop_count` above 0 a `stop_hook_active`), and
   discovers the project from its `cwd`;
2. runs nock's own handlers:
   - **SessionStart** rewrites the primer when the committed settings say
     otherwise (`primer.refresh`), then returns the project's tools, any
     load failures, and, for a session the human started, `status.Standing`'s
     short lines (the first few items of each kind): a round due, "N new in
     Topics (emails: 2, pricing: 1)", what waits on agents there (threads
     where the owner wrote last, rejected items), and — once per round — an
     unshared summary. The standing is said once a day,
     keyed in `nudged` by the date and a digest of what calls (a round due,
     what waits on agents in Topics, an unshared summary, a newer nock,
     a logika round), so something new is said at once and the same thing
     not again that day. What calls for the human is said to them too, as
     `systemMessage`;
   - **UserPromptSubmit** tells the session what the owner said in the
     topics it worked in — messages with their notes, their word on
     proposals, Done on a review — once each (the `told` table);
   - **PreToolUse**, wired with a Bash matcher and the hook `if` rule
     `Bash(*.nock/nock *)` unless a project hook wants every tool, notes the
     `.nock/nock` command about to run with the subagent running it
     (`callers.Callers.note`: the hook input's `agent_id` and `agent_type`,
     NULL for the session's own thread) in the `callers` table. The command,
     running, claims the newest unclaimed note of its session (within an
     hour) carrying each of its plain arguments (`Callers.claim`, once per
     process, from `Project.writer`), which then stamps its records with
     the subagent as `session`, the session as `parent`, its type as
     `role`. A subagent's own environment has only its parent's
     `CLAUDE_CODE_SESSION_ID`, so this is the one way to tell them apart;
     a session nock dispatches gets `NOCK_PARENT_SESSION` instead;
   - **Stop**, besides refusing a turn with a round left open, refuses once
     a session (the `stated` table) the end of a turn when the session, or
     a subagent of it, did its own work in a planned or active topic (review,
     like done and abandoned, says where it stands: `FINISHED`) (opened
     it, or wrote an item, an asset, a review or a message there: the
     `wrote` table, which `Topics.heard` fills from each settle's agent
     events, so the owner's word never counts)
     and never set its state or status (`Topics.unstated`);
   - **PostToolUse**, wired with an edit-tools-and-Bash matcher unless a
     project hook wants every tool, first settles what the tool wrote in the
     store (`HookRunner.settled`: `Shared.settle_changes`, one `git status`
     when nothing changed), as the payload's session (a subagent by its
     `agent_id`, its session the parent), writes the touched topics' views
     (`views.Views`, `.nock/local/views/`), and refuses a change that does not
     hold in the same turn (`{"decision": "block", "reason": …}`), nothing of
     it committed; then it shows the decisions not rejected whose assets'
     latest versions hold the edited file or were derived `from` it, once per
     session (the `shown_items` table). In Codex it settles too. At
     SessionStart, the prompt and Stop, the same settle sweeps up what no
     hook saw, its writer unknown, and Stop refuses the end of a turn while
     a change there does not hold; every nock command sweeps likewise first
     (`shared.sweep`, in `cli.Invocation.sweep`), naming on stderr what stays
     uncommitted. It and the prompt's handler read every item
     through `Topics.summaries`: what they look for in each decision
     (`topics.summary`) kept in `.nock/local/item-summaries.json` beside its
     event folders' modification times (`folder_stamp`), so a decision is
     folded again only once it gained an event, and the decisions they tell
     of are read whole;
   - **SessionEnd** ingests the transcript and, for a session the human
     started, sends the usage statistics when due (`usage.Usage.send`);
3. runs the project's `@nock.hook`s for the event, each in a fixture
   `Scope` with `payload`. The toolbox is loaded for it only when the project
   may have one: every full load records, per working tree, the events its
   hooks listen to with a stamp of `.nock/tools/*.py` (name, modification
   time, size) in `.nock/local/hook-events.json` (`Project.hook_events`), and
   a hook for another event, with the stamp unchanged, skips the load. Returned text is joined into `additionalContext`,
   and `Block` at `stop` becomes `{"decision": "block"}`;
4. answers in the harness's format: Claude Code's and Codex's are the same
   (`hookSpecificOutput.additionalContext`, `systemMessage`, `decision:
   block`); Cursor's session start says it all as `additional_context`, and
   its stop's block is a `followup_message`;
5. **fails open**: any exception is printed to stderr, and the hook exits 0.

Each harness is wired with the events it sends that nock handles
(`Harness.events`, `own_events`): Claude Code all of the above; Codex
SessionStart, UserPromptSubmit and Stop, and a project hook's PreToolUse or
PostToolUse (its tool calls name no subagent, its edits no file, and it has
no session end); Cursor sessionStart and stop, and no project hook, its
payloads not being Claude Code's. The background-agents wait at a stop reads
Claude Code's transcript, so it applies there only.

`reminders = false` turns off everything nock's own handlers would add to
the context (SessionStart's tools and standing, the prompt's news, the
edit's items), and the primer becomes a short note on what nock is;
ingest, the usage send and the project's own hooks go on.
   A broken toolbox must never block the tool call that would fix it.

`setup.wired_events` wires the built-in events plus any event a project hook
listens to. `setup.wanted_permissions` makes the rules, one per command
(`Bash(.nock/nock PATH:*)`): every `confirm=True` command, nock's `init`,
`upgrade` and `share` among them, gets an `ask` rule, which Claude Code puts
before `allow`, so an agent's call waits on the owner; every other command
an `allow` rule, except `run` (`setup.UNLISTED`), which runs any command
and so gets none; and `.nock/nock` bare is allowed, for the listing.
With `permissions.confirm = "allow"` (`Configuration.confirm`, a
`configuration.Confirm`) the `confirm=True` commands get `allow` rules and
nothing is asked, since an `ask` rule prompts even in bypass mode; the
toolbox's listings then mark them `tools.CONFIRM_NOTES[ALLOW]`, for when the
owner's request calls for them, instead of "asks the owner".
`wire_claude` replaces nock's own rules (any `Bash(.nock/nock …)`) and keeps
the rest. The
`nock-wiring` check fails when a hook exists for an event that isn't wired,
a `confirm` command has no ask rule (or, with `confirm = "allow"`, nock
still has one), or a command has no allow rule yet.

### Topics

The store (`shared.Shared`) is the main checkout's `.nock/shared/`, committed
in the project's repository whichever worktree writes it: a directory per
topic (`topics/NAME/events/`: its state, its chat, the owner's notes, Done,
its plan), its items (`items/SLUG/events/`: a decision or a proposal, its
revisions, a proposal's verdict and its being carried out), its assets
(`assets/NAME/events/` and `versions/N/asset.json` with the small text
beside it) and its review (`review/versions/N/review.json` with its html
blocks' files; `review/events/` the versions); media by sha256 in `media/`;
and `memory.md`, what nock has learned here. Each event is one immutable
file, `<stamp>-<id>.json` (`records.EVENT_FILE`), holding its `kind`, its
fields and its envelope (`moment`, `id`, `by`: author, on behalf of whom,
user, sessions, role, host); `records` has each kind's schema by where it
lives, and the review's blocks (`records.BLOCKS`). `fold.Fold` reads the
events in name order into the records the rest of nock reads: a topic with
its chat (messages, Done, status entries), its notes as they stand (each the
latest of its edits, with the message that carried it, `notes_of`) and its
plan (`plan_of`); an item with its status (decision; a proposal open,
accepted or rejected; carried out, a decision with what was done) and its
history; an asset with its versions; the review with its versions and every
block's id. Each is folded again only once its folders changed
(`folder_stamp`).

Every write — an agent's own files, `Topics`' methods, the studio — goes
through `Shared.settle`: it reads `git status` under the root, groups the
changes by topic, item, asset and review (a topic's first, then its items
and assets, then the review that shows them), checks each group whole (no
committed event changed, every draft fitting its kind, a verdict only on a
proposal, `implemented` only on one accepted, a new item or asset in an
open topic, an asset version one file, a review's blocks naming items and
asset versions that exist and html files beside it, a message's notes
existing, its blocks valid), and completes the groups that hold no problem:
the envelope filled in, drafts renamed, `versions/next/` numbered with its
`version` event, a project file linked at the last commit that changed it
(or kept by content when it has uncommitted changes), media moved to
`media/`. It commits only those paths, with `git commit --only` and the
trailers `Nock-User`, `Nock-On-Behalf`, `Nock-Session`,
`Nock-Parent-Session`, `Nock-Host`, waiting for another git process's
`index.lock` (`Git.changing`). A change it cannot commit now (the main
checkout mid-merge or mid-rebase, git failing) is kept in
`.nock/local/uncommitted.json` with its writer, and the next settle commits
it as theirs before anything else (`commit_or_keep`, `commit_pending`).
Every commit of the store is made under the `shared` lock. `Topics` writes
its changes as drafts (`Topics.draft`) and settles only those (`only`),
under the lock (`Topics.drafting`, waiting at most `STORE_PATIENCE`), so no
other process's sweep takes them as its own. A message or a note may carry
the id the studio chose: one already there is not written again.

After every settle, `Topics.heard` writes the touched topics' views, counts
the agents' work (`wrote`, for the stop hook) and tells the owner when it
is their turn (`turn_of`: a review version or a move to review, an agent's
answer in the chat, a new proposal) through `notify.Notifications.tell`,
with the timeline's event (`Timeline.latest`). The hooks' settles and the
studio's runs go through it too.

The owner's side is `Topics.note` (a note on an item, an asset — a version,
a line — a block of the review — a span of its text — or a line of the
memory; `replaces` edits or, empty, removes one not sent), `send` (a
message carrying every unsent note, maybe empty, `now` for an answer now),
`judge` (a proposal accepted or rejected) and `done` (Done on the current
review: unsent notes go as a message, a `reviewed` event, and the topic
done when nothing waits on agents). What waits on the owner
(`waiting_on_owner`: open proposals, a review not done) and on agents
(`waiting_on_agent`: their message unanswered, proposals accepted and not
carried out) make each topic's `row`, with its `progress` (`topics.progress`:
the share of the plan's estimate done, the current step, the minutes left —
the estimates left times the pace so far, less the current step's time).
`news_for` and `governing` are the prompt and edit hooks'. `memory_problems`
is the `nock-memory` check (at most `MEMORY_LIMIT` characters, citations
`[topic/slug]` that exist). The word the owner reads for a topic is
`topics.WORD`, "task".

`timeline.Timeline` reads the topics as events (`Kind`: opened, state,
review, reviewed, item, revised, implemented, verdict, asset, reply,
message), newest first, each with a stable `key`, a `phrase`, a `title`, a
preview and its address in the studio (`#/t/TOPIC`, `/item/SLUG`,
`/asset/NAME`, `/chat`). Nothing is stored, so it covers all of the topics'
history and reads the same on every machine.

### The studio

`nock studio` serves one page from one process, `studio.Studio`, a
`ThreadingHTTPServer` on 127.0.0.1: `pages/studio.html` with `studio.css`
and each tab's fragment put in, the Topics (`topics.html`, its look
`topics.css` and `chat.css`) and the Timeline (`timeline.html`,
`timeline.css`). The address's hash says which tab and what in it is open
(`#topics/TOPIC`, `#topics/TOPIC/SLUG` an item, `#topics/TOPIC:ASSET` an
asset, `~chat` its chat); the addresses nock gives elsewhere (`#/t/TOPIC`
and what is in it) are read as the same. A topic opens in place on its
review, drawn with the list's own parts (an item as its bubble, a diff or a
document as the viewer shows a file), then its open and closed items and
its assets; its one chat floats from its row. A plan's progress is a count
in the row and a hairline in the open topic; a round due is one quiet
button among the filters, Run, In a week and Never behind it, with how
often it comes; work under way is a toast with Open and Stop. `studio.Api` answers `/api/…`, JSON both ways, a nock `Error`
becoming 404 or 400: `GET topics` (every task's row with what it holds and
where its chat stands, the two counts' lists, the rounds due, the round
runs, the runs under way), `topic/NAME` (a task
whole: its items, its assets with each version's address and small text,
its review, its chat with each message's notes, its runs), `asset/…` and
`attachment/…` (files as they are, a byte range when asked), `html/…` (an
html block with `view.css` and the bridge, `studio.BRIDGE`: `nock.note`,
`accept`, `reject`, `open`, its size, posted to the page), `history`,
`runs`, `run/ID` (a run with its turn's events, live), `rounds`,
`settings`, and `stamp`, which the page polls to read again when
the store, the runs or the notifications moved. `POST note`, `send` (then
an answer now), `verdict`, `done`, `upload`, `runs/stop`, `rounds/run`, `rounds/snooze`, `rounds/set`. `GET
/notifications` is the page's poll for what to tell the owner (in the page,
or through the browser's notifications), `POST /usage` their answer on
sharing, `/restart` whether the code changed and a restart in place.

`runs.Runs` keeps the studio's headless sessions, one per task or round at a
time, in `.nock/local/runs/ID.json` with each turn's stream-json beside it
(`ID.jsonl`, read into events: reasoning, text, each tool call and its
result). **Answer now**: an agent waiting on `nock inbox --wait`
(`inbox.listeners`) gets the message first (`inbox.urge`); otherwise the
`answerer` is dispatched with `briefs/answer.md`, resuming the task's chat
session when Claude Code still has it (`runs-sessions.json`), allowed the
task's assets' recipes; what it wrote in the store is settled as its own and
its reply linked to the run. **Run** on a round dispatches the `reflector`
with `briefs/round.md`: it runs `nock reflect NAME` whole, whose submit
writes the round's task.

### Dispatch

`dispatch.Dispatcher.launch` runs `claude -p --output-format stream-json
--session-id …` (`agent.command`, `agent.model`) for the sessions no human
sits in: the sharer, and the studio's answerer and reflector. (A reflection
round's parts are the lead's own subagents, not dispatched: the types in
`briefs/KIND/agents/`, which `nock init` installs in `.claude/agents/`, each
with only the tools its part needs.) It:

- gives the role its seat from `dispatch.SEATS`, and nothing else:
  `--permission-mode dontAsk` (anything no rule allows is refused, never
  prompted), `--setting-sources user` (the project's and the checkout's
  Claude Code settings, whose allow rules would widen the seat, are not
  loaded), `--strict-mcp-config`, `--tools` (the seat's tools) and
  `--allowedTools` (its rules; a seat's `store` adds reading
  `.nock/shared/`, the views and the linked files' cache, or writing the store
  too, by absolute path, since it may lie outside the directory the seat runs
  in; a long brief's file adds a `Read` of that file; a launch may add rules
  of its own, an asset's recipe), and `--disallowedTools` for what its rules would let through but
  must not run (git's `--output`, `dispatch.GIT_WRITING`). A role with no seat is refused, and so is an `agent.command` with a
  bypass flag (`dispatch.BYPASS`) or one of these flags of its own;
- reads what Claude Code refused from the result's `permission_denials`
  into `Session.denied`, and appends it to the run's log; the sharer keeps
  it in `outgoing.json` and the share's failure, a studio run in its problem;

- runs under a Supervisor, with `agent.deadline` (or the caller's) and
  `agent.silence`;
- strips the parent session's variables, and sets `NOCK_ROLE`;
- ingests the transcript afterwards, with that role, so the reflection
  material leaves those sessions out.

### Reflection

A round is one protocol run once. A protocol is a folder
`rounds/<namespace>/<protocol>/` (`rounds.manifests`: the shipped ones in
`nock/rounds/`, then the project's `.nock/rounds/`, which override by name):
`round.toml` (title, summary, relevant, `requires` files and commands,
`[due]` — its measure, paths, `any`, threshold —
`[material.NAME]` with one source of python, command, topic or git, `[lead]`
reads, writes and `share`, `[[agents]]` with name, reads, changes and
`fan_out`, `[end]` checks, quick, commit and kinds), `lead.md`,
`agents/NAME.md`, and `material.py` for material no command gives. Its
functions are the `python` materials and, where a protocol needs them,
hooks `rounds.Protocol` calls: `unavailable`, `measure`, `begun` (kept in
`round.json`), `kept` (kept in the record) and `problems` (the end's own).

`rounds.Protocol` does the rest the same for every protocol. `unavailable`
names a required file or command missing; `adopted` is on: every protocol
that can run here, unless `.nock/config.toml` turns it off (`[rounds."NAME"]
enabled = false`), and never one whose measure is `never`. `setting(key)`
reads that config, then the manifest's `[due]`. `measure` counts from the
baseline — its last run, or never run the fit round's — what it is about:
`lines` changed (`git diff --numstat` from the commit that run started at,
lockfiles and `.nock/` left out unless its paths name them) in its `paths`,
a file among `any` changed at all; `sessions`; project `tools` run and
failing; `topics` events; or `python`, its `material.py`'s `measure`. `due`
says why, against its threshold, unless snoozed (`snooze_until`, or
`snooze_at` a measure): the fit round at once where it never ran, the
others only once it has. `snooze` and `configure` write the config and
commit it. `start`
names the round by date (`Rounds.new_name`, or picks up `Rounds.current`),
writes each material into `.nock/local/reflections/<name>/DATE/` with
`round.json` (the sessions that started it, the commit), opens or revives
the round's task (`round-NAMESPACE-PROTOCOL`, `ensure_task`), and returns what the lead
does: its brief, each agent's subagent type (`<namespace>-<protocol>` for a
protocol's one agent, else with `-<agent>` after it), brief and material,
the files to write in `.nock/shared/rounds/<name>/DATE/`, and the submit.
`submit` checks the changes' kinds, requires the files, runs the end's
checks, writes `record.json` beside them, commits the manifest's `commit`
paths in the working tree and the record in the main checkout, and writes
the round's task (`write_task`: its changes as decisions, a review of the
summary, the report and the items its lead recorded, the task to review).

`builtin.reflect` is one command: bare, every protocol's `standing`; NAME
starts a protocol, or every adopted one of a namespace at once; `--submit
JSON` checks the record against the `Record` TypedDict (protocol, summary,
changes, verdicts, notes) and hands it to its protocol, then sends the fit
round's summary when `share` is true (`share_with_makers`; a send that
fails leaves the round recorded and says so). The Stop hook refuses, once
(never when `stop_hook_active`), the end of a turn of a session that
started a round still open, with `Protocol.left_open`: the files unwritten,
else what the quick checks find, and the submit to run.

`setup.Installer.install_rounds` installs a skill per namespace of nock's
(`/nock-reflect`, `reflect nock`), per other namespace with two or more
adopted protocols (`/logika`) and per adopted protocol outside nock's
(`/logika-rules`), each a single line naming its `reflect`, and each
adopted protocol's agents into `.claude/agents/`, their name added to the
front matter; it removes the skills and subagents of the kinds of round
that came before.

nock's own protocols are `nock.toolbox` (material `process`,
`reflect.Material`: the human's prompts, the commits and the areas they
touch, the last round's `expect` lines beside each tool's numbers now and in
its snapshot; then per-tool calls, failures by kind, duration, bytes,
capping, caching and retire candidates below ½·log₁₀(total calls), unknown
commands, Bash commands grouped by `shape()`, the files read most, the
sessions; its record keeps the per-tool snapshot; its end runs `nock-tools`
and `nock-generators`) and `nock.fit` (`evidence`, `reflect.Evidence`: the
window's metrics beside every earlier fit round's, the first being the
baseline; `catalogue`, every protocol with its settings and measure, to set
them up here; `presentation`, the html blocks agents wrote, the owner's
notes on blocks and what they skipped; `knowledge`, `reflect.Knowledge`: the
memory, the owner's notes on its lines, the items changed, every topic, and
each finished step's estimate beside its actual time; its record keeps the
metrics and `shared`; its end runs `nock-share` and `nock-memory` and
commits `.nock/config.toml`). nock's window (`Reflection.window`, for
the metrics, `nock query stats` and the usage report) opens at the latest
fit round's `finished`. Rounds are directories named by date, so records
from different machines merge as plain files.

**The logika protocols.** `logika.rules`, `logika.analytics` and `logika.instrument` require
`logika.json` in the working tree and `logika` on PATH (`Logika.unavailable`);
the first two are on where the ledger is, due by their measures (the rules:
`logika map`'s open items grown by 5; the analytics: 5 events added);
`status.Standing` offers them (`rounds`), and the session start says so at
most once a week (`nudged` keys `KIND:LAST:WEEK`). Their material comes from the ledger, git and the
items of the `logika` topic: `rules.md` (`logika.Material`) and
`analytics.md` (`logika.Analytics`: params and their flags, funnels,
milestones, views); `reflection.logika.lead` is the lead's guide and
`reflection.logika.rules` and `.analytics` the agents' briefs. The rules
material lists what each event already says must hold; the round's work
list is `logika map`'s open items (unread and verdicts events), and the
lead dispatches a rules agent per directory with open items.
`logika.instrument` is never on or due (its measure is `never`) and has no agents: an agent
runs it by name for one area. Several share one round, so its material
(`logika.Instrument`) is the whole repository's `logika map --json` at the
start (`logika.Map`, a subprocess at the working tree's root): the counts,
the directories and each open item as a submission names it (`silent
<file> <function>`, `verdicts <event>`, `unread <event>`), with the reason
its latest earlier round gave (a change of kind `reason`, by target);
`begun` and `kept` keep the open counts beside the ledger's. Each end requires
`report.md` and a parsing ledger (`tested` is optional), keeps the ledger's
counts before and after, and commits `logika.json`. The rounds read Logika's
docs through the `logika` CLI rather than copying them.

`usage.Usage` keeps `.nock/local/usage.json`: when this machine asked the
owner whether nock shares (`ask`, called by a round's start, `studio` and
the owner's first verdict, only while
`share` is unanswered; the page asks under the title, with buttons posting
to `POST /usage`, until it is answered), the answer (`answer`, from `nock
config share true|false` or the page: `share` written with `with_setting` into
the team's settings, `.nock/shared/settings.toml`, and committed, or the
local config that already sets it; when, where and the question's version in
the state), and the reports sent. `share` unset is unanswered
(`sharing` falls back to this machine's recorded answer, so a worktree reads
it before its branch has the config); a `share = true` already in a config is
a yes whose counting starts the first time `send` sees it. `report` is the
next one, built from `Reflection.metrics` over the window since the last
report (or the answer), nock's own commands' calls and failures, the
toolbox's counts, versions and switches, and the project's random id. `identity` reads it
from the main checkout's committed `.nock/project.json`, or — as the first
report is sent, which is after the yes — makes a random UUID4 under a
lock, writes it there and commits that file alone (left uncommitted if git
refuses), so every clone and worktree reports the same id. A report built
only to be shown (`nock config share`) never makes it: it shows `UNMADE` instead. `send` posts the report to
`endpoints.usage` when the answer is yes and a week has
passed (a day after a failed try), with a three-second timeout. `nock config share`
shows it all.

`share.Sharing` reads a round's `share.md`. Its `problems` — the
`nock-share` check — flag every line naming the repository's directory or
remotes, a tracked path or a file name (common ones aside), an author's
name or address, an email address or a link off nock.dev. `share`
dispatches the sharer (`briefs/share.md`) to vet the summary, scrubs its
answer the same way, and keeps it in the round's scratch directory, keyed
by the summary, so a preview and the send that follows vet once. It
returns the text and where it would go; with `send`, it posts it to
`endpoints.reflections`, records `shared` in the fit round's record, and
commits it in the store; it refuses to send, before vetting, when `share` is false.

`reports.Reports` builds what `nock report` sends: the text (the argument,
else stdin when it is not a terminal), stripped, non-empty and at most
10,000 characters, with `releases.VERSION` and `sys.platform`, nothing else.
Without `--yes` it asks: on a terminal (stdin a TTY) it writes the body and
`endpoints.reports` to stderr and reads `[y/N]`; with no terminal it raises
a `PolicyError` (43) whose value is the body it would send, so an agent can
show the user before passing `--yes`. It posts to `endpoints.reports` with a
30-second timeout and returns the body, the endpoint and the server's id; a
refusal or no answer is an `ExternalError` (52). `share` does not gate it:
each report is the user's own words, sent on their word. It is
`confirm=True`, so Claude Code asks before an agent runs it, and the primer
(`primer.REPORT`, and a sentence in the quiet one) tells agents to offer it
when the user needs something nock lacks.

On api.nock.dev (`server/`, its README has the API), `POST /reports` takes
exactly `{text, nock, platform}`: the text non-empty, at most 10,000
characters, kept stripped, Postgres-storable; `nock` and `platform` held to
the usage report's patterns; the body at most 40 KB (`413` past it, unread).
It shares the per-address in-memory rate limit with every other `POST`, keeps
the row in `reports` (`id`, `received`, `text`, `nock`, `platform`; migration
`0002_reports.sql`), nothing about the sender, and answers `201 {"id": N}`.
Its spans are `report` with a `kept` (row id, character count) or `refused`
child, never the text. The makers read the latest with `nock-api reports
[--limit N]` (newest first, 20 by default) on the box.

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
| catalog | `.nock/generators/NAME/` | its files, written by hand | `generators.Catalog` |
| brief | `.nock/briefs/NAME.md` (answer, round, share) | the file's presence | `templates.Library`, before the packaged briefs |
| skill | `.claude/skills/nock-reflect/`, `.claude/skills/nock-triage/`, `.claude/skills/nock-work/` (and `.agents/skills/nock-work/` where Codex is found), a skill per other adopted round (`.claude/skills/logika/`, `logika-rules/`, `logika-analytics/` in Logika projects), and the rounds' agents in `.claude/agents/` | `nock init` | Claude Code and Cursor, and Codex for `/nock-work`; `nock init` rewrites them |
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
  (`checks.CONCURRENCY`, via file locks), so parallel sessions don't pile up
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

`setup.Installer.install` installs into the working tree it runs in (a
worktree's install is that branch's change, never the main checkout's):

- copies the core and writes the shim, `.gitignore` (`local/`, `__pycache__/`),
  `config.toml`, `context.md` (the primer, from the settings) and `tools/`;
- records the version, the source (`pypi` unless told otherwise) and, from a
  checkout, its commit in `.nock/core/VERSION.json`;
- finds the agent harnesses the repository uses (`harnesses.found`): Claude
  Code always; Codex when there is a `.codex/` or `codex` on PATH; Cursor
  when there is a `.cursor/` or `cursor` or `cursor-agent` on PATH;
- where Codex or Cursor is found, writes the primer into AGENTS.md between
  `<!-- nock -->` and `<!-- /nock -->` (they read AGENTS.md and follow no
  import), replaced in place; `primer.refresh` keeps it current like
  `context.md`;
- imports `@.nock/context.md` into CLAUDE.md, unless CLAUDE.md imports
  AGENTS.md and AGENTS.md holds the primer, where it takes its own import out
  so Claude Code reads the primer once;
- wires each found harness's hooks file, replacing nock's entries and
  keeping everyone else's; in `.claude/settings.json` also an `allow` rule
  per command but `run`, and an `ask` rule per `confirm=True` command (an
  `allow` rule with `permissions.confirm = "allow"`);
- writes the `/nock-reflect`, `/nock-triage` and `/nock-work` skills into
  `.claude/skills/`, and each other adopted round's (`/logika`,
  `/logika-rules`, `/logika-analytics` in a Logika project), with their
  agents' subagent types in
  `.claude/agents/`. `/nock-work`, which any harness can follow, goes also
  into each found harness's skills directory that no directory written
  before is one it reads (`harnesses.skill_installs`): `.agents/skills/` for
  Codex, nothing for Cursor, which reads `.claude/skills/`; a copy nock wrote
  where no found harness reads it is taken out, an edited one kept;
- prints what it found, each file it created, updated or removed with what
  it holds, Codex's word on trusting hooks, and the next step; a file
  already as nock would write it is left alone and not listed.

It is idempotent, so running it again re-wires. It copies the core only when
there is none; a vendored core is the project's, changed only by
`nock upgrade`'s merge, so an `init` run from elsewhere (`NOCK_SOURCE`, a
checkout) re-wires around it and says it kept it.

`setup.Upgrader.upgrade` fetches the source — the latest release on PyPI
(`releases.Releases`, which reads the wheel), or a git URL or a local
checkout — and does a per-file three-way merge with `git merge-file`:

- the base is the vendored release's files (or, from git, the vendored
  commit's);
- ours is the project's `.nock/core`;
- theirs is upstream.

Conflicts are left marked and reported. Without a findable base, it refuses
unless `--force` is given. `nock upgrade` then runs the upgraded core's
`nock init`, which rewrites the primer and the skills and re-wires the hooks;
that subprocess runs without `NOCK_SOURCE`, so what re-wires is the core just
merged, not the checkout the upgrade itself may run from.

`releases.Updates.newer` is what the session start and `nock status` say
about a newer release: it asks `upgrade.index` at most once a day, with a
two-second timeout, keeps the answer in `.nock/local/latest.json`, and is
silent on any failure. A session the human starts first upgrades itself
(`hooks.HookRunner.upgrade_itself`): when `Updates.automatic` names a newer
release (`upgrade.auto` on, a core vendored from PyPI, the release not tried
since the last look-up, which it marks in `latest.json`), it runs
`.nock/nock upgrade --only-clean` as a subprocess, so the new core re-wires
the project; `only_clean` plans every file's merge before writing any and
raises a `ConflictError` with nothing changed if one conflicts. A clean
upgrade is said in one line, to the agent and the human.

Nothing in `.github/workflows/` runs on an ordinary push. `gate.yml` (ruff
check, ruff format --check, basedpyright, and the suite on Python 3.12 and
3.14) runs only by hand (`gh workflow run gate --ref BRANCH`) or when
`release.yaml` calls it. `release.yaml` runs on a pushed tag `vX.Y.Z`, which
`scripts/release.py` creates and pushes once the owner says yes: it runs the
gate on the tagged commit, checks the tag names the package's version, builds
the sdist and the wheel, publishes them to PyPI as `nock` through trusted
publishing (environment `pypi`), and attaches them with their SHA-256 sums to
a GitHub release.

## Tests

- `tests/` runs the vendored `.nock/nock` in real temporary repositories,
  with real git and real processes. The dispatched agents are
  `tests/fake_agent.py`, configured as `agent.command`: it answers as the
  sharer, the answerer and the reflector. It will not start with permissions bypassed, keeps its
  command line for a test to read, and refuses and reports a call its
  seat's rules don't allow, as Claude Code does in `dontAsk`. There are no
  mocks.

The gates are `uv run pytest -n 4`, `uv run ruff check`,
`uv run ruff format` and `uv run basedpyright`. The conventions are in
`CLAUDE.md`.
