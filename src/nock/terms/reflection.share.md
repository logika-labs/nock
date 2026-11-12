---
term: reflection.share
aliases: [share, summary]
description: A fit round's summary, vetted, sent on the owner's word
---

The `nock.fit` round's `share.md` says how nock did, abstractly enough that nobody could tell the project: no names, paths, code, people or links (the `nock-share` check). With `share = true`, submitting it has a fresh agent vet it and sends it to nock's makers, who alone read it; otherwise `.nock/nock share` vets it and shows what would be sent, and `'{"send": true}'`, only on the owner's yes, sends it. Nothing is published. With `share = false` it refuses to send.
