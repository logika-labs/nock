---
term: topics
aliases: [topic, task, tasks, decisions, decision, proposals]
description: Topics (tasks, to the owner): where you put your work before the owner
---

A topic (the owner reads "task") is a stream of work: a name, why it exists, where it stands (`docs topics.state`), one chat. It holds decisions and proposals (`docs topics.items`), assets (`docs files.asset`) and its review, the page you compose for the owner (`docs review`). Find yours (`.nock/nock search`, then `.nock/local/views/`) or open one: `topics/NAME/events/new.json` `{"kind": "created", "description": "…"}`. nock commits every file you write there.
