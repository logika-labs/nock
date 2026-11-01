---
term: sharing
aliases: [usage, share-level, statistics, telemetry-sharing, project-id]
description: share = true | false | unset: what nock sends its makers, only on a yes from the owner
---

`share` unset is unanswered: nothing is sent. nock asks the owner once (first round, studio or review: `ask_the_owner`); record their words with `.nock/nock usage share yes|no`, never your own. `share = true` sends a weekly report: counts and categories (sessions, nock's commands and outcomes, toolbox and decision counts, versions) and a random project id in `.nock/project.json`; never code, paths, names or prompts. `share = false` sends nothing, summaries included. `.nock/nock usage` shows it.
