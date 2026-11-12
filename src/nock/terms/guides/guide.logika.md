---
term: guide.logika
aliases: []
description: In a Logika project, the rounds that write the rules which catch bugs before they happen
---

# nock in Logika

nock grew up inside [Logika](https://logika.host), and in a Logika project it
has two more rounds: the ones that catch bugs before they happen, and say
what is worth measuring.

## Tests pass, and the bug ships anyway

Logika is observability and analytics for coding agents. A project declares a
typed ledger, `logika.json`, of the events its code emits as OpenTelemetry
spans: what each event means, the params it carries, and the **risks** it
covers. A webhook's delivery, say, carries the risk `once`, with
`attempt` and `will_retry` as the params that are its evidence:
`"risks": {"once": ["attempt", "will_retry"]}`. Logika's
server judges the stream of events against the ledger's rules, and when the
system misbehaves, it raises an anomaly into a queue your own coding agent
works through: it wakes up, claims the anomaly, reads the evidence and fixes
it.

That works only as well as the rules. A risk with no rule never fires. And
writing rules is exactly the kind of work that gets skipped: it isn't a
feature, nothing fails without it, and its value shows only on the day it
catches something. So nock makes it a round.


## The logika rounds

In a project with a `logika.json` at its root and the `logika` CLI on PATH,
two more protocols are adopted, and `nock init` installs their skills:
`/logika` runs both at once, `/logika-rules` and `/logika-analytics` one
each. Each round's agents run as subagents while the session works with you:

- **`logika.rules`**, a subagent per directory, turns the risks the ledger declares on
  each event into what must hold: validations, paths, timeouts, invariants,
  error marking. For each risk, the rule over its evidence, or the reason it
  gets none, each rule with a one-sentence description that becomes the
  anomaly's title when it fires;
- **`logika.analytics`** declares what you want to measure: which params are identities
  and dimensions, the funnels, milestones and views, so that Logika's analytics
  fill from real captures.

They are never automatic: they run only when you ask. When one is due, the
session start offers it, at most once a week: when it hasn't run yet and the
ledger declares events, or 30 days after its last round (the protocol's
`[due]`), once `logika.json` has changed since.
`nock status` always says.

## How a round goes

1. **`nock reflect logika`** starts both rounds and writes each one's
   material: for rules, what the
   ledger already says per event and per component, with the commits that
   touched each component since the last round; for analytics, each param with
   the events that carry it, and what's already declared; for both, the
   ledger's history, the last round's changes and expectations, and the items
   of the `logika` topic.
2. **The session decides what must hold.** `logika map` lists, per file,
   function and event, each risk "guarded by" a rule, at "no rule yet", or
   "ruled out": the gaps. A rules part per directory with gaps reads the code,
   the product's docs and copy and real captures (`logika query sql`), learns
   the forms from Logika's own docs (`logika docs rules`) rather than a copy,
   and brings back each risk's rule or its reason. The session writes them into
   `logika.json` and runs `logika map` again. Thresholds come from the data,
   with a stated margin.
3. **One noise check at the end**: `logika replay '{"on": "capture"}'`, or a
   query over production's events, judges the new rules against normal
   behavior. What fires on it is fixed; the rest is kept, since a little noise
   is calibrated in production, and a missing rule never fires.
4. **A rule that needs state the code doesn't record gets it.** The session
   adds the field to the code and the ledger, rather than writing a weaker rule
   or an empty funnel. Only the session writes code and `logika.json`; the
   parts read.
5. **You settle only directions and genuine ambiguities**, asked in the session
   with the answer the session proposes and carries on with; a question for
   later becomes a decision item in the `logika` topic. The rest you review in
   each round's report.
6. **`nock reflect --submit JSON`**, once per round, requires its report and
   a `logika.json` that parses, records the rules, risks and declarations changed,
   each with what showed it, and the ledger's numbers before and after, and
   commits the record and `logika.json`. Deploying the ledger (`logika sync`) is
   left to your word.

## Why they are rounds

The same idea as nock's own rounds, applied to a different kind of tool. A rule
in a ledger is code, not prose: it fires or it doesn't, and the next round can
see which. The round reads what the code does and what production actually
sends, writes down what must hold, and checks it against real traffic before
anything breaks. When a bug does ship, the rule is already there, and your agent
is woken to fix it.

Each protocol keeps its own rounds, so none moves another's window.
