---
term: guide.telemetry
aliases: []
description: Every call and session in a local SQLite file, never committed, and how to read it
---

# Telemetry

Everything is in `.nock/local/nock.db`, a local SQLite file that is never
committed:

| table | holds |
|---|---|
| `calls` | every nock call, including refused ones: the command, its arguments, session, duration, exit code, bytes printed and in full, whether it was cached, and the error |
| `runs` | every supervised process; the logs are in `.nock/local/logs/` |
| `sessions` | each Claude Code session's role, title, tokens by kind, API-equivalent cost, prompts, interrupts and compactions |
| `prompts` | what the human typed |
| `events` | every tool call of every session: the command, path or pattern, whether it failed, the bytes returned, and the duration |
| `told` | which sessions were told the owner's verdicts and messages on the items they submitted |
| `shown_items` | which sessions were shown the items about a file they edited |
| `nudged` | what a session start said and when: the day's standing, a round's unshared summary, a logika round's offer |
| `transcripts` | how far each session's transcript has been read, and what reading on needs |

Sessions are read from Claude Code's transcripts when they end and whenever
telemetry is read (`nock usage` and its report, `stats`, `status`, `query`,
`sessions`, a session start's standing, a round): each transcript is read on
from where the last read stopped, so a session that runs for days is counted
as it goes and nothing is counted twice; a transcript that has not grown costs
one `stat`.

- **Roles.** A session someone works in is `interactive`. A `claude -p` run or
  an Agent SDK session that nock did not dispatch (its transcript says
  `"entrypoint": "sdk-…"`) is `headless`: graders, planners, CI. Headless
  sessions are kept out of the numbers (sessions, requests, interrupts, tool
  calls) and out of what a reflection round reads; the usage report counts
  them apart, as `headless_sessions`. Sessions nock dispatched carry their
  role (`consultant`, …).
- **Windows.** A window's requests and tool calls are those made inside it,
  even in a session that began before it; tokens are the sessions'.
- **Cost** is API-equivalent: what the tokens would cost at the API's list
  prices, by model and kind (input, output, cache read, cache write) — a
  subscription does not pay per token. The prices are LiteLLM's public table,
  fetched at most daily and cached in `.nock/local/prices.json`; `[pricing]`
  overrides them by model-name prefix. A model in neither, or no table at all
  (offline, `pricing.fetch = false`), leaves the session unpriced: its cost is
  unknown, never 0, and totals say how many sessions they leave out.
- **Calls made while another nock call runs are not recorded.** Every nock
  command sets `NOCK_UNRECORDED=1` for what it starts, so a test suite run by
  `nock check`, `nock run` or a project's test tool never records the nock
  calls its tests make. A call an agent makes directly is recorded, and so
  are those of the agents nock dispatches. Set `NOCK_UNRECORDED=1` yourself
  for anything else that should stay out.

To look:

- `nock calls`, `nock stats` and `nock sessions` summarize the data;
- `nock query "SELECT …"` runs read-only SQL.
