---
term: topics.search
aliases: [list, show, search, view-files]
description: Finding topics and items: search, then the views
---

`.nock/nock search "words"` ranks topics and items by plain full text — names, descriptions, titles, what they mean, the chat, asset files, the review — and gives each its view: `.nock/local/views/<topic>.md` holds the topic whole (decisions, proposals, assets with each version's path, the review's blocks, the owner's unsent notes, the chat), `index.md` every topic in the owner's order. An item resolves by `topic/slug`.
