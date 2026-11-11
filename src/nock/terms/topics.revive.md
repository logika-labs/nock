---
term: topics.revive
aliases: [revive, finished, again, reopen]
description: A done or abandoned topic that comes back: revived, its history kept
---

A done or abandoned topic takes no new decisions; messages, versions and verdicts on its decisions go on. When its work comes back, revive it rather than open another: a `state` event in its `events/`, `{"kind": "state", "state": "active", "revived": true, "note": "why it is back"}`. The note reads as its description from then on; in the studio its decisions show newest first, the revival in its chat.
