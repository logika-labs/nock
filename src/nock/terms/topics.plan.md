---
term: topics.plan
aliases: [plan, steps, step, estimate, estimates]
description: A topic's plan: steps with estimates, marked started and done, for the owner's progress bar
---

In the topic's `events/`: `{"kind": "plan", "steps": [{"title": "Move the table", "estimate": 30}, …]}` (minutes; a new plan revises it, steps kept by title), then `{"kind": "step", "title": "Move the table", "state": "started"}` and `"done"`; nock stamps the times. The studio shows a progress bar, the current step and the time left (the estimates left, corrected by the pace so far). Each done step keeps its estimate beside its actual time; reflection calibrates from them.
