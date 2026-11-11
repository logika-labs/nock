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
the project uses nock, to consult before changing code, to put work before you
in topics, to run noisy commands through `nock run`, and to offer to tell nock's
makers what nock lacks.

A session you start also hears where things stand, in a few lines, once a day
or sooner when something new calls (a round falls due, you reject an item),
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

A round is one protocol run once. nock ships three of its own, and a project
can have more (see [Protocols](#protocols)):

- **`nock.toolbox`** reads the work and the telemetry: what you asked for,
  where the code is going, each tool's calls and failures, the commands
  agents tried that don't exist, the raw shell work that recurs, and what the
  last round expected. It adds, changes or retires tools, checks and
  generators, or changes nothing, when nothing earns a change;
- **`nock.map`** reads the items submitted and decided since its last round,
  and every topic, and rewrites the map that consulting reads (see [The map
  and consulting](#the-map-and-consulting));
- **`nock.fit`** reads the window's numbers beside every earlier round's (the
  first round's are the baseline), looks behind them, and forms an opinion:
  what works, what doesn't, what nock should change, and which other rounds
  would serve the project.

When they are due, by default after 15 sessions or 7 days, whichever comes
first, the session start says so, to the agent and to you. The
`/nock-reflect` skill, which `nock init` installs, runs all three at once in
a session like any other:

1. **`nock reflect nock`** starts a round of each, named by its date, and
   writes what its agents will read into `.nock/local/reflections/`. Run
   again while a round is open, it picks it up and rewrites nothing; a round
   started after one finished the same day is `DATE-2`. It prints, for each,
   what the lead does: its brief, its agent with its brief and material, the
   files to write and how to submit.
2. **Three subagents** run at once, one per round.
3. **The reports**, `.nock/shared/rounds/<protocol>/DATE/report.md`: what
   changed in the toolbox and the map, what needs you, and how nock is doing
   here.
4. **The summary to share**, the fit round's `share.md`: the same, abstractly
   enough that nobody could tell which project it is.
5. **`nock reflect --submit JSON`**, once per round, requires its files and
   runs its checks: the tools load and their examples run, the map's
   citations hold, and the summary names nothing of the project (no paths,
   file names, names of the project or its authors, addresses or links). It
   records the round beside its files and commits them, with the toolbox or
   the map it changed.

`nock reflect` alone lists every protocol: whether it can run here, whether
it is adopted, whether it is due and why, its last round and its skill.

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
  check for the mistake that keeps coming back, a generator for the file that
  keeps drifting;
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
from a command, a topic, the commits that touched some paths, or a function
in `material.py`), what they write and what its end checks and commits;
`lead.md` is the lead's brief and `agents/NAME.md` each agent's. nock ships
its own and Logika's (see [nock in Logika](#nock-in-logika)); a project adds
its own, or overrides a shipped one by name, in `.nock/rounds/`. `nock init`
installs a skill for each adopted one outside nock's (`/team-docs` runs
`nock reflect team.docs`) and one for a namespace with two or more.

A protocol is adopted always, where its files are, or once you accept the
fit round's recommendation of it, a decision in the topic `rounds`. Its due
rules (`sessions`, `days`, `changed` files, `first`) are its manifest's; a
project changes them with a protocol folder of its own in `.nock/rounds/`. Each protocol keeps its own rounds, so none moves
another's window.

## What nock shares

nock tells its makers how it's used, so they can improve it ([privacy
policy](https://nock.dev/privacy/)), but only with your yes. It asks once on a
machine, the first time you engage with nock there: the first reflection
round, opening the studio, or your first verdict on an item. Your answer is
`share` in `.nock/config.toml`, and it has no default:

- **unanswered**: nothing is sent, and no id is made;
- **`share = true`**: a weekly usage report, counts and categories only:
  nock's version, Python's and the platform; the window's numbers a round also
  keeps (sessions, requests, tool calls and failed ones, tokens, cost, nock
  calls by how they ended, consultations, topics and items by verdict); calls
  and failures per nock command, by nock's own names; how many tools, checks,
  hooks and generators the toolbox has. Never code, paths, file or tool names,
  prompts, command arguments, what items say, or anything else written in the
  project. It carries the project's id, a random UUID committed in
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
.nock/nock report "I need nock to list the decisions a commit touched."
```

It goes with nock's version and the platform, and nothing from the repository
unless the text says it. Your agent offers to send one when it hits a gap, and
sends it only on your go-ahead. This is how nock learns what to fix.

Apart from these, nock reaches out only to fetch, sending nothing about the
project: PyPI's `nock` page, at most daily, to learn of a newer release (and
the release itself when it upgrades), and LiteLLM's price table.
