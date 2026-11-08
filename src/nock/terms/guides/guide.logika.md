---
term: guide.logika
aliases: [guide.logika-round]
description: In a Logika project, the round that writes the rules Logika checks and what to measure
---

# The logika round

In a [Logika](https://logika.host) project (a `logika.json` ledger at the
root, the `logika` CLI on PATH) there is a second kind of round: the
`/nock-reflect-logika` skill, which `nock init` installs only there. It
has two parts, run as subagents while the session works with the owner:

- **rules**, a subagent per directory, turns the risks the ledger declares
  on each event (`"risks": {"webhooks.retry": ["attempt", "will_retry"],
  "webhooks.once": "why it doesn't apply"}`, a `concern.risk` key mapped to
  the params that are its evidence, or to a reason) into what must hold
  (validations, paths, timeouts, rules, invariants and error marking): for
  each risk, the rule over its evidence, or the reason it gets none, so
  that Logika wakes an agent when the system misbehaves, each rule with a
  one-sentence `description` that becomes the anomaly's title;
- **analytics** declares what the owner wants to measure (which params are
  identities and dimensions, funnels, milestones and views), so that
  Logika's analytics fill from real captures.

It is never automatic. It runs only when the owner asks. When one is due,
the session start offers it at most once a week: when no logika round has
run yet and the ledger declares events, or `reflect.logika.days` (30)
after the last one, once `logika.json` has changed since then. `nock
status` always says.

1. **`nock reflect logika`** writes each part's material: for rules, what
   the ledger already says per event and per component (with the commits
   that touched each component since the last round); for analytics, each
   param with its flags and the events that carry it, and the funnels,
   milestones and views declared; for both, the ledger's history, the last
   logika round's changes and expectations, and the items of the `logika`
   topic.
2. **The session decides what must hold and what to measure.** `logika
   map` lists, per file, function and event, each risk "guarded by" a
   rule, at "no rule yet" or "ruled out": the gaps. A rules part per
   directory with gaps reads the code, the product's docs and copy and real
   captures (`logika query sql`), learns the forms from Logika's own docs
   (`logika docs rules`, `logika docs <concern>.<risk>`) instead of a copy,
   and brings back each risk's rule or its reason; the session writes them
   into `logika.json`, runs `logika map` again, and once more over what is
   still open if that is much. Thresholds come from the data, with a stated
   margin. At the end, one noise check (`logika replay '{"on":
   "capture"}'`, or `'{"on": "query", "query": "…"}'` over production's
   events): what fires on normal behaviour is fixed, the rest kept, since
   a little noise is calibrated in production and a missing rule never
   fires.
3. **The owner settles only directions and genuine ambiguities**, asked in
   the session with the answer the session proposes and carries on with; a
   question for later becomes a decision item in the `logika` topic.
   The rest the owner reviews in the round's report. A rule or a measure
   that needs state the code doesn't record gets it: the session adds the
   field to the code and the ledger (kind `instrumentation`), not a weaker
   rule or an empty funnel; only the session (the lead) writes the code and
   `logika.json`, the parts read.
4. **`nock reflect logika finish JSON`** requires the round's
   `report.md` and a `logika.json` that parses. It records the rules, risks
   and declarations changed (each with what showed it, `tested`, where
   something did), and the ledger's numbers before and after
   in `.nock/reflections/logika/DATE/record.json`, and commits `.nock/` and
   `logika.json`. Deploying the ledger (`logika sync`) is left to the
   owner's word.

Logika rounds are kept apart from nock's own, so neither moves the other's
window.
