---
term: topics.versions
aliases: [update, version, rework, compare, before, after, correct, revise]
description: New versions of an asset or the review, and revising an item
---

Events and versions are never edited: write the next one. An asset's new version is `assets/NAME/versions/next/` with its `asset.json` and file — before and after are versions 1 and 2; a review's, `review/versions/next/review.json`. An item is revised with a `revised` event (title, means, why, takes). nock numbers versions and links project files at their last commit (by content when uncommitted). A wrong state is corrected by another `state` event.
