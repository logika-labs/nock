---
term: files.topic
aliases: []
description: A topic's events: created, described, renamed, state, message
---

`topics/orders/events/x.json`:

    {"kind": "created", "description": "Where orders are kept."}
    {"kind": "state", "state": "review", "status": "built; verdicts remain"}
    {"kind": "state", "state": "active", "revived": true, "note": "why it is back"}
    {"kind": "message", "text": "…", "attachments": [{"path": "shot.png"}]}

Also `described` {description}, `renamed` {name}. A message after the owner's waiting one answers it.
