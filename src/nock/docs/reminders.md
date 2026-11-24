---
term: reminders
aliases: [quiet, nudges, reminder]
description: What nock says unasked, and `reminders = false`, which silences it
---

Unasked, nock says at a session's start, in one line, which rounds are due, once a day or when that changes; and its primer asks agents to read the memory and to report to whoever dispatched them. `.nock/nock config reminders false` silences all of it and shrinks the primer; telemetry is still recorded and `nock status` still answers.
