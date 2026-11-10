---
term: telemetry.tables
aliases: [tables, nock-db]
description: The tables of nock.db, for nock query
---

`calls`, per nock call: `tool` (the command as typed), `arguments`, `session`, `started`, `duration`, `exit_code`, `output_bytes`, `full_bytes`, `cached`, `error`. `runs`: supervised processes. `sessions`: `role`, `title`, `model`, `*_tokens`, `cost` (NULL: unpriced), `prompts`. `prompts`: `session`, `text`. `events`, a session's tool calls: `tool` (Bash, Read…), `input` (the command, path or pattern), `failed`, `output_bytes`, `duration`. `told`, `shown_items`, `nudged`: who was told what.
