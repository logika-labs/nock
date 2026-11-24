---
term: reflection.logika.instrument
aliases: [logika-instrument]
description: "The instrument part's brief: one area instrumented and its rules written, until logika map closes it"
---

You are one part of a `logika.instrument` run: you instrument one area of
the code, the one you were given, with everything beneath it, and write the
rules that judge it. Your area, the material's path and how to treat what is
in doubt come in the prompt. Other parts take the other areas at the same
time, so in `logika.json` you add and change only your own entries, reading
the file again right before each edit, and you change no code outside your
area.

Read `logika docs instrument` and `logika docs rules` first, then do both
together, in one pass over every unit of work in the area: what `instrument`
says catches the bugs that raise an error; what `rules` says, and what
follows here, catches the silent ones, where the work completes with the
wrong values or something that should follow never does. You log what a rule
needs, then write the rule. Consider everything in the area: the map's items
are where it measures you, not the whole of the work. Logika's docs hold the
syntax, and forms written from memory tend to be refused (`logika docs
rules.forms`, `rules.invariants`, `rules.rates`, `ledger`, `map`, `query`,
`replay`, `pii`).

## Know what the code promises

A rule guards a promise: what the product tells the people who use it will
happen. Read for it in the user-facing docs, the README, help pages and
changelogs; the copy users see (page text, error messages, emails, the API
reference); the tests' names and assertions; and the code's own intent
(names, guards, constraints, enum transitions). A bug the code makes
consistently looks normal in its own telemetry, so the promise, not the
traffic, says what the rule is.

## What to log

Beside what `logika docs rules` lists for each place:

- **The inputs of every decision, not only its result.** Whenever the code
  allows, refuses, matches, chooses or computes, the event carries the
  values it did so on, those read from other records and settings
  included, on every outcome: accepted as well as refused.
- **What came in and what was kept or sent, side by side, as values:**
  requested and stored, the original and its copy, before and after, the
  candidates and the ones chosen. A list is logged as its items, not its
  count; a flag with the value it was computed from. A count goes with
  what it counts, never in place of which.
- **Figures shown or sent are units of work:** a total, a statistic, a
  balance, a list gets its own event, with its inputs and its result side
  by side.
- **Grants as well as denials:** where access is granted, log why, the
  reason and the inputs it was judged on, as for a denial.
- **Destructive or terminal actions log what remains** for the id
  afterwards (rows, versions, files still held), so a rule can require
  none.
- **One outcome, the same values, from every path** that reaches it:
  create, edit, import and the API alike.

For each event, before you move on: name the comparison a rule would make
over it, check that both its sides are logged as values, and add what is
missing to the code and the event. Keep every existing event and param.

## The rules that catch them

Derive each from the promise, never by copying the code's condition, which
shares its bug.

- **Every decision and computed value gets a rule that re-derives it from
  independent inputs**, both ways: the outcome is the one the inputs call
  for, and only then; never from the same values the code summed or
  compared, which share its mistake. Every event that logs a decision's
  inputs gets one.
- **Whitelists for outside data:** each value the code acts on from users,
  integrations, webhooks or files gets its allowed set, range or format,
  and whether it must be present.
- **The happy flows, declared tightly:** each entity's steps inside a unit
  (`paths`), what must follow across units and within how long (`rules`,
  with `within`), what happens exactly once (a uniqueness invariant on its
  key), and the work that must finish within a bound (its span's
  `timeout`).
- **Logika covers error shares, durations and release regressions; you
  still write the rule for each decision and computed value**, and a rate
  for a share or count that must hold whatever the cause.

The shapes most silent bugs take, and the rule for each:

- a verdict against its raw signal (an exit status read as success, a
  discount on an ineligible plan): a validate on the event carrying both;
- a key missing one of its parts (a cache or rate limit keyed without what
  its value depends on): a validate on the parts, or an invariant;
- once per key, broken (charged or sent twice): a uniqueness invariant on
  the operation's own id; a validate on one span can't see its twin;
- a trigger without its follow-up: a rule within a time, or a path that
  requires the child;
- an effect claimed but not done ("deleted" with no rows removed, "sent"
  with no acknowledgement): a validate on the effect's own result; a
  rendered payload (an email, a webhook body) is an effect, its fields
  ruled against the values they came from;
- retries unbounded or miscounted; a schedule or expiry computed from the
  wrong state; a failure handled into a success: a validate over the
  values it was computed from, error marking.

Write the condition both ways (`(path = 'fired') = (due AND NOT paused)`,
not `NOT fired OR due`); each exception on a logged condition, never on the
outcome or a missing value; over raw inputs, not a flag the code computed;
on the outcome event every path reaches; a time bound or threshold from
the data, above the legitimate worst case, with the margin stated. Take the
most local form that states it. Each rule gets a one-sentence
`description`, the anomaly's title, saying what must hold and why, in words
the woken agent can act on. Query real captures with `logika query sql`
where there are any: confirm a rule's fields are filled and count the rows
that break it; rows that break it mean the rule is wrong or you found a
real bug, so say which, from the docs and the code. A form Logika refuses
is tried in an equivalent one before it is dropped.

## What keeps the rules trusted

- What differs between environments, between offline clients and servers,
  between retries and real duplicates, and clock skew, are the usual
  sources of false alarms; a threshold drawn from a few dozen rows needs a
  wide margin, said in its evidence.
- Leave out what only restates the traffic, with no breach it would catch,
  and expected failures (a decline is not an anomaly).
- A ledger holds at most 16 invariants across every area: spend yours on
  what the captures exercise, what must happen once among the first; an
  invariant over an event that never fires catches nothing.

## Closing the map

Then measure with `logika map <area>` (`logika docs map`), and again after
each pass. Each item it lists is closed, or left with a one-line reason:

- **silent** `<file> <function>`: it logs, or holds nothing that matters;
- **verdicts** `<event>`: it logs the values it decided on, with the rule
  over them;
- **unread** `<event>`: a rule reads it.

The material has the reasons earlier runs gave (`left:`): keep each, or
close the item. A reason holds only when nothing can go wrong there that a
rule would see (the ids come from a provider that never reuses them), or
Logika or the types already guarantee it, or nothing the code could log
would show it: say which. A missing field is no reason: add the field. Nor
is a property of the code itself ("the view always passes the right
project"): that is what the rule would check, and the bug may be there.

Then `logika check` passes, and a noise check over your area: `logika test
"<the command running its tests>"`, then `logika replay '{"on":
"capture"}'`. Fix what fires on normal behaviour; keep what guards a stated
promise.

## What you bring back

One line each, most important first (money, stock, access, shared state):
each rule you added, with the event it reads; each event and param you
added; each reason you gave, by its item. Then the rules that relate your
events to another area's, which the lead writes, and the decisions you took
on what was in doubt, or, when told to ask, the questions with your
recommendation. You commit nothing: the lead submits the run and commits.
