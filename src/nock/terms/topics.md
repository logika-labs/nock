---
term: topics
aliases: [topic, decisions, decision, decide, review, important]
description: Topics: where you put your work before the owner, as bare items
---

A topic is a piece of work: a name, why it exists, a thread. Find the one for what you are doing (`.nock/nock topics list --query "…"`) or open one: `topics create '{"name": "checkout-emails", "description": "…"}'`. Submit items into it (`docs topics.items`); the owner gives each a verdict (`docs topics.verdicts`). A finished topic that comes back is revived (`docs topics.revive`). All of it is committed on the main checkout, whichever worktree writes.
