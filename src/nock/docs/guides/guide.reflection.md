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
tools it was missing. The next sessions use them, and the run after that
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
kept out of the numbers and out of what a run reads. A test suite run by
`nock check` or `nock run` never records the nock calls its tests make: every
nock command sets `NOCK_UNRECORDED=1` for what it starts, and you can set it
yourself for anything else that should stay out.

You can look at it all: `nock query calls`, `nock query stats` and `nock
query sessions` summarize it, and `nock query "SELECT …"` runs read-only SQL
over its tables.

## The first session

CLAUDE.md imports a short primer, `.nock/context.md`: why
the project uses nock, to read its memory first, to report to whoever
dispatched the work, to run noisy commands through `nock run`, and to offer
to tell nock's makers what nock lacks.

A session you start hears, through the agent's session-start hook, one line
naming the rounds that are due and the skills that run them, once a day or at
once when what is due changes; nothing else, and nothing when none is.
`nock status` says the rest: the last fit run, a summary not yet shared, a
newer nock.

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

A round is a group of subrounds, each one part of it: `audit` is
`audit.performance`, `audit.security` and `audit.tests`. nock ships its own
round, `nock`, and a project can have more (see [Subrounds](#subrounds)):

- **`nock.toolbox`** reads the work and the telemetry: what you asked for,
  where the code is going, each tool's calls and failures, the commands
  agents tried that don't exist, the raw shell work that recurs, and what the
  last run expected. It adds, changes or retires tools and checks, or
  changes nothing, when nothing earns a change;
- **`nock.fit`** reads the window's numbers beside every earlier run's (the
  first run's are the baseline), looks behind them, and forms an opinion:
  what works, what doesn't, what nock should change. It sets up the other
  subrounds for the project, and keeps the memory (`.nock/shared/memory.md`:
  what is where, the owner's preferences), reshaping it from how it was used.

When they are due, the session start says so. The `/nock-reflect` skill,
which `nock init` installs, runs the round in a session like any other: like
every skill nock installs, it says only which brief to follow (`nock docs
nock`), so the brief can improve without touching the skill.

1. **`nock reflect nock`** prints the plan: one subagent per subround that is
   on here, each with its prompt, which points it at its lead's brief (`nock
   docs nock.fit`). The session dispatches them all at once, in the
   background, and tells you each one's report as it ends.
2. **Each subagent leads its subround** by its brief: `nock reflect nock.fit` starts a run,
   named by its date, and writes what its agents will read into
   `.nock/local/reflections/`. Run again while a run is open, it picks it up
   and rewrites nothing; a run started after one finished the same day is
   `DATE-2`. It prints what the lead works with: where its brief is, its
   agents with their briefs and material, the files to write and how to submit. A subround can
   fan out agents of its own: one per area of the code, one per package.
3. **The reports**, `.nock/local/reflections/<subround>/DATE/report.md`:
   what changed in the toolbox and the memory, what needs you, and how nock
   is doing here.
4. **The summary to share**, the fit run's `share.md`: the same, abstractly
   enough that nobody could tell which project it is.
5. **`nock reflect --submit JSON`**, once per subround, requires its files and
   runs its checks: the tools load and their examples run, the memory is
   small, and the summary names nothing of the project (no paths, file
   names, names of the project or its authors, addresses or links). It
   commits the run's record, in `.nock/shared/rounds/<subround>/DATE/`,
   with the toolbox or the memory it changed.

`nock reflect` alone lists every subround: whether it can run here, whether
it is on, whether it is due and why (its measure against its threshold), its last run and its skill.

A session that started a run can't end its turn while the run is open:
nock refuses the stop once, naming what is still missing, and lets the next
stop through. A turn that ends only to wait on agents running in the
background isn't refused: nock asks once they are back.

The toolbox part starts from the big picture, not just the numbers. A command
that would save three calls a week on a path the project is leaving isn't worth
writing; one for the chore every session in the new module repeats is.

## Calibrating over runs

A run doesn't just change the toolbox, it writes down what each change should
do by the next run: "`failures` replaces the pytest-and-grep sequence; it
should take most of those calls". The next run reads those expectations
first and gives each a verdict, held or not, with its evidence, or too early to
tell. So over a few runs the toolbox calibrates itself:

- **adding** what's missing: a tool for the chore that keeps costing turns, a
  check for the mistake that keeps coming back;
- **retiring** what's unused: a tool nobody has called in weeks moves to
  `.nock/tools/archive/`, kept but never loaded, so a later run can bring it
  back (a tool rarely used but vital is `pinned=True`, and never retired);
- **sharpening** what's there: a flag for the filtering sessions kept doing by
  hand, a shorter output, a better error.

Each change is code, so it is live on the next call, and it is held to the
same gate as everything else: its examples run in `nock check`, so a tool that
breaks fails the gate instead of quietly misleading the next agent.

## Subrounds

A subround is a folder, `rounds/<round>/<subround>/`: `round.toml` says
what it is for, when it is due, what its lead and agents read (each material
from a command, the commits that touched some paths, the earlier runs'
records, or a function in `material.py`), what they write and what its end
checks and commits;
`agents/NAME.md` declares each agent, pointing at its brief in `nock docs`;
the lead's brief is the term named after the subround (`nock docs
audit.security`, in `docs/briefs/`), and the round's the term named after
the round (`nock docs audit`). nock ships
its own, Logika's (see [nock in Logika](#nock-in-logika)), and audits and
fuzzing (`audit.performance`, `audit.security`, `audit.tests`, `fuzz.api`,
`fuzz.ui`); a project adds
its own, or overrides a shipped one by name, in `.nock/rounds/`, with its
briefs in `.nock/docs/briefs/` (`team.docs.md`, and `team.md` for the round).
`nock init` installs a skill for each one that is on outside nock's
(`/team-docs` says to follow the brief `team.docs`) and one for a round with
two or more (`/audit` says to follow `nock docs audit`).

**When a subround is due.** Every subround whose `requires` holds is on (the
logika subrounds where there is a `logika.json`), and due when enough changed since its
last run, measured from the commit that run started at: lines changed
(`git diff --numstat`, added and removed) in the paths it looks at, lockfiles
and nock's own files left out unless it names them, against a threshold; or a
change to a file that makes it due at once (a lockfile, an API's schema).
Subrounds that lines don't fit measure what they are about. The defaults, in
each `round.toml`:

| subround | due after |
|---|---|
| `audit.tests` | 500 lines of source and test code |
| `audit.performance` | 1,500 lines of source |
| `audit.security` | any change to a dependency manifest or lockfile, or 300 lines in code that authenticates, authorizes, routes requests or handles uploads |
| `fuzz.api` | any change to the API's routes or schema, or 300 lines in route code |
| `fuzz.ui` | 300 lines in the web UI |
| `logika.instrument` | 5 more open items in `logika map` (events no rule reads, verdict-only events) |
| `logika.analytics` | 5 events added to `logika.json` |
| `nock.fit` | 10 agent sessions |
| `nock.toolbox` | 50 tool runs, or a tool failing 3 times |

At first only the fit subround is due. Its job is to set the others up for the
project: which fit, the paths each looks at (where this project
authenticates, routes requests, keeps its web UI), the thresholds. It writes
them in `.nock/config.toml` (`[rounds."audit.security"]`: `enabled`,
`paths`, `any`, `threshold`), where everything about the subrounds lives, and
says in its report what it set. From then on each subround is due by its own
measure, and the session start names it (`nock status` says why: "1,240
of 500 lines changed in what Tests looks at"). Nothing starts one but your
request: its skill (`/audit-tests`, or `/audit` for the whole round) runs
it, and the session tells you what it found. Each subround keeps its own
runs, so none moves another's window.

## What nock shares

nock tells its makers how it's used, so they can improve it ([privacy
policy](https://nock.dev/privacy/)), but only with your yes. It asks once on a
machine, the first time you engage with nock there: the first reflection
run. Your answer is
`share` in `.nock/config.toml`, and it has no default:

- **unanswered**: nothing is sent, and no id is made;
- **`share = true`**: a weekly usage report, counts and categories only:
  nock's version, Python's and the platform; the window's numbers a run also
  keeps (sessions, requests, tool calls and failed ones, tokens, cost, nock
  calls by how they ended, the memory's size); calls and failures per nock
  command, by nock's own names; how many tools, checks and hooks the toolbox
  has. Never code, paths, file or tool names, prompts, command arguments, or
  anything else written in the project. It carries the project's id, a random UUID committed in
  `.nock/project.json` and derived from nothing, so the makers can count
  projects without knowing which;
- **`share = false`**: nothing is ever sent, run summaries included.

`.nock/nock config share` shows your answer, the reports sent, and exactly what the
next one would carry, even before you answer, so you see what you are asked
about.

A fit run's summary goes only with your yes: submitting it sends it
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
