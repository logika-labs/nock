---
term: telemetry
aliases: [calls, stats, sessions, query, sql]
description: Every call and session, recorded: nock calls, stats, sessions, query
---

Every call (refused ones too) and every Claude Code session is recorded in `.nock/local/nock.db`, never committed. `.nock/nock calls --tool NAME` shows how a tool was called and how it ended; `stats` each command's use since the last round; `sessions` recent sessions, their role and API-equivalent cost (`telemetry.sessions`); `query "SELECT …"` read-only SQL (`.nock/nock docs telemetry.tables`). Calls made inside another nock call are not recorded (`telemetry.unrecorded`).
