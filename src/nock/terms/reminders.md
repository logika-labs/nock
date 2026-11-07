---
term: reminders
aliases: [quiet, nudges, reminder]
description: What nock says unasked, and `reminders = false`, which silences it
---

Unasked, nock lists the project's tools at a session's start and, once a day or when something new calls, where things stand in a few lines; tells a session the owner's verdicts and messages on its items at a prompt; shows the items about a file after an edit; and its primer asks agents to consult and to put their work in Topics. `reminders = false` in `.nock/config.toml` silences all of it and shrinks the primer; telemetry is still recorded and `nock status` still answers.
