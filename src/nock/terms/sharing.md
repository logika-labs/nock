---
term: sharing
aliases: [usage, share-level, statistics, telemetry-sharing]
description: share.level: what nock sends its makers, and when the owner is told
---

`share.level`: `anonymous` (default) sends counts and categories (sessions, calls to nock's commands and how they ended, toolbox and decision counts, versions), never code, paths, names, prompts or arguments; `public` adds the project's tool names and is published on nock.dev; `none` sends nothing, summaries included. Nothing goes before the owner is told, once: their first round, studio or review. Then weekly. `.nock/nock usage` shows the next report.
