---
term: guide.consult
aliases: [guide.map, guide.consulting]
description: The map of what the topics mean for the work, and the consultant an agent asks before changing code
---

# The map and consulting

## The map

`.nock/topics/map.md` says what the topics and items mean for the work: when
each matters, and how they bear on each other. A consultant is given it
with its brief. A reflection round keeps it, within three rules:

- triggers, not facts: "if you touch X, then Y, because Z [charge-sweep/dead-charges-only]";
- a rejected option comes with what would make it viable again;
- what was inferred, rather than read or observed, is marked *(inferred)*.

`nock init` starts it empty. It cites items by ref in brackets (an earlier
decision as `[D7]`); the `nock-map` check fails when it cites one that does
not exist.

## Consulting

Before an agent changes code, it consults:

```sh
$ .nock/nock consult '{"intent": "Move orders to Postgres.", "context": "SQLite locks under load."}'
```

A fresh headless agent is given the map, the project's tools and checks,
and reads the topics and items about what the work touches. It changes
nothing, and takes the intent as given: it doesn't redesign the task. It
advises in a few lines — the topic to submit into, what the items mean for
this work (what to keep to, a rejected option the work would bring back, a
todo it could close, and first, plainly, an accepted decision the intent
goes against), the tools that do its steps, a choice the work is about to
make that should be submitted, and the checks to pass — or says that
nothing in nock bears on it. It submits with `nock advise`, which refuses an
item, tool or check that doesn't exist, so it fixes the name; the calling
agent reads the advice exactly as submitted, followed by each named item's
title and verdict, each tool's usage and the `nock check` to run. Where
nock fell short for the task goes to the next reflection round. The caller
waits up to `consult.deadline` seconds.

The primer asks agents to consult before changing code, unless the task is
really straightforward and unambiguous. **`consult.enabled = false`** turns
it off: the primer no longer mentions it, and `nock consult` says so and
dispatches nothing.
