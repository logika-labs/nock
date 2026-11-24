---
term: reflection.tests.promises
aliases: []
description: The tests round's promises brief: what the specification promises that no test holds
---

You read the project's specification (the documents the lead names, else
the ones its instructions call the source of truth) and its tests. Change
nothing.

1. List the promises a user or another component relies on: limits and
   quotas, error responses, permissions, retention and deletion, ordering
   and idempotence, what happens on failure or restart, every number the
   documents state.
2. For each, find the test that holds it: search the tests for the number,
   the route, the error, the name. A test that only touches the code path
   without checking the promise does not hold it.
3. Keep the promises with no test, the important ones first: money,
   access, data loss, then the rest. Skip what is plainly cosmetic.

Return each gap with: the promise quoted with its document and section,
the code that implements it at `file:line` if any, the test that comes
closest and what it misses, the case to add, and how sure you are
(confirmed you searched and found none, likely, possible).
