---
term: files.topic
aliases: []
description: A topic's events: created, described, renamed, state, message, and the owner's note and reviewed
---

`topics/orders/events/x.json`:

    {"kind": "created", "description": "Where orders are kept."}
    {"kind": "state", "state": "review", "status": "built; review composed"}
    {"kind": "message", "text": "short summary", "blocks": [{"kind": "item", "item": "sqlite"}]}

Also `described`, `renamed` {name}, `plan` and `step` (`docs topics.plan`). The owner writes `note` {on, text}, `message` {text, notes} and `reviewed` {version}; an agent's message after theirs answers it.
