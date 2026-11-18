---
term: files.item
aliases: [files.decision, files.proposal]
description: An item: a decision or a proposal, its events
---

`topics/orders/items/sqlite/events/x.json`:

    {"kind": "created", "type": "decision", "title": "Orders live in SQLite", "means": "One file to back up; no server.", "why": "load is low"}
    {"kind": "created", "type": "proposal", "title": "Archive orders after a year", "means": "…", "takes": "a nightly job, half a day"}
    {"kind": "revised", "means": "…"}
    {"kind": "implemented", "means": "what was done"}

The owner's `verdict` {accepted|rejected} is on proposals only.
