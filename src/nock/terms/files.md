---
term: files
aliases: [shared, store]
description: .nock/shared/: topics, their items, assets and review, one immutable event per file
---

`.nock/shared/` (main checkout): `topics/<topic>/events/`; its `items/<slug>/events/`, `assets/<asset>/events/` and `versions/N/`, `review/versions/N/`; `media/`, `map.md`, `review.md` (the review preferences). Write a new file, never edit one: `events/x.json` with the event's `kind` and fields, a new version in `versions/next/`. nock fills in `moment`, `id`, `by`, numbers versions, keeps media by sha256 and commits it; a bad file stays uncommitted and is named.
