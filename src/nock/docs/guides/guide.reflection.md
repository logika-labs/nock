---
term: guide.reflection
aliases: []
description: Your sessions recorded on your machine, and the rounds in which your agent turns them into tools
---

# Agents that build their own tools

Watch your agent for a week and you will see it repeat itself. It runs the same
five shell commands to find out why a test fails. It writes the same throwaway
script to query the database. It pipes the same noisy output through `tail`.
It trips over the mistake you already corrected twice. Every repeat costs turns
and tokens, and every session starts again from nothing.

nock's answer has two halves. Your machine keeps a record of what every session
did. And every so often, you send your agent to read that record and write the
tools it was missing. The next sessions use them, and the round after that
judges whether they helped.

## Telemetry

After `nock init` and a commit, your sessions work as before, and each one is
recorded when it ends. Everything goes into `.nock/local/nock.db`, a SQLite
file on your machine that is never committed:

- **every nock call**, refused ones included: the command and its arguments,
  how long it took, its exit code, how many bytes it printed, whether it came
  from the cache, and the error;
- **every session of your coding agent**: what you typed, each tool call the agent
  made (nock or not), what failed, the interrupts and compactions, and the
  tokens by kind;
- **every supervised process**, with its log in `.nock/local/logs/`.

Sessions are read from the agent's transcripts, from where the last read
stopped, so a session that runs for days is counted as it goes and nothing is
counted twice.

Cost is API-equivalent: what the tokens would cost at the API's list prices,
by model and kind, from LiteLLM's public price table (fetched at most daily).
A subscription doesn't pay per
token, but the number still says where the effort went. A model nock can't
price leaves its session unpriced, never at 0, and totals say how many they
leave out.

A session you work in is `interactive`. A `claude -p` run or an Agent SDK
session that nock didn't start is `headless` (graders, planners, CI), and is
kept out of the numbers and out of what a round reads. A test suite run by
`nock check` or `nock run` never records the nock calls its tests make: every
nock command sets `NOCK_UNRECORDED=1` for what it starts, and you can set it
yourself for anything else that should stay out.

You can look at it all: `nock query calls`, `nock query stats` and `nock
query sessions` summarize it, and `nock query "SELECT …"` runs read-only SQL
over its tables.

## The first session

Every session starts with the project's toolbox listed, through the agent's
session-start hook. CLAUDE.md imports a short primer, `.nock/context.md`: why
the project uses nock, to read its memory first, to report to whoever
dispatched the work, to run noisy commands through `nock run`, and to offer
to tell nock's makers what nock lacks.

A session you start also hears where things stand, in a few lines, once a day
or sooner when something new calls (a round falls due, a newer nock is out),
with a word on what to do with it: take into account what bears on your
request, and mention the rest only when relevant or once the work is done.

The toolbox answers mistakes instead of just refusing them:

```sh
$ .nock/nock failurs
nock: no command `failurs` — did you mean `failures`? (`.nock/nock` lists them all)
$ .nock/nock failures --pth tests
nock: unrecognized arguments: --pth tests; --pth → did you mean --path?
```

For work that isn't a tool yet, `.nock/nock run -- COMMAND` runs anything
long or noisy under supervision: colors and redrawn progress bars dropped,
repeated lines folded into one with a count, long output cut to its end with
the log's path. A failing call that repeats an earlier one byte for byte says
so ("same result as call 41 (3m ago) and no file has changed since"), though it
still runs, since something outside the repository may have changed.

All of these are recorded too, and that's the point: a command that doesn't
exist, a `run` that keeps wrapping the same script, a tool whose output gets
filtered by hand every time, are each a tool waiting to be written.

## Reflection rounds

