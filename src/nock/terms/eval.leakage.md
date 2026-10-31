---
term: eval.leakage
aliases: [leakage, leaks, blind]
description: Nothing downstream sees what it is scored on; a scripted owner knows the product, never the bugs
---

A step must never see what it is scored on: the planted bug, the answer key, the arm it is in when that changes behaviour. Keep answers in parameters only the scoring step reads, out of the state agents work in, and check the state for traces. A scripted owner may know the product, never the bugs.
