---
term: topics.versions
aliases: [update, version, rework, compare, before, after, correct]
description: A new version of a decision or of an asset, and correcting what was said
---

Events and versions are never edited: write the next one. A new version of a decision is `versions/next/decision.json`; of an asset, `assets/NAME/versions/next/` with its `assets.json` and files — before and after are versions 1 and 2 of one asset. nock numbers it, links project files at their last commit (by content when they have uncommitted changes) and reopens a decided decision. A new title is a `titled` event; a wrong verdict or state, one that corrects it.
