---
term: reminders
aliases: [quiet, nudges, reminder]
description: What nock says unasked, and `reminders = false`, which silences it
---

Unasked, nock lists the project's tools at a session's start and, once a day or when something new calls, where things stand in a few lines; tells a session what the owner said in its tasks at a prompt; shows the tasks whose assets show a file after an edit; and its primer asks agents to read the memory and to put their work in Topics. `.nock/nock config reminders false` silences all of it and shrinks the primer; telemetry is still recorded and `nock status` still answers.
