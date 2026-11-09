---
term: topics.state
aliases: [progress, done, abandoned, planned, active, in-review, dispatch, task, tasks, topic-status, priority]
description: A topic's state and status: where its work stands, kept current as you work
---

`state`: planned, active (a new topic's), review (built, only the owner's verdicts left: no studio mark, under Needs me), done, abandoned; `status`: where the work is, in a line. `topics update TOPIC '{"state": "active", "status": "eval running, about 2 h"}'`, or the status alone: at start and each milestone. A state change without a status clears it; each change is a status entry in its thread. Dispatched work too. `priority`: the owner's order, 1 first. `topics list --state review`.
