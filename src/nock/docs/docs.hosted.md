---
term: docs.hosted
aliases: [hosted-docs, publish-docs, nock-docs-bundled]
description: nock's docs from api.nock.dev, newer than the vendored core's, signed by nock's makers
---

`nock docs` asks api.nock.dev at most hourly (2 s timeout) for the newest docs bundle this nock fits, kept in `.nock/local/docs.json` once its Ed25519 signature verifies; it shows it while it is newer than the core's own docs, else those. `NOCK_DOCS=bundled` shows the core's only. Makers publish with `scripts/publish_docs.py`.
