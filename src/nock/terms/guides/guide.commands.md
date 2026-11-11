---
term: guide.commands
aliases: [guide.reference, guide.exit-codes]
description: Every nock command, and the exit codes that tell an agent what to do next
---

# Commands and exit codes

## Commands

| command | does |
|---|---|
| `nock` | the toolbox: the project's tools first, then nock's |
| `nock check [NAME…] [--all] [--fix]` | run the checks the branch's changes can affect (`--all` every one, or exactly the checks and chains named), side by side; prints nothing when all pass |
| `nock run -- COMMAND` | run anything supervised and condensed (Claude Code asks, as for the command itself) |
| `nock docs [TERM…]` | nock's documentation for agents, a short article per term: with no term, the terms |
| `nock calls`, `stats`, `sessions`, `query SQL` | the telemetry |
| `nock status` | a round due, the open items by topic, what waits on agents in Topics, an unshared summary, a logika round to offer |
| `nock topics list [--query Q] [--state S] [--full]`, `create JSON`, `update TOPIC [JSON] [--reply MD] [--revive MD]`, `delete TOPIC`, `show TOPIC`, `judge TOPIC JSON`, `migrate [--mark-seen]` | the topics: a summary and the list (in the owner's order: by priority, then newest activity; or ranked by a query, or of one state), opened, their state, status and priority kept current, changed or answered in, revived, deleted when empty, in full, every open item judged (asks the owner), an earlier nock's decisions and review items moved in, earlier topics given their state |
| `nock items list [TOPIC] [--query Q] [--full]`, `create TOPIC JSON`, `update REF [JSON] [--version JSON] [--reply MD]`, `delete REF`, `show REF`, `judge REF JSON` | the items: a summary and the list, submitted, changed in place or by a new version or answered in, deleted while open and unanswered, in full, judged (asks the owner) |
| `nock topics ask QUESTION`, `topics answer JSON` | the studio's Ask: a fresh agent answers a question about the topics; only that agent submits the answer |
| `nock studio [JSON]` | the owner's page: the topics and their items, a chat with a headless agent, and Tidy up |
| `nock consult JSON` | a fresh agent advises on a task: the topics, items, tools, checks and docs that bear on it; the caller waits |
| `nock advise JSON` | the consultant's advice, submitted; only a consultant nock dispatched runs it |
| `nock usage` | what nock shares with its makers, the owner's answer, and exactly what the next report carries |
| `nock usage share yes\|no` | records the owner's answer on sharing the usage report |
| `nock reflect [KIND]`, `nock reflect [KIND] finish JSON` | a reflection round: nock's own (`/nock-reflect`), or another kind, `logika` (`/nock-reflect-logika`) |
| `nock share [JSON]` | a round's summary as it would be sent, and sending it (asks the owner) |
| `nock report [TEXT] [--yes]` | send nock's makers what you need from nock or what is wrong with it (shows it and asks; with no terminal, only with `--yes`) |
| `nock gen write`, `new`, `add`, `set`, `rm`, `show`, `bind`, `unbind` | generators |
| `nock init`, `nock upgrade` | install (or re-wire), and upgrade the vendored core to the latest release, with a three-way merge (each asks the owner) |

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
