---
term: report
aliases: [feedback, feature-request, complaint, bug-report, makers]
description: nock report: what the user wants nock's makers to know, sent on their word
---

When the user needs something nock lacks, or nock is broken or confusing, offer `.nock/nock report "TEXT"` (or the text on stdin): it sends the text, nock's version and the platform to nock's makers, nothing from the repository, and answers a reference id. It matters to them. With no terminal it refuses without `--yes`: show the user what it would send, and pass `--yes` only on their go-ahead. No code or secrets unless they ask.
