---
term: files.decision
aliases: [files.item]
description: A decision: its events, its versions' decision.json, its assets
---

`topics/orders/decisions/sqlite/`: `events/x.json` and `versions/next/decision.json` {"answer", "alternatives": [{"option", "why_not"}], "status": "done"}.

    {"kind": "created", "title": "Orders live in SQLite", "description": "…"}
    {"kind": "verdict", "verdict": "accepted", "comment": "…"}
    {"kind": "moved", "to": "storage"}

Also `titled`, `message`. Files go in its assets (`docs files.asset`); a file to review with no choice gets a "Review: …" decision.
