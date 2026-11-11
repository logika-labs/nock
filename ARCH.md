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
  reflect.py         Round (a kind of round: start, finish, its checks, a round left open),
                     Rounds; Reflection, nock's own kind (due, metrics), and what each part
                     reads: Material (the toolbox), Knowledge (the map), Evidence (nock itself)
  logika.py          the `logika` kind: Ledger (logika.json read and counted), LogikaRound,
                     and what its two parts read: Material (rules), Analytics
  kinds.py           KINDS: the kinds of round, the default first; adding one is an entry here
  records.py         the file kinds of `.nock/shared/`: each event's schema by where it lives
                     (topic, decision, asset), decision.json, assets.json, event file names
  shared.py          Shared, the store: its root, media and committer; `settle`, the write
                     path (validate, complete, commit with trailers) every writer goes through
  fold.py            Fold: the store's events read as topics, decisions and their assets
  topics.py          Topics: topics and their decisions (each holding its assets, a project or
                     a derived file, its variants and views, by version), read from the fold
                     and written as events; where files are (`located`: the one layer
                     reading them), the owner's verdicts, the threads, search, what waits on
                     an agent, what an edited file's decisions are, the map's problems
  legacy.py          LegacyTopics: the topics as an earlier nock kept them in `.nock/topics/`,
                     read only by the migrations
  timeline.py        Timeline: what happened in the topics, read from them as events, newest
                     first; the notifications are these events
  migration.py       Migration: an earlier nock's decisions and review items into topics, once;
                     Splitting: one asset per item; Storing: `.nock/topics/` into the store
  asking.py          Asker: the studio's Ask, a fresh agent answering through `topics answer`
  chats.py           Chats: the studio's chat with a headless agent (a session per chat,
                     streamed, resumed or re-briefed with its transcript, named on leaving),
                     Tidy up (its writes as one commit, Undo a revert), Address my
                     comments and Address now (one thread); `.nock/local/chats/`
  studio.py          the owner's page (`nock studio`): a local server, a Tab per tab, the chat's
                     routes; `code_moment`, so a studio older than its code offers to restart
                     in place (`POST /restart`, a re-exec on the same port)
  transcription.py   Transcription: the studio's recorder, a recording forwarded to the
                     Whisper server `studio.transcribe_url` names and made text
  pages/             studio.html, the shell (band with the title and the menu, routing by
                     `#NAME/ROUTE`; every tab's tokens, `--time` the one grey of every
                     timestamp); studio.css, its look (`--foil-ring` the verdict marks'), put in the shell;
                     NAME.html, each tab's fragment (markup, style, a script registering it);
                     topics.css, the topics tab's own look, put before its fragment;
                     chat.css, the topics' filters and Tidy up and the global chat, with topics.css;
                     timeline.css, the Timeline's (on the topics' look); view.css, the look a
                     view is served with; icon.png, nock's logo, shown with every notification
  status.py          Standing: a round due, the open items by topic, what waits on agents in
                     Topics, an unshared summary
  share.py           Sharing: a round's summary, held to naming nothing, sent on the owner's word
  usage.py           Usage: the report shared with nock's makers on the owner's yes (`share`),
                     the question asked once, the project's random id, the weekly send
  reports.py         Reports: what the user writes to nock's makers (`nock report`), shown and
                     asked on a terminal, sent with no terminal only with `--yes`
  consult.py         Consultant: a fresh agent advises on a task, submitting through `nock advise`
  dispatch.py        Dispatcher: launch a headless `claude -p` session and ingest it
  hooks.py           `nock hook EVENT [HARNESS]`: nock's own handlers, then the project's
  harnesses.py       Harness: Claude Code, Codex, Cursor; which are found, and each one's
                     skills directory, hooks file and events
  primer.py          the primer `.nock/context.md`, as the committed settings have it, and
                     its copy between nock's markers in AGENTS.md
  docs.py            Docs: the terms of `nock docs`, parsed and validated; the closest to a miss
  terms/             one article per term (`tools.caching.md`): front matter term, aliases,
                     description; at most 500 characters. The briefs point at the terms
    briefs/          the long texts the installed skills and subagents follow:
                     reflection.lead and its parts reflection.toolbox, .map, .nock;
                     reflection.logika.lead and its parts .rules, .analytics;
                     topics.triage; work and work.subagent (the orchestrator, and what it dispatches)
    guides/          the documentation for people: a few long essays (guide.why, guide.review, …)
                     and the reference (guide.commands), nock.dev's docs built from them; at most
                     16,000 characters, printed whole
  briefs/
    nock-reflect/    the `/nock-reflect` skill (SKILL.md) and its three parts' subagent
                     types (agents/): each its front matter and one line pointing at
                     its brief in `nock docs`
    nock-reflect-logika/  the `/nock-reflect-logika` skill and its two parts' subagent types,
                     installed in Logika projects only; pointers likewise
    nock-triage/     the `/nock-triage` skill, a pointer to `topics.triage`
    nock-work/       the `/nock-work` skill, a pointer to `work`, in `.agents/skills/` too
                     where Codex is found
    ask.md           the brief of the agent that answers the studio's Ask
    consult.md       the consultant's brief
    share.md         the brief of the agent that vets a summary before it is shared
    chat.md          the studio's chat agent's brief, with its first message
    name.md          the brief of the agent that names a chat the owner leaves
    tidy.md          Tidy up's brief: regroup, set states, drop what is stale, prioritize
    address.md       Address my comments' brief: answer each waiting comment in its thread

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
  fake_agent.py      the scripted stand-in for the dispatched agents (consultant, asker, sharer,
                     the studio's chatter, namer, tidier and addresser)
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
  the loop   │ hooks.py  reflect.py  topics.py  consult.py …     │
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
| `told` | `topics.Topics.news_for` | when a session is told the owner's verdict or message on an item it submitted |
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
   - **UserPromptSubmit** tells the session the owner's verdicts and
     messages on the items it submitted, once per change (the `told` table);
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
     it, or submitted, versioned or answered an item there: the `wrote`
     table, so a migration's rewrites and the owner's verdicts never count)
     and never set its state or status (`Topics.unstated`);
   - **PostToolUse**, wired with an edit-tools matcher unless a project hook
     wants every tool, shows the items not rejected whose latest version holds
     the edited file or was derived `from` it, once per session (the
     `shown_items` table). It and the prompt's handler read every item
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
the context (SessionStart's tools and standing, the prompt's verdicts, the
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
topic (`topics/NAME/events/`), its decisions (`decisions/SLUG/events/` and
`versions/N/decision.json`), each decision's assets (`assets/NAME/events/`
and `versions/N/assets.json` with the small text beside it), media by sha256
in `media/`, and `map.md`. Each event is one immutable file,
`<stamp>-<id>.json` (`records.EVENT_FILE`), holding its `kind`, its fields
and its envelope (`moment`, `id`, `by`: author, on behalf of whom, user,
sessions, role, host); `records` has each kind's schema by where it lives.
`fold.Fold` reads the events in name order into the records the rest of nock
reads: a topic with its thread, a decision (`item`) with its versions,
verdict, thread and assets, each asset with its versions and preferred
variant. A decision's verdict stands only while no version of it or of one
of its assets came after it.

