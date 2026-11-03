---
term: permissions
aliases: [allow, allowlist, dont-ask, seats, refused, bypass]
description: What nock's agents may do: the rules init writes, each dispatched seat's allowlist
---

`nock init` allows each `.nock/nock` command but `run`, and asks the owner for `confirm=True` ones (`init`, `upgrade`, `share` too); `permissions.confirm = "allow"` allows them: run them only when the owner's request calls for them. A dispatched agent runs in `dontAsk` with only its seat's tools and rules; anything else is refused and reported, never prompted. A round's parts are subagents with only their tools. When a call is refused, don't work around it: say what you needed and why.
