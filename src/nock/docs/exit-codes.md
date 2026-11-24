---
term: exit-codes
aliases: [exit, codes, exit-code]
description: What each exit code means, and what to do next
---

0 yes. 1 no, the subject failed: fix the code. 40 called wrong: change the request. 41 not authenticated: log in. 42 the machine or state isn't ready: fix that, never the code. 43 policy: don't. 44 not found: check the reference. 49 conflict: reconcile. 50 nock or a tool crashed: report it, or fix the tool. 52 an external service failed: retry later. 54 timed out: raise the bound or split the work. 55 hung, no output too long: suspect a deadlock. 56 killed by nock: see the log.
