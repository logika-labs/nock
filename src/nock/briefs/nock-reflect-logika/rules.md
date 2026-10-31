# From data to rules

A rule says how the system is expected to behave. Each time it fires, an
agent is woken and someone pays for it. A rule that fires on normal behaviour
teaches the owner to ignore Logika, and that costs more than a bug the rule
would have caught. So aim for precision first and coverage second: each rule
should be one an agent would act on every time it fires.

This brief is the workflow and the judgement. Logika's docs are the authority
on syntax: never write a form from memory. Run `logika docs` for the list,
and `logika docs <term>` before you write a form for the first time. The
terms are `ledger.paths`, `ledger.validate`, `ledger.invariants` (and its
children), `ledger.rules`, `ledger.timeout`, `anomalies.error`, `query`,
`query.events`, `test` and `test.replay`.

Take each component through the five steps below, one operation at a time.

## 1. List the operations and the state they change

Read the ledger (the material has it event by event) and the instrumented
code behind it. List each operation the code performs, the span it runs as,
its child spans, and the state it changes: money, stock, quotas,
permissions, ownership, status lifecycles, and effects outside the system
(charges, emails, webhooks, jobs). For each one, note what the code itself
says must be true: guards and raises, assertions, database constraints and
unique indexes, enum transitions, retries and their limits, the timeouts the
code sets, what the tests assert, comments and docs, and the decisions
recorded in nock and in `logika.json`.

## 2. Explore what really happens

Query real captures with `logika show query`, which is read-only DuckDB.
Always bound a query by `_environment` and `_start`. Each declared event has
a view named by its dotted path (`"checkout.captured"`), the same views an
invariant runs over, so a query you write while exploring can be pasted into
an invariant. Look at:

- value ranges, nulls and distinct values;
- durations at p99 and at max;
- the child sequences that actually occur;
- the gap between a trigger and what follows it;
- rows that relate by key or by trace.

The code says what is intended and the data says what happens. A rule built
from the data alone treats today's bugs as normal. A rule built from the code
alone ignores what really happens. Write a rule when the two agree. When they
disagree, you have found either a bug or a rule nobody wrote down, so ask
the owner which.

## 3. Decide with the owner what must hold

For each operation, propose to the owner what must hold, and on which span
with which keys. Each fact takes one form; use the most local one that
states it:

- **a path**: which child steps happen, in which order;
- **a validate**: a condition on one sighting's own values;
- **an invariant**: a relation between rows that share a key or a trace.
  The kinds are agreement, conservation, continuity, ordering, references
  and uniqueness, and each has its own `logika docs ledger.invariants.<kind>`;
- **a rule**: an obligation that something follows within a time;
- **a timeout**: an operation that must end within a time;
- **error marking**: a failure that should close its span as an error, and
  which paths accept that error.

Leave out:

- what the types or Logika already guarantee (a required param is already
  checked for being missing);
- expected failures (a decline is not an anomaly);
- thresholds that depend on outside timing you cannot bound;
- any value you have seen only once.

Set every time bound above the legitimate worst case: the observed maximum
with a wide margin, never the mean. When a rule depends on a reason that
isn't obvious (why 10 minutes, why a zero amount is allowed), record it with
`logika decide`, so it stays with the ledger.

## 4. Prove each rule both ways

A rule lands only once you have seen it both stay quiet and fire:

1. **Quiet on the clean capture.** Run `logika test "<the narrowest command
   that exercises it>"` and confirm it passes. Then count the existing rows
   that break the rule, with `logika show query` (the negation of a
   validate, or an invariant's own query). If any rows break it, either the
   rule is wrong or you have found a real bug. A bug goes to the owner,
   never into a rule that encodes it.
2. **Fires on the misbehaviour it is for.** Use `logika test --replay`. It
   must raise exactly the anomaly you meant, with evidence an agent could
   act on.

Record both in the change's `tested` field.

## 5. When the state isn't captured, propose instrumentation

If a rule needs something the code doesn't emit (a before or after value, a
step as a child span, the id on a follow-up, an outcome that is only a log
line), propose the instrumentation instead of writing a weaker rule. Prefer
recording every change to shared state, with its before and after values.
Each proposal becomes a todo tagged `logika` and `instrumentation`, naming
the event, its params, where in the code it goes, and the rule it would make
possible. The rule itself waits for a later round.

## Keeping out false positives

- If in doubt, leave the rule out or ask. A missing rule costs nothing until
  the day it would have fired.
- Prefer loose bounds that are certainly right to tight ones that are
  probably right.
- Watch for what differs between environments, between offline clients and
  servers, and between retries and real duplicates, and for clock skew.
- A threshold drawn from a few dozen rows is a guess: ask the owner.
- The last round's rules come first. If one fired on normal behaviour, fix
  it or take it out before you add anything new.

## What you change

Only `logika.json`: params, events (`validate`, `span.timeout`,
`span.paths`, whether a param is optional), `rules` and `invariants`, plus
the decisions `logika decide` writes into it. Change nothing else, not the
code and not `.nock/`, except by recording questions and todos. Commit
nothing: `.nock/nock reflect finish --topic logika` commits.
