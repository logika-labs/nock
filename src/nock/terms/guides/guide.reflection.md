---
term: guide.reflection
aliases: [guide.rounds]
description: Rounds that read the record and improve the toolbox, keep the map and judge how nock is doing
---

# Reflection rounds

Rounds come in kinds. nock's own is the default: `nock reflect` starts it,
and `nock reflect finish JSON` ends it. Another kind is named:
`nock reflect logika`, then `nock reflect logika finish JSON` (see [The
logika round](#the-logika-round)). Each kind has its skill, the files its
lead writes and the checks its end must pass, and keeps its rounds apart.
A session that started a round cannot end its turn while the round is
open: nock refuses the stop once, naming the kind and what is still
missing (the files to write, what the checks find, the `finish` to run),
and lets the next stop through.

nock's round is the `/nock-reflect` skill, which `nock init` installs, run in a
session like any other. When one is due, the session start says so, to the
agent and to you: by default after 15 sessions or 7 days, whichever comes
first.

1. **`nock reflect`** starts the round, named by its date, and writes
   what its parts read into `.nock/local/reflections/DATE/`.
2. **Three subagents**, at once:
   - **the toolbox** reads the work and the telemetry — what the human asked
     for, where the code is going, each tool's calls and failures, commands
     agents tried that do not exist, raw shell work that recurs, the last
     round's expectations — and adds, changes or retires tools, checks and
     generators (retired tools go to `.nock/tools/archive/`), or changes
     nothing, when nothing earns a change;
   - **the map** reads the items submitted, changed and decided since the
     last round, and every topic, and rewrites the map;
   - **nock** reads the window's numbers beside every earlier round's — the
     first round's are the baseline — looks behind them, and forms an
     opinion: what works, what does not, what nock should change.
3. **The report**, `.nock/reflections/DATE/report.md`: what needs the owner,
   what changed in the toolbox and the map, and how nock is doing here.
4. **The summary to share**, `share.md` beside it: the same, abstractly
   enough that nobody could tell which project it is.
5. **`nock reflect finish JSON`** requires both, runs nock's checks — the tools
   load and their examples run (a `confirm` tool's are only parsed), the map's citations hold, the summary names
   nothing of the project (no paths, file names, the project's or its
   authors' names, addresses or links) — and records the round in
   `record.json`: the toolbox's changes with what each should do by the next
   round, verdicts on the last round's, the window's numbers and each tool's.
   It commits `.nock/`.

The round ends by asking the owner whether to share the summary. `nock share`
has a fresh agent vet it — it reads the project
to learn its names, people, partners and customers, and rewrites whatever
would identify it — scrubs the result again, and shows exactly what would be
sent. With `'{"send": true}'` it goes to nock's makers, who alone read it;
nothing is published. Nothing is sent otherwise, and nothing at all when
`share` is false.
