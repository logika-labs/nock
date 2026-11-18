---
term: topics.state
aliases: [progress, done, abandoned, planned, active, in-review, dispatch, task-state, topic-status, priority]
description: A topic's state and status: where its work stands, kept current as you work
---

`state`: planned, active (a new topic's), review (built and its review composed: it tells the owner), done, abandoned; `status`: where the work is, in a line. A `state` event in the topic's `events/`: `{"kind": "state", "state": "active", "status": "benchmarks running, about 2 h"}`, or the status alone: at start and each milestone. A state change without a status clears it. The owner's Done sets it done when nothing waits on agents. `priority`: the owner's order.