Every write — an agent's own files, `Topics`' methods, the studio, a
migration's — goes through `Shared.settle`: it reads `git status` under the
root, groups the changes by topic and by decision (a topic's first, so a
decision may come with its new topic), checks each group whole (no committed
event changed, every draft fitting its kind, a new decision or asset with
its first version, an asset version one file or variants of one type, an
acceptance only once every asset with variants has one preferred), and
completes the groups that hold no problem: the envelope filled in, drafts
renamed, `versions/next/` numbered with its `version` event, a project file
linked at the last commit that changed it (or kept by content when it has
uncommitted changes), media moved to `media/`. It commits only those paths,
with `git commit --only` and the trailers `Nock-User`, `Nock-On-Behalf`,
`Nock-Session`, `Nock-Parent-Session`, `Nock-Host`; it skips the commit, and
says so, when the main checkout is mid-merge or mid-rebase, and for Tidy up,
whose writes `Chats.gather` commits together. A group with a problem is left
uncommitted and its problems returned. `Topics` writes its changes as drafts
(`Topics.draft`, `decision_version`, `asset_version`), settles only those
(`only`), and discards them, and any folder they leave empty, when the change
fails. A ref is `topic/slug`; `resolve` also takes a ref it had before it moved,
or an asset item's that the migration made its asset.

