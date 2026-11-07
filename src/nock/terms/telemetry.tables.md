---
term: telemetry.tables
aliases: [tables, nock-db]
description: The tables of nock.db, for nock query
---

`calls`: each nock call's command, arguments, session, duration, exit code, bytes printed and in full, cached, error. `runs`: supervised processes. `sessions`: role, title, tokens by kind, cost (API-equivalent; NULL: unpriced), prompts, interrupts, compactions. `transcripts`: how far each is read. `prompts`: what the human typed. `events`: every tool call of every session: command, path or pattern, failed, bytes, duration. `told`, `shown_items`, `nudged`: which sessions were told what.
