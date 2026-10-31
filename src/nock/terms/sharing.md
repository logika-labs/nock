---
term: sharing
aliases: [usage, share-level, statistics, telemetry-sharing, project-id]
description: share = true | false: what nock sends its makers, and when the owner is told
---

`share = true` (default) sends a weekly anonymous report: counts and categories (sessions, calls to nock's commands and how they ended, toolbox and decision counts, versions) and a random project id in the committed `.nock/project.json`, never code, paths, names, prompts or arguments. `share = false` sends nothing, summaries included, and makes no id. Nothing goes before the owner is told, once: their first round, studio or review. `.nock/nock usage` shows the next report.
