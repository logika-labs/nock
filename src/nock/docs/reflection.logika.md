---
term: reflection.logika
aliases: [logika-round]
description: "The logika round: instrument and analytics, for the ledger, from the code and the data"
---

In a Logika project (`logika.json`, the `logika` CLI): `logika.instrument` splits the code into areas, an agent each (`reflection.logika.instrument`), instrumenting it and writing its rules until `logika map` leaves each item closed or with its reason; due once the map's open items grew by 5. `logika.analytics` declares what is worth measuring; due once 5 events were added. `/logika` runs both, `/logika-instrument` and `/logika-analytics` one; never unasked.
