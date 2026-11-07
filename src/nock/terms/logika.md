---
term: logika
aliases: [ledger, logika-json]
description: In a Logika project: what the toolbox leaves to Logika
---

In a Logika project (a `logika.json` at the root), Logika owns the events the code emits, the rules they are judged by, and the local capture (`logika docs`). A tool may wrap a `logika query sql` agents keep rewriting, but doesn't redo what `logika test` or `logika check` do, and a check doesn't repeat a ledger rule. The ledger's rules come from the logika round, not the toolbox.