A topic's `state` (`State`: planned, active, review, done, abandoned) and `status`
change through `update_topic`, which writes a `state` event with both (a
change of state without a status clears it), read into the thread as a
status entry (`kind: "status"`); `talk` leaves status entries out wherever
the thread is a conversation (`pending`, `said_in`, `chat_state`,
`awaiting`, `withdraw`). `create_item` refuses a done or abandoned topic
(`CLOSED`): `update_topic --revive` writes a `state` event setting it active,
`revived` with its `note`, which `current_description` reads (or an older
`kind: "revival"` note) as the description. Every event's `by` is
`shared.by_for`: `Project.writer()` (`session`, `role`, and `parent` for a
subagent or a dispatched session), the author, on behalf of whom, the user
and the host.
`create_item` maps an item draft onto a decision and its assets: its
`decision` (or, for files to review with no choice in them, a plain
"Review: TITLE." answer) a decision version, each project file an asset of
its own, the derived files one asset (`check_assets`: several only as
variants of one type); `update_item` with `--version` writes new versions of
the decision and of the assets the change names (by project path or derived
file name), or, given nothing, the decision again and every project-file
asset linked afresh; an in-place change (open items only) writes `titled`
and new versions likewise. `prefer` writes an asset's `preferred`; `judge`
and `judge_topic` (a `Word`: verdict and comment, the comment in the
decision's thread) write `verdict` events, refusing an acceptance while an
asset's variants have none preferred (`judge_topic` accepting all leaves
those out), from the studio (the owner) or the `judge` commands
(`confirm=True`); Tidy up's drops are its own. A thread is a chat: `said_in`
refuses the owner a second message while their last is `pending` (no answer
yet, no verdict since), and an agent's message after it answers it
(`answers`, its id); `withdraw` writes a message withdrawing the pending one.
A message may carry files (`attachments`: name, type, bytes, sha256), kept
in `media/` and addressed as `attachments/SHA256/NAME`; `thread_shown` adds
`where`, the absolute path an agent reads.
`summary` is the open items by topic and `awaiting` (threads where
the owner wrote last, with `attachments`, the paths their last message
carries, when it carries any; rejected items), for the lists and `status.Standing`;
`search_items` and `search_topics` rank plain full text. `news_for` and
`governing` are the prompt and edit hooks'. `citation_problems` is the
`nock-map` check, on `[topic/slug]` citations. `nock init` writes
an empty `map.md`.

`migration.Migration` moves an earlier nock's `.nock/decisions/*.json` and
`.nock/review/KEY/N/` into topics once, by `nock init` (so `nock upgrade`
too, which runs the new core's init) or `nock topics migrate`: each old tag a
topic (the first not `important`; none, `general`), each decision a decision
item (summary, evidence and touches folded into the answer, its number an
alias, its note an owner message, supersession a thread line), each review
item an item of derived files with every version and its recipe (notes and
feedback thread messages), verdicts kept, the map moved beside the topics and
the `[decisions]` tags dropped from the config, in one commit. The owner's words it carries over count as told already (`told` rows for
every session that made a version), so the prompt hook announces only what
the owner says afterwards; `topics migrate --mark-seen`, on a project already
migrated, records every word said so far as told (local state, nothing
committed), idempotently. Then `migration.Splitting`, by the same commands,
splits each item from before one asset per item that holds several files
(not variants): the item keeps its first file (a decision, its decision and
project files) under its ref, each other file becomes `SLUG-FILE` with the
versions holding it under their own numbers, the verdict kept and the thread
copied after a `split` note dated at the item's creation, so it changes
nothing about who spoke last; one commit, once.

