---
term: guide.commands
aliases: []
description: Every nock command, and the exit codes that tell an agent what to do next
---

# Commands and exit codes

## Commands

| command | does |
|---|---|
| `nock` | the toolbox: the project's tools first, then nock's |
| `nock check [NAME…] [--all] [--fix]` | run the checks the branch's changes can affect (`--all` every one, or exactly the checks and chains named), side by side; prints nothing when all pass |
| `nock run -- COMMAND` | run anything supervised and condensed (your agent asks you, as for the command itself) |
| `nock docs [TERM…]` | nock's documentation for agents, a short article per term: with no term, the terms |
| `nock status` | a round due, an unshared summary, a newer nock, a logika round to offer |
| `nock config [KEY [VALUE]] [--local]` | the team's settings (with `--local`, this machine's): listed, read, set (`share` too: your answer on sharing the usage report) |
| `nock query SQL\|calls\|stats\|sessions` | the telemetry: read-only SQL, or one of its views |
| `nock reflect [NAME]`, `nock reflect --submit JSON` | the rounds: listed; one protocol's started (`nock.toolbox`), or a namespace's at once (`nock`: `/nock-reflect`; `logika`: `/logika`); a round's result recorded |
| `nock share [JSON]` | the fit round's summary as it would be sent, and sending it (asks you) |
| `nock report [TEXT] [--yes]` | send nock's makers what you need from nock or what is wrong with it (shows it and asks; with no terminal, only with `--yes`) |
| `nock init`, `nock upgrade` | install (or re-wire), and upgrade the vendored core to the latest release, with a three-way merge (each asks you) |

Every command takes `--json` and `--full`, and every cached command also takes
`--fresh`.

## Exit codes

The codes are modelled on HTTP's, and each one tells the agent what to do
next.

| code | meaning | do |
|---|---|---|
| 0 | yes | — |
| 1 | no: the subject failed (a check, a test) | fix the code |
| 40 | called wrong | change the request |
| 41 | not authenticated | log in |
| 42 | the machine or the state is not ready | fix that first, never the code |
| 43 | policy | don't |
| 44 | not found | check the reference |
| 49 | conflict | reconcile |
| 50 | nock or a tool crashed | report it, or fix the tool |
| 52 | an external service failed | retry later |
| 54 | timed out | raise the bound or split the work |
| 55 | hung: no output for too long | suspect a deadlock |
| 56 | killed by nock | see the log |
