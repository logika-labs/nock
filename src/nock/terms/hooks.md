---
term: hooks
aliases: [hook, block, events]
description: @nock.hook reacts to Claude Code's events
---

`@nock.hook("session-start")` (or `prompt`, `after-tool`, `tool-failed`, `stop`, `session-end`), asking for `payload`, the event's JSON. Text it returns is added to what the agent reads; `raise nock.Block("why")` at `stop` refuses the end of the turn. A hook runs on every such event of every session and fails open: keep it fast, and prefer a check. An event no hook listened to before needs `.nock/nock init` (`nock-wiring` says so).
