---
term: topics.threads
aliases: [thread, reply, message, messages, discuss, attachment, attachments]
description: The threads: what to say there, and when to say nothing
---

Each topic and item has a markdown thread. `--reply "…"` on `topics update` or `items update` adds a message; status entries answer nothing. The owner's message waits for one answer: give it. Owner in the session: discuss there, a line in the thread at most; away: answer briefly there; nothing if the new version shows it. Files the owner attaches carry `where`, their path, in `items show`, `topics show`, `awaiting_you.attachments` and the prompt hook: Read them first.
