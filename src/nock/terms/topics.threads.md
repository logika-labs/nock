---
term: topics.threads
aliases: [thread, reply, message, messages, discuss, attachment, attachments]
description: The threads: what to say there, and when to say nothing
---

Each topic and decision has a markdown thread: write a message event in its `events/`, `{"kind": "message", "text": "…"}`, with `"attachments": [{"path": FILE}]` for files. The owner's message waits for one answer: give it (yours after it answers it). Owner in the session: discuss there, a line in the thread at most; away: answer briefly there; nothing if the new version shows it. Files the owner attaches have a `where`, their path in media/, in the views and `.nock/nock inbox`: Read them first.
