---
term: logika
aliases: [ledger, logika-json]
description: "In a Logika project: what the toolbox leaves to Logika, and the logika round"
---

In a Logika project (a `logika.json` at the root), Logika owns the events, their rules and the local capture (`logika docs`). A tool may wrap a `logika query sql` agents keep rewriting, but doesn't redo `logika test` or `logika check`, and a check doesn't repeat a ledger rule. The rules come from the logika round: `.nock/nock reflect logika` prints its plan, an agent per subround, which you dispatch at once and whose reports you relay.
