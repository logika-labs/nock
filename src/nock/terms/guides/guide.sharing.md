---
term: guide.sharing
aliases: [guide.share, guide.privacy]
description: Nothing without your yes: the usage report, a round's summary, and telling nock's makers
---

# What nock shares

nock tells its makers how it is used, so they can improve it ([privacy
policy](https://nock.dev/privacy/)), but only with the owner's yes. `share` in
`.nock/config.toml` (or, for one machine, `.nock/local/config.toml`) is their
answer, and has no default:

- **unset**: unanswered. Nothing is sent and no id is made until the owner
  answers (below).
- **`share = true`**: a weekly usage report, counts
  and categories only. Each report carries nock's version, Python's (`3.12`)
  and the platform (`darwin`, `linux`); whether reminders and the consultant
  are on and whether it is a Logika project; the window's numbers that a
  reflection round also keeps (how many days, sessions and headless ones,
  requests, interrupts, compactions, tool calls and failed ones, tokens in
  all and by kind, the API-equivalent cost and how many sessions are unpriced,
  commits, nock calls by how they ended, consultations, topics and items by
  verdict, how many of the project's tools were used and how often, the
  map's length and citations); calls and failures per nock command (`check`,
  `items create`, …: nock's own names); how many tools, checks, hooks and
  generators the toolbox has and how many failed to load; and how many
  rounds have run. Never code, paths, file or tool names, prompts, command
  arguments, what items say, or anything else written in the project.
  It also carries the project's id: a random UUID, committed in
  `.nock/project.json` so every clone of the project sends the same one. It
  is made only as the first report is sent, after the owner said yes (until
  then `nock usage` shows "(created when the first report is sent)" in its
  place), is derived from nothing — not the path, the remote or any name —
  and lets nock's makers count projects without knowing which; since every
  report of a project carries it, the reports are pseudonymous rather than
  anonymous. Nothing is published.
- **`share = false`**: nothing is ever sent — no report, no id is made, and
  `nock share` won't send a summary either. Only what you write and send
  yourself with `nock report` (below) still goes.

An earlier nock's `[share]` table with `level` still reads: `"none"` as
`share = false`, any other level as `share = true` (which now sends only the
anonymous report, never tool names); `nock usage` notes it until the table
is replaced.

## Asking

nock asks the owner once on a machine, while nobody has answered, the first
time they engage with nock there: the first reflection round, opening the
studio (`nock studio`), or their first verdict on an item. The
page shows the question under the title with **Share** and **Don't share**
until it is answered; the round and `/nock-triage` ask it in the session
(`ask_the_owner`), and the agent records exactly what the owner says with
`.nock/nock usage share yes` or `.nock/nock usage share no`. Either writes
`share` to the main checkout's `.nock/config.toml` and commits it (or to
`.nock/local/config.toml` when that already sets it), and keeps when the
answer was given, where, and the version of the question in
`.nock/local/usage.json`, so the consent can be shown. A `share = true` or
`share = false` already in a config is an answer, and is never asked about.
Counting starts at the yes. The first report goes a week later, as a
session ends, then at most weekly, to `endpoints.usage`, with a three-second
timeout; a failure is silent and tried again a day later. `.nock/nock usage`
shows the answer (unanswered, yes or no), when it was asked and given, the
reports sent and exactly what the next would carry (while unanswered too, so
the owner sees what they are asked about).

A round's summary is sent only with `nock share` and the owner's yes (see
[Reflection rounds](#reflection-rounds)).

## What nock fetches

Apart from these, nock reaches out only to fetch, sending nothing about the
project: PyPI's `nock` page, at most daily, to learn of a newer release, and
that release's wheel (and the vendored one's, the merge's base) when it
upgrades itself (`upgrade.check`, `upgrade.auto`); and LiteLLM's price
table (`pricing.fetch`).

## Telling nock's makers what you need

When nock lacks something you need, or something in it is broken or
confusing, tell its makers: they read what arrives and it shapes what they
build next.

```sh
.nock/nock report "I need nock to list the decisions a commit touched."
```

The text is the argument, or stdin. It goes to `endpoints.reports` with
nock's version and the platform (`darwin`, `linux`) and nothing else —
nothing from the repository unless the text says it — and the makers'
answer is a reference id, printed with what was sent. On a terminal nock shows
exactly what would go and asks `[y/N]`; with no terminal to ask on (an
agent's session) it refuses unless `--yes` is passed, and shows what it would
have sent. The primer tells agents that this channel exists and matters:
when you need something nock lacks, your agent offers to send it, and sends
it only on your go-ahead (then with `--yes`), never code or secrets unless
you ask; Claude Code asks you before each call too (it is a `confirm=True`
command). The text is at most 10,000 characters. Reports are sent whatever
`share` says: each is something you wrote and chose to send.
