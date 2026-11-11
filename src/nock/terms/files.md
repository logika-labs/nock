---
term: files
aliases: [shared, store]
description: .nock/shared/: topics, their decisions and assets, one immutable event per file
---

`.nock/shared/` (main checkout): `topics/<topic>/events/`, `decisions/<decision>/events/` and `versions/N/`, its `assets/<asset>/events/` and `versions/N/`, `media/`, `map.md`. Write a new file, never edit one: `events/x.json` with the event's `kind` and fields, a new version in `versions/next/`. nock fills in `moment`, `id`, `by`, numbers versions, keeps media by sha256 and commits it alone; a bad file stays uncommitted and is named.
