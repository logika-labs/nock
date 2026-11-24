---
term: telemetry
aliases: [calls, stats, sessions, query, sql]
description: Every call and session, recorded: nock query calls, stats, sessions, SQL
---

Every call (refused ones too) and every agent session is recorded in `.nock/local/nock.db`, never committed. `.nock/nock query calls --tool NAME` shows how a tool was called and how it ended; `query stats` each command's use since the last round; `query sessions` recent sessions, their role and API-equivalent cost (`telemetry.sessions`); `query "SELECT …"` read-only SQL (`.nock/nock docs telemetry.tables`). Calls made inside another nock call are not recorded (`telemetry.unrecorded`).
