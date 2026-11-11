---
term: topics
aliases: [topic, decisions, decision, decide, review, important]
description: Topics: where you put your work before the owner, as decisions with their assets
---

A topic is a piece of work: a name, why it exists, a thread, where it stands (`docs topics.state`). Find yours (`.nock/nock search "…"`, then its view in `.nock/local/views/`) or open one: write `.nock/shared/topics/NAME/events/new.json` holding `{"kind": "created", "description": "…"}`. Keep its status current; done when finished. Its decisions hold their assets (`docs topics.items`); the owner gives each a verdict (`docs topics.verdicts`). nock commits every file you write there.
