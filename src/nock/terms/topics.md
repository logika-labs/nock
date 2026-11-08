---
term: topics
aliases: [topic, decisions, decision, decide, review, important]
description: Topics: where you put your work before the owner, as bare items
---

A topic is a piece of work: a name, why it exists, a thread, where it stands (`docs topics.state`). Find yours (`.nock/nock topics list --query "…"`) or open one: `topics create '{"name": "checkout-emails", "description": "…", "status": "…"}'`. Keep its status current; done when finished. Submit items into it (`docs topics.items`); the owner gives each a verdict (`docs topics.verdicts`). All of it is committed on the main checkout.
