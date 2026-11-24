---
term: guide.logika
aliases: []
description: In a Logika project, the round that writes the rules which catch bugs before they happen
---

# nock in Logika

nock grew up inside [Logika](https://logika.host), and in a Logika project it
has one more round: the one that catches bugs before they happen, and says
what is worth measuring.

## Tests pass, and the bug ships anyway

Logika is observability and analytics for coding agents. A project declares a
typed ledger, `logika.json`, of the events its code emits as OpenTelemetry
spans: what each event means and the params it carries. Logika's server
judges the stream of events against the ledger's rules, and when the system
misbehaves, it raises an anomaly into a queue your own coding agent works
through: it wakes up, claims the anomaly, reads the evidence and fixes it.

That works only as well as the rules. `logika map` shows where they are
missing: an event **unread**, one no rule reads; an event of **verdicts**,
logged where the code decides but carrying only what it decided, not what
it decided on; a function **silent**, doing something that matters and
logging nothing. An event no rule reads never fires. And
writing rules is exactly the kind of work that gets skipped: it isn't a
feature, nothing fails without it, and its value shows only on the day it
catches something. So nock makes it a round.


## The logika round

In a project with a `logika.json` at its root and the `logika` CLI on PATH,
nock has one more round, `logika`, with two subrounds, and `nock init`
installs their skills: `/logika` runs both, each in its own agent,
`/logika-instrument` and `/logika-analytics` one each.

- **`logika.instrument`** splits the code into areas, a subagent each. Each
  logs what its area does and writes its rules in one pass: for each
  decision, the values it decided on and the rule that re-derives the
  outcome from them; for each event no rule reads, a rule over its values;
  validations, paths, timeouts, invariants, error marking, each rule with a
  one-sentence description that becomes the anomaly's title when it fires.
  It works until `logika map` leaves each item in its area closed or with a
  one-line reason. It is due once the map's open items grew by 5 since its
  last run;
- **`logika.analytics`** declares what you want to measure: which params are identities
  and dimensions, the funnels, milestones and views, so that Logika's analytics
  fill from real captures. It is due once 5 events were added to the ledger.

They are never automatic: they run only when you ask. When one is due, the
session start says so, in its one line; `nock status` always says.

## How a run goes

1. **`nock reflect logika.instrument`** starts a run and writes its
   material: the repository's `logika map` when it starts, each open item
   with the reason an earlier run left it with.
2. **The lead splits the code** into areas, a component's directory or part
   of a large one, and dispatches one part per area, all at once. Each part
   reads the code, the product's docs and copy and real captures (`logika
   query sql`), learns what to log and the forms from Logika's own docs
   (`logika docs instrument`, `logika docs rules`) rather than a copy, and
   changes its area's code and its own entries in `logika.json`. Thresholds
   come from the data, with a stated margin.
3. **One noise check at the end**: `logika test` over the tests, then
   `logika replay '{"on": "capture"}'`, or a query over production's events,
   judges the new rules against normal behavior. What fires on it is fixed;
   the rest is kept, since a little noise is calibrated in production, and a
   missing rule never fires.
4. **A rule that needs state the code doesn't record gets it.** The part
   adds the field to the code and the ledger, rather than writing a weaker
   rule.
5. **You settle only directions and genuine ambiguities**, asked in the session
   with the answer proposed and carried on with; the rest you read in the
   run's report, and in what the session tells you at the end.
6. **`nock reflect --submit JSON`**, once per run, requires its report and
   a `logika.json` that parses, records the rules, reasons and declarations
   changed, each with what showed it, the ledger's numbers and the map's
   open items before and after, and commits the record and `logika.json`.
   Deploying the ledger (`logika sync`) is left to your word.

The analytics subround goes the same way, with one part for the whole and
the lead alone writing `logika.json`.

## Why it is a round

The same idea as nock's own round, applied to a different kind of tool. A rule
in a ledger is code, not prose: it fires or it doesn't, and the next run can
see which. A run reads what the code does and what production actually
sends, writes down what must hold, and checks it against real traffic before
anything breaks. When a bug does ship, the rule is already there, and your agent
is woken to fix it.

Each subround keeps its own runs, so none moves another's window.
