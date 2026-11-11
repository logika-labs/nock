---
term: sharing
aliases: [usage, share-level, statistics, telemetry-sharing, project-id]
description: share = true | false | unset: what nock sends its makers, only on a yes from the owner
---

`share` unset is unanswered: nothing is sent. nock asks the owner once (`ask_the_owner`); record their words with `.nock/nock config share true|false`, never your own. `true` sends a weekly report: counts and categories (sessions, nock's commands and outcomes, toolbox and topic counts, versions) and a random project id in `.nock/project.json`; never code, paths, names or prompts. `false` sends nothing, summaries included. `.nock/nock config share` shows it.