A round is one protocol run once. nock ships two of its own, and a project
can have more (see [Protocols](#protocols)):

- **`nock.toolbox`** reads the work and the telemetry: what you asked for,
  where the code is going, each tool's calls and failures, the commands
  agents tried that don't exist, the raw shell work that recurs, and what the
  last round expected. It adds, changes or retires tools and checks, or
  changes nothing, when nothing earns a change;
- **`nock.fit`** reads the window's numbers beside every earlier round's (the
  first round's are the baseline), looks behind them, and forms an opinion:
  what works, what doesn't, what nock should change. It sets up the other
  rounds for the project, and keeps the memory (`.nock/shared/memory.md`:
  what is where, the owner's preferences), reshaping it from how it was used.

When they are due, the session start says so. The `/nock-reflect` skill,
which `nock init` installs, runs both at once in a session like any other:

1. **`nock reflect nock`** starts a round of each, named by its date, and
   writes what its agents will read into `.nock/local/reflections/`. Run
   again while a round is open, it picks it up and rewrites nothing; a round
   started after one finished the same day is `DATE-2`. It prints, for each,
   what the lead does: its brief, its agent with its brief and material, the
   files to write and how to submit.
2. **Two subagents** run at once, one per round.
3. **The reports**, `.nock/local/reflections/<protocol>/DATE/report.md`:
   what changed in the toolbox and the memory, what needs you, and how nock
   is doing here. The session tells you the same in a few lines when the
   rounds are done.
4. **The summary to share**, the fit round's `share.md`: the same, abstractly
   enough that nobody could tell which project it is.
5. **`nock reflect --submit JSON`**, once per round, requires its files and
   runs its checks: the tools load and their examples run, the memory is
   small, and the summary names nothing of the project (no paths, file
   names, names of the project or its authors, addresses or links). It
   commits the round's record, in `.nock/shared/rounds/<protocol>/DATE/`,
   with the toolbox or the memory it changed.

`nock reflect` alone lists every protocol: whether it can run here, whether
it is on, whether it is due and why (its measure against its threshold), its last round and its skill.

A session that started a round can't end its turn while the round is open:
nock refuses the stop once, naming what is still missing, and lets the next
stop through. A turn that ends only to wait on the round's parts, running in
the background, isn't refused: nock asks once they are back.

The toolbox part starts from the big picture, not just the numbers. A command
that would save three calls a week on a path the project is leaving isn't worth
writing; one for the chore every session in the new module repeats is.

## Calibrating over rounds

A round doesn't just change the toolbox, it writes down what each change should
do by the next round: "`failures` replaces the pytest-and-grep sequence; it
should take most of those calls". The next round reads those expectations
first and gives each a verdict, held or not, with its evidence, or too early to
tell. So over a few rounds the toolbox calibrates itself:

- **adding** what's missing: a tool for the chore that keeps costing turns, a
  check for the mistake that keeps coming back;
- **retiring** what's unused: a tool nobody has called in weeks moves to
  `.nock/tools/archive/`, kept but never loaded, so a later round can bring it
  back (a tool rarely used but vital is `pinned=True`, and never retired);
- **sharpening** what's there: a flag for the filtering sessions kept doing by
  hand, a shorter output, a better error.

Each change is code, so it is live on the next call, and it is held to the
same gate as everything else: its examples run in `nock check`, so a tool that
breaks fails the gate instead of quietly misleading the next agent.

## Protocols

A protocol is a folder, `rounds/<namespace>/<protocol>/`: `round.toml` says
what it is for, when it is due, what its lead and agents read (each material
from a command, the commits that touched some paths, the earlier rounds'
records, or a function in `material.py`), what they write and what its end
checks and commits;
`lead.md` is the lead's brief and `agents/NAME.md` each agent's. nock ships
its own, Logika's (see [nock in Logika](#nock-in-logika)), and audits and
fuzzing (`audit.performance`, `audit.security`, `audit.tests`, `fuzz.api`,
`fuzz.ui`); a project adds
its own, or overrides a shipped one by name, in `.nock/rounds/`. `nock init`
installs a skill for each one that is on outside nock's (`/team-docs` runs
`nock reflect team.docs`) and one for a namespace with two or more.

**When a round is due.** Every round whose `requires` holds is on (the logika
rounds where there is a `logika.json`), and due when enough changed since its
last run, measured from the commit that run started at: lines changed
(`git diff --numstat`, added and removed) in the paths it looks at, lockfiles
and nock's own files left out unless it names them, against a threshold; or a
change to a file that makes it due at once (a lockfile, an API's schema).
Rounds that lines don't fit measure what they are about. The defaults, in
each `round.toml`:

| round | due after |
|---|---|
| `audit.tests` | 500 lines of source and test code |
| `audit.performance` | 1,500 lines of source |
| `audit.security` | any change to a dependency manifest or lockfile, or 300 lines in code that authenticates, authorizes, routes requests or handles uploads |
| `fuzz.api` | any change to the API's routes or schema, or 300 lines in route code |
| `fuzz.ui` | 300 lines in the web UI |
| `logika.rules` | 5 more open items in `logika map` (events no rule reads, verdict-only events) |
| `logika.analytics` | 5 events added to `logika.json` |
| `nock.fit` | 10 agent sessions |
| `nock.toolbox` | 50 tool runs, or a tool failing 3 times |
| `logika.instrument` | never by itself: the logika-instrument skill starts it |

At first only the fit round is due. Its job is to set the others up for the
project: which fit, the paths each looks at (where this project
authenticates, routes requests, keeps its web UI), the thresholds. It writes
them in `.nock/config.toml` (`[rounds."audit.security"]`: `enabled`,
`paths`, `any`, `threshold`), where everything about the rounds lives, and
says in its report what it set. From then on each round is due by its own
measure, and the session start says so with its measure ("1,240 of 500
lines changed in what Tests looks at"). Nothing starts a round but your
request: its skill (`/audit-tests`) runs it in the session, which ends by
telling you what it found. Each protocol keeps its own rounds, so none
moves another's window.

## What nock shares

nock tells its makers how it's used, so they can improve it ([privacy
policy](https://nock.dev/privacy/)), but only with your yes. It asks once on a
machine, the first time you engage with nock there: the first reflection
round. Your answer is
`share` in `.nock/config.toml`, and it has no default:

- **unanswered**: nothing is sent, and no id is made;
- **`share = true`**: a weekly usage report, counts and categories only:
  nock's version, Python's and the platform; the window's numbers a round also
  keeps (sessions, requests, tool calls and failed ones, tokens, cost, nock
  calls by how they ended, the memory's size); calls and failures per nock
  command, by nock's own names; how many tools, checks and hooks the toolbox
  has. Never code, paths, file or tool names, prompts, command arguments, or
  anything else written in the project. It carries the project's id, a random UUID committed in
  `.nock/project.json` and derived from nothing, so the makers can count
  projects without knowing which;
- **`share = false`**: nothing is ever sent, round summaries included.

`.nock/nock config share` shows your answer, the reports sent, and exactly what the
next one would carry, even before you answer, so you see what you are asked
about.

A round's summary goes only with your yes: submitting the fit round sends it
when `share = true`, and otherwise `nock share` sends it once you say so. A
fresh agent first vets it: it reads the project to learn its names, people, partners and
customers, and rewrites whatever would identify it. nock scrubs the result
again and shows exactly what would be sent. The makers alone read it; nothing
is published.

And when nock lacks something you need, or something in it is broken or
confusing, tell its makers:

```sh
.nock/nock report "I need nock to say which checks a file is read by."
```

It goes with nock's version and the platform, and nothing from the repository
unless the text says it. Your agent offers to send one when it hits a gap, and
sends it only on your go-ahead. This is how nock learns what to fix.

Apart from these, nock reaches out only to fetch, sending nothing about the
project: PyPI's `nock` page, at most daily, to learn of a newer release (and
the release itself when it upgrades), and LiteLLM's price table.