`timeline.Timeline` reads the topics as events (`Event`: a topic opened, its
state or status changed, it was revived, an item submitted, a version made,
an agent's message, marked when it answers the owner), newest first, each
with a stable `key`, a `phrase` for what happened, a `title`, a preview and
its address in the studio (`#topics/REF~chat` opens the chat, `~reply` with
its field focused, `~vN` a version); a topic's status changes with nothing
between them fold into the latest, with their `count`. Nothing is stored, so
it covers all of the topics' history and reads the same on every machine.
`Topics.owners_turn` hands `notify.Notifications.tell` the event the agent
just wrote (`TURNS`, by reason), whose key and address the notification row
keeps: the Timeline and the notifications are one source.

`consult.Consultant` renders `briefs/consult.md` with the caller's intent
and context, the map, the project's tools and the checks, and dispatches a
read-only consultant in the caller's working tree under `consult.DEADLINE`,
with `NOCK_CONSULTATION` naming the file its submission goes to. The
consultant ends with `nock advise` (`Advice`: advice, items, tools,
checks, feedback), which only that role may run and which refuses an
item, tool or check that doesn't exist. The caller prints the advice as
submitted, then each named item's title and verdict, each tool's usage
and the checks to run; a consultant that submits nothing (a project's own
brief) is heard by its last message. The consultation is kept in
`.nock/local/consultations/`, and its `feedback` goes to the next round's
nock material. `consult.enabled = false` returns a line saying the
consultant is off, dispatching nothing, and drops consulting from the
primer.

### The studio

`nock studio` serves one page from one process, `studio.Studio`, a
`ThreadingHTTPServer` on 127.0.0.1. The page is `pages/studio.html` with
its look (`pages/studio.css`), each tab's link in the menu and its fragment
(`pages/NAME.html`) put in; the browser
shows the tab the address names (`#NAME`, or `#NAME/ROUTE` for something in
it; an address naming no tab goes to the first, so `#7` opens the item a
decision 7 became).
A tab away keeps what it drew, and the shell keeps where each tab was
scrolled, so coming back shows it at once as it was left: a link within the
studio changes the address with `history.pushState` (no element's id is a
tab's name, and the browser's own jump to the fragment is never taken), and
Work arrives at its address again only when it changed.
On the server, `/NAME/ROUTE` goes to that tab's `get` or `post`, JSON both
ways, a nock `Error` becoming 404 or 400. A tab is a `studio.Tab` subclass
listed in `TABS`, and a fragment whose script calls
`studio.register(NAME, {show(route), hide()})`; the studio gives it
`studio.summary` (the counts under the title) and `studio.toast`. Fragments
share the page's scripts and styles, so a tab keeps its script in a closure
and its style under its own class. The band's title is nock's name; the menu
holds the tabs and the settings, each group of them (sharing, notifications,
transcription) folding on its own. Two tabs: `TimelineTab`, the timeline's
events (`GET /timeline?query=&filter=&limit=`: searched as the topics are,
kept to one filter of kinds, `FILTERS`); and `TopicsTab`, which serves every
topic with its items and where each chat stands (`topics.chat_state`:
pending, unseen since `studio.Seen`'s last look, kept in
`.nock/local/studio/seen.json`), a version's files as they are, the owner's
verdicts, preferred options and messages (`withdraw` takes back one still waiting), the
files dropped into a composer (`studio.Uploads`: a POST whose body is not JSON
is an `Upload`, staged in `.nock/local/studio/uploads/TOKEN/` until the
message they go with is sent; a withdrawn message's come back there), a
recording made text (`transcription.Transcription`: multipart, as OpenAI's
`/v1/audio/transcriptions` takes it, to the configured URL, the key from the
environment variable the configuration names; refused while no URL is set,
which the page shows as a faded recorder saying how to set one), and the Ask (`studio.Asking`: one `nock topics ask` process at a
time, cancelled by stopping it; `asking.Asker` dispatches the asker seat,
which answers through `nock topics answer`, held to naming items that
exist; `GET /topics/ask` where it stands, for the Timeline's bar). Its search
ranks as `Topics.score` does (every word first, more often higher, then all
but one, a word found where a word starts). A version's view is served at
`/topics/view/TOPIC/SLUG/N/NAME` with `view.css` and `window.nock` put in its
head, and any other name there is the version's file of that name, so a view
reaches the item's files by relative addresses. The page draws a topic's
assets as a grid of cards or a list of rows, and opens one in a viewer of
one size, its chat open; under the owner's waiting message, Address now
(`POST /chat/address` with the thread) sends the addresser to that one
thread, and `chat.addressing` (the threads a running one answers) is in each
thread's `chat`.

The global chat is no tab: `studio.ChatRoutes` answers `/chat/…` for
`chats.Chats`, and the topics tab's fragment draws it in `#topics-global`,
marked `data-everywhere`, so it writes with the same composer as every chat;
on another tab the shell sets the topics panel `data-away` instead of
hidden (no room, nothing visible but that). Its button sits in the shell
beside the gear. A turn runs `Dispatcher.launch` in a thread with the
`chatter` seat, `--include-partial-messages`, and a `listener` the
Supervisor calls with each chunk of output: `chats.Turn` reads the
stream-json into whole text blocks, the block being written and the tools
run, which `GET /chat/ID` serves while it runs (the page polls every 350 ms
then); a `stop` event kills it. The next turn resumes the session
(`--resume`) when `sessions.find_transcript` finds it and Claude Code takes
it; otherwise, or when the resume fails before a word, a new session is
briefed with the chat's transcript. Files a message carries go up as in
every chat (the topics tab's `Uploads`) and are moved to
`.nock/local/chats/ID/STAMP/`, the agent told where to read them. Leaving a chat for a new one dispatches
the `namer` (no tools) for a title and summary. `GET /chat/search/QUERY` is
the Chats list's search: the chats holding every word in their title,
summary or messages (`Chats.search`), the page marking the words as the topics'
search does. Tidy up is a chat whose
agent is the `tidier`: `Topics.commit` commits nothing for that role, and
when it ends `Chats.gather` commits `.nock/shared` once; Undo is `git
revert` of that commit, aborted when it conflicts. `items judge` refuses the
tidier anything but a drop (`"rework": false`). Address my comments is a chat
whose agent is the `addresser` (Edit and Write inside the project, nock's
reply and version commands, the project's check and test): `Topics.comments`
lists the threads where the owner's comment waits (`pending`), quoted in the
chat's first message (`chats.address_request`). A topic's `priority` orders the list
(`topics.in_order`) in the studio and in `topics list`.

### Dispatch

`dispatch.Dispatcher.launch` runs `claude -p --output-format stream-json
--session-id …` (`agent.command`, `agent.model`) for the sessions no human
sits in: the consultant, the asker, the sharer, and the studio's chatter,
namer, tidier and addresser. (A reflection
round's parts are the lead's own subagents, not dispatched: the types in
`briefs/KIND/agents/`, which `nock init` installs in `.claude/agents/`, each
with only the tools its part needs.) It:

- gives the role its seat from `dispatch.SEATS`, and nothing else:
  `--permission-mode dontAsk` (anything no rule allows is refused, never
  prompted), `--setting-sources user` (the project's and the checkout's
  Claude Code settings, whose allow rules would widen the seat, are not
  loaded), `--strict-mcp-config`, `--tools` (the seat's tools) and
  `--allowedTools` (its rules; a long brief's file adds a `Read` of that
  file), and `--disallowedTools` for what its rules would let through but
  must not run (git's `--output`, `dispatch.GIT_WRITING`). A role with no seat is refused, and so is an `agent.command` with a
  bypass flag (`dispatch.BYPASS`) or one of these flags of its own;
- reads what Claude Code refused from the result's `permission_denials`
  into `Session.denied`, and appends it to the run's log; the consultant
  keeps it in the consultation's record and its failure, the asker in its
  log, the sharer in `outgoing.json` and the share's failure;

- runs under a Supervisor, with `agent.deadline` (or the caller's) and
  `agent.silence`;
- strips the parent session's variables, and sets `NOCK_ROLE`;
- ingests the transcript afterwards, with that role, so the reflection
  material leaves those sessions out.

### Reflection

Rounds come in kinds: `kinds.KINDS` maps each name to a `reflect.Round`
subclass, which says its skill, whether its skill is installed in a
repository (`wanted`), where it can run (`unavailable`) and when it is due,
what its lead reads (`begin`), the files the lead writes, the nock checks
its end runs (`checks`, and the `quick` ones for a round left open) and its
record's own (`problems`), what the record keeps (`kept`), and what is
committed beside `.nock/` (`also`). `Round.start` and `Round.finish` do the
rest the same for every kind: name the round by date, keep `round.json`
(with the sessions that started it), require the files, run the checks,
write `record.json`, commit. `builtin` makes the commands from the
registry: `reflect` (the default kind) and `reflect finish`, and for each
other kind `reflect KIND` and `reflect KIND finish` — a command named like
its group is the group's default (`commands.Group.default`), and `finish`
is reserved. The Stop hook refuses, once (never when `stop_hook_active`),
the end of a turn of a session that started a round still open, with
`Round.left_open`: the files unwritten, else what the quick checks find,
and the finish to run.

nock's own kind is the `/nock-reflect` skill in an ordinary session. `nock init`
renders `briefs/nock-reflect/` into `.claude/skills/nock-reflect/`, a pointer
at `reflection.lead`; each part's subagent points at its brief
(`reflection.toolbox`, `reflection.map`, `reflection.nock`), and the
toolbox brief names the `nock docs` terms the part reads before writing.

1. **Start.** `nock reflect` catches up on transcripts
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
   - `knowledge.md`, `reflect.Knowledge`: the items changed since the
     window opened, every topic with its items in a line, the map;
   - `nock.md`, `reflect.Evidence`: the window's metrics beside every
     earlier round's, the first being the baseline.
2. **The parts.** The lead runs three subagents on them, and writes
   `report.md` and `share.md` in `.nock/reflections/DATE/`.
3. **Finish.** `nock reflect finish JSON` is checked against the `Record`
   TypedDict (summary, changes, verdicts, notes); requires both files; runs
   `ROUND_CHECKS` (`nock-tools`, `nock-generators`, `nock-map`,
   `nock-share`); writes `record.json` with the window, the metrics, the
   per-tool snapshot and `shared: null`; and commits `.nock/` (and the main
   checkout's topics, from a worktree).

`Rounds` reads `.nock/reflections/*/record.json`. Rounds are directories named by date, so records from
different machines merge as plain files. The next round's window opens at
the latest one's `finished`.

`Reflection.due()` is the cheap check that SessionStart runs. A round is due
after `SESSIONS` (15) sessions or `DAYS` (7) days since the last
round, whichever comes first, given at least one session.

**The logika kind.** `logika.LogikaRound` keeps its rounds in
`.nock/reflections/logika/` (and `.nock/local/reflections/logika/`), where
nock's `*/record.json` never sees them. It can run only when `logika.json`
is in the working tree and `logika` on PATH, and its skill is installed
only where `logika.json` is. Its `due` — never run while the ledger
declares events, or `reflect.logika.days` after the last with commits to
`logika.json` since — goes into `status.Standing` as an offer (`rounds`),
and the session start says it at most once a week (`nudged` keys
`KIND:LAST:WEEK`), as for any kind other than the default. `begin` writes
its two parts' material from the ledger, git and the items of the
`logika` topic: `rules.md` (`logika.Material`) and `analytics.md`
(`logika.Analytics`: params and their flags, funnels, milestones, views);
the `reflection.logika.rules` and `reflection.logika.analytics` terms are
the parts' briefs. The rules
material lists each event's `risks` (`concern.risk` by its evidence params,
or ruled out); the round's work list is `logika map`, and the lead
dispatches a rules part per directory with gaps. Its end requires
`report.md` and a parsing ledger (`tested` is optional), and commits
`logika.json` too. The round itself reads Logika's docs through the
`logika` CLI rather than copying them.

`usage.Usage` keeps `.nock/local/usage.json`: when this machine asked the
owner whether nock shares (`ask`, called by a round's start, `studio` and
the owner's first verdict through `items judge` or `topics judge`, only while
`share` is unanswered; the page asks under the title, with buttons posting
to `POST /usage`, until it is answered), the answer (`answer`, from `nock
usage share yes|no` or the page: `share` written with `with_setting` into
the main checkout's config and committed, or the local config that already
sets it, and a worktree's copy that sets it; when, where and the question's
version in the state), and the reports sent. `share` unset is unanswered
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
only to be shown (`nock usage`) never makes it: it shows `UNMADE` instead. `send` posts the report to
`endpoints.usage` when the answer is yes and a week has
passed (a day after a failed try), with a three-second timeout. `nock usage`
shows it all.

`share.Sharing` reads a round's `share.md`. Its `problems` — the
`nock-share` check — flag every line naming the repository's directory or
remotes, a tracked path or a file name (common ones aside), an author's
name or address, an email address or a link off nock.dev. `share`
dispatches the sharer (`briefs/share.md`) to vet the summary, scrubs its
answer the same way, and keeps it in the round's scratch directory, keyed
by the summary, so a preview and the send that follows vet once. It
returns the text and where it would go; with `send`, it posts it to
`endpoints.reflections`, records `shared` in the round's record, and
commits; it refuses to send, before vetting, when `share` is false.

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
| catalog | `.nock/generators/NAME/` | `nock gen new` | `generators.Catalog` |
| brief | `.nock/briefs/NAME.md` (consult, ask) | the file's presence | `templates.Library`, before the packaged briefs |
| skill | `.claude/skills/nock-reflect/`, `.claude/skills/nock-triage/`, `.claude/skills/nock-work/` (and `.agents/skills/nock-work/` where Codex is found), `.claude/skills/nock-reflect-logika/` (Logika projects) | `nock init` | Claude Code and Cursor, and Codex for `/nock-work`; `nock init` rewrites them |
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
  `.claude/skills/`, and in a Logika project (`logika.json` at the root)
  `/nock-reflect-logika`, with their parts' subagent types in
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
  consultant and as the asker. It will not start with permissions bypassed, keeps its
  command line for a test to read, and refuses and reports a call its
  seat's rules don't allow, as Claude Code does in `dontAsk`. There are no
  mocks.

The gates are `uv run pytest -n 4`, `uv run ruff check`,
`uv run ruff format` and `uv run basedpyright`. The conventions are in
`CLAUDE.md`.
