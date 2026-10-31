---
term: tools.confirm
aliases: [confirm, owner-word, deploy]
description: confirm=True: a command only the owner may set off
---

`@nock.command(confirm=True)` is for a command only the owner may set off: a deploy, a release, a payment. `nock init` adds a Claude Code `ask` rule for it, so an agent's call waits for the owner's approval although `.nock/nock` is otherwise allowed. The `nock-wiring` check fails while the rule is missing: run `.nock/nock init`.
