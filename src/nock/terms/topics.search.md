---
term: topics.search
aliases: [list, show, search, view-files]
description: Finding topics and decisions: search, then the views
---

`.nock/nock search "words"` ranks topics and decisions by plain full text — names, descriptions, titles, answers, threads, file paths, `when` — and gives each its view: `.nock/local/views/<topic>.md` holds the topic whole (each decision's answer, its assets with each file's path, the threads), `index.md` every topic in the owner's order. The files themselves are under `.nock/shared/topics/`. An item resolves by `topic/slug` or a ref it had before it moved.
